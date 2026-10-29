"""Public release retries must verify bytes before any mutation."""

import gzip
import importlib.util
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release-artifacts.py"


def wheel_bytes(name="biomedmcp", version="0.2.0"):
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as wheel:
        wheel.writestr(
            name + "-" + version + ".dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nRequires-Dist: example>=1; python_version >= '3.13'\nLicense-Expression: MIT\n\n",
        )
        wheel.writestr(name + "-" + version + ".dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
    return target.getvalue()


@pytest.fixture
def release():
    assert SCRIPT.is_file(), "Release retry implementation is missing"
    spec = importlib.util.spec_from_file_location("release_artifacts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workflow_uses_resumable_publisher():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert "scripts/release-artifacts.py publish" in workflow
    assert "gh release create" not in workflow
    assert "cancel-in-progress: false" in workflow


def test_bundle_ignores_filesystem_order_permissions_and_timestamps(release, tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    for name, data in [("z-1-py3-none-any.whl", b"Z"), ("a-1-py3-none-any.whl", b"A")]:
        (wheels / name).write_bytes(data)
    kwargs = {
        "version": "0.2.0",
        "revision": "a" * 40,
        "epoch": 1700000000,
        "tree_sha256": "b" * 64,
        "lock_sha256": "c" * 64,
    }
    first = release.bundle(wheels, tmp_path / "one", **kwargs)
    for path in wheels.iterdir():
        os.utime(path, (1800000000, 1800000000))
        path.chmod(0o755)
    second = release.bundle(wheels, tmp_path / "two", **kwargs)
    assert first == second
    for name in ("public-wheels.tar.gz", "release-receipt.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()
    assert gzip.decompress((tmp_path / "one/public-wheels.tar.gz").read_bytes())
    with tarfile.open(tmp_path / "one/public-wheels.tar.gz") as archive:
        assert archive.getnames() == ["a-1-py3-none-any.whl", "z-1-py3-none-any.whl"]
        assert all(m.uid == m.gid == 0 and m.mode == 0o644 for m in archive.getmembers())


@pytest.mark.parametrize("bad", ["empty", "symlink", "extra-file"])
def test_invalid_bundle_inputs_fail_before_output(release, tmp_path, bad):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    if bad == "symlink":
        (wheels / "a.whl").symlink_to(tmp_path / "missing")
    elif bad == "extra-file":
        (wheels / "secret.txt").write_text("synthetic sentinel")
    with pytest.raises(release.ReleaseError):
        release.bundle(
            wheels,
            tmp_path / "out",
            version="0.2.0",
            revision="a" * 40,
            epoch=1700000000,
            tree_sha256="b" * 64,
            lock_sha256="c" * 64,
        )
    assert not (tmp_path / "out").exists()


class Remote:
    """Independent fake server state; interrupted calls can still take effect."""

    def __init__(self, release, directory, receipt):
        self.module = release
        self.directory = directory
        self.receipt = receipt
        self.repository = {"full_name": release.REPOSITORY, "private": False, "permissions": {"push": True}}
        self.tag = None
        self.releases = []
        self.assets = []
        self.contents = {}
        self.mutations = []
        self.interrupt = None
        self.annotated = None
        self.next_id = 100

    def changed(self, operation):
        self.mutations.append(operation)
        if self.interrupt == operation:
            self.interrupt = None
            raise self.module.ReleaseError("Synthetic lost response")

    def verify_attestations(self, directory, receipt):
        assert directory == self.directory and receipt == self.receipt
        self.module.wheel_sbom(directory, receipt)

    def api(self, path, *, method="GET", payload=None, missing=False):
        prefix = "repos/" + self.module.REPOSITORY
        if path == prefix:
            return self.repository.copy()
        if path == prefix + "/git/ref/tags/v" + self.receipt["version"]:
            if self.tag is None:
                assert missing
                return None
            return {
                "object": {"type": "tag" if self.annotated else "commit", "sha": self.annotated or self.tag}
            }
        if path == prefix + "/git/tags/" + str(self.annotated):
            return {"object": {"type": "commit", "sha": self.tag}}
        if path == prefix + "/git/commits/" + self.receipt["source_commit"]:
            return {"sha": self.receipt["source_commit"]}
        if path == prefix + "/git/refs":
            assert method == "POST" and self.tag is None
            assert payload["ref"] == "refs/tags/v" + self.receipt["version"]
            self.tag = payload["sha"]
            self.changed("tag")
            return {"object": {"type": "commit", "sha": self.tag}}
        if path == prefix + "/releases":
            assert method == "POST" and not self.releases
            self.releases.append(dict(id=1, **payload))
            self.changed("draft")
            return self.releases[0].copy()
        if path == prefix + "/releases/1":
            if method == "PATCH":
                assert payload == {"draft": False}
                self.releases[0]["draft"] = False
                self.changed("publish")
            else:
                assert method == "GET"
            return self.releases[0].copy()
        pytest.fail(f"Unexpected API call {method} {path}")

    def pages(self, path):
        if path.endswith("/releases"):
            return [r.copy() for r in self.releases]
        assert path.endswith("/releases/1/assets")
        return [a.copy() for a in self.assets]

    def asset_sha(self, asset_id):
        data = self.contents[asset_id]
        return len(data), self.module.sha(data)

    def upload(self, tag, path):
        assert tag == "v" + self.receipt["version"]
        assert path.name not in {a["name"] for a in self.assets}
        self.next_id += 1
        data = path.read_bytes()
        self.assets.append({"name": path.name, "size": len(data), "id": self.next_id, "state": "uploaded"})
        self.contents[self.next_id] = data
        self.changed("upload:" + path.name)


@pytest.fixture
def prepared(release, tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "biomedmcp-0.2.0-py3-none-any.whl").write_bytes(wheel_bytes())
    directory = tmp_path / "assets"
    receipt = release.bundle(
        wheels,
        directory,
        version="0.2.0",
        revision="a" * 40,
        epoch=1700000000,
        tree_sha256="b" * 64,
        lock_sha256="c" * 64,
    )
    return directory, receipt, Remote(release, directory, receipt)


def test_new_release_and_complete_rerun_are_idempotent(release, prepared):
    directory, receipt, remote = prepared
    result = release.publish(remote, directory, receipt, "Reviewed changelog")
    assert result["status"] == "published"
    assert remote.mutations == [
        "tag",
        "draft",
        "upload:public-wheels.tar.gz",
        "upload:release-receipt.json",
        "publish",
    ]
    remote.mutations.clear()
    result = release.publish(remote, directory, receipt, "Reviewed changelog")
    assert result["status"] == "already_published"
    assert remote.mutations == []


@pytest.mark.parametrize(
    "interrupt", ["tag", "draft", "upload:public-wheels.tar.gz", "upload:release-receipt.json", "publish"]
)
def test_lost_response_resumes_without_duplicate_or_replaced_assets(release, prepared, interrupt):
    directory, receipt, remote = prepared
    remote.interrupt = interrupt
    with pytest.raises(release.ReleaseError, match="lost response"):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert release.publish(remote, directory, receipt, "Reviewed changelog")["status"] in {
        "published",
        "already_published",
    }
    assert (
        remote.mutations.count("tag")
        == remote.mutations.count("draft")
        == remote.mutations.count("publish")
        == 1
    )
    assert len(remote.assets) == 2
    assert remote.mutations.count("upload:public-wheels.tar.gz") == 1
    assert remote.mutations.count("upload:release-receipt.json") == 1


@pytest.mark.parametrize("draft", [True, False])
@pytest.mark.parametrize(
    "conflict",
    ["tag", "body", "title", "bytes", "size", "extra", "duplicate", "starter", "missing-published"],
)
def test_conflicting_existing_release_stops_without_mutations(release, prepared, conflict, draft):
    directory, receipt, remote = prepared
    release.publish(remote, directory, receipt, "Reviewed changelog")
    remote.releases[0]["draft"] = draft
    if conflict == "tag":
        remote.tag = "d" * 40
    elif conflict == "body":
        remote.releases[0]["body"] = "unreviewed notes"
    elif conflict == "title":
        remote.releases[0]["name"] = "different title"
    elif conflict == "bytes":
        asset = remote.assets[0]
        remote.contents[asset["id"]] = b"X" * asset["size"]
    elif conflict == "size":
        remote.assets[0]["size"] += 1
    elif conflict == "extra":
        remote.assets.append({"name": "unreviewed.whl", "id": 999, "size": 5, "state": "uploaded"})
    elif conflict == "duplicate":
        remote.assets.append(remote.assets[0].copy())
    elif conflict == "starter":
        remote.assets[0]["state"] = "starter"
    elif conflict == "missing-published":
        if draft:
            remote.assets.pop()
            remote.mutations.clear()
            assert release.publish(remote, directory, receipt, "Reviewed changelog")["status"] == "published"
            assert remote.mutations == ["upload:release-receipt.json", "publish"]
            return
        remote.assets.pop()
    remote.mutations.clear()
    with pytest.raises(release.ReleaseError):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert remote.mutations == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("full_name", "another-org/biomedmcp"),
        ("private", True),
        ("permissions", {"push": False}),
    ],
)
def test_wrong_destination_or_unobservable_drafts_stop_before_mutations(release, prepared, field, value):
    directory, receipt, remote = prepared
    remote.repository[field] = value
    with pytest.raises(release.ReleaseError):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert remote.mutations == []


def test_annotated_matching_tag_is_verified(release, prepared):
    directory, receipt, remote = prepared
    remote.tag = receipt["source_commit"]
    remote.annotated = "d" * 40
    assert release.publish(remote, directory, receipt, "Reviewed changelog")["status"] == "published"
    assert "tag" not in remote.mutations


def test_conflicting_tag_without_release_stops_before_creation(release, prepared):
    directory, receipt, remote = prepared
    remote.tag = "d" * 40
    with pytest.raises(release.ReleaseError, match="different source"):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert remote.mutations == []


@pytest.mark.parametrize(
    "field,value", [("source_commit", "d" * 40), ("archive", {}), ("repository", "other/repo")]
)
def test_changed_local_receipt_stops_before_any_remote_call(release, prepared, field, value):
    directory, receipt, remote = prepared
    receipt[field] = value
    with pytest.raises(release.ReleaseError):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert remote.mutations == []


def test_api_errors_are_not_absence_and_do_not_echo_sentinels(release, monkeypatch):
    import subprocess

    def observed(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, b"HTTP/2.0 403 Forbidden\r\n\r\n{}", b"synthetic-secret"
        )

    monkeypatch.setattr(release.subprocess, "run", observed)
    with pytest.raises(release.ReleaseError, match="HTTP 403") as error:
        release.GitHub().api("repos/example", missing=True)
    assert "synthetic-secret" not in str(error.value)


def test_api_explicit_get_404_is_distinct_from_transport_failure(release, monkeypatch):
    import subprocess

    def observed(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, b"HTTP/2.0 404 Not Found\n\n{}", b"synthetic-secret")

    monkeypatch.setattr(release.subprocess, "run", observed)
    assert release.GitHub().api("repos/example", missing=True) is None
    with pytest.raises(release.ReleaseError):
        release.GitHub().api("repos/example", method="POST", missing=True)
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, b"", b"synthetic-secret"),
    )
    with pytest.raises(release.ReleaseError, match="observation failed"):
        release.GitHub().api("repos/example", missing=True)


