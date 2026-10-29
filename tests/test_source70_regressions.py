"""Identity preflight and recoverable scientific views across composed operations."""

import pytest
from native_helpers import BRAF, HTTP
from test_reactome_contracts import PARTICIPANT, PID, REACTION, reactome_http  # noqa: F401

from biomedmcp.contracts import Provenance, ResearchResult
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.pagination import page_payload
from biomedmcp.scientific_records import literature_record


@pytest.mark.parametrize("filters", [{"gene": "KRAS"}, {"hgvsp": "G12D"}, {"gene": "KRAS", "hgvsp": "G12D"}])
async def test_conflicting_variant_shorthand_is_rejected_before_acquisition(filters):
    http = HTTP({"total": 1, "hits": [BRAF]})
    with pytest.raises(ResearchError) as caught:
        await execute(
            ResearchService(http=http),
            "search",
            {
                "entity": "variant",
                "query": "BRAF V600E",
                "filters": filters,
            },
            scope="test",
        )
    assert caught.value.code == "invalid_parameters" and not http.calls


async def test_equivalent_explicit_variant_filters_preserve_identity():
    http = HTTP({"total": 1, "hits": [BRAF]})
    result = await execute(
        ResearchService(http=http),
        "search",
        {
            "entity": "variant",
            "query": "BRAF V600E",
            "filters": {"gene": "braf", "hgvsp": "p.Val600Glu"},
        },
        scope="test",
    )
    assert len(result.records) == 1
    assert 'dbnsfp.genename:"BRAF"' in http.calls[0][2]["params"]["q"]
    assert "Val600Glu" in http.calls[0][2]["params"]["q"]


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"species": 10090}, "unsupported_species"),
        ({"assembly": "grch38"}, "invalid_assembly"),
        ({"sections": ["invalid"]}, "unknown_section"),
        ({"section_parameters": {"genes": {"limit": 1}}}, "unsupported_section_parameters"),
    ],
)
@pytest.mark.parametrize("dispatch", [False, True])
async def test_pathway_name_scope_rejected_before_even_empty_discovery(
    monkeypatch, arguments, code, dispatch
):
    service = ResearchService()
    calls = []

    async def empty(*args, **kwargs):
        calls.append(True)
        return page_payload([], raw_count=0, exhausted=True)

    monkeypatch.setattr(service.providers, "search", empty)
    with pytest.raises(ResearchError) as caught:
        if dispatch:
            await execute(
                service,
                "research",
                {
                    "workflow": "pathway_review",
                    "focus": "Synthetic pathway",
                    **arguments,
                },
                scope="test",
            )
        else:
            await service.research("pathway_review", "Synthetic pathway", scope="test", **arguments)
    assert (
        caught.value.code
        == ("invalid_parameters" if dispatch and "section_parameters" in arguments else code)
        and not calls
    )


