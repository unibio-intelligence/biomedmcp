"""Source identity and projection regressions for the open literature alternative."""

import pytest
from native_helpers import HTTP

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.openalex import OpenAlex, work

pytestmark = pytest.mark.source_permissions


def author():
    return {
        "id": "https://openalex.org/A123",
        "display_name": "Jane Researcher",
        "orcid": "https://orcid.org/0000-0002-1825-0097",
        "works_count": 5,
        "cited_by_count": 10,
        "private_unexpected": "excluded",
    }


def article(n=1):
    return {
        "id": f"https://openalex.org/W{n}",
        "ids": {"doi": f"https://doi.org/10.1234/test{n}"},
        "title": "Synthetic research",
        "publication_date": "2024-01-01",
        "is_retracted": False,
        "open_access": {"is_oa": True},
        "cited_by_count": 0,
        "authorships": [{"author": author()}],
        "related_works": ["https://openalex.org/W2"],
        "abstract_inverted_index": {"held": [0]},
        "tldr": "excluded",
    }


async def test_author_search_pagination_and_record_are_source_qualified():
    http = HTTP({"meta": {"count": 2}, "results": [author()]}, author())
    api = OpenAlex(http)
    out = await api.search_authors("Jane Researcher", 1, 1)
    assert out["records"][0]["id"] == "openalex:A123"
    assert out["_provider_page"]["exhausted"]
    assert http.calls[0][2]["params"]["page"] == 2
    assert "private_unexpected" not in str(out)
    assert (await api.get_author("openalex:A123"))["name"] == "Jane Researcher"


async def test_author_works_prove_author_membership_and_preserve_typed_bibliography():
    http = HTTP({"meta": {"count": 5}, "results": [article()]})
    out = await OpenAlex(http).author_works("openalex:A123", 2)
    assert out["coverage"]["source_total"] == 5 and not out["coverage"]["exhaustive"]
    row = out["records"][0]
    assert row["identities"][0]["namespace"] == "doi"
    assert any(x["namespace"] == "openalex" for x in row["identities"])
    assert row["citation_count"] == 0 and row["is_retracted"] is False
    assert row["content_scope"] == "bibliographic"
    assert "tldr" not in row and "abstract_inverted_index" not in row


async def test_related_work_order_and_exact_seed_identity():
    seed = article()
    seed["related_works"] = ["https://openalex.org/W3", "https://openalex.org/W2"]
    http = HTTP(seed, {"meta": {"count": 2}, "results": [article(2), article(3)]})
    out = await OpenAlex(http).recommendations("10.1234/test1", 2)
    assert [r["openalex_id"] for r in out["records"]] == ["openalex:W3", "openalex:W2"]
    assert "shared topics" in out["method"] and not out["coverage"]["exhaustive"]


@pytest.mark.parametrize("change", ["identity", "count", "authors", "citation_count", "access_flag"])
async def test_malformed_source_metadata_is_not_empty_evidence(change):
    row = article()
    if change == "identity":
        row["id"] = "https://evil.example/W1"
    if change == "authors":
        row["authorships"] = None
    if change == "citation_count":
        row["cited_by_count"] = True
    if change == "access_flag":
        row["open_access"]["is_oa"] = "yes"
    http = HTTP({"meta": {"count": "bad" if change == "count" else 1}, "results": [row]})
    with pytest.raises(ResearchError):
        await OpenAlex(http).author_works("openalex:A123", 2)


async def test_mismatched_seed_and_unexpected_related_ids_fail():
    with pytest.raises(ResearchError, match="identity"):
        await OpenAlex(HTTP(article())).recommendations("10.1234/other", 2)
    with pytest.raises(ResearchError):
        await OpenAlex(HTTP(article(), {"meta": {"count": 1}, "results": [article(3)]})).recommendations(
            "10.1234/test1", 2
        )


async def test_canonical_dispatch_and_capabilities_offer_open_author_and_related_work_routes():
    service = ResearchService(
        http=HTTP(
            {"meta": {"count": 1}, "results": [author()]},
            author(),
            {"meta": {"count": 1}, "results": [article()]},
            article(),
            {"meta": {"count": 1}, "results": [article(2)]},
        )
    )
    search = await execute(
        service,
        "search",
        {"entity": "author", "query": "Jane", "filters": {"source": "openalex"}, "limit": 2},
        scope="one",
    )
    assert search.outcome == "data"
    profile = await execute(service, "get", {"entity": "author", "id": "openalex:A123"}, scope="one")
    assert profile.outcome == "data"
    works = await execute(
        service,
        "relate",
        {"entity": "author", "id": "openalex:A123", "relation": "articles", "limit": 2},
        scope="one",
    )
    assert works.outcome == "data"
    related = await execute(
        service,
        "relate",
        {"entity": "article", "id": "openalex:W1", "relation": "recommendations", "limit": 2},
        scope="one",
    )
    assert related.outcome == "data"
    caps = await service.capabilities(source="openalex")
    assert caps["configured"] and len(caps["canonical_routes"]) >= 3


