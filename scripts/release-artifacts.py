#!/usr/bin/env python3
"""Deterministic public wheel assets and fail-closed, resumable publication.

Only the protected manual public-release workflow should invoke ``publish``.
This script never replaces assets, moves tags, or deletes remote state.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath
from urllib.parse import quote

REPOSITORY = "unibio-intelligence/biomedmcp"
MAX_ASSET_BYTES = 512 * 1024 * 1024
MAX_PAGES = 20
MAX_SBOM_BYTES = 16 * 1024 * 1024
SIGNER_WORKFLOW = REPOSITORY + "/.github/workflows/release.yml"
PROVENANCE_TYPE = "https://slsa.dev/provenance/v1"
SBOM_TYPE = "https://cyclonedx.org/bom"


class ReleaseError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def validate_identity(version, revision):
    require(
        isinstance(version, str)
        and len(version) <= 128
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?", version),
        "Use a bounded semantic release version.",
    )
    require(
        isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "Use a full source commit."
    )


def bundle(wheels, output, *, version, revision, epoch, tree_sha256, lock_sha256):
    validate_identity(version, revision)
    require(type(epoch) is int and 315532800 <= epoch <= 2147483647, "Invalid source timestamp.")
    for digest in (tree_sha256, lock_sha256):
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid source digest.")
    marker = wheels / ".gitignore"
    if marker.exists() or marker.is_symlink():
        require(
            marker.is_file() and not marker.is_symlink() and marker.read_bytes() == b"*",
            "Unexpected wheel-directory marker; use a clean uv build directory.",
        )
    paths = sorted(path for path in wheels.iterdir() if path.name != ".gitignore")
    require(0 < len(paths) <= 100, "Wheel directory must contain 1–100 wheels.")
    require(
        all(
            p.is_file()
            and not p.is_symlink()
            and re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", p.name)
            and 0 < p.stat().st_size <= MAX_ASSET_BYTES
            for p in paths
        ),
        "Wheel directory contains an invalid file; use a clean build directory.",
    )
    require(sum(p.stat().st_size for p in paths) <= MAX_ASSET_BYTES, "Wheel bundle exceeds its budget.")
    require(not output.exists(), "Bundle destination must be new; retain prior assets for comparison.")
    output.mkdir(parents=True)
    archive = output / "public-wheels.tar.gz"
    rows = []
    with (
        archive.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, filename="", mtime=0, mode="wb") as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as target,
    ):
        for path in paths:
            data = path.read_bytes()
            info = tarfile.TarInfo(path.name)
            info.size = len(data)
            info.mtime = epoch
            info.mode = 0o644
            target.addfile(info, io.BytesIO(data))
            rows.append({"name": path.name, "size": len(data), "sha256": sha(data)})
    receipt = {
        "format": 1,
        "repository": REPOSITORY,
        "version": version,
        "source_commit": revision,
        "source_date_epoch": epoch,
        "source_tree_sha256": tree_sha256,
        "uv_lock_sha256": lock_sha256,
        "wheels": rows,
        "archive": {
            "name": archive.name,
            "size": archive.stat().st_size,
            "sha256": sha(archive.read_bytes()),
        },
    }
    (output / "release-receipt.json").write_bytes(encoded(receipt))
    return receipt


def wheel_component(name, data):
    """Inventory the shipped wheel bytes; do not resolve optional dependencies."""
    try:
        parts = name.removesuffix(".whl").split("-")
        require(len(parts) in (5, 6), "Invalid wheel filename.")
        distribution, version = parts[:2]
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            members = wheel.infolist()
            names = [m.filename for m in members]
            require(
                0 < len(names) <= 10000 and len(names) == len(set(names)),
                "Invalid wheel member inventory.",
            )
            require(
                all(
                    not PurePosixPath(n).is_absolute()
                    and ".." not in PurePosixPath(n).parts
                    and "\\" not in n
                    and n.rstrip("/") == PurePosixPath(n).as_posix()
                    for n in names
                )
                and sum(m.file_size for m in members) <= MAX_ASSET_BYTES,
                "Unsafe or oversized wheel member inventory.",
            )
            metadata_names = [n for n in names if n.endswith(".dist-info/METADATA")]
            expected = distribution + "-" + version + ".dist-info/METADATA"
            require(metadata_names == [expected], "Wheel metadata identity differs from its filename.")
            info = wheel.getinfo(expected)
            require(0 < info.file_size <= 1024 * 1024, "Wheel metadata exceeds its budget.")
            metadata = Parser().parsestr(wheel.read(expected).decode("utf-8"))
            require(not metadata.defects, "Malformed wheel metadata.")
            for field in ("Name", "Version", "Metadata-Version"):
                require(len(metadata.get_all(field, [])) == 1, "Ambiguous wheel metadata identity.")
            package = metadata["Name"]

            def normalize(value):
                return re.sub(r"[-_.]+", "-", value).lower()

            require(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", package)
                and normalize(package) == normalize(distribution)
                and metadata["Version"] == version
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+!]*", version),
                "Wheel package identity differs from its filename.",
            )
            properties = [{"name": "ubi:wheel:filename", "value": name}]
            for field in ("Requires-Dist", "License-Expression", "License", "License-File"):
                for value in metadata.get_all(field, []):
                    require(len(value) <= 8192, "Wheel metadata value exceeds its budget.")
                    properties.append({"name": "ubi:wheel:" + field.lower(), "value": value})
            return {
                "type": "library",
                "bom-ref": "wheel:" + name,
                "name": package,
                "version": version,
                "purl": "pkg:pypi/" + normalize(package) + "@" + quote(version, safe=""),
                "hashes": [{"alg": "SHA-256", "content": sha(data)}],
                "properties": properties,
            }
    except (zipfile.BadZipFile, UnicodeError, RuntimeError, OSError):
        raise ReleaseError("Invalid wheel metadata; attestation stopped.") from None


def wheel_sbom(directory, receipt):
    """Deterministic CycloneDX inventory of the exact released archive, not its runtime."""
    validate_identity(receipt["version"], receipt["source_commit"])
    require(receipt.get("repository") == REPOSITORY, "Wrong SBOM source repository.")
    for field in ("source_tree_sha256", "uv_lock_sha256"):
        require(
            isinstance(receipt.get(field), str) and re.fullmatch(r"[0-9a-f]{64}", receipt[field]),
            "Invalid SBOM source identity.",
        )
    archive = directory / "public-wheels.tar.gz"
    require(
        archive.is_file() and not archive.is_symlink() and 0 < archive.stat().st_size <= MAX_ASSET_BYTES,
        "Invalid wheel archive.",
    )
    data = archive.read_bytes()
    require(
        receipt.get("archive") == {"name": archive.name, "size": len(data), "sha256": sha(data)},
        "Wheel archive differs from its release receipt.",
    )
    rows = receipt.get("wheels")
    require(isinstance(rows, list) and 0 < len(rows) <= 100, "Invalid wheel receipt inventory.")
    expected = {}
    for row in rows:
        require(
            isinstance(row, dict)
            and isinstance(row.get("name"), str)
            and re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", row["name"])
            and row["name"] not in expected
            and type(row.get("size")) is int
            and 0 < row["size"] <= MAX_ASSET_BYTES
            and isinstance(row.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "Invalid or duplicate wheel receipt member.",
        )
        expected[row["name"]] = row
    require(sum(r["size"] for r in rows) <= MAX_ASSET_BYTES, "Wheel inventory exceeds its budget.")
    components = []
    seen = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle_archive:
            for member in bundle_archive:
                require(
                    member.isfile()
                    and member.name in expected
                    and member.name not in seen
                    and member.size == expected[member.name]["size"],
                    "Archive contains an unexpected, duplicate or unsafe wheel.",
                )
                seen.add(member.name)
                source = bundle_archive.extractfile(member)
                require(source is not None, "Missing wheel bytes.")
                wheel = source.read(member.size + 1)
                require(
                    len(wheel) == member.size and sha(wheel) == expected[member.name]["sha256"],
                    "Archive wheel differs from the release receipt.",
                )
                components.append(wheel_component(member.name, wheel))
    except (tarfile.TarError, EOFError, OSError):
        raise ReleaseError("Invalid wheel archive; attestation stopped.") from None
    require(seen == expected.keys(), "Archive omits a receipted wheel.")
    identities = [c["purl"] for c in components]
    require(len(set(identities)) == len(identities), "Duplicate package identity in release archive.")
    report = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "biomedmcp-wheel-bundle",
                "version": receipt["version"],
                "hashes": [{"alg": "SHA-256", "content": receipt["archive"]["sha256"]}],
            },
            "properties": [
                {"name": "ubi:source_commit", "value": receipt["source_commit"]},
                {"name": "ubi:source_tree_sha256", "value": receipt["source_tree_sha256"]},
                {"name": "ubi:uv_lock_sha256", "value": receipt["uv_lock_sha256"]},
                {
                    "name": "ubi:inventory_scope",
                    "value": "Exact shipped wheel files and reported metadata. Requires-Dist values are unresolved declarations; installed/transitive/runtime inventory and license approval require separate qualification.",
                },
            ],
        },
        "components": sorted(components, key=lambda c: c["bom-ref"]),
    }
    require(len(encoded(report)) <= MAX_SBOM_BYTES, "Wheel SBOM exceeds the attestation budget.")
    return report


def source_identity(root, version, revision):
    """Verify the public export's selected bytes before building or publishing."""
    validate_identity(version, revision)
    require(
        tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == version,
        "Release version differs from the qualified scientific package.",
    )
    manifest = json.loads((root / "source-manifest.json").read_text())
    require(manifest.get("publication_ready") is True, "Export has no approved license.")
    rows = manifest.get("files")
    require(
        isinstance(rows, dict) and {"LICENSE", "uv.lock", "pyproject.toml"} <= rows.keys(),
        "Incomplete export.",
    )
    for name, entry in rows.items():
        relative = PurePosixPath(name)
        require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and name == relative.as_posix()
            and all(
                not (root.joinpath(*relative.parts[:i])).is_symlink()
                for i in range(1, len(relative.parts) + 1)
            ),
            "Unsafe export path.",
        )
        path = root / name
        require(
            path.is_file()
            and sha(path.read_bytes()) == entry.get("sha256")
            and bool(path.stat().st_mode & 0o111) == entry.get("executable"),
            "Public source differs from its qualified export; regenerate and requalify.",
        )
    tree = sha(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    require(tree == manifest.get("tree_sha256"), "Export manifest digest differs.")
    require((root / "LICENSE").stat().st_size > 0, "An approved nonempty LICENSE is required.")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    require(
        commit.returncode == 0 and commit.stdout.strip() == revision, "Checkout is not the reviewed commit."
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    require(status.returncode == 0 and not status.stdout.strip(), "Checkout has uncommitted source changes.")
    return tree, sha((root / "uv.lock").read_bytes())


class GitHub:
    """Use gh's existing authentication without echoing its errors or credentials."""

    def verify_attestations(self, directory, receipt):
        sbom = wheel_sbom(directory, receipt)
        for name, predicate_type, expected in (
            ("public-wheels.tar.gz", PROVENANCE_TYPE, None),
            ("release-receipt.json", PROVENANCE_TYPE, None),
            ("public-wheels.tar.gz", SBOM_TYPE, sbom),
        ):
            path = directory / name
            try:
                result = subprocess.run(
                    [
                        "gh",
                        "attestation",
                        "verify",
                        str(path),
                        "--hostname",
                        "github.com",
                        "--repo",
                        REPOSITORY,
                        "--signer-workflow",
                        SIGNER_WORKFLOW,
                        "--signer-digest",
                        receipt["source_commit"],
                        "--source-digest",
                        receipt["source_commit"],
                        "--deny-self-hosted-runners",
                        "--predicate-type",
                        predicate_type,
                        "--limit",
                        "100",
                        "--format",
                        "json",
                    ],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise ReleaseError("Release attestation verification unavailable; no publication.") from None
            require(
                result.returncode == 0 and len(result.stdout) <= MAX_SBOM_BYTES,
                "Release attestation verification failed; no publication.",
            )
            try:
                results = json.loads(result.stdout)
                require(
                    isinstance(results, list) and 0 < len(results) <= 100,
                    "Invalid verified attestation response.",
                )
                digest = sha(path.read_bytes())
                accepted = False
                for row in results:
                    require(
                        isinstance(row, dict) and isinstance(row.get("verificationResult"), dict),
                        "Invalid verified attestation result.",
                    )
                    statement = row["verificationResult"]["statement"]
                    require(isinstance(statement, dict), "Invalid verified attestation statement.")
                    subjects = statement["subject"]
                    require(
                        isinstance(subjects, list) and all(isinstance(s, dict) for s in subjects),
                        "Invalid verified attestation subjects.",
                    )
                    if (
                        statement["predicateType"] == predicate_type
                        and any(s.get("digest") == {"sha256": digest} for s in subjects)
                        and (expected is None or statement["predicate"] == expected)
                    ):
                        accepted = True
                require(accepted, "Attestation does not bind the expected artifact and SBOM.")
            except (KeyError, TypeError, ValueError):
                raise ReleaseError("Invalid verified attestation response; no publication.") from None

    def api(self, path, *, method="GET", payload=None, missing=False):
        command = ["gh", "api", "--hostname", "github.com", "--include", "--method", method, path]
        if payload is not None:
            command.extend(["--input", "-"])
        result = subprocess.run(
            command, input=encoded(payload) if payload is not None else None, capture_output=True, check=False
        )
        raw = result.stdout.replace(b"\r\n", b"\n")
        header, separator, body = raw.partition(b"\n\n")
        status = re.match(rb"HTTP/\S+ (\d{3})(?: |\n|$)", header)
        require(
            bool(status) and bool(separator), "GitHub observation failed; rerun to reconcile remote state."
        )
        code = int(status[1])
        if code == 404 and missing and method == "GET":
            return None
        require(
            result.returncode == 0 and 200 <= code < 300,
            f"GitHub {method} failed (HTTP {code}); rerun to reconcile, never force or overwrite.",
        )
        try:
            return json.loads(body)
        except (ValueError, UnicodeError):
            raise ReleaseError("Malformed GitHub response; publication stopped.") from None

    def pages(self, path):
        rows = []
        for page in range(1, MAX_PAGES + 1):
            batch = self.api(f"{path}?per_page=100&page={page}")
            require(isinstance(batch, list), "Malformed GitHub collection.")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise ReleaseError(
            "GitHub inventory exceeds the observation budget; inspect manually before resuming."
        )

    def asset_sha(self, asset_id):
        with tempfile.TemporaryFile() as target:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "--hostname",
                    "github.com",
                    f"repos/{REPOSITORY}/releases/assets/{asset_id}",
                    "--header",
                    "Accept: application/octet-stream",
                ],
                stdout=target,
                stderr=subprocess.PIPE,
                check=False,
            )
            require(result.returncode == 0, "Existing asset could not be verified; publication stopped.")
            target.seek(0)
            digest, size = hashlib.sha256(), 0
            while data := target.read(1024 * 1024):
                size += len(data)
                require(size <= MAX_ASSET_BYTES, "Existing asset exceeds the observation budget.")
                digest.update(data)
            return size, digest.hexdigest()

    def upload(self, tag, path):
        result = subprocess.run(
            ["gh", "release", "upload", tag, str(path), "--repo", "github.com/" + REPOSITORY],
            capture_output=True,
            check=False,
        )
        require(
            result.returncode == 0,
            "Upload outcome is uncertain; rerun to verify bytes and resume. No clobber.",
        )


def tag_commit(github, tag):
    ref = github.api(f"repos/{REPOSITORY}/git/ref/tags/{tag}", missing=True)
    if ref is None:
        return None
    obj = ref.get("object", {})
    for _ in range(8):
        require(
            isinstance(obj, dict) and re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")),
            "Invalid tag identity.",
        )
        if obj.get("type") == "commit":
            return obj["sha"]
        require(obj.get("type") == "tag", "Release tag does not identify a commit.")
        obj = github.api(f"repos/{REPOSITORY}/git/tags/{obj['sha']}").get("object", {})
    raise ReleaseError("Release tag nesting exceeds its budget.")


def verified_assets(github, release_id, assets):
    rows = github.pages(f"repos/{REPOSITORY}/releases/{release_id}/assets")
    names = [a.get("name") for a in rows if isinstance(a, dict)]
    require(
        len(names) == len(rows) == len(set(names)) and set(names) <= assets.keys(),
        "Unexpected or duplicate release asset; review remote state, never overwrite.",
    )
    present = set()
    for asset in rows:
        name = asset["name"]
        require(
            type(asset.get("id")) is int and asset["id"] > 0 and asset.get("state") == "uploaded",
            "Incomplete remote asset; review the draft manually before resuming. No automatic deletion.",
        )
        expected = assets[name]
        require(
            type(asset.get("size")) is int and asset["size"] == expected[0],
            "Existing asset size differs; use a new version or review recovery, never overwrite.",
        )
        require(
            github.asset_sha(asset["id"]) == expected,
            "Existing asset bytes differ; use a new version or review recovery, never overwrite.",
        )
        present.add(name)
    return present


def publish(github, directory, receipt, notes):
    version, revision = receipt["version"], receipt["source_commit"]
    validate_identity(version, revision)
    require(receipt.get("repository") == REPOSITORY, "Wrong public repository.")
    tag, title = "v" + version, "biomedmcp " + version
    assets = {
        name: (path.stat().st_size, sha(path.read_bytes()))
        for name in ("public-wheels.tar.gz", "release-receipt.json")
        if (path := directory / name).is_file()
    }
    require(len(assets) == 2, "Both qualified release assets are required.")
    require(
        receipt["archive"]
        == {
            "name": "public-wheels.tar.gz",
            "size": assets["public-wheels.tar.gz"][0],
            "sha256": assets["public-wheels.tar.gz"][1],
        },
        "Local archive differs from receipt.",
    )
    require((directory / "release-receipt.json").read_bytes() == encoded(receipt), "Local receipt differs.")
    # Verify before every remote mutation, including retrying an already-published version.
    github.verify_attestations(directory, receipt)
    body = f"{notes.rstrip()}\n\nSource commit: {revision}\nRelease receipt SHA-256: {assets['release-receipt.json'][1]}\n"
    metadata = github.api("repos/" + REPOSITORY)
    require(
        metadata.get("full_name") == REPOSITORY and metadata.get("private") is False,
        "Destination must be the exact public release repository.",
    )
    require(
        metadata.get("permissions", {}).get("push") is True,
        "Authenticated push access is required to observe drafts.",
    )
    matches = [r for r in github.pages(f"repos/{REPOSITORY}/releases") if r.get("tag_name") == tag]
    require(len(matches) <= 1, "Multiple matching releases; reconcile manually.")
    release = matches[0] if matches else None
    prerelease = "-" in version

    def check_release(value):
        require(
            isinstance(value, dict)
            and type(value.get("id")) is int
            and value["id"] > 0
            and value.get("tag_name") == tag
            and value.get("name") == title
            and value.get("body") == body
            and value.get("prerelease") is prerelease
            and type(value.get("draft")) is bool,
            "Release metadata differs from qualified inputs; review manually, never overwrite.",
        )
        if value["draft"]:
            require(value.get("target_commitish") == revision, "Draft targets a different source commit.")

    if release is not None:
        check_release(release)
        present = verified_assets(github, release["id"], assets)
    else:
        present = set()
    observed = tag_commit(github, tag)
    require(
        observed is None or observed == revision,
        "Version tag targets different source bytes; use a new version.",
    )
    if release is not None and not release["draft"]:
        require(
            observed == revision and present == assets.keys(),
            "Published release is incomplete; review manually.",
        )
        return {"status": "already_published", "tag": tag, "source_commit": revision}
    if observed is None:
        commit = github.api(f"repos/{REPOSITORY}/git/commits/{revision}")
        require(commit.get("sha") == revision, "Reviewed source commit is unavailable.")
        github.api(
            f"repos/{REPOSITORY}/git/refs",
            method="POST",
            payload={"ref": "refs/tags/" + tag, "sha": revision},
        )
        require(
            tag_commit(github, tag) == revision, "Tag creation could not be verified; rerun to reconcile."
        )
    if release is None:
        release = github.api(
            f"repos/{REPOSITORY}/releases",
            method="POST",
            payload={
                "tag_name": tag,
                "target_commitish": revision,
                "name": title,
                "body": body,
                "draft": True,
                "prerelease": prerelease,
            },
        )
        check_release(release)
    for name in assets:
        if name not in present:
            github.upload(tag, directory / name)
    # Re-observe remote state after all mutations; failures leave the draft recoverable.
    fresh = github.api(f"repos/{REPOSITORY}/releases/{release['id']}")
    check_release(fresh)
    require(tag_commit(github, tag) == revision, "Tag changed; publication stopped.")
    require(verified_assets(github, release["id"], assets) == assets.keys(), "Draft assets are incomplete.")
    if fresh["draft"]:
        final = github.api(
            f"repos/{REPOSITORY}/releases/{release['id']}", method="PATCH", payload={"draft": False}
        )
        check_release(final)
        require(final["draft"] is False, "Publication outcome is uncertain; rerun to reconcile.")
    return {"status": "published", "tag": tag, "source_commit": revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bundle", "sbom", "publish"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Fresh SBOM output path, outside release assets")
    args = parser.parse_args()
    try:
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
            "Only the approved public release repository is supported.",
        )
        version, revision = os.environ["RELEASE_VERSION"], os.environ["GITHUB_SHA"]
        tree, lock = source_identity(args.root, version, revision)
        if args.action == "bundle":
            require(args.wheels is not None, "A clean wheel directory is required.")
            report = bundle(
                args.wheels,
                args.assets,
                version=version,
                revision=revision,
                epoch=int(os.environ["SOURCE_DATE_EPOCH"]),
                tree_sha256=tree,
                lock_sha256=lock,
            )
        else:
            receipt = json.loads((args.assets / "release-receipt.json").read_text())
            require(
                receipt.get("version") == version
                and receipt.get("source_commit") == revision
                and receipt.get("source_tree_sha256") == tree
                and receipt.get("uv_lock_sha256") == lock,
                "Release receipt does not identify the qualified checkout.",
            )
            if args.action == "sbom":
                require(
                    args.output is not None
                    and not args.output.exists()
                    and args.assets.resolve() not in args.output.resolve().parents,
                    "Use a fresh SBOM output path outside release assets.",
                )
                report = wheel_sbom(args.assets, receipt)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(encoded(report))
            else:
                report = publish(GitHub(), args.assets, receipt, (args.root / "CHANGELOG.md").read_text())
        print(json.dumps(report, sort_keys=True))
    except ReleaseError as error:
        parser.exit(1, str(error) + "\n")
    except (OSError, KeyError, TypeError, ValueError):
        parser.exit(1, "Invalid local release inputs; publication stopped.\n")


if __name__ == "__main__":
    main()
