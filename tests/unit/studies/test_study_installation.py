import hashlib
import json
from pathlib import Path

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.study_installation import install_release


def reviewed(study):
    directory, install = study
    install()
    manifest = directory.parent.parent / "manifest.json"
    document = json.loads(manifest.read_text())
    document["studies"][0]["data_rights"] = {
        "license": "CC0-1.0",
        "evidence_url": "https://example.org/synthetic-permission",
        "scope": "all_declared_files",
    }
    manifest.write_text(json.dumps(document))
    return directory, manifest


def test_create_only_release_retains_every_hash_and_can_be_reverified(study, tmp_path):
    directory, manifest = reviewed(study)
    destination = tmp_path / "releases"
    first = install_release(manifest, directory.parent, destination)
    second = install_release(manifest, directory.parent, destination)
    assert first["status"] == "installed" and second["status"] == "verified_existing"
    published = Path(first["directory"])
    assert published.parent.name == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert (published / "manifest.json").read_bytes() == manifest.read_bytes()
    for relative, expected in json.loads(manifest.read_text())["studies"][0]["files"].items():
        member = published / "studies" / directory.name / relative
        assert hashlib.sha256(member.read_bytes()).hexdigest() == expected
        assert member.stat().st_mode & 0o222 == 0
    assert not list(destination.glob(".study-stage-*"))


@pytest.mark.parametrize("license", [None, "CC-BY-NC-4.0", "CC-BY-ND-4.0", "unknown", "Apache-2.0"])
def test_code_license_or_restricted_unknown_data_never_installs(study, tmp_path, license):
    directory, manifest = reviewed(study)
    document = json.loads(manifest.read_text())
    document["studies"][0]["data_rights"]["license"] = license
    manifest.write_text(json.dumps(document))
    with pytest.raises(ResearchError, match="reviewed permissive rights") as caught:
        install_release(manifest, directory.parent, tmp_path / "releases")
    assert caught.value.code == "source_license_unreleased"
    assert not (tmp_path / "releases").exists()


def test_copy_time_change_never_publishes_or_leaves_staging(study, tmp_path, monkeypatch):
    directory, manifest = reviewed(study)
    from biomedmcp import study_installation

    original = study_installation._verify_studies

    def change_after_verify(path, root):
        result = original(path, root)
        if root == directory.parent:
            (directory / "data_mutations.txt").write_text("changed after verification\n")
        return result

    monkeypatch.setattr(study_installation, "_verify_studies", change_after_verify)
    destination = tmp_path / "releases"
    with pytest.raises(ResearchError) as caught:
        install_release(manifest, directory.parent, destination)
    assert caught.value.code == "study_version_changed"
    assert list(destination.iterdir()) == []


def test_declared_new_release_preserves_old_installation_and_revalidates_new_bytes(study, tmp_path):
    directory, manifest = reviewed(study)
    destination = tmp_path / "releases"
    first = install_release(manifest, directory.parent, destination)
    old_manifest = (Path(first["directory"]) / "manifest.json").read_bytes()
    document = json.loads(manifest.read_text())
    document["studies"][0]["release"] = "synthetic-v2"
    manifest.write_text(json.dumps(document))
    second = install_release(manifest, directory.parent, destination)
    assert first["identity"] != second["identity"]
    assert (Path(first["directory"]) / "manifest.json").read_bytes() == old_manifest
    assert (
        json.loads((Path(second["directory"]) / "manifest.json").read_text())["studies"][0]["release"]
        == "synthetic-v2"
    )


def test_existing_tampered_release_is_never_replaced(study, tmp_path):
    directory, manifest = reviewed(study)
    destination = tmp_path / "releases"
    first = install_release(manifest, directory.parent, destination)
    member = Path(first["directory"]) / "studies" / directory.name / "data_mutations.txt"
    member.chmod(0o644)
    member.write_text("tampered\n")
    with pytest.raises(ResearchError) as caught:
        install_release(manifest, directory.parent, destination)
    assert caught.value.code == "study_version_changed"
    assert member.read_text() == "tampered\n"


def test_incomplete_reserved_identity_requires_reconciliation(study, tmp_path):
    directory, manifest = reviewed(study)
    destination = tmp_path / "releases"
    identity = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (destination / identity).mkdir(parents=True)
    with pytest.raises(ResearchError) as caught:
        install_release(manifest, directory.parent, destination)
    assert caught.value.code == "provider_busy" and caught.value.retryable
    assert (destination / identity).is_dir()
