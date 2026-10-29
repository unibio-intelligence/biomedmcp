"""Application workflows exercise owned Python clients, not delegated CLI calls."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from native_helpers import BRAF, HTTP, PUBMED
from test_research_contracts import Adapters

from biomedmcp.contracts import Entity, GetRequest, SearchRequest
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError


@pytest.mark.parametrize(
    "arguments",
    [
        {"entity": "gene", "id": "BRAF", "sections": ["eqtl"]},
        {
            "entity": "gene",
            "id": "BRAF",
            "sections": ["expression"],
            "source_versions": {"gtex": "gtex_v999"},
        },
        {"entity": "gene", "id": "BRAF", "sections": ["unknown"]},
        {"entity": "gene", "id": "BRAF", "sections": ["all"]},
        {"entity": "gene", "id": "BRAF", "sections": ["target_evidence"], "sources": ["opentargets"]},
        {"entity": "variant", "id": "BRAF V600E", "assembly": "grch38"},
        {
            "entity": "article",
            "id": "123",
            "sections": ["fulltext"],
            "section_parameters": {"fulltext": {"start": 1, "end": 1000}},
        },
    ],
)
async def test_invalid_late_batch_item_prevents_all_outbound_requests(arguments):
    adapters = Adapters()
    http = HTTP()
    service = ResearchService(adapters=adapters, http=http)
    with pytest.raises((ResearchError, ValueError)):
        await execute(
            service,
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "gene", "id": "BRAF"}},
                    {"operation": "get", "arguments": arguments},
                ]
            },
            scope="alice",
        )
    assert adapters.calls == [] and http.calls == []


async def test_duplicate_query_source_in_batch_rejected_before_any_provider():
    adapters = Adapters()
    service = ResearchService(adapters=adapters)
    with pytest.raises(ResearchError, match="not a public advanced"):
        await execute(
            service,
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "gene", "id": "BRAF"}},
                    {
                        "operation": "query_source",
                        "arguments": {
                            "source": "uniprot",
                            "operation": "query_proteins",
                            "params": {"query": "P15056"},
                        },
                    },
                ]
            },
            scope="alice",
        )
    assert adapters.calls == []


async def test_target_join_uses_resolved_ensembl_once_for_multiple_sections():
    adapters = Adapters()
    result = await ResearchService(adapters=adapters).get(
        GetRequest(
            entity="gene",
            id="BRAF",
            sections=["target_evidence", "diseases", "druggability"],
            sources=["mygene", "opentargets"],
        ),
        scope="alice",
    )
    assert result.outcome == "data"
    assert len([c for c in adapters.calls if c[0] == "mygene"]) == 1
    assert len([c for c in adapters.calls if c[0] == "opentargets"]) == 1
    assert adapters.calls[-1][2]["entity_id"] == "ENSG00000157764"
    assert all(p.sources == ["mygene", "opentargets"] for p in result.provenance)


async def test_ambiguous_identity_stops_downstream_join():
    adapters = Adapters()
    adapters.call = AsyncMock(
        return_value={
            "hits": [
                {"symbol": "BRAF", "taxid": 9606, "_id": "1"},
                {"symbol": "BRAF", "taxid": 9606, "_id": "2"},
            ]
        }
    )
    result = await ResearchService(adapters=adapters).get(
        GetRequest(entity="gene", id="BRAF", sections=["target_evidence"]), scope="alice"
    )
    assert result.outcome == "ambiguous"
    assert adapters.call.await_count == 1


async def test_explicit_pubmed_never_enriches_through_other_sources():
    http = HTTP({"esearchresult": {"idlist": ["123"]}}, PUBMED)
    result = await ResearchService(http=http).search(
        SearchRequest(entity="article", query="BRAF", filters={"source": "pubmed"}), scope="alice"
    )
    assert result.records[0]["pmid"] == "123"
    assert all("eutils.ncbi.nlm.nih.gov" in c[1] for c in http.calls)
    assert result.query["execution"]["sources"] == ["pubmed"]
    assert result.provenance[0].source == "pubmed"


async def test_failed_federation_is_partial_not_empty_evidence():
    service = ResearchService()
    service.providers.literature.search_source = AsyncMock(
        side_effect=[[], ResearchError("source_unavailable", "Provider unavailable")]
    )
    result = await service.search(
        SearchRequest(entity="article", query="BRAF", filters={"author": ["A Smith"]}), scope="alice"
    )
    assert result.outcome == "partial"
    assert result.sections["pubmed"].outcome == "empty"
    assert result.sections["europepmc"].outcome == "unavailable"
    assert len(result.provenance) == 1


async def test_variant_empty_and_ambiguous_are_not_data():
    for response, expected in [
        ({"hits": [], "total": 0}, "empty"),
        ({"hits": [BRAF, {**BRAF, "_id": "second"}], "total": 2}, "ambiguous"),
    ]:
        result = await ResearchService(http=HTTP(response)).get(
            GetRequest(entity="variant", id="BRAF V600E"), scope="alice"
        )
        assert result.outcome == expected


async def test_relations_do_not_alias_sections():
    service = ResearchService()
    with pytest.raises(ResearchError, match="Use get"):
        await service.relate(Entity.gene, "BRAF", "expression", scope="alice")


async def test_capabilities_exclude_duplicate_uniprot_and_gtex_routes():
    service = ResearchService()
    for source, forbidden in [
        ("uniprot", {"query_proteins", "advanced_search", "batch_protein_lookup", "export_protein_data"}),
        ("gtex", {"query_expression", "query_qtl", "get_annotation"}),
    ]:
        catalog = await service.capabilities(source=source)
        assert not forbidden & {o["name"] for o in catalog["operations"]}
        assert catalog["canonical_routes"]
    gene = await service.capabilities(entity=Entity.gene)
    assert gene["sections"]["expression"] == "gtex"
    protein = await service.capabilities(entity=Entity.protein)
    assert protein["record_owner"] == "uniprot"


async def test_negative_evidence_remains_scoped():
    service = ResearchService()
    service.providers.literature.search_source = AsyncMock(return_value=[])
    result = await service.research("negative_evidence", "BRAF", scope="alice")
    assert result.query["universal_absence"] is False and result.outcome == "empty"


async def test_cli_and_mcp_need_no_subprocess_even_for_capabilities(monkeypatch):
    from biomedmcp.cli import execute as cli_execute

    monkeypatch.setenv("UBI_PROFILE", "local")

    def forbidden(*a, **k):
        raise AssertionError("Executable launch forbidden")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    result = await cli_execute("capabilities", {"entity": "article"})
    assert "pubmed" in result["search_sources"]
