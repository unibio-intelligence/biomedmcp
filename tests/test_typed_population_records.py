"""Qualified population identities, frequency inputs and delivered agent evidence."""

import json
from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client
from gnomad_helpers import IDENTITY, population
from native_helpers import HTTP
from pydantic import ValidationError

from biomedmcp.mcp.server import create_server
from biomedmcp.native.gnomad import VariantPopulationRecord
from biomedmcp.native.variants import Variants
from biomedmcp.receipts import verify_receipt
from biomedmcp.runtime import digest

pytest_plugins = ["test_gnomad_responses"]

ARGS = {"id": "chr7:140753336:A:T", "assembly": "grch38", "sections": ["population"]}


@pytest.fixture
async def record():
    return await Variants(HTTP(population())).population({"identity": IDENTITY})


async def test_frequency_family_binds_identity_units_inputs_and_mutable_source(record):
    assert record["record_type"] == "variant_population"
    assert record["assertion_type"] == "descriptive_population_measurements"
    assert record["species"] == 9606 and record["identity"] == IDENTITY
    assert record["transcript"] is None and record["release"] is None
    assert record["reproducibility"] == "mutable_provider_alias"
    assert record["source_record_sha256"] == digest(population()["data"]["variant"])
    for name in ("exome", "genome", "joint"):
        row = record["variant"][name]
        assert row["allele_frequency"] == 0.02 and row["an"] == 100
        assert row["frequency_unit"] == "proportion"
        assert row["denominator_unit"] == "observed alleles"
        assert row["input_locators"] == [f"/data/variant/{name}/ac", f"/data/variant/{name}/an"]
        assert row["populations"][0]["input_locators"] == [
            f"/data/variant/{name}/populations/0/ac",
            f"/data/variant/{name}/populations/0/an",
        ]
    jsonschema.validate(record, VariantPopulationRecord.model_json_schema())


@pytest.mark.parametrize(
    "ac,an,value,missingness",
    [
        (0, 100, 0.0, "reported"),
        (None, 100, None, "allele_count_not_supplied"),
        (0, None, None, "allele_number_not_supplied"),
        (0, 0, None, "zero_allele_number"),
    ],
)
async def test_zero_and_each_unknown_denominator_case_remain_distinct(ac, an, value, missingness):
    data = population()
    data["data"]["variant"]["exome"].update(ac=ac, an=an, populations=[])
    result = await Variants(HTTP(data)).population({"identity": IDENTITY})
    row = result["variant"]["exome"]
    assert row["allele_frequency"] == value and row["missingness"] == missingness
    assert result["section_outcomes"]["exome"] == ("data" if value is not None else "unavailable")


@pytest.mark.parametrize("missing", ["variant", "exome"])
async def test_no_indexed_record_or_modality_is_unavailable_without_invented_counts(missing):
    data = population()
    if missing == "variant":
        data["data"]["variant"] = None
    else:
        data["data"]["variant"]["exome"] = None
    result = await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert result["section_outcomes"][missing] == "unavailable"
    assert (result["variant"] if missing == "variant" else result["variant"]["exome"]) is None
    assert result["source_record_sha256"] == digest(data["data"]["variant"])


@pytest.mark.parametrize(
    "path,value",
    [
        (("species",), 10090),
        (("transcript",), "ENST00000288602"),
        (("release",), "4.1"),
        (("assertion_type",), "clinical_classification"),
        (("identity", "alternate"), "A"),
        (("identity", "position"), 1),
        (("variant", "exome", "allele_frequency"), 0.03),
        (("variant", "joint", "an"), 300),
        (("variant", "exome", "allele_frequency"), True),
        (("variant", "exome", "allele_frequency"), float("nan")),
        (("variant", "exome", "denominator_unit"), "participants"),
        (("variant", "exome", "missingness"), "allele_count_not_supplied"),
        (("variant", "exome", "method"), "sum the modalities"),
        (("variant", "exome", "input_locators"), ["/data/variant/genome/ac", "/data/variant/genome/an"]),
        (
            ("variant", "genome", "populations", 0, "input_locators"),
            ["/data/variant/genome/ac", "/data/variant/genome/an"],
        ),
        (("variant", "joint", "populations", 0, "allele_frequency"), 0.01),
        (("variant", "joint", "populations", 0, "ac"), 3),
        (("source_record_sha256",), "0" * 64),
        (("section_outcomes", "exome"), "unavailable"),
    ],
)
async def test_contradictory_identity_and_derived_measurements_are_rejected(record, path, value):
    row = deepcopy(record)
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        VariantPopulationRecord.model_validate(row)


