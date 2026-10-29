"""Trial registry identities, enrollment meanings and delivered wire evidence."""

import json
from copy import deepcopy

import jsonschema
import pytest
from clinical_trials_helpers import STUDY, study
from fastmcp import Client
from native_helpers import HTTP

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.output_contracts import output_schema
from biomedmcp.receipts import verify_receipt
from biomedmcp.trial_records import TrialRecord, trial_record


class Adapter:
    def __init__(self, row=None):
        self.row = deepcopy(STUDY if row is None else row)
        self.calls = []

    async def validate(self, *args):
        pass

    async def call(self, source, operation, params):
        self.calls.append((source, operation, params))
        return (
            {"studies": [deepcopy(self.row)], "totalCount": 1}
            if operation == "search_studies"
            else deepcopy(self.row)
        )


def nci(**extra):
    return {
        "nci_id": "NCI-2020-08118",
        "nct_id": "NCT04681105",
        "brief_title": "Synthetic NCI record",
        "phase": {"phase": "I"},
        "current_trial_status": "Active",
        "minimum_target_accrual_number": 40,
        **extra,
    }


@pytest.mark.parametrize(
    "basis,expected", [("ACTUAL", "actual"), ("ESTIMATED", "estimated"), (None, "not_supplied")]
)
def test_clinical_enrollment_keeps_count_unit_and_basis(basis, expected):
    row = study()
    row["protocolSection"]["designModule"]["enrollmentInfo"] = {
        "count": 0,
        **({"type": basis} if basis else {}),
    }
    result = trial_record(row, "clinical-trials")
    assert result["enrollment"] == {
        "count": 0,
        "basis": expected,
        "role": "registry_enrollment",
        "unit": "participants",
        "missingness": "reported",
    }
    assert result["has_results"] is False and result["results_missingness"] == "reported"
    assert result["protocolSection"] == row["protocolSection"]
    assert result["identities"] == [{"namespace": "nct", "value": "NCT04368728"}]


def test_omitted_trial_metadata_is_unknown_not_zero_negative_or_empty():
    raw = {"protocolSection": {"identificationModule": {"nctId": "NCT04368728"}}}
    row = trial_record(raw, "clinical-trials")
    assert row["title"] is row["status"] is row["phases"] is row["study_type"] is row["has_results"] is None
    assert row["enrollment"]["count"] is None and row["enrollment"]["missingness"] == "not_supplied"
    assert row["results_missingness"] == "not_supplied" and row["source_release"] is None
    assert row["assertion_type"] == "registry_record" and row["species"] == 9606


def test_nci_accrual_is_a_target_and_registry_codes_are_not_translated():
    row = trial_record(nci(results_posted="2020-01-01"), "nci")
    assert row["enrollment"] == {
        "count": 40,
        "basis": "minimum_target",
        "role": "minimum_target_accrual",
        "unit": "participants",
        "missingness": "reported",
    }
    assert row["phases"] == ["I"] and row["status"] == "Active"
    assert row["identities"] == [
        {"namespace": "nci", "value": "NCI-2020-08118"},
        {"namespace": "nct", "value": "NCT04681105"},
    ]
    assert row["has_results"] is None and row["results_missingness"] == "not_normalized"
    assert row["results_posted"] == "2020-01-01"


@pytest.mark.parametrize("count", [None, 0, 15])
def test_missing_and_zero_nci_target_accrual_stay_distinct(count):
    row = trial_record(nci(minimum_target_accrual_number=count), "nci")
    assert row["enrollment"]["count"] == count
    assert row["enrollment"]["missingness"] == ("not_supplied" if count is None else "reported")