@pytest.fixture
def public_checkout(release, tmp_path):
    import subprocess

    root = tmp_path / "public"
    root.mkdir()
    files = {
        "pyproject.toml": '[project]\nversion = "0.2.0"\n',
        "uv.lock": "synthetic lock\n",
        "LICENSE": "SYNTHETIC TEST LICENSE; no repository license decision\n",
        "CHANGELOG.md": "Reviewed changelog\n",
    }
    for name, text in files.items():
        (root / name).write_text(text)
    rows = {name: {"sha256": release.sha((root / name).read_bytes()), "executable": False} for name in files}
    tree = release.sha(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    manifest = {"format": 1, "publication_ready": True, "files": rows, "tree_sha256": tree}
    (root / "source-manifest.json").write_bytes(release.encoded(manifest))

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Synthetic Qualification")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-qm", "Synthetic public checkout")
    return root, git("rev-parse", "HEAD"), manifest


def test_source_identity_matches_exact_clean_export(release, public_checkout):
    root, revision, manifest = public_checkout
    assert release.source_identity(root, "0.2.0", revision) == (
        manifest["tree_sha256"],
        release.sha((root / "uv.lock").read_bytes()),
    )


@pytest.mark.parametrize(
    "change",
    [
        "license-missing",
        "license-empty",
        "unlicensed",
        "source-drift",
        "manifest-drift",
        "wrong-head",
        "version",
        "untracked",
        "symlink",
        "unsafe-path",
    ],
)
def test_source_changes_or_absent_license_stop_before_publication(release, public_checkout, change):
    root, revision, manifest = public_checkout
    version = "0.2.0"
    if change == "license-missing":
        (root / "LICENSE").unlink()
    elif change == "license-empty":
        (root / "LICENSE").write_text("")
    elif change == "unlicensed":
        manifest["publication_ready"] = False
    elif change == "source-drift":
        (root / "uv.lock").write_text("Changed dependency lock\n")
    elif change == "manifest-drift":
        manifest["tree_sha256"] = "d" * 64
    elif change == "wrong-head":
        revision = "d" * 40
    elif change == "version":
        version = "0.3.0"
    elif change == "untracked":
        (root / "unreviewed.py").write_text("UNREVIEWED = True\n")
    elif change == "symlink":
        target = root.parent / "unreviewed-license"
        target.write_bytes((root / "LICENSE").read_bytes())
        (root / "LICENSE").unlink()
        (root / "LICENSE").symlink_to(target)
    elif change == "unsafe-path":
        manifest["files"]["../private"] = {"sha256": "d" * 64, "executable": False}
    (root / "source-manifest.json").write_bytes(release.encoded(manifest))
    with pytest.raises(release.ReleaseError):
        release.source_identity(root, version, revision)


