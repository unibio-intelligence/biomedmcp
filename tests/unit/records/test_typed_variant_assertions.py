"""ClinGen categorical claims bind source identity/version without clinical synthesis."""

import json
from copy import deepcopy

import httpx
import jsonschema
import pytest
from clingen_helpers import ASSERTION, envelope
from fastmcp import Client
from native_helpers import HTTP
from pydantic import ValidationError

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.native.variants import Variants
from biomedmcp.receipts import verify_receipt
from biomedmcp.runtime import digest
from biomedmcp.variant_assertion_records import ExpertVariantAssertionRecord

pytestmark = pytest.mark.source_permissions


@pytest.fixture
async def record():
    result = await Variants(HTTP(envelope([ASSERTION]))).assertions("CA1")
    return result["records"][0]


async def test_source_allele_panel_version_and_exact_input_locations(record):
    assert record["record_type"] == "variant_assertion"
    assert record["assertion_type"] == "provider_expert_classification"
    assert record["variant_identity"]["namespace"] == "clingen_allele_id"
    assert record["variant_identity"]["value"] == "CA1"
    assert all(record["variant_identity"][k] is None for k in ("species", "assembly", "transcript"))
    assert record["condition"] is None and record["source_release"] is None
    assert record["source_record_sha256"] == digest(ASSERTION)
    assert record["input_locator"]["classification_pointer"] == "/records/0/provider_record/classification"
    assert record["input_locator"]["provider_record_pointer"] == "/data/0"
    assert record["docVersion"] == "1.0" and "not a replay pin" in record["reproducibility"]
    assert record["unit"] == "source_categorical_classification"
    jsonschema.validate(record, ExpertVariantAssertionRecord.model_json_schema())


@pytest.mark.parametrize("value", [None, False, True])
async def test_source_retraction_missingness_is_independent_of_claim(value):
    raw = {**ASSERTION, **({"retracted": value} if value is not None else {})}
    result = await Variants(HTTP(envelope([raw]))).assertions("CA1")
    record = result["records"][0]
    assert record["retracted"] is value
    assert record["retraction_missingness"] == ("not_supplied" if value is None else "reported")
    assert record["classification"] == "Pathogenic"


async def test_conflicting_panels_and_versions_remain_separate():
    rows = [
        ASSERTION,
        {
            **ASSERTION,
            "classification": "Benign",
            "ep": "Another panel",
            "docVersion": "2.0",
            "retracted": True,
        },
    ]
    result = await Variants(HTTP(envelope(rows))).assertions("CA1")
    records = result["records"]
    assert [r["classification"] for r in records] == ["Pathogenic", "Benign"]
    assert [r["provider_record"] for r in records] == rows
    assert (
        records[0]["input_locator"]["classification_pointer"]
        != records[1]["input_locator"]["classification_pointer"]
    )
    assert result["coverage"]["exhaustive"] is False


@pytest.mark.parametrize(
    "path,value",
    [
        (("assertion_type",), "computed_pathogenicity"),
        (("unit",), "probability"),
        (("classification",), "Benign"),
        (("ep",), "Other panel"),
        (("uuid",), "wrong"),
        (("docVersion",), "2.0"),
        (("caId",), "CA2"),
        (("variant_identity", "value"), "CA2"),
        (("variant_identity", "species"), 9606),
        (("variant_identity", "assembly"), "GRCh38"),
        (("variant_identity", "transcript"), "NM_004333.6"),
        (("condition",), "Melanoma"),
        (("source_release",), "2026"),
        (("retracted",), False),
        (("input_locator", "row_index"), 1),
        (("input_locator", "source_page"), True),
        (("input_locator", "source_page"), 1.0),
        (("input_locator", "classification_pointer"), "/records/1/provider_record/classification"),
        (("input_locator", "source_url"), "https://untrusted.invalid/CA1"),
        (("source_record_sha256",), "0" * 64),
    ],
)
async def test_contradictory_meanings_identity_and_inputs_are_rejected(record, path, value):
    mutated = deepcopy(record)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        ExpertVariantAssertionRecord.model_validate(mutated)


async def test_rehashed_source_numeric_flag_cannot_masquerade_as_boolean(record):
    record["provider_record"]["retracted"] = 0
    record["retracted"] = False
    record["retraction_missingness"] = "reported"
    record["source_record_sha256"] = digest(record["provider_record"])
    with pytest.raises(ValidationError):
        ExpertVariantAssertionRecord.model_validate(record)


async def test_actual_mcp_rows_keep_source_hash_and_time_dependent_receipt(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    raw = [
        {**ASSERTION, "classification": "Pathogenic"},
        {**ASSERTION, "classification": "Benign", "uuid": "other"},
    ]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=envelope(deepcopy(raw)))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source", {"source": "clingen", "operation": "assertions", "params": {"caid": "CA1"}}
            )
        ).data
        schemas = await client.read_resource("biomedmcp://schemas/records/variant")
    assert result["outcome"] == "data" and len(calls) == 1
    records = result["sections"]["clingen"]["data"]["records"]
    assert [r["classification"] for r in records] == ["Pathogenic", "Benign"]
    assert result["provenance"][0]["source_version"] is None
    assert verify_receipt(result)
    assert result["receipt"]["time_dependent"] is True
    schema = json.loads(schemas[0].text)
    for record in records:
        jsonschema.validate(record, schema)
