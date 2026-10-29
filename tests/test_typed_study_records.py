"""Measurement meanings enforced at study output and exposed to agent clients."""

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
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt
from biomedmcp.study_records import StudyMeasurementRecord


@pytest.fixture
def measurement(study):
    directory, install = study
    (directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt").write_text(
        "Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\t0\t2\tNA\tNA\n"
    )
    return directory, install().run("query", request(gene="ERBB2", type="expression"))


def test_measurement_family_retains_zero_missingness_inputs_and_units(measurement):
    directory, row = measurement
    assert row["record_type"] == "study_measurements"
    assert row["assertion_type"] == "verified_release_measurements"
    assert row["values"] == {"S1": 0.0, "S2": 2.0}
    assert row["counts"] == {"0.0": 1, "2.0": 1}
    assert row["total_samples"] == row["evaluable_samples"] == row["measured_samples"] == 2
    assert row["eligible_samples"] == row["clinical_samples"] == 4
    assert row["missing_samples"] == 2
    coverage = row["measurement_coverage"]["expression:ERBB2"]
    assert coverage["missing_sample_ids"] == ["S3", "S4"]
    assert coverage["units"] == "z_score"
    assert row["units_basis"] == "managed cBioPortal file format"
    assert "species" not in row and "assembly" not in row
    assert row["identity_scope"] == "gene row within this verified study release"
    assert row["sample_unit"] == "samples"
    assert "no imputation or normalization" in row["method"]
    for locator in row["input_locators"]:
        assert locator["sha256"] == hashlib.sha256((directory / locator["file"]).read_bytes()).hexdigest()
    jsonschema.validate(row, StudyMeasurementRecord.model_json_schema())


@pytest.mark.parametrize("kind", ["cna", "expression"])
def test_both_matrix_assays_use_the_family_without_changing_values(study, kind):
    _, install = study
    row = install().run("query", request(gene="ERBB2", type=kind))
    assert row["record_type"] == "study_measurements"
    assert row["total_samples"] == 4
    assert row["values"] == (
        {"S1": 2.0, "S2": 0.0, "S3": 1.0, "S4": -2.0}
        if kind == "cna"
        else {"S1": 2.0, "S2": 1.0, "S3": 4.0, "S4": 2.0}
    )
    assert row["input_locators"][1]["gene"] == "ERBB2"


@pytest.mark.parametrize(
    "path,value",
    [
        (("total_samples",), 0),
        (("measured_samples",), True),
        (("missing_samples",), "2"),
        (("eligible_samples",), 5),
        (("clinical_samples",), 1),
        (("values", "S1"), True),
        (("values", "S1"), "0"),
        (("values", "S1"), float("nan")),
        (("values", "S1"), float("inf")),
        (("counts", "0.0"), 0),
        (("measurement",), "tpm"),
        (("denominator",), "patients"),
        (("measurement_coverage", "expression:ERBB2", "units"), "TPM"),
        (("measurement_coverage", "expression:ERBB2", "missing_sample_ids"), ["S1", "S3"]),
        (("measurement_coverage", "expression:ERBB2", "missing_sample_ids"), ["S3", "S3"]),
        (("measurement_coverage", "expression:ERBB2", "missing_sample_ids_truncated"), True),
        (("measurement_coverage", "expression:ERBB2", "measured_samples"), 3),
        (("release", "id"), "foreign"),
        (("release", "sha256"), "missing"),
        (("input_locators", 1, "gene"), "TP53"),
        (("input_locators", 1, "sha256"), "0" * 64),
        (("input_locators", 1, "role"), "clinical_sample_population"),
        (("input_locators", 0, "file"), "data_clinical_patient.txt"),
        (("sample_unit",), "patients"),
    ],
)
def test_contradictory_measurement_meanings_are_rejected(measurement, path, value):
    row = deepcopy(measurement[1])
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        StudyMeasurementRecord.model_validate(row)


async def test_actual_mcp_exposes_inspectable_schema_and_receipted_measurements(measurement, monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        capabilities = (await client.call_tool_mcp("capabilities", {"source": "study"})).structured_content
        schema = capabilities["record_schemas"]["study_measurements"]
        jsonschema.Draft202012Validator.check_schema(schema)
        result = await client.call_tool_mcp(
            "study_analysis",
            {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "ERBB2", "type": "expression"},
        )
        assert not result.is_error
        value = result.structured_content
        assert verify_receipt(value)
        rows = [
            section["data"]
            for section in value["sections"].values()
            if isinstance(section.get("data"), dict)
            and section["data"].get("record_type") == "study_measurements"
        ]
        assert len(rows) == 1
        jsonschema.validate(rows[0], schema)
        assert rows[0]["values"] == {"S1": 0.0, "S2": 2.0}
        text_value = json.loads(result.content[0].text)
        assert text_value == value


def test_release_declared_units_are_retained_without_transforming_values(measurement):
    from biomedmcp.native.study import StudyAnalytics

    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    manifest = json.loads(path.read_text())
    manifest["studies"][0]["assays"] = {"expression": {"units": "source-specific arbitrary units"}}
    path.write_text(json.dumps(manifest))
    row = StudyAnalytics().run("query", request(gene="ERBB2", type="expression"))
    assert row["measurement_coverage"]["expression:ERBB2"]["units"] == "source-specific arbitrary units"
    assert row["units_basis"] == "manifest declaration"
    assert row["values"] == {"S1": 0.0, "S2": 2.0}
    assert row["release"]["metadata_sha256"] != measurement[1]["release"]["metadata_sha256"]


async def test_failed_measurement_contract_returns_controlled_error_and_retry_can_succeed(
    measurement, monkeypatch
):
    from biomedmcp.native import study as module

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = module.study_measurement_record

    def inconsistent(row, **kwargs):
        return original({**row, "measured_samples": row["measured_samples"] + 1}, **kwargs)

    monkeypatch.setattr(module, "study_measurement_record", inconsistent)
    args = {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "ERBB2", "type": "expression"}
    async with Client(create_server(service=ResearchService())) as client:
        failure = await client.call_tool_mcp("study_analysis", args)
        assert failure.is_error
        value = failure.structured_content
        assert value["outcome"] == "error"
        assert value["sections"]["study"]["error"]["code"] == "invalid_study"
        assert value["provenance"] == []
        assert value["sections"]["study"]["data"] is None
        assert "ERBB2" not in json.dumps(value["sections"]["study"]["error"])
        monkeypatch.setattr(module, "study_measurement_record", original)
        success = await client.call_tool_mcp("study_analysis", args)
        assert not success.is_error
        row = success.structured_content["sections"]["study"]["data"]
        assert row["record_type"] == "study_measurements" and row["measured_samples"] == 2