@pytest.mark.parametrize("action", ["bundle", "publish"])
def test_actual_cli_uses_public_export_and_stops_wrong_repository_without_gh(
    release, public_checkout, tmp_path, action
):
    import subprocess
    import sys

    root, revision, _ = public_checkout
    env = {
        **os.environ,
        "GITHUB_REPOSITORY": "example-org/unapproved-repository",
        "GITHUB_SHA": revision,
        "RELEASE_VERSION": "0.2.0",
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), action, "--root", str(root), "--assets", str(tmp_path / "unused")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Only the approved public" in result.stderr
    assert "Traceback" not in result.stderr


def test_actual_cli_constructs_deterministic_assets_from_clean_public_export(
    release, public_checkout, tmp_path
):
    import subprocess
    import sys

    root, revision, manifest = public_checkout
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "fixture-0.2.0-py3-none-any.whl").write_bytes(wheel_bytes("fixture"))
    env = {
        **os.environ,
        "GITHUB_REPOSITORY": release.REPOSITORY,
        "GITHUB_SHA": revision,
        "RELEASE_VERSION": "0.2.0",
        "SOURCE_DATE_EPOCH": "1700000000",
    }
    for name in ("first", "second"):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "bundle",
                "--root",
                str(root),
                "--wheels",
                str(wheels),
                "--assets",
                str(tmp_path / name),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert (
            receipt["source_commit"] == revision and receipt["source_tree_sha256"] == manifest["tree_sha256"]
        )
    assert (tmp_path / "first/release-receipt.json").read_bytes() == (
        tmp_path / "second/release-receipt.json"
    ).read_bytes()