@pytest.mark.parametrize(
    "path,value",
    [
        (("identificationModule", "nctId"), "wrong"),
        (("identificationModule", "nctId"), "NCT00000000"),
        (("identificationModule", "nctIdAliases"), [True]),
        (("identificationModule", "briefTitle"), []),
        (("statusModule", "overallStatus"), []),
        (("statusModule", "overallStatus"), "Active"),
        (("designModule", "phases"), "PHASE2"),
        (("designModule", "phases"), ["II"]),
        (("designModule", "studyType"), []),
        (("designModule", "studyType"), "UNKNOWN"),
        (("designModule", "enrollmentInfo"), {"count": True}),
        (("designModule", "enrollmentInfo"), {"count": -1}),
        (("designModule", "enrollmentInfo"), {"count": 1.5}),
        (("designModule", "enrollmentInfo"), {"count": "1"}),
        (("designModule", "enrollmentInfo"), {"type": []}),
        (("designModule", "enrollmentInfo"), []),
    ],
)
def test_malformed_core_trial_fields_cannot_become_registry_evidence(path, value):
    row = study()
    row["protocolSection"][path[0]][path[1]] = value
    with pytest.raises(ResearchError) as error:
        trial_record(row, "clinical-trials")
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "field,value",
    [
        ("nci_id", None),
        ("nci_id", True),
        ("nct_id", "bad"),
        ("brief_title", {}),
        ("phase", []),
        ("phase", {"phase": True}),
        ("current_trial_status", {}),
        ("minimum_target_accrual_number", True),
        ("minimum_target_accrual_number", -1),
        ("minimum_target_accrual_number", "1"),
    ],
)
def test_nci_fields_are_not_coerced_or_misidentified(field, value):
    with pytest.raises(ResearchError) as error:
        trial_record(nci(**{field: value}), "nci")
    assert error.value.code == "invalid_source_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,args",
    [
        ("trial_search", {"query": "synthetic"}),
        ("get", {"entity": "trial", "id": "NCT04368728"}),
        ("resolve", {"entity": "trial", "query": "NCT04368728"}),
    ],
)
async def test_actual_mcp_trial_record_links_registry_assertions_to_its_source(operation, args, monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    adapter = Adapter()
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = await client.call_tool_mcp(operation, args)
    assert not result.is_error
    value = result.structured_content
    row = value["records"][0] if operation == "trial_search" else value["sections"]["record"]["data"]
    assert row["record_type"] == "trial" and row["enrollment"]["basis"] == "actual"
    proofs = {p["evidence_id"]: p for p in value["provenance"]}
    assert row["evidence_ids"] and all(proofs[k]["source"] == row["source"] for k in row["evidence_ids"])
    assert verify_receipt(value)
    jsonschema.validate(value, output_schema(operation))
    assert json.loads(result.content[0].text) == value
    TrialRecord.model_validate(row)


@pytest.mark.asyncio
async def test_nci_search_keeps_target_semantics_without_exposing_auth(monkeypatch):
    monkeypatch.setenv("NCI_API_KEY", "synthetic-nci-sentinel")
    result = await execute(
        ResearchService(http=HTTP({"data": [nci()], "total": 1})),
        "trial_search",
        {"query": "synthetic", "filters": {"source": "nci"}},
        scope="local",
    )
    value = result.model_dump(mode="json")
    assert value["records"][0]["enrollment"]["basis"] == "minimum_target"
    assert value["records"][0]["evidence_ids"] == [value["provenance"][0]["evidence_id"]]
    assert "synthetic-nci-sentinel" not in json.dumps(value)
    assert verify_receipt(value)
    jsonschema.validate(value, output_schema("trial_search"))


@pytest.mark.asyncio
async def test_trial_wire_schema_rejects_malformed_units_counts_and_identity():
    value = (
        await execute(
            ResearchService(adapters=Adapter()),
            "get",
            {"entity": "trial", "id": "NCT04368728"},
            scope="local",
        )
    ).model_dump(mode="json")
    for key, replacement in [
        (
            "enrollment",
            {
                "count": True,
                "basis": "actual",
                "role": "registry_enrollment",
                "unit": "participants",
                "missingness": "reported",
            },
        ),
        (
            "enrollment",
            {
                "count": 0,
                "basis": "actual",
                "role": "registry_enrollment",
                "unit": "samples",
                "missingness": "reported",
            },
        ),
        (
            "enrollment",
            {
                "count": None,
                "basis": "actual",
                "role": "registry_enrollment",
                "unit": "participants",
                "missingness": "reported",
            },
        ),
        ("identities", [{"namespace": "nct", "value": "NCI-2020-08118"}]),
        ("species", 10090),
        ("has_results", 0),
    ]:
        bad = deepcopy(value)
        bad["sections"]["record"]["data"][key] = replacement
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, output_schema("get"))


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", [False, True])
async def test_trial_get_requires_requested_identity_or_explicit_registry_alias(alias):
    row = study("NCT04681105")
    if alias:
        row["protocolSection"]["identificationModule"]["nctIdAliases"] = ["NCT04368728"]
    result = await execute(
        ResearchService(adapters=Adapter(row)), "get", {"entity": "trial", "id": "NCT04368728"}, scope="local"
    )
    if alias:
        assert result.outcome == "data"
        assert result.sections["record"].data["identities"] == [
            {"namespace": "nct", "value": "NCT04681105"},
            {"namespace": "nct", "value": "NCT04368728"},
        ]
    else:
        assert result.outcome == "error"
        assert result.sections["record"].error["code"] == "invalid_source_response"


@pytest.mark.asyncio
async def test_malformed_trial_batch_peer_does_not_discard_valid_typed_evidence(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")

    class ByIdentity(Adapter):
        async def call(self, source, operation, params):
            row = study(params["nct_id"])
            if params["nct_id"] == "NCT04681105":
                row["protocolSection"]["designModule"]["enrollmentInfo"]["count"] = True
            return row

    async with Client(create_server(service=ResearchService(adapters=ByIdentity()))) as client:
        result = await client.call_tool_mcp(
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "trial", "id": identifier}}
                    for identifier in ["NCT04368728", "NCT04681105"]
                ]
            },
        )
    assert not result.is_error and result.structured_content["outcome"] == "partial"
    good, bad = result.structured_content["results"]
    assert good["sections"]["record"]["data"]["enrollment"]["count"] == 100
    assert bad["outcome"] == "error" and bad["sections"]["record"]["data"] is None
    assert verify_receipt(good) and verify_receipt(bad)
    jsonschema.validate(result.structured_content, output_schema("batch"))
