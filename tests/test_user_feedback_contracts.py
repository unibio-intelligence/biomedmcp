"""Regressions for the public-tool feedback of 2026-10-13."""

import json
from copy import deepcopy

import pytest
from fastmcp import Client
from native_helpers import BRAF, HTTP
from test_reactome_contracts import PARTICIPANT, PID, REACTION, reactome_http  # noqa: F401
from test_research_contracts import Adapters

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.civic import evidence
from biomedmcp.native.literature import focus_matches
from biomedmcp.native.variants import Variants
from biomedmcp.pagination import page_payload
from biomedmcp.receipts import verify_receipt
from biomedmcp.scientific_records import literature_record
from biomedmcp.trial_records import rank_trials


async def test_batch_success_and_indexed_validation_before_any_acquisition():
    service = ResearchService(adapters=Adapters())
    args = {"calls": [{"operation": "get", "arguments": {"entity": "gene", "id": "BRAF"}}]}
    result = await execute(service, "batch", args, scope="test")
    assert result["outcome"] == "data"
    assert verify_receipt(result["results"][0])
    service = ResearchService(adapters=Adapters())
    args["calls"].append(
        {"operation": "search", "arguments": {"entity": "gene", "query": "BRAF", "limit": 0}}
    )
    with pytest.raises(ResearchError) as caught:
        await execute(service, "batch", args, scope="test")
    assert caught.value.as_dict()["fields"] == {"$.calls[1].arguments.limit": "greater_than_equal"}
    assert not service.adapters.calls


