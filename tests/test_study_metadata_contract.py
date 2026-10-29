"""Metadata discovery cannot manufacture assay counts or silently enable releases."""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
from fastmcp import Client
from pydantic import ValidationError
from test_native_studies import request

from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt
from biomedmcp.record_schemas import record_schema
from biomedmcp.studies import load_studies
from biomedmcp.study_metadata import StudyMetadataRecord


def installed(study):
    _, install = study
    analytics = install()
    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    return analytics, path, json.loads(path.read_text())


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "false"), ("enabled", 1), ("enabled", None),
        ("release", {"wrong": "shape"}), ("release", 1), ("release", ""), ("release", " "),
        ("source_url", 42), ("source_url", "javascript:alert(1)"),
        ("source_url", "https://user:secret@example.org/study"),
        ("source_url", "https://example.org/\ninvalid"),
        ("files", []), ("files", {"file": 1}),
        ("sha256", True), ("sha256", "not-a-digest"),
        ("id", "../foreign"), ("id", ""),
        ("assays", []), ("assays", {"expression": {"units": 12}}),
        ("assays", {"expression": {"units": ""}}),
    ],
)
def test_invalid_metadata_fails_before_registry_or_file_verification(study, monkeypatch, field, value):
    _, path, manifest = installed(study)
    manifest["studies"][0][field] = value
    path.write_text(json.dumps(manifest))
    from biomedmcp import studies

    def unexpected(*args):
        pytest.fail("Malformed metadata reached source-member verification")

    monkeypatch.setattr(studies, "verify_study_member", unexpected)
    with pytest.raises(ResearchError) as caught:
        load_studies()
    assert caught.value.code == "invalid_study_manifest"


def test_disabled_release_remains_disabled_without_needing_installed_members(study):
    _, path, manifest = installed(study)
    manifest["studies"][0] = {"enabled": False, "id": "uninstalled"}
    path.write_text(json.dumps(manifest))
    assert load_studies() == {}


def test_duplicate_enabled_id_cannot_replace_another_release(study):
    _, path, manifest = installed(study)
    duplicate = deepcopy(manifest["studies"][0])
    duplicate["release"] = "conflicting-release"
    manifest["studies"].append(duplicate)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ResearchError) as caught:
        load_studies()
    assert caught.value.code == "invalid_study_manifest"


def test_metadata_retains_manifest_hash_and_unknown_populations_without_reading_tables(study, monkeypatch):
    analytics, _, manifest = installed(study)
    entry = manifest["studies"][0]
    from biomedmcp.native import study as module

    def unexpected(*args, **kwargs):
        pytest.fail("Metadata discovery parsed a study table")

    monkeypatch.setattr(module, "read_table", unexpected)
    record = analytics.run("list", request())["studies"][0]
    assert record["record_type"] == "study_metadata"
    assert record["sample_count"] is record["patient_count"] is None
    assert record["count_missingness"] == "not_calculated_by_metadata_discovery"
    assert record["metadata_sha256"] == hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert record["sha256"] == entry["sha256"]
    assert record["mutation_coverage"] == entry["mutation_coverage"]
    assert "species" not in record and "assembly" not in record
    jsonschema.validate(record, record_schema("study"))


@pytest.mark.parametrize(
    "path,value",
    [
        (("enabled",), 1), (("enabled",), False), (("release",), {}),
        (("source_url",), "javascript:alert(1)"),
        (("sample_count",), 0), (("patient_count",), 4),
        (("assays", "expression", "available"), "yes"),
        (("assays", "expression", "sha256"), None),
        (("assays", "expression", "sample_coverage"), "all samples"),
        (("assays", "expression", "units"), ""),
        (("assays", "expression", "file"), "data_cna.txt"),
    ],
)
def test_record_rejects_changed_measurement_meanings(study, path, value):
    analytics, _, _ = installed(study)
    record = analytics.run("list", request())["studies"][0]
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        StudyMetadataRecord.model_validate(record)


async def test_public_search_get_schema_and_receipts_share_the_verified_metadata(study, monkeypatch):
    installed(study)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        caps = (await client.call_tool_mcp("capabilities", {"source": "study"})).structured_content
        schema = caps["record_schemas"]["study_metadata"]
        jsonschema.Draft202012Validator.check_schema(schema)
        found = await client.call_tool_mcp("search", {"entity": "study", "query": "ubi_synthetic"})
        assert not found.is_error
        result = found.structured_content
        assert verify_receipt(result)
        rows = result["records"]
        assert len(rows) == 1
        jsonschema.validate(rows[0], schema)
        fetched = await client.call_tool_mcp("get", {"entity": "study", "id": "ubi_synthetic"})
        assert not fetched.is_error and verify_receipt(fetched.structured_content)
        section = fetched.structured_content["sections"]["record"]["data"]
        jsonschema.validate(section, schema)
        for key in ("id", "release", "metadata_sha256", "sha256", "assays"):
            assert section[key] == rows[0][key]
        resource = await client.read_resource("biomedmcp://schemas/records/study")
        assert json.loads(resource[0].text)["$id"] == "biomedmcp://schemas/records/study"