async def test_actual_mcp_schema_receipt_and_text_locate_independent_measurements(actual_gnomad):
    service, state = actual_gnomad
    data = population()
    data["data"]["variant"]["genome"].update(ac=1, an=50, populations=[])
    data["data"]["variant"]["joint"].update(ac=2, an=120, populations=[])
    state["responses"] = [data]
    async with Client(create_server(service=service)) as client:
        schema = (await client.call_tool_mcp("capabilities", {"source": "gnomad"})).structured_content[
            "record_schemas"
        ]["variant_population"]
        result = await client.call_tool_mcp("variant_evidence", ARGS)
    assert not result.is_error
    value = result.structured_content
    assert verify_receipt(value) and json.loads(result.content[0].text) == value
    section = value["sections"]["population"]
    row = section["data"]
    jsonschema.validate(row, schema)
    assert row["variant"]["joint"]["an"] == 120
    assert row["variant"]["joint"]["allele_frequency"] == 2 / 120
    assert row["source_record_sha256"] == digest(data["data"]["variant"])
    assert section["evidence_ids"] == [value["provenance"][0]["evidence_id"]]
    assert value["receipt"]["time_dependent"] is True
    assert value["receipt"]["reproduction"] == "not_established"
    assert len(state["calls"]) == 1


async def test_invalid_derived_contract_has_no_evidence_and_valid_retry_is_uncached(
    actual_gnomad, monkeypatch
):
    from biomedmcp.native import gnomad

    service, state = actual_gnomad
    state["responses"] = [population(), population()]
    original = gnomad.frequency_record

    def broken(*args):
        return {**original(*args), "denominator_unit": "participants"}

    monkeypatch.setattr(gnomad, "frequency_record", broken)
    async with Client(create_server(service=service)) as client:
        failed = (await client.call_tool_mcp("variant_evidence", ARGS)).structured_content
        section = failed["sections"]["population"]
        assert section["data"] is None and section["evidence_ids"] == []
        assert section["error"]["code"] == "invalid_source_response"
        assert failed["provenance"] == []
        monkeypatch.setattr(gnomad, "frequency_record", original)
        success = await client.call_tool_mcp("variant_evidence", ARGS)
        assert not success.is_error
        assert (
            success.structured_content["sections"]["population"]["data"]["record_type"]
            == "variant_population"
        )
    assert len(state["calls"]) == 2


async def test_omitted_ancestry_measurements_keep_exact_inputs_in_same_snapshot(actual_gnomad):
    service, state = actual_gnomad
    data = population()
    data["data"]["variant"]["exome"]["populations"] = [
        {"id": f"synthetic-{index}", "ac": 0, "an": 1, "homozygote_count": 0, "hemizygote_count": 0}
        for index in range(31)
    ]
    state["responses"] = [data]
    async with Client(create_server(service=service)) as client:
        value = (await client.call_tool_mcp("variant_evidence", ARGS)).structured_content
        section = value["sections"]["population"]
        assert section["truncated"] and verify_receipt(value)
        row = section["data"]
        assert len(row["variant"]["exome"]["populations"]) == 25
        omission = next(
            item
            for item in section["recovery"]["omissions"]
            if item["pointer"] == "/variant/exome/populations"
        )
        recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
    assert recovered["evidence_ids"] == section["evidence_ids"]
    assert len(recovered["value"]) == 6 and not recovered["next_uri"]
    assert recovered["value"][0]["input_locators"] == [
        "/data/variant/exome/populations/25/ac",
        "/data/variant/exome/populations/25/an",
    ]
    assert recovered["value"][0]["allele_frequency"] == 0.0
    assert row["source_record_sha256"] == digest(data["data"]["variant"])
    assert len(state["calls"]) == 1