async def test_mcp_batch_errors_expose_schema_paths_but_not_unknown_keys(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as client:
        value = (
            await client.call_tool_mcp(
                "batch", {"calls": [{"operation": "get", "credential-sentinel": "secret"}]}
            )
        ).structured_content
    assert "$.calls[0].arguments" in value["error"]["fields"]
    assert "credential-sentinel" not in json.dumps(value) and "secret" not in json.dumps(value)


async def test_civic_normalizes_official_relative_record_links_and_rejects_external_paths():
    from civic_helpers import response

    fixture = response()
    fixture["data"]["evidenceItems"]["nodes"][0]["link"] = "/evidence/1"
    fixture["data"]["evidenceItems"]["nodes"][0]["source"]["link"] = "/sources/123"
    value = await evidence(HTTP(fixture), "BRAF V600E", "variant")
    assert value["evidenceItems"]["nodes"][0]["link"] == "https://civicdb.org/evidence/1"
    fixture["data"]["evidenceItems"]["nodes"][0]["link"] = "//attacker.example/evidence/1"
    with pytest.raises(ResearchError):
        await evidence(HTTP(fixture), "BRAF V600E", "variant")


async def test_civic_rsid_resolves_one_conjunctive_annotation_and_tracks_dependency():
    from civic_helpers import response

    variant = {**deepcopy(BRAF), "dbsnp": {"rsid": "rs113488022"}}
    service = ResearchService(http=HTTP({"total": 1, "hits": [variant]}, response()))
    value = await execute(
        service, "variant_evidence", {"id": "rs113488022", "sections": ["civic"]}, scope="test"
    )
    assert value.sections["civic"].outcome == "data"
    assert set(value.provenance[0].sources) == {"civic", "myvariant"}
    assert verify_receipt(value.model_dump(mode="json"))


async def test_variant_shorthand_search_qualifies_gene_and_change():
    http = HTTP({"total": 1, "hits": [BRAF]})
    value = await Variants(http).search("BRAF V600E", {}, 1)
    assert len(value["hits"]) == 1
    query = http.calls[0][2]["params"]["q"]
    assert 'dbnsfp.genename:"BRAF"' in query and "Val600Glu" in query
    other = deepcopy(BRAF)
    other["dbnsfp"]["hgvsp"] = "p.Val600Lys"
    other["snpeff"]["ann"][0]["hgvs_p"] = "p.Val600Lys"
    value = await Variants(HTTP({"total": 1, "hits": [other]})).search("BRAF V600E", {}, 1)
    assert value["hits"] == [] and value["_provider_page"]["filtered_count"] == 1


async def test_relations_and_section_dependencies_are_discoverable():
    from biomedmcp.contracts import Entity

    service = ResearchService(adapters=Adapters())
    capability = await execute(service, "capabilities", {}, scope="test")
    assert "references" in capability["relations"]["article"]
    drug = await execute(service, "capabilities", {"entity": "drug"}, scope="test")
    assert drug["section_dependencies"]["label"] == ["openfda"]
    with pytest.raises(ResearchError, match="articles, trials"):
        await service.relate(Entity.gene, "KRAS", "interacts_with", scope="test")
    with pytest.raises(ResearchError, match=r'get\(entity="protein"'):
        await execute(
            service,
            "query_source",
            {"source": "uniprot", "operation": "get_entry", "params": {}},
            scope="test",
        )


async def test_gene_annotations_have_field_error_and_canonical_guidance():
    with pytest.raises(ResearchError) as caught:
        await execute(
            ResearchService(),
            "get",
            {"entity": "gene", "id": "KRAS", "sections": ["annotations"]},
            scope="test",
        )
    assert "$.sections" in caught.value.as_dict()["fields"]
    assert 'sections=["go"]' in caught.value.correction


async def test_label_automatically_selects_openfda(monkeypatch):
    service, calls = ResearchService(), []

    async def fda(path, query, *args, **kwargs):
        calls.append((path, query))
        return [{"id": "label-1", "openfda": {"generic_name": ["pembrolizumab"]}}]

    monkeypatch.setattr(service.providers, "fda", fda)
    result = await execute(
        service, "get", {"entity": "drug", "id": "pembrolizumab", "sections": ["label"]}, scope="test"
    )
    assert result.outcome == "data" and result.provenance[0].source == "openfda"
    assert calls == [("drug/label", 'openfda.generic_name:"pembrolizumab"')]


async def test_pathway_sections_use_current_retained_contract_and_filter_comentions(
    reactome_http, monkeypatch
):
    reactome_http["payloads"][f"/ContentService/data/participants/{PID}"] = [PARTICIPANT]
    reactome_http["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [REACTION]
    service = ResearchService()

    async def papers(source, *args, **kwargs):
        rows = [
            literature_record(
                {"pmid": "1", "title": "Synthetic pathway signaling", "abstract": "Mechanism"}, source
            ),
            literature_record(
                {"pmid": "2", "title": "Artemisinin and cardiac arrest", "abstract": "Other text"}, source
            ),
        ]
        return page_payload(rows, raw_count=2, exhausted=True)

    monkeypatch.setattr(service.providers.literature, "search_source", papers)
    result = await execute(service, "research", {"workflow": "pathway_review", "focus": PID}, scope="test")
    assert result.sections["genes"].outcome == result.sections["events"].outcome == "data"
    assert {r["pmid"] for r in result.sections["literature"].data["records"]} == {"1"}
    assert result.sections["literature"].data["query"]["relevance_filter"]["filtered_weak_comentions"] == 1


def test_pathway_filter_uses_phrase_and_mechanism_without_substring_matches():
    assert focus_matches({"title": "Apoptosis signaling in cancer"}, "apoptosis")
    assert not focus_matches(
        {"title": "Cardiac arrest", "abstract": "apoptosis was also observed"}, "apoptosis"
    )
    assert not focus_matches({"title": "Anti-apoptosis2 changes"}, "apoptosis")


async def test_default_study_is_verified_and_clearly_synthetic(monkeypatch):
    monkeypatch.delenv("UBI_PUBLIC_STUDY_DIR", raising=False)
    monkeypatch.delenv("UBI_PUBLIC_STUDY_MANIFEST", raising=False)
    result = await execute(
        ResearchService(),
        "study_analysis",
        {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"},
        scope="test",
    )
    assert result.outcome == "data"
    assert result.sections["study"].data["mutation_count"] == 2
    assert result.sections["study"].data["release"]["synthetic"] is True
    assert "Synthetic demonstration" in result.sections["study"].data["warnings"][0]


async def test_summary_preserves_limit_and_exact_recovery_for_large_records(monkeypatch):
    service = ResearchService()
    records = [
        {
            "safetyreportid": str(i),
            "narrative": "x" * 150000,
            "patient": {"drug": [{"medicinalproduct": "test"}] * 200},
        }
        for i in range(2)
    ]

    async def search(*args, **kwargs):
        return page_payload(records, raw_count=2, exhausted=True)

    monkeypatch.setattr(service.providers, "search", search)
    result = await execute(
        service, "search", {"entity": "adverse-event", "query": "test", "limit": 1}, scope="test"
    )
    value = result.model_dump(mode="json")
    assert len(result.records) == 1 and len(json.dumps(value)) < 30000
    assert result.records[0]["summary_omissions"]
    assert result.query["output_omissions"]["composed_recovery"]["snapshot_status"] == "available"
    assert verify_receipt(value)


async def test_empty_searches_agree_but_failures_never_become_empty():
    author = await execute(
        ResearchService(http=HTTP({"meta": {"count": 0}, "results": []})),
        "search",
        {"entity": "author", "query": "no-name"},
        scope="test",
    )
    assert author.outcome == "empty"
    failure = await execute(
        ResearchService(http=HTTP(ResearchError("source_rate_limited", "Limited"))),
        "search",
        {"entity": "author", "query": "no-name"},
        scope="test",
    )
    assert failure.outcome != "empty" and failure.sections["openalex"].error


async def test_alias_ambiguity_explains_rule_and_top_candidate(monkeypatch):
    service = ResearchService(adapters=Adapters())

    async def search(*args, **kwargs):
        return {
            "hits": [{"_id": "2064", "symbol": "ERBB2", "taxid": 9606, "alias": ["HER2"], "_score": 999}],
            "total": 1,
        }

    monkeypatch.setattr(service.providers, "search", search)
    result = await execute(service, "resolve", {"entity": "gene", "query": "HER2"}, scope="test")
    assert result.outcome == "ambiguous" and result.records[0]["identity_match"] == "alias"
    assert result.query["resolution_policy"]["provider_score_used_for_identity"] is False
    assert result.next_actions[0]["arguments"]["id"] == "2064"


@pytest.mark.parametrize(
    "date,status",
    [("2099-12-01", "future_dated"), ("2024-02-30", "invalid_calendar_date"), ("2024", "valid")],
)
def test_provider_dates_are_flagged_without_discarding_bibliography(date, status):
    row = literature_record({"pmid": "1", "title": "Paper", "date": date}, "europepmc")
    assert row["date"] == date and row["date_validation"]["status"] == status


def test_trial_ranking_prioritizes_direct_matches_without_excluding_subtypes():
    rows = [
        {"title": "Leptomeningeal tumors", "conditions": ["Melanoma"]},
        {"title": "Advanced melanoma", "conditions": ["Melanoma"]},
        {"title": "Iris tumor", "conditions": ["Ocular melanoma"]},
    ]
    ranked = rank_trials(rows, "melanoma")
    assert ranked[0]["title"] == "Advanced melanoma" and len(ranked) == 3
    assert ranked[0]["ranking"]["scope"].startswith("Fetched")