@pytest.mark.parametrize("repetitions", [35, 8000])
async def test_pathway_relevance_precedes_excerpt_and_nested_recovery_is_exact(
    reactome_http, monkeypatch, repetitions  # noqa: F811
):
    reactome_http["payloads"][f"/ContentService/data/participants/{PID}"] = [PARTICIPANT]
    reactome_http["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [REACTION]
    service = ResearchService()
    abstract = "Background context. " * repetitions + "Synthetic pathway signaling is the mechanism tested."

    async def papers(source, *args, **kwargs):
        rows = [
            literature_record(
                {"pmid": "100", "title": "A molecular experiment", "abstract": abstract}, source
            ),
            literature_record(
                {"pmid": "101", "title": "Unrelated experiment", "abstract": "No relation"}, source
            ),
        ]
        return page_payload(rows, raw_count=2, exhausted=True)

    monkeypatch.setattr(service.providers.literature, "search_source", papers)
    result = await execute(service, "research", {"workflow": "pathway_review", "focus": PID}, scope="test")
    data = result.sections["literature"].data
    assert len(data["records"]) == 1 and data["records"][0]["pmid"] == "100"
    assert len(data["records"][0]["abstract"]) == 500
    recovery = data["query"]["output_omissions"]["composed_recovery"]
    assert recovery["snapshot_status"] == "available"
    recovered = await service.read_evidence(recovery["uri"], scope="test")
    assert len(recovered["value"]["records"]) == 1
    from biomedmcp.recovery import parse_uri, resource_uri

    handle, _, _, _ = parse_uri(recovery["uri"])
    uri = resource_uri(handle, "/records/0/abstract", count=4000)
    chunks = []
    while uri:
        page = await service.read_evidence(uri, scope="test")
        chunks.append(page["value"])
        uri = page["next_uri"]
    assert "".join(chunks) == abstract
    with pytest.raises(ResearchError):
        await service.read_evidence(recovery["uri"], scope="other")


async def test_both_nested_research_sections_preserve_pending_recovery(monkeypatch):
    service = ResearchService()
    proof = Provenance(evidence_id="ev_synthetic_composed", source="pubmed", content_hash="a" * 64)

    async def base(*args, **kwargs):
        return ResearchResult(entity="drug", outcome="data")

    async def summary(*args, **kwargs):
        result = ResearchResult(
            entity="article", outcome="data", records=[{"id": "short"}], provenance=[proof]
        )
        result._omitted_evidence = {"records": [{"id": "short", "omitted": "RECOVER-ME"}]}
        return result

    monkeypatch.setattr(service, "get", base)
    monkeypatch.setattr(service, "search", summary)
    monkeypatch.setattr(service, "relate", summary)
    result = await execute(service, "research", {"workflow": "drug_review", "focus": "drug"}, scope="test")
    for name in ("literature", "related_trials"):
        recovery = result.sections[name].data["query"]["output_omissions"]["composed_recovery"]
        value = await service.read_evidence(recovery["uri"], scope="test")
        assert value["value"]["records"][0]["omitted"] == "RECOVER-ME"


async def test_nested_omission_storage_failure_is_explicit():
    from biomedmcp.evidence import compose_evidence

    result = ResearchResult(outcome="data", records=[{"id": "short"}])
    result._omitted_evidence = {"records": [{"id": "full"}]}
    section = await compose_evidence(result, store=None, scope="test", operation="literature_search")
    recovery = section.data["query"]["output_omissions"]["composed_recovery"]
    assert recovery == {"snapshot_status": "unavailable", "reason": "snapshot_storage_unavailable"}


def test_error_constraints_discover_schema_once_and_generic_errors_never_do(monkeypatch):
    from biomedmcp import errors, public_catalog
    from biomedmcp.utility_contracts import validate_utility

    errors._parameter_field_names.cache_clear()
    original = public_catalog.schema
    calls = []

    def counted(operation):
        calls.append(operation)
        return original(operation)

    monkeypatch.setattr(public_catalog, "schema", counted)
    try:
        errors.invalid_parameters()
        assert calls == []
        for _ in range(2):
            with pytest.raises(ResearchError) as caught:
                validate_utility("batch", {"calls": []})
            assert caught.value.as_dict()["fields"] == {"$.calls": "too_short"}
        assert calls and len(calls) == len(set(calls))
    finally:
        errors._parameter_field_names.cache_clear()


@pytest.mark.parametrize("incomplete", ["cursor", "truncated", "partial"])
async def test_pathway_name_does_not_resolve_from_incomplete_window(monkeypatch, incomplete):
    service = ResearchService()

    async def search(*args, **kwargs):
        return ResearchResult(
            entity="pathway",
            outcome="partial" if incomplete == "partial" else "data",
            records=[{"id": PID, "name": "Synthetic pathway"}],
            next_cursor="uninspected-candidates" if incomplete == "cursor" else None,
            truncated=incomplete == "truncated",
        )

    async def forbidden(*args, **kwargs):
        pytest.fail("Incomplete discovery must not choose a pathway")

    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service, "get", forbidden)
    result = await execute(
        service, "research", {"workflow": "pathway_review", "focus": "Synthetic pathway"}, scope="test"
    )
    assert result.outcome == "ambiguous"