def test_collection_pagination_never_treats_budget_exhaustion_as_absence(release, monkeypatch):
    github = release.GitHub()
    monkeypatch.setattr(github, "api", lambda path: [{}] * 100)
    with pytest.raises(release.ReleaseError, match="observation budget"):
        github.pages("repos/example/releases")


def test_collection_pagination_observes_drafts_beyond_first_page(release, monkeypatch):
    github = release.GitHub()
    observed = []

    def api(path):
        observed.append(path)
        return [{}] * 100 if path.endswith("&page=1") else [{"tag_name": "v0.2.0", "draft": True}]

    monkeypatch.setattr(github, "api", api)
    assert github.pages("repos/example/releases")[-1] == {"tag_name": "v0.2.0", "draft": True}
    assert len(observed) == 2


@pytest.mark.parametrize(
    "failure", [None, "tag", "draft", "upload:public-wheels.tar.gz", "upload:release-receipt.json", "publish"]
)
def test_actual_publisher_cli_recovers_lost_responses_with_persisted_remote_state(
    release, public_checkout, tmp_path, failure
):
    import subprocess
    import sys

    root, revision, manifest = public_checkout
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "fixture-0.2.0-py3-none-any.whl").write_bytes(wheel_bytes("fixture"))
    directory = tmp_path / "assets"
    release.bundle(
        wheels,
        directory,
        version="0.2.0",
        revision=revision,
        epoch=1700000000,
        tree_sha256=manifest["tree_sha256"],
        lock_sha256=release.sha((root / "uv.lock").read_bytes()),
    )
    executable = tmp_path / "bin/gh"
    executable.parent.mkdir()
    fixture = ROOT / "tests/fixtures/release-gh-fixture.py"
    executable.write_text(f"#!{sys.executable}\n" + fixture.read_text().split("\n", 1)[1])
    executable.chmod(0o755)
    state_file = tmp_path / "remote.json"
    state_file.write_text(
        json.dumps(
            {
                "tag": None,
                "releases": [],
                "assets": [],
                "contents": {},
                "mutations": [],
                "fail": failure,
                "sbom": release.wheel_sbom(
                    directory, json.loads((directory / "release-receipt.json").read_text())
                ),
            }
        )
    )
    env = {
        **os.environ,
        "PATH": str(executable.parent) + os.pathsep + os.environ["PATH"],
        "UBI_RELEASE_TEST_STATE": str(state_file),
        "GH_HOST": "untrusted.invalid",
        "GITHUB_REPOSITORY": release.REPOSITORY,
        "GITHUB_SHA": revision,
        "RELEASE_VERSION": "0.2.0",
    }
    command = [sys.executable, str(SCRIPT), "publish", "--root", str(root), "--assets", str(directory)]
    first = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert first.returncode == (1 if failure else 0), first.stderr
    assert "synthetic-release-credential-sentinel" not in first.stdout + first.stderr
    assert "Traceback" not in first.stderr
    second = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["status"] in {"published", "already_published"}
    state = json.loads(state_file.read_text())
    assert state["tag"] == revision and state["releases"][0]["draft"] is False
    assert state["mutations"] == [
        "tag",
        "draft",
        "upload:public-wheels.tar.gz",
        "upload:release-receipt.json",
        "publish",
    ]
    for _ in range(2):
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0 and json.loads(result.stdout)["status"] == "already_published"
    assert json.loads(state_file.read_text())["mutations"] == state["mutations"]


