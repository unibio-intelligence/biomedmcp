#!/usr/bin/env python3
"""Audit frozen registry nodes and a local runtime image; retain failing evidence."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCANNER = "anchore/grype@sha256:e4a44ef45d285b829ce6efe2642980329661bd2d18eab5fc539138d4adaebbbe"
VERSION = "0.120.1"
SEVERITIES = {"Negligible", "Low", "Medium", "High", "Critical", "Unknown"}
CONFIG = """check-for-app-update: false
ignore: []
match-upstream-kernel-headers: true
external-sources:
  enable: false
db:
  cache-dir: /db
  validate-by-hash-on-start: true
  validate-age: true
  max-allowed-built-age: 120h
  auto-update: true
  require-update-check: true
  max-update-check-frequency: 0s
"""


class ScanError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ScanError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def name(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value), "Invalid package name"
    )
    return re.sub(r"[-_.]+", "-", value).lower()


def lock_nodes(path):
    lock = tomllib.loads(path.read_text())
    registry, local = set(), []
    for row in lock["package"]:
        package = name(row["name"])
        version = row["version"]
        require(
            isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9_.+!-]+", version), "Invalid locked version"
        )
        source = row["source"]
        if "registry" in source:
            require(source == {"registry": "https://pypi.org/simple"}, "Unreviewed package registry")
            registry.add(f"pkg:pypi/{package}@{quote(version, safe='._-')}")
        else:
            require(set(source) == {"editable"}, "Unreviewed nonregistry source")
            local.append({"name": package, "version": version, "source": source})
    require(registry, "No frozen registry nodes to audit")
    return sorted(registry), sorted(local, key=lambda row: row["name"])


def archive_identity(path, image_id):
    # Docker's containerd store can identify the OCI index, while Grype identifies
    # the selected image configuration. Bind both through validated saved blobs.
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        member_names = {member.name for member in members}
        require(len(member_names) == len(members), "Ambiguous image archive members")

        def read(member_name):
            member = archive.getmember(member_name)
            require(member.isfile() and member.size <= 1048576, "Invalid image identity member")
            return archive.extractfile(member).read()

        manifests = json.loads(read("manifest.json"))
        require(isinstance(manifests, list) and len(manifests) == 1, "Archive must contain one runtime image")
        config = read(manifests[0]["Config"])
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()

        def reaches_config(digest, depth=0):
            require(
                depth < 5 and re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "Invalid image manifest graph"
            )
            member_name = "blobs/sha256/" + digest[7:]
            # A saved official index can retain references to unpulled platforms.
            # Only a present, hash-verified path can prove the selected identity.
            if member_name not in member_names:
                require(depth > 0, "Local image identity is absent from archive")
                return False
            raw = read(member_name)
            require("sha256:" + hashlib.sha256(raw).hexdigest() == digest, "Image manifest digest differs")
            document = json.loads(raw)
            if "config" in document:
                return document["config"]["digest"] == config_digest
            children = document["manifests"]
            require(isinstance(children, list) and 0 < len(children) <= 32, "Invalid image index")
            return any(reaches_config(child["digest"], depth + 1) for child in children)

        require(
            image_id == config_digest or reaches_config(image_id),
            "Saved image does not match local image identity",
        )
        data = json.loads(config)
        return {"image_config_digest": config_digest, "architecture": data["architecture"], "os": data["os"]}


def validate(report, bom, *, target, expected, now=None):
    require(isinstance(report, dict) and isinstance(report.get("matches"), list), "Missing scanner findings")
    descriptor = report["descriptor"]
    require(descriptor["name"] == "grype" and descriptor["version"] == VERSION, "Unreviewed scanner version")
    configuration = descriptor["configuration"]
    require(
        not configuration.get("ignore") and not report.get("ignoredMatches"),
        "Suppressed findings are forbidden",
    )
    require(
        configuration.get("exclude") == []
        and not configuration.get("only-fixed")
        and not configuration.get("only-notfixed"),
        "Filtered findings are forbidden",
    )
    require(configuration["externalSources"]["enable"] is False, "External package resolution is forbidden")
    db = configuration["db"]
    require(
        db["validate-by-hash-on-start"] is True and db["validate-age"] is True,
        "Database verification disabled",
    )
    require(
        db["auto-update"] is (target == "dependencies")
        and db["require-update-check"] is (target == "dependencies"),
        "Unexpected database update policy",
    )
    status = descriptor["db"]["status"]
    require(status["valid"] is True, "Invalid advisory database")
    built = datetime.fromisoformat(status["built"])
    require(
        built.tzinfo is not None and -600 <= ((now or datetime.now(UTC)) - built).total_seconds() <= 432000,
        "Stale advisory database",
    )
    origin = urlsplit(status["from"])
    checksum = parse_qs(origin.query).get("checksum", [])
    require(
        origin.scheme == "https"
        and origin.netloc == "grype.anchore.io"
        and origin.path.startswith("/databases/")
        and len(checksum) == 1
        and re.fullmatch(r"sha256:[a-f0-9]{64}", checksum[0]),
        "Unverified advisory database origin",
    )
    require({"github", "debian"} <= descriptor["db"]["providers"].keys(), "Required advisory feeds absent")
    require(
        bom["bomFormat"] == "CycloneDX"
        and bom["specVersion"] == "1.7"
        and isinstance(bom["components"], list)
        and bom["components"],
        "Missing CycloneDX inventory",
    )
    components = bom["components"]
    purls = {row["purl"] for row in components if row.get("purl")}
    require(len({row["bom-ref"] for row in components}) == len(components), "Duplicate SBOM identities")
    if target == "dependencies":
        require(
            report["source"] == {"type": "sbom-file", "target": "/inputs/locked.purls"},
            "Wrong lock scan target",
        )
        require(purls == set(expected), "Incomplete frozen dependency inventory")
    else:
        require(expected["installed"], "Empty runtime Python inventory")
        require(
            report["source"]["type"] == "image"
            and report["source"]["target"]["imageID"] == expected["image_config_digest"],
            "Wrong runtime image identity",
        )
        actual = {
            (name(row["name"]), row["version"])
            for row in components
            if row.get("purl", "").startswith("pkg:pypi/")
        }
        require(
            set(map(tuple, expected["installed"])) <= actual, "Installed Python packages missing from SBOM"
        )
    findings = []
    for match in report["matches"]:
        vulnerability, artifact = match["vulnerability"], match["artifact"]
        severity = vulnerability["severity"]
        require(
            severity in SEVERITIES
            and all(
                isinstance(vulnerability.get(key), str) and vulnerability[key] for key in ("id", "namespace")
            ),
            "Invalid advisory identity or severity",
        )
        require(
            all(isinstance(artifact.get(key), str) and artifact[key] for key in ("name", "version", "type")),
            "Invalid affected package",
        )
        fix = vulnerability["fix"]
        # The pinned scanner emits Go's empty zero value for some Alpine APK
        # advisories lacking remediation metadata. Preserve that reported value
        # and classify it as unknown; severity gating is independent of fixes.
        reported_state = fix.get("state")
        state = reported_state
        if (reported_state == "" and fix.get("versions") == []
                and artifact["type"] == "apk"
                and isinstance(artifact.get("purl"), str) and artifact["purl"].startswith("pkg:apk/alpine/")
                and isinstance(report.get("distro"), dict) and report["distro"].get("name") == "alpine"
                and vulnerability["namespace"] == "nvd:cpe"):
            state = "unknown"
        require(
            state in {"fixed", "not-fixed", "wont-fix", "unknown"}
            and isinstance(fix["versions"], list)
            and all(isinstance(value, str) for value in fix["versions"]),
            "Invalid fix information",
        )
        findings.append(
            {
                "id": vulnerability["id"],
                "package": artifact["name"],
                "version": artifact["version"],
                "type": artifact["type"],
                "severity": severity,
                "fix_state": state,
                "fix_versions": fix["versions"],
                "blocking": target == "dependencies" or severity in {"High", "Critical", "Unknown"},
            }
        )
        if reported_state != state:
            findings[-1]["reported_fix_state"] = reported_state
    return {
        "result": "failed" if any(row["blocking"] for row in findings) else "passed",
        "findings": findings,
        "component_count": len(components),
        "database": status,
        "database_archive_checksum": checksum[0],
    }


def run(arguments, *, timeout=600):
    return subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=False)


def docker_scan(inputs, output, cache, *, target, online):
    container = "biomedmcp-security-" + uuid4().hex
    arguments = [
        "docker",
        "run",
        "--rm",
        "--name",
        container,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,mode=1777",
        "-v",
        f"{inputs}:/inputs:ro",
        "-v",
        f"{output}:/output",
        "-v",
        f"{cache}:/db:{'rw' if online else 'ro'}",
    ]
    if not online:
        arguments += [
            "--network",
            "none",
            "-e",
            "GRYPE_DB_AUTO_UPDATE=false",
            "-e",
            "GRYPE_DB_REQUIRE_UPDATE_CHECK=false",
        ]
    arguments += [
        SCANNER,
        "-c",
        "/inputs/grype.yaml",
        target,
        "--output",
        "json=/output/report.json",
        "--output",
        "cyclonedx-json=/output/sbom.cdx.json",
        "--fail-on",
        "low" if online else "high",
    ]
    try:
        process = run(arguments)
    finally:
        run(["docker", "rm", "-f", container], timeout=30)
    (output / "scanner.log").write_text(process.stderr)
    require(process.returncode in {0, 2}, "Scanner execution failed; inspect retained scanner.log")
    return process.returncode


def scan(root, output, image, *, cache=None):
    root, output = root.resolve(), output.resolve()
    require(
        not output.exists(), "Choose a fresh output directory; previous results cannot establish a new scan"
    )
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}", image), "Invalid local image reference")
    cache = cache or root / "reports/security-db"
    require(not cache.is_symlink(), "Database cache cannot be a symlink")
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True)
    sources = [root / "uv.lock", root / "pyproject.toml", root / "scripts/scan-security.py"]
    manifest = root / "source-manifest.json"
    if manifest.is_file():
        sources.append(manifest)
    before = {str(path.relative_to(root)): sha(path) for path in sources}
    receipt = {
        "schema_version": 1,
        "result": "failed",
        "scanned_at": datetime.now(UTC).isoformat(),
        "scanner_image": SCANNER,
        "inputs_sha256": before,
        "policy": "All dependency advisories block. Runtime High/Critical/Unknown findings block, including unfixed findings. No configured ignores, excludes or fix-state filters; pinned upstream matching policy applies.",
        "limitations": "Known-advisory scan and discovered package inventory only; no claim of exploitability, absence of vulnerabilities, complete native-library detection or source-code security.",
    }
    try:
        try:
            revision = run(["git", "-C", str(root), "rev-parse", "HEAD"], timeout=10)
            receipt["source_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
        except OSError:
            receipt["source_revision"] = None
        if manifest.is_file():
            receipt["export_tree_sha256"] = json.loads(manifest.read_text())["tree_sha256"]
        purls, local = lock_nodes(root / "uv.lock")
        receipt["local_workspace_packages_not_advisory_qualified"] = local
        identity = run(["docker", "image", "inspect", "--format", "{{.Id}}", image])
        require(
            identity.returncode == 0 and re.fullmatch(r"sha256:[a-f0-9]{64}", identity.stdout.strip()),
            "Local runtime image is unavailable",
        )
        image_id = identity.stdout.strip()
        receipt["image_id"] = image_id
        code = "import importlib.metadata,json,re;print(json.dumps(sorted({(re.sub(r'[-_.]+','-',d.metadata['Name']).lower(),d.version) for d in importlib.metadata.distributions()})))"
        installed = run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python", image_id, "-c", code]
        )
        require(installed.returncode == 0, "Runtime Python inventory failed")
        packages = json.loads(installed.stdout)
        frozen = tomllib.loads((root / "uv.lock").read_text())["package"]
        require(
            packages and set(map(tuple, packages)) <= {(name(row["name"]), row["version"]) for row in frozen},
            "Runtime Python versions differ from the reviewed lock",
        )
        receipt["installed_python"] = packages
        with tempfile.TemporaryDirectory(prefix="ubi-security-inputs-") as directory:
            inputs = Path(directory)
            (inputs / "locked.purls").write_text("\n".join(purls) + "\n")
            (inputs / "grype.yaml").write_text(CONFIG)
            receipt["scan_input_sha256"] = {
                "locked.purls": sha(inputs / "locked.purls"),
                "grype.yaml": sha(inputs / "grype.yaml"),
            }
            save = run(["docker", "image", "save", image_id, "--output", str(inputs / "runtime.tar")])
            require(save.returncode == 0, "Runtime archive save failed")
            receipt["runtime_archive_sha256"] = sha(inputs / "runtime.tar")
            identity = archive_identity(inputs / "runtime.tar", image_id)
            receipt["archive_identity"] = identity
            results = {}
            receipt["scans"] = results
            for label, target, expected in [
                ("dependencies", "purl:/inputs/locked.purls", purls),
                (
                    "runtime",
                    "docker-archive:/inputs/runtime.tar",
                    {**identity, "installed": packages},
                ),
            ]:
                folder = output / label
                folder.mkdir()
                exit_code = docker_scan(inputs, folder, cache, target=target, online=label == "dependencies")
                report, bom = (
                    json.loads((folder / file).read_text()) for file in ("report.json", "sbom.cdx.json")
                )
                results[label] = validate(report, bom, target=label, expected=expected)
                threshold = (
                    {"Low", "Medium", "High", "Critical"} if label == "dependencies" else {"High", "Critical"}
                )
                require(
                    exit_code
                    == (2 if any(row["severity"] in threshold for row in results[label]["findings"]) else 0),
                    "Scanner exit code disagrees with findings",
                )
                results[label]["scanner_exit_code"] = exit_code
                results[label]["outputs_sha256"] = {
                    file: sha(folder / file) for file in ("report.json", "sbom.cdx.json", "scanner.log")
                }
            require(
                results["dependencies"]["database"] == results["runtime"]["database"],
                "Database changed between scans",
            )
            receipt["scans"] = results
        require(
            before == {str(path.relative_to(root)): sha(path) for path in sources},
            "Source inputs changed during scan",
        )
        receipt["result"] = (
            "passed" if all(row["result"] == "passed" for row in results.values()) else "failed"
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        receipt["error"] = (
            str(error)
            if isinstance(error, ScanError)
            else "Security scan could not establish complete verified evidence; inspect retained reports and logs"
        )
    finally:
        (output / "security-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="biomedmcp:candidate")
    args = parser.parse_args()
    try:
        receipt = scan(ROOT, args.output, args.image)
    except (OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {"result": "failed", "error": "Invalid security scan input or pre-existing output directory"}
            )
        )
        return 1
    print(
        json.dumps(
            {
                "result": receipt["result"],
                "receipt": str(args.output / "security-receipt.json"),
                "blocking_findings": {
                    name: sum(row["blocking"] for row in value["findings"])
                    for name, value in receipt.get("scans", {}).items()
                },
            }
        )
    )
    return int(receipt["result"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
