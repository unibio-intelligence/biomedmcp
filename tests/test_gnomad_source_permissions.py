"""Direct primary-data access cannot unlock aggregators or imported annotations."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from gnomad_helpers import population

from biomedmcp import source_licensing, transport
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions


async def call_population(monkeypatch, payload, *, identifier="chr7:140753336:A:T", assembly="grch38"):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def provider(request):
        calls.append(request)
        assert request.url.host == "gnomad.broadinstitute.org"
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider))
    )
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        result = await client.call_tool_mcp(
            "variant_evidence",
            {
                "id": identifier,
                "assembly": assembly,
                "sections": ["population"],
                "sources": ["gnomad"],
            },
        )
    return result.structured_content, calls


async def test_direct_cc0_population_does_not_fetch_held_identity_annotations(monkeypatch):
    assert source_licensing.availability("gnomad") == (True, None)
    assert not source_licensing.availability("myvariant")[0]
    result, calls = await call_population(monkeypatch, population())
    assert len(calls) == 1
    assert result["provenance"][0]["source"] == "gnomad"
    assert "myvariant" not in result["provenance"][0].get("sources", [])
    data = result["sections"]["population"]["data"]
    assert data["identity"]["assembly"] == "grch38"
    assert data["variant"]["joint"]["allele_frequency"] == 0.02
    query = json.loads(calls[0].content)["query"]
    assert not any(field in query.lower() for field in ["spliceai", "cadd", "dbnsfp", "clinvar", "vep"])


@pytest.mark.parametrize("field", ["spliceai", "cadd", "dbnsfp"])
async def test_unrequested_restricted_predictor_fields_are_never_evidence(monkeypatch, field):
    payload = deepcopy(population())
    payload["data"]["variant"][field] = {"restricted_sentinel": 0.99}
    result, calls = await call_population(monkeypatch, payload)
    assert len(calls) == 1
    assert not result["provenance"]
    assert "restricted_sentinel" not in json.dumps(result)


async def test_direct_population_checks_returned_allele_before_emitting_evidence(monkeypatch):
    payload = population()
    payload["data"]["variant"]["alt"] = "C"
    result, calls = await call_population(monkeypatch, payload)
    assert len(calls) == 1 and not result["provenance"]


async def test_missing_population_ids_preserve_measurements_and_partial_status(monkeypatch):
    from biomedmcp.native.gnomad import VariantPopulationRecord

    payload = population()
    unnamed = deepcopy(payload["data"]["variant"]["joint"]["populations"][0])
    unnamed["id"] = ""
    payload["data"]["variant"]["joint"]["populations"].extend([unnamed, deepcopy(unnamed)])
    result, calls = await call_population(monkeypatch, payload)
    assert len(calls) == 1
    data = result["sections"]["population"]["data"]
    assert data["section_outcomes"]["joint"] == "partial"
    groups = data["variant"]["joint"]["populations"]
    assert [p["id"] for p in groups] == ["afr", "", ""]
    assert [p["id_status"] for p in groups] == ["reported", "missing", "missing"]
    assert all(p["ac"] == 2 and p["an"] == 100 and p["allele_frequency"] == 0.02 for p in groups)
    assert groups[1]["input_locators"] == ["/data/variant/joint/populations/1/ac", "/data/variant/joint/populations/1/an"]
    changed = deepcopy(data)
    changed["variant"]["joint"]["populations"][1]["id_status"] = "reported"
    with pytest.raises(ValueError):
        VariantPopulationRecord.model_validate(changed)


async def test_duplicate_source_population_ids_remain_ambiguous_rows(monkeypatch):
    from biomedmcp.native.gnomad import VariantPopulationRecord

    payload = population()
    payload["data"]["variant"]["joint"]["populations"] *= 2
    result, _ = await call_population(monkeypatch, payload)
    data = result["sections"]["population"]["data"]
    groups = data["variant"]["joint"]["populations"]
    assert len(groups) == 2 and all(p["id"] == "afr" and p["id_status"] == "ambiguous" for p in groups)
    assert data["section_outcomes"]["joint"] == "partial"
    assert groups[0]["input_locators"] != groups[1]["input_locators"]
    changed = deepcopy(data)
    changed["variant"]["joint"]["populations"][0]["id_status"] = "reported"
    with pytest.raises(ValueError):
        VariantPopulationRecord.model_validate(changed)


@pytest.mark.parametrize(
    "identifier,assembly",
    [
        ("rs113488022", "grch38"),
        ("chr7:140753336:A:T", "grch37"),
        ("chr7:140753336:A:AT", "grch38"),
    ],
)
async def test_direct_route_does_not_invent_normalization_or_assembly_mapping(
    monkeypatch, identifier, assembly
):
    result, calls = await call_population(monkeypatch, population(), identifier=identifier, assembly=assembly)
    assert calls == [] and not result.get("provenance")