def test_upload_host_is_bound_independently_of_gh_host(release, monkeypatch, tmp_path):
    import subprocess

    calls = []
    monkeypatch.setenv("GH_HOST", "untrusted.invalid")

    def capture(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(release.subprocess, "run", capture)
    release.GitHub().upload("v0.2.0", tmp_path / "synthetic-asset")
    assert calls[0][calls[0].index("--repo") + 1] == "github.com/" + release.REPOSITORY
    assert "--clobber" not in calls[0]


def test_exact_uv_output_marker_is_excluded_from_archive(release, tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / ".gitignore").write_bytes(b"*")
    (wheels / "fixture-0.2.0-py3-none-any.whl").write_bytes(wheel_bytes("fixture"))
    release.bundle(
        wheels,
        tmp_path / "out",
        version="0.2.0",
        revision="a" * 40,
        epoch=1700000000,
        tree_sha256="b" * 64,
        lock_sha256="c" * 64,
    )
    with tarfile.open(tmp_path / "out/public-wheels.tar.gz") as archive:
        assert archive.getnames() == ["fixture-0.2.0-py3-none-any.whl"]


@pytest.mark.parametrize("kind", ["unexpected-bytes", "symlink"])
def test_unrecognized_or_symlinked_build_marker_fails(release, tmp_path, kind):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "fixture-0.2.0-py3-none-any.whl").write_bytes(wheel_bytes("fixture"))
    if kind == "unexpected-bytes":
        (wheels / ".gitignore").write_bytes(b"Unreviewed marker\n")
    else:
        (wheels / ".gitignore").symlink_to(tmp_path / "outside")
    with pytest.raises(release.ReleaseError, match="marker"):
        release.bundle(
            wheels,
            tmp_path / "out",
            version="0.2.0",
            revision="a" * 40,
            epoch=1700000000,
            tree_sha256="b" * 64,
            lock_sha256="c" * 64,
        )
    assert not (tmp_path / "out").exists()


