from copy import deepcopy

import pytest
from native_helpers import HTTP
from string_helpers import edge
from test_qualified_gene_identity import MOUSE, GeneAdapters

from biomedmcp.contracts import GetRequest
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.providers import NativeProviders

BAD_RESPONSES = [
    None,
    {},
    "",
    {"error": "failure"},
    [None],
    [{}],
    [{"error": "failure"}],
    [edge(ncbiTaxonId=10090)],
    [edge(stringId_B="10090.ENSMUSP123")],
    [edge(stringId_A="9606.")],
    [edge(preferredName_A="")],
    *[[edge(score=v)] for v in [None, True, "0.8", -0.1, 1.01, 10**1000, float("nan"), float("inf")]],
    [edge(escore="unknown")],
    [edge(error="failure")],
    [edge(), {}],
    [edge(), edge(ncbiTaxonId=10090)],
    [edge(ncbiTaxonId=True)],
    *[[edge(ncbiTaxonId=v)] for v in ["09606", "9606.0", " 9606", "-9606", "10090"]],
    *[
        [{k: v for k, v in edge().items() if k != field}]
        for field in (
            "stringId_A",
            "stringId_B",
            "preferredName_A",
            "preferredName_B",
            "ncbiTaxonId",
            "score",
        )
    ],
    [*[edge() for _ in range(25)], {}],
]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", BAD_RESPONSES)
async def test_malformed_network_never_becomes_scientific_evidence(payload):
    native = NativeProviders(GeneAdapters(), HTTP(payload))
    with pytest.raises(ResearchError) as caught:
        await native.section("gene", "673", "interactions", GetRequest(entity="gene", id="673"), {})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.asyncio
async def test_network_preserves_scores_identifiers_and_documented_query():
    rows = [edge(), edge(stringId_A="9606.ENSP123.1", preferredName_A="NEIGHBOR", score=0)]
    http = HTTP(rows)
    result = await NativeProviders(GeneAdapters(), http).section(
        "gene", "ENSG00000157764", "interactions", GetRequest(entity="gene", id="ENSG00000157764"), {}
    )
    assert result["records"] == rows
    assert result["network_type"] == "functional"
    assert result["requested_symbol"] == "BRAF" and result["requested_species"] == 9606
    assert http.calls[0][2]["params"] == {
        "identifiers": "BRAF",
        "species": 9606,
        "add_nodes": 10,
        "network_type": "functional",
        "caller_identity": "biomedmcp",
    }
    assert "physical binding" in " ".join(result["warnings"])
    assert "neighbor" in " ".join(result["warnings"])


@pytest.mark.parametrize("taxon", [9606, "9606"])
async def test_live_taxonomy_representations_survive_dispatch_without_changing_source(taxon):
    row = edge(ncbiTaxonId=taxon)
    result = await execute(
        ResearchService(adapters=GeneAdapters(), http=HTTP([row])),
        "get",
        {"entity": "gene", "id": "BRAF", "sections": ["interactions"]},
        scope="public",
    )
    assert result.outcome == "data"
    assert result.sections["interactions"].data["records"] == [row]
    assert result.sections["interactions"].evidence_ids


@pytest.mark.asyncio
async def test_missing_channel_is_unreported_not_zero():
    row = edge()
    del row["escore"]
    result = await NativeProviders(GeneAdapters(), HTTP([row])).section(
        "gene", "BRAF", "interactions", GetRequest(entity="gene", id="BRAF"), {}
    )
    assert "escore" not in result["records"][0]
    assert "escore" in " ".join(result["warnings"])


@pytest.mark.asyncio
async def test_mouse_network_keeps_qualified_species_and_symbol():
    http = HTTP([edge(10090)])
    result = await NativeProviders(GeneAdapters([MOUSE]), http).section(
        "gene", "22059", "interactions", GetRequest(entity="gene", id="22059", species=10090), {}
    )
    assert result["requested_symbol"] == "Trp53"
    assert result["requested_species"] == 10090
    assert http.calls[0][2]["params"]["species"] == 10090


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", BAD_RESPONSES)
async def test_dispatch_retains_record_and_retries_failed_network(payload):
    service = ResearchService(adapters=GeneAdapters(), http=HTTP(payload, [edge()]))
    arguments = {"entity": "gene", "id": "673", "sections": ["record", "interactions"]}
    bad = await execute(service, "get", deepcopy(arguments), scope="public")
    assert bad.outcome == "partial"
    assert bad.sections["record"].outcome == "data"
    assert bad.sections["interactions"].outcome == "error"
    assert bad.sections["interactions"].error["code"] == "invalid_source_response"
    assert bad.sections["interactions"].evidence_ids == []
    assert all(p.source != "string" for p in bad.provenance)
    good = await execute(service, "get", deepcopy(arguments), scope="public")
    assert good.outcome == "data"
    assert good.sections["interactions"].data["records"] == [edge()]
    assert good.sections["interactions"].evidence_ids
    assert len(service.providers.http.calls) == 2


@pytest.mark.asyncio
async def test_explicit_empty_network_is_valid_with_interpretation_limits():
    result = await execute(
        ResearchService(adapters=GeneAdapters(), http=HTTP([])),
        "get",
        {"entity": "gene", "id": "BRAF", "sections": ["interactions"]},
        scope="public",
    )
    assert result.outcome == "empty"
    assert result.sections["interactions"].data["records"] == []
    assert result.sections["interactions"].evidence_ids
    assert "absence" in " ".join(result.sections["interactions"].warnings)


@pytest.mark.asyncio
async def test_actual_mcp_boundary_preserves_partial_result_and_cache_provenance(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP([edge(10090)], [edge()])
    service = ResearchService(adapters=GeneAdapters(), http=http)
    arguments = {"entity": "gene", "id": "673", "sections": ["record", "interactions"]}
    async with Client(create_server(service=service)) as client:
        failed = (await client.call_tool("get", arguments)).data
        good = (await client.call_tool("get", arguments)).data
        cached = (await client.call_tool("get", arguments)).data
    assert failed["outcome"] == "partial"
    assert failed["sections"]["record"]["outcome"] == "data"
    assert failed["sections"]["interactions"]["error"]["code"] == "invalid_source_response"
    assert failed["sections"]["interactions"]["evidence_ids"] == []
    assert good["sections"]["interactions"]["data"]["records"] == [edge()]
    first = next(p for p in good["provenance"] if p["source"] == "string")
    repeated = next(p for p in cached["provenance"] if p["source"] == "string")
    assert first["evidence_id"] == repeated["evidence_id"]
    assert first["source_version"] is None and repeated["cached"]
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_network_bounds_preserve_recoverable_neighbor_edges(monkeypatch):
    import json

    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    rows = [edge(stringId_B=f"9606.ENSP{i}", preferredName_B=f"NEIGHBOR{i}") for i in range(30)]
    http = HTTP(rows)
    async with Client(create_server(service=ResearchService(adapters=GeneAdapters(), http=http))) as client:
        result = (
            await client.call_tool(
                "get",
                {
                    "entity": "gene",
                    "id": "673",
                    "sections": ["interactions"],
                },
            )
        ).data
        section = result["sections"]["interactions"]
        assert len(section["data"]["records"]) == 25 and section["truncated"]
        omitted = next(o for o in section["recovery"]["omissions"] if o["pointer"] == "/records")
        recovered = json.loads((await client.read_resource(omitted["uri"]))[0].text)
        assert recovered["value"] == rows[25:]
        assert recovered["evidence_ids"] == section["evidence_ids"]
    assert len(http.calls) == 1
