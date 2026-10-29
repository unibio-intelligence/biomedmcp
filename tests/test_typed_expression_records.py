"""Expression measurement meaning and source identity through the actual MCP boundary."""

import json
from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client
from gtex_helpers import GENCODE, expression, page
from pydantic import ValidationError

from biomedmcp.errors import ResearchError
from biomedmcp.expression_records import EXPRESSION_RECORDS, expression_window
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt
from biomedmcp.runtime import digest

pytest_plugins = ["test_gtex_pagination"]


def window(*, detailed=False, release="gtex_v10", values=None):
    row = expression(detailed=detailed)
    row["datasetId"] = release
    if values is not None:
        row["data" if detailed else "median"] = values
    return {
        **page([row]),
        "gene_identity": {
            "gencode_id": GENCODE,
            "dataset_id": release,
            "gencode_version": "v39" if release == "gtex_v10" else "v26",
            "genome_build": "GRCh38/hg38",
        },
    }


def normalize(value, detailed=False):
    return expression_window(value, "gene_tissue" if detailed else "gene_median")["data"][0]


@pytest.mark.parametrize("detailed", [False, True])
@pytest.mark.parametrize("release", ["gtex_v8", "gtex_v10"])
def test_expression_assertions_preserve_source_identity_values_and_unknown_cohort(detailed, release):
    original = window(detailed=detailed, release=release, values=[0, 1.5] if detailed else 0)
    row = normalize(original, detailed)
    assert row["record_type"] == "expression" and row["species"] == 9606
    assert row["identity_namespace"] == "gencode_gene" and row["gencodeId"] == GENCODE
    assert row["source_release"] == release and row["gene_identity"] == original["gene_identity"]
    assert row["transcript"] is None and row["unit"] == "TPM"
    assert row["participant_count"] is row["missing_measurement_count"] is None
    assert row["measurement_missingness"] == "reported"
    assert row["provided_value_count"] == (2 if detailed else None)
    assert row["assertion_type"] == (
        "provider_expression_values" if detailed else "provider_median_expression"
    )
    assert row["source_record_sha256"] == digest(original["data"][0])
    assert row["input_locator"]["measurement_pointer"] == ("/data/0/data" if detailed else "/data/0/median")
    assert row["ontologyId"] == original["data"][0]["ontologyId"]
    assert "no tissue-to-ontology equivalence" in row["ontology_interpretation"]
    jsonschema.validate(row, EXPRESSION_RECORDS.json_schema())


@pytest.mark.parametrize("unit", ["TPM", "read count", "log(CP10K)"])
def test_provider_units_and_raw_number_kinds_are_retained_without_conversion(unit):
    original = window(detailed=True, values=[0, 1.5])
    original["data"][0].update(unit=unit, subsetGroup=None)
    row = normalize(original, True)
    assert row["unit"] == unit and row["data"] == [0, 1.5] and type(row["data"][0]) is int
    assert row["subsetGroup"] is None
    assert row["source_record_sha256"] == digest(original["data"][0])


@pytest.mark.parametrize(
    "path,value",
    [
        (("participant_count",), 2),
        (("missing_measurement_count",), 0),
        (("provided_value_count",), True),
        (("provided_value_count",), 3),
        (("source_release",), "gtex_v8"),
        (("gene_identity", "dataset_id"), "gtex_v8"),
        (("gene_identity", "gencode_version"), "v26"),
        (("gencodeId",), "ENSG00000000001.1"),
        (("gene_identity", "genome_build"), "GRCh37/hg19"),
        (("species",), 10090),
        (("transcript",), "ENST00000288602"),
        (("unit",), "z_score"),
        (("data", 0), True),
        (("data", 0), float("nan")),
        (("data", 0), -1),
        (("input_locator", "measurement_pointer"), "/data/1/data"),
        (("input_locator", "endpoint"), "/expression/medianGeneExpression"),
        (("source_record_sha256",), "0" * 64),
        (("method",), "Infer a participant denominator"),
    ],
)
def test_contradictory_expression_meanings_are_rejected(path, value):
    row = normalize(window(detailed=True), True)
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        EXPRESSION_RECORDS.validate_python(row)