def test_sbom_binds_archive_and_preserves_unresolved_metadata(release, prepared):
    directory, receipt, _ = prepared
    report = release.wheel_sbom(directory, receipt)
    assert report == release.wheel_sbom(directory, receipt)
    (component,) = report["components"]
    assert report["bomFormat"] == "CycloneDX" and report["specVersion"] == "1.6"
    assert component["purl"] == "pkg:pypi/biomedmcp@0.2.0"
    assert component["hashes"][0]["content"] == receipt["wheels"][0]["sha256"]
    assert {"name": "ubi:wheel:license-expression", "value": "MIT"} in component["properties"]
    assert any(p["name"] == "ubi:wheel:requires-dist" and ";" in p["value"] for p in component["properties"])
    assert "dependencies" not in report and "licenses" not in component
    assert report["metadata"]["component"]["hashes"][0]["content"] == receipt["archive"]["sha256"]


@pytest.mark.parametrize(
    "case",
    [
        "wrong-package",
        "wrong-version",
        "duplicate-name",
        "duplicate-path",
        "traversal",
        "bad-utf8",
        "oversized-metadata",
        "not-zip",
    ],
)
def test_invalid_wheel_metadata_stops_attestation(release, case):
    metadata = "Metadata-Version: 2.4\nName: biomedmcp\nVersion: 0.2.0\n\n"
    if case == "wrong-package":
        metadata = metadata.replace("biomedmcp", "wrong")
    if case == "wrong-version":
        metadata = metadata.replace("0.2.0", "9.9.9")
    if case == "duplicate-name":
        metadata = metadata.replace("Name: biomedmcp", "Name: biomedmcp\nName: wrong")
    if case == "oversized-metadata":
        metadata += "x" * (1024 * 1024)
    raw = metadata.encode() if case != "bad-utf8" else b"\xff"
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as wheel:
        wheel.writestr("biomedmcp-0.2.0.dist-info/METADATA", raw)
        if case == "duplicate-path":
            with pytest.warns(UserWarning):
                wheel.writestr("biomedmcp-0.2.0.dist-info/METADATA", raw)
        if case == "traversal":
            wheel.writestr("../outside", b"data")
    with pytest.raises(release.ReleaseError):
        release.wheel_component(
            "biomedmcp-0.2.0-py3-none-any.whl", b"not zip" if case == "not-zip" else target.getvalue()
        )


@pytest.mark.parametrize(
    "case", ["archive-bytes", "member-hash", "missing-member", "duplicate-row", "bool-size", "source-hash"]
)
def test_invalid_sbom_receipt_stops_attestation(release, prepared, case):
    directory, receipt, _ = prepared
    receipt = json.loads(json.dumps(receipt))
    if case == "archive-bytes":
        (directory / "public-wheels.tar.gz").write_bytes(b"changed")
    if case == "member-hash":
        receipt["wheels"][0]["sha256"] = "0" * 64
    if case == "missing-member":
        receipt["wheels"][0]["name"] = "absent-0.2.0-py3-none-any.whl"
    if case == "duplicate-row":
        receipt["wheels"].append(receipt["wheels"][0].copy())
    if case == "bool-size":
        receipt["wheels"][0]["size"] = True
    if case == "source-hash":
        receipt["source_tree_sha256"] = "invalid"
    with pytest.raises(release.ReleaseError):
        release.wheel_sbom(directory, receipt)