def test_unexpected_narrative_never_leaks_from_openalex_metadata():
    assert "excluded" not in str(work(article()))


@pytest.mark.parametrize(
    "field,url,expected",
    [
        ("pmid", "https://pubmed.ncbi.nlm.nih.gov/123", "123"),
        ("pmid", "http://www.ncbi.nlm.nih.gov/pubmed/123", "123"),
        ("pmcid", "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/", "PMC123"),
        ("pmcid", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123", "PMC123"),
    ],
)
def test_official_current_and_historical_ncbi_uri_forms(field, url, expected):
    row = article()
    row["ids"][field] = url
    assert work(row)[field] == expected


async def test_related_ids_missing_from_current_index_remain_explicit_unresolved_evidence():
    seed = article()
    seed["related_works"] = ["https://openalex.org/W3", "https://openalex.org/W2"]
    http = HTTP(seed, {"meta": {"count": 1}, "results": [article(2)]})
    out = await OpenAlex(http).recommendations("10.1234/test1", 2)
    assert out["unresolved_related_work_ids"] == ["openalex:W3"]
    assert out["coverage"]["requested_window"] == 2
    assert out["coverage"]["unresolved"] == 1
    assert [r["openalex_id"] for r in out["records"]] == ["openalex:W2"]


@pytest.mark.parametrize("host,expected", [("api.openalex.org", True), ("api.openalex.org.example", False)])
async def test_operator_key_is_wire_only_and_bound_to_exact_openalex_origin(monkeypatch, host, expected):
    import httpx

    from biomedmcp.native import http

    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, url, **kwargs):
            calls.append(kwargs)
            return httpx.Response(200, json={"results": []}, request=httpx.Request(method, url))

    monkeypatch.setenv("OPENALEX_API_KEY", "synthetic-operator-key")
    monkeypatch.setattr(http.httpx, "AsyncClient", Client)
    result = await http.ProviderHTTP().get("https://" + host + "/authors", params={"search": "Jane"})
    assert ("synthetic-operator-key" in str(calls[0].get("headers"))) is expected
    assert "synthetic-operator-key" not in str(calls[0].get("params"))
    assert "synthetic-operator-key" not in str(result)


async def test_all_unresolved_related_work_metadata_is_partial_not_evidence_of_no_work():
    seed = article()
    service = ResearchService(http=HTTP(seed, {"meta": {"count": 0}, "results": []}))
    result = await execute(
        service,
        "relate",
        {"entity": "article", "id": "10.1234/test1", "relation": "recommendations", "limit": 2},
        scope="one",
    )
    assert result.outcome == "partial"
    assert result.sections["recommendations"].data["unresolved_related_work_ids"] == ["openalex:W2"]


async def test_pmid_uses_documented_shorthand_and_confirms_returned_identity():
    seed = article()
    seed["ids"]["pmid"] = "https://pubmed.ncbi.nlm.nih.gov/123"
    http = HTTP(seed, {"meta": {"count": 1}, "results": [article(2)]})
    await OpenAlex(http).recommendations("123", 2)
    assert http.calls[0][1].endswith("/works/pmid%3A123")


async def test_pmcid_uses_exact_epmc_identity_bridge_with_both_source_notices():
    bridge = {
        "resultList": {"result": [{"source": "MED", "id": "123", "pmcid": "PMC123", "doi": "10.1234/test1"}]}
    }
    service = ResearchService(http=HTTP(bridge, article(), {"meta": {"count": 1}, "results": [article(2)]}))
    result = await execute(
        service,
        "relate",
        {"entity": "article", "id": "PMC123", "relation": "recommendations", "limit": 2},
        scope="one",
    )
    assert result.outcome == "data"
    assert result.provenance[0].sources == ["europepmc", "openalex"]
    assert service.providers.http.calls[0][2]["params"]["query"] == "PMCID:PMC123"
    assert result.sections["recommendations"].data["identity_bridge"]["pmcid"] == "PMC123"


@pytest.mark.parametrize(
    "row",
    [
        [],
        [{"source": "MED", "id": "123", "pmcid": "PMC999", "doi": "10.1234/test1"}],
        [{"source": "PMC", "id": "PMC123", "pmcid": "PMC123"}],
    ],
)
async def test_pmcid_identity_bridge_cannot_invent_or_substitute_an_article(row):
    http = HTTP({"resultList": {"result": row}})
    with pytest.raises(ResearchError):
        await OpenAlex(http).recommendations("PMC123", 2)
    assert len(http.calls) == 1


async def test_direct_epmc_article_read_uses_exact_unquoted_pmcid_syntax():
    from biomedmcp.native.literature import Literature

    http = HTTP(
        {
            "resultList": {
                "result": [{"source": "MED", "id": "123", "pmcid": "PMC123", "doi": "10.1234/test1"}]
            }
        }
    )
    result = await Literature(http).get("PMC123", "europepmc")
    assert result["pmcid"] == "PMC123"
    assert http.calls[0][2]["params"]["query"] == "PMCID:PMC123"