@pytest.mark.parametrize(
    "case", ["median_as_series", "series_as_median", "service_annotation", "missing_value", "empty_series"]
)
def test_malformed_or_mixed_assertions_do_not_become_measurements(case):
    detailed = case in {"series_as_median", "empty_series"}
    original = window(detailed=detailed)
    raw = original["data"][0]
    if case == "median_as_series":
        raw["data"] = [1.5]
    elif case == "series_as_median":
        raw["median"] = 1.5
    elif case == "service_annotation":
        raw["participant_count"] = 2
    elif case == "missing_value":
        del raw["median"]
    else:
        raw["data"] = []
    with pytest.raises(ResearchError) as caught:
        normalize(original, detailed)
    assert caught.value.code == "invalid_source_response"


async def test_actual_mcp_discriminated_schema_and_receipt_preserve_measurement_scope(paged_gtex):
    service, state = paged_gtex
    original = expression()
    state["pages"]["/expression/medianGeneExpression"] = {0: page([original])}
    args = {"entity": "gene", "id": GENCODE, "sources": ["gtex"], "sections": ["expression"]}
    async with Client(create_server(service=service)) as client:
        schema = (await client.call_tool_mcp("capabilities", {"source": "gtex"})).structured_content[
            "record_schemas"
        ]["expression"]
        result = await client.call_tool_mcp("get", args)
    assert not result.is_error
    value = result.structured_content
    assert json.loads(result.content[0].text) == value and verify_receipt(value)
    row = value["sections"]["expression"]["data"]["data"][0]
    jsonschema.validate(row, schema)
    assert row["participant_count"] is None and row["provided_value_count"] is None
    assert row["source_record_sha256"] == digest(original)
    assert value["receipt"]["time_dependent"] and value["receipt"]["reproduction"] == "not_established"


async def test_bounded_series_recovers_exact_supplied_values_without_another_request(paged_gtex):
    service, state = paged_gtex
    raw = expression(detailed=True)
    raw["data"] = list(range(31))
    state["pages"]["/expression/geneExpression"] = {0: page([raw])}
    args = {
        "entity": "gene",
        "id": GENCODE,
        "sections": ["expression"],
        "sources": ["gtex"],
        "section_parameters": {
            "expression": {"query_type": "gene_tissue", "tissue_id": "Thyroid", "limit": 25}
        },
    }
    async with Client(create_server(service=service)) as client:
        value = (await client.call_tool_mcp("get", args)).structured_content
        section = value["sections"]["expression"]
        assert section["truncated"] and verify_receipt(value)
        row = section["data"]["data"][0]
        assert section["data"]["paging_info"]["totalNumberOfItems"] == 1
        assert row["provided_value_count"] == 31 and len(row["data"]) == 25
        omission = next(x for x in section["recovery"]["omissions"] if x["pointer"] == "/data/0/data")
        recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
    assert recovered["value"] == list(range(25, 31))
    assert recovered["evidence_ids"] == section["evidence_ids"]
    assert row["source_record_sha256"] == digest(raw)
    assert len([x for x in state["requests"] if x.url.path.endswith("/expression/geneExpression")]) == 1


async def test_failed_contract_has_no_evidence_and_valid_retry_can_be_cached(paged_gtex):
    service, state = paged_gtex
    raw = expression()
    state["pages"]["/expression/medianGeneExpression"] = {0: page([{**raw, "participant_count": 2}])}
    args = {"entity": "gene", "id": GENCODE, "sources": ["gtex"], "sections": ["expression"]}
    async with Client(create_server(service=service)) as client:
        failure = (await client.call_tool_mcp("get", args)).structured_content
        section = failure["sections"]["expression"]
        assert section["data"] is None and section["evidence_ids"] == []
        assert section["error"]["code"] == "invalid_source_response" and failure["provenance"] == []
        state["pages"]["/expression/medianGeneExpression"][0] = page([deepcopy(raw)])
        success = (await client.call_tool_mcp("get", args)).structured_content
        cached = (await client.call_tool_mcp("get", args)).structured_content
    assert success["outcome"] == cached["outcome"] == "data"
    assert cached["provenance"][0]["cached"]
    assert len([x for x in state["requests"] if x.url.path.endswith("/expression/medianGeneExpression")]) == 2
