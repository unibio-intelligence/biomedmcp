"""Shared checksummed public study fixture."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from biomedmcp.native.study import StudyAnalytics


@pytest.fixture(autouse=True)
def synthetic_source_permissions(request, monkeypatch):
    """Science fixtures qualify adapter behavior, never real data-use rights.

    Permission-boundary tests use the shipped policy without this fixture.
    This is a Python test mock, not a runtime/environment license override.
    """
    if request.node.get_closest_marker("source_permissions"):
        return
    from biomedmcp import source_licensing
    from biomedmcp.source_policy import source_names

    fixture_sources = set(source_names())
    monkeypatch.setattr(
        source_licensing,
        "availability",
        lambda source: (True, None) if source in fixture_sources else (False, "Unknown fixture source"),
    )
    monkeypatch.setattr(
        source_licensing, "operation_allowed", lambda source, operation: source in fixture_sources
    )


@pytest.fixture(autouse=True)
def isolated_local_cli_state(tmp_path, monkeypatch):
    monkeypatch.setenv("UBI_LOCAL_STATE_DIR", str(tmp_path / "local-cli-state"))


@pytest.fixture
def study(tmp_path, monkeypatch):
    root = tmp_path / "studies"
    directory = root / "ubi_synthetic"
    shutil.copytree(Path(__file__).parent / "fixtures/studies/ubi_synthetic", directory)

    def manifest(coverage=True):
        files = {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*")
            if p.is_file()
        }
        data = {
            "id": "ubi_synthetic",
            "enabled": True,
            "release": "synthetic-v1",
            "source_url": "https://example.org/synthetic",
            "data_rights": {
                "license": "CC0-1.0",
                "evidence_url": "https://example.org/synthetic",
                "scope": "all_declared_files",
            },
            "files": files,
            "sha256": hashlib.sha256(
                json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
        if coverage:
            data["mutation_coverage"] = {"samples": ["S1", "S2", "S3", "S4"], "genes": "all"}
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps({"studies": [data]}))
        monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", str(path))
        monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", str(root))
        return StudyAnalytics()

    return directory, manifest