def test_failed_attestation_stops_before_remote_activity(release, prepared, monkeypatch):
    directory, receipt, remote = prepared

    def fail(*args):
        raise release.ReleaseError("Synthetic signature rejection")

    monkeypatch.setattr(remote, "verify_attestations", fail)
    monkeypatch.setattr(remote, "api", lambda *a, **kw: pytest.fail("Remote activity before gate"))
    with pytest.raises(release.ReleaseError, match="signature rejection"):
        release.publish(remote, directory, receipt, "Reviewed changelog")
    assert remote.mutations == [] and remote.tag is None and remote.releases == []


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "signature-rejected",
        "wrong-subject",
        "wrong-type",
        "changed-sbom",
        "empty",
        "malformed",
        "invalid-subject",
    ],
)
def test_verifier_enforces_trust_scope_digest_and_exact_sbom(release, prepared, monkeypatch, case):
    import subprocess

    directory, receipt, _ = prepared
    calls = []

    def verify(command, **kwargs):
        calls.append(command)
        path = Path(command[3])
        kind = command[command.index("--predicate-type") + 1]
        for flag, value in [
            ("--hostname", "github.com"),
            ("--repo", release.REPOSITORY),
            ("--signer-workflow", release.SIGNER_WORKFLOW),
            ("--signer-digest", receipt["source_commit"]),
            ("--source-digest", receipt["source_commit"]),
        ]:
            assert command[command.index(flag) + 1] == value
        assert "--deny-self-hosted-runners" in command and kwargs["timeout"] == 60
        predicate = release.wheel_sbom(directory, receipt) if kind == release.SBOM_TYPE else {}
        statement = {
            "subject": [{"digest": {"sha256": release.sha(path.read_bytes())}}],
            "predicateType": kind,
            "predicate": predicate,
        }
        if case == "wrong-subject":
            statement["subject"][0]["digest"]["sha256"] = "0" * 64
        if case == "wrong-type":
            statement["predicateType"] = "wrong"
        if case == "invalid-subject":
            statement["subject"] = [False]
        if case == "changed-sbom" and kind == release.SBOM_TYPE:
            predicate["components"] = []
        result = [{"verificationResult": {"statement": statement}}]
        if case == "empty":
            result = []
        raw = b"invalid JSON" if case == "malformed" else json.dumps(result).encode()
        return subprocess.CompletedProcess(
            command, 1 if case == "signature-rejected" else 0, raw, b"synthetic-credential-sentinel"
        )

    monkeypatch.setattr(release.subprocess, "run", verify)
    if case == "valid":
        release.GitHub().verify_attestations(directory, receipt)
        assert len(calls) == 3
    else:
        with pytest.raises(release.ReleaseError) as error:
            release.GitHub().verify_attestations(directory, receipt)
        assert "synthetic-credential-sentinel" not in str(error.value)


def test_workflow_attests_between_security_and_publication():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["release"]
    assert job["environment"] == "public-release"
    assert job["permissions"] == {"contents": "write", "id-token": "write", "attestations": "write"}
    steps = workflow["jobs"]["release"]["steps"]
    indexed = {s.get("id"): i for i, s in enumerate(steps) if s.get("id")}
    assert indexed["provenance"] < indexed["wheel_sbom"]
    for key in ["provenance", "wheel_sbom"]:
        assert steps[indexed[key]]["uses"] == "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
    security = next(i for i, s in enumerate(steps) if "scan-security.py" in s.get("run", ""))
    publish = next(i for i, s in enumerate(steps) if "release-artifacts.py publish" in s.get("run", ""))
    assert security < indexed["provenance"] < indexed["wheel_sbom"] < publish
    assert all(
        s.get("if") != "always()"
        for s in [steps[indexed["provenance"]], steps[indexed["wheel_sbom"]], steps[publish]]
    )
