"""Bibliographic relations use the released Europe PMC projection, without S2."""

import pytest
from native_helpers import HTTP

from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.literature import Literature
from biomedmcp.dispatch import execute as dispatch


def response(relation="citations", rows=None, total=1):
    field = "citation" if relation == "citations" else "reference"
    return {"version": "6.9", "hitCount": total,
            field + "List": {field: rows if rows is not None else [
                {"source": "MED", "id": "456", "title": "BRAF study", "pubYear": 2024}]}}


@pytest.mark.parametrize("relation", ["citations", "references"])
@pytest.mark.parametrize("identifier,source,value", [("123", "MED", "123"), ("PMC123", "PMC", "PMC123")])
async def test_public_graph_uses_epmc_and_retains_bounded_coverage(relation, identifier, source, value):
    http = HTTP(response(relation, total=8))
    data = await Literature(http).open_graph(identifier, relation, limit=1)
    assert http.calls[0][1].endswith(f"/{source}/{value}/{relation}")
    assert http.calls[0][2]["params"] == {"format": "json", "pageSize": 1, "page": 1}
    assert data["records"][0]["pmid"] == "456"
    assert data["coverage"]["source_total"] == 8
    assert data["coverage"]["more_available"] is True
    assert data["coverage"]["exhaustive"] is False
    assert "abstract" not in data["records"][0] or data["records"][0]["abstract"] is None


@pytest.mark.parametrize("value", [{}, None, {"hitCount": 1, "citationList": {"citation": []}},
                                     response(rows=[{"title": "missing identity"}]),
                                     response(total=0), response(total=True)])
async def test_bad_graph_shapes_never_become_empty(value):
    with pytest.raises(ResearchError) as error:
        await Literature(HTTP(value)).open_graph("123", "citations")
    assert error.value.code == "invalid_source_response"


async def test_empty_graph_is_explicitly_source_scoped():
    data = await Literature(HTTP(response(rows=[], total=0))).open_graph("123", "citations")
    assert data["records"] == []
    assert data["coverage"]["source_total"] == 0
    assert data["coverage"]["exhaustive"] is False


async def test_unmatched_reference_remains_bibliography_without_invented_article_id():
    data = await Literature(HTTP(response("references", rows=[
        {"authorString": "Example A.", "pubYear": 2000, "citedOrder": 1, "match": "N"}
    ]))).open_graph("123", "references")
    row = data["records"][0]
    assert row["article_identity"] == "unresolved"
    assert row["reference_position"] == 1
    assert not row.get("pmid") and not row.get("doi") and not row.get("id")


async def test_doi_requires_one_exact_epmc_identity():
    http = HTTP({"resultList": {"result": [{"source": "MED", "id": "123", "doi": "10.1234/example"}]}},
                response())
    data = await Literature(http).open_graph("10.1234/example", "citations")
    assert data["records"][0]["pmid"] == "456"
    assert len(http.calls) == 2


async def test_doi_mismatch_stops_before_graph_acquisition():
    http = HTTP({"resultList": {"result": [{"source": "MED", "id": "123", "doi": "10.1234/other"}]}})
    with pytest.raises(ResearchError, match="identity"):
        await Literature(http).open_graph("10.1234/example", "references")
    assert len(http.calls) == 1


@pytest.mark.source_permissions
@pytest.mark.parametrize("relation", ["citations", "references"])
async def test_real_released_dispatch_never_calls_semantic_scholar(relation):
    service = ResearchService(http=HTTP(response(relation)))
    result = await dispatch(service, "relate", {"entity": "article", "id": "123", "relation": relation}, scope="test")
    assert result.outcome == "data"
    assert result.provenance[0].source == "europepmc"
    assert all("semanticscholar" not in call[1] for call in service.providers.http.calls)


@pytest.mark.source_permissions
async def test_removed_source_only_ids_are_rejected():
    service = ResearchService(http=HTTP())
    for identifier, relation in [("a" * 40, "recommendations"), ("a" * 40, "citations")]:
        with pytest.raises(ResearchError) as error:
            await dispatch(service, "relate", {"entity": "article", "id": identifier,
                                               "relation": relation}, scope="test")
        assert error.value.code == "invalid_identifier"
    assert not service.providers.http.calls
