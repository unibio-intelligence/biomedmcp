import pytest
from defusedxml import ElementTree
from native_helpers import HTTP, JATS, PUBMED

from biomedmcp.errors import ResearchError
from biomedmcp.evidence import deduplicate_articles
from biomedmcp.native.literature import Literature, article_id, plan_sources, rank_articles


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({"source": "pubmed"}, ["pubmed"]),
        ({"source": "europepmc", "open_access": True}, ["europepmc"]),
        ({"author": ["A Smith"]}, ["pubmed", "europepmc"]),
        ({"no_preprints": True}, ["europepmc"]),
        ({"open_access": True, "author": ["A Smith"]}, ["europepmc"]),
    ],
)
def test_source_planner_is_filter_compatible_and_explicit(filters, expected):
    assert plan_sources(filters) == expected


@pytest.mark.parametrize(
    "filters",
    [
        {"source": "pubtator", "author": ["A"]},
        {"source": "pubmed", "open_access": True},
        {"source": "unknown"},
        {"ranking_mode": "lexical", "sort": "date"},
    ],
)
def test_source_restrictions_fail_before_requests(filters):
    with pytest.raises(ResearchError):
        plan_sources(filters)


def test_xml_complete_authors_retraction_identity_and_mesh():
    row = Literature.parse_pubmed(ElementTree.fromstring(PUBMED))[0]
    assert row["authors"] == ["Alice Smith", "Study Group"]
    assert row["author_records"][0]["affiliations"] == ["Example University"]
    assert row["is_retracted"] is True
    assert row["pmid"] == "123" and row["doi"] == "10.1234/synthetic"
    assert row["title"] == "BRAF V600E in cancer"
    assert row["mesh"] == ["Neoplasms"]


async def test_pubmed_provider_query_and_fetch_ids():
    http = HTTP({"esearchresult": {"idlist": ["123"]}}, PUBMED)
    rows = await Literature(http).search_source(
        "pubmed", "BRAF", {"author": ["Alice Smith"], "date_from": "2023-01-01"}, 10
    )
    assert rows[0]["pmid"] == "123"
    assert '"Alice Smith"[Author]' in http.calls[0][2]["params"]["term"]
    assert http.calls[0][2]["params"]["mindate"] == "2023-01-01"
    assert http.calls[1][2]["params"]["id"] == "123"


async def test_epmc_explicit_access_filters_and_provider_cursor():
    http = HTTP(
        {"resultList": {"result": [{"id": str(n), "source": "MED", "title": str(n)} for n in (2, 3)]}}
    )
    rows = await Literature(http).search_source(
        "europepmc", "BRAF", {"open_access": True, "no_preprints": True}, 2, 2, continuation="provider-token"
    )
    assert [r["pmid"] for r in rows] == ["2", "3"]
    q = http.calls[0][2]["params"]["query"]
    assert "OPEN_ACCESS:Y" in q and "NOT SRC:PPR" in q
    assert http.calls[0][2]["params"]["pageSize"] == 2
    assert http.calls[0][2]["params"]["cursorMark"] == "provider-token"


async def test_pubtator_page_boundary_nonmultiple_of_ten():
    http = HTTP(
        *[
            {"results": [{"pmid": str(i), "title": str(i)} for i in range(start, start + 10)]}
            for start in (0, 10)
        ]
    )
    rows = await Literature(http).search_source("pubtator", "BRAF", {}, 5, 8)
    assert [r["pmid"] for r in rows] == ["8", "9", "10", "11", "12"]
    assert [call[2]["params"]["page"] for call in http.calls] == [1, 2]


async def test_litsense_uses_sentence_reranking_endpoint():
    http = HTTP([{"pmid": 123, "sentence": "BRAF is involved."}])
    rows = await Literature(http).search_source("litsense2", "BRAF", {}, 10)
    assert http.calls[0][1].endswith("/api/sentences/")
    assert http.calls[0][2]["params"]["rerank"] == "true"
    assert rows[0]["abstract"] == "BRAF is involved."


async def test_fulltext_bounded_lines_license_and_metadata_assets():
    client = Literature(HTTP(JATS, JATS, JATS))
    outline = await client.fulltext("PMC123", view="outline")
    assert outline["outline"] == [{"line": 1, "title": "Results"}]
    lines = await client.fulltext("PMC123", view="lines", start=2, end=2)
    assert lines["lines"] == [{"number": 2, "text": "Measured BRAF V600E activity."}]
    assert lines["license"] == "CC BY 4.0" and lines["truncated"]
    assets = await client.fulltext("PMC123", view="assets")
    assert assets["assets"][0]["retrieval"] == "metadata_only"
    assert len(client.http.calls) == 3  # no arbitrary attachment fetch


async def test_metadata_only_article_is_not_presented_as_full_text():
    with pytest.raises(ResearchError, match="body"):
        await Literature(HTTP("<article><front/></article>")).fulltext("PMC123")


def test_transitive_identity_merges_ranks_and_preserves_retraction():
    rows = [
        {"pmid": "1", "_provider_ranks": {"pubmed": 2}, "sources": ["pubmed"], "is_retracted": False},
        {
            "doi": "10.1234/x",
            "_provider_ranks": {"europepmc": 1},
            "sources": ["europepmc"],
            "is_retracted": True,
        },
        {
            "pmid": "1",
            "doi": "10.1234/x",
            "_provider_ranks": {"openalex": 3},
            "sources": ["openalex"],
            "is_retracted": None,
        },
    ]
    merged = deduplicate_articles(rows)
    assert len(merged) == 1 and merged[0]["is_retracted"] is True
    assert merged[0]["_provider_ranks"] == {"pubmed": 2, "europepmc": 1, "openalex": 3}
    assert len(merged[0]["sources"]) == 3


def test_ranking_lexical_provider_and_date_are_distinct():
    rows = [
        {"pmid": "1", "title": "BRAF variant", "date": "2020", "_provider_ranks": {"pubmed": 9}},
        {"pmid": "2", "title": "Other subject", "date": "2024", "_provider_ranks": {"pubmed": 1}},
    ]
    assert rank_articles(rows, "BRAF", mode="lexical")[0]["pmid"] == "1"
    assert rank_articles(rows, "BRAF", mode="provider")[0]["pmid"] == "2"
    assert rank_articles(rows, "BRAF", sort="date")[0]["pmid"] == "2"




@pytest.mark.parametrize("value", ["../secret", "paper title", "https://private.invalid/x"])
def test_arbitrary_article_urls_are_not_fetchable(value):
    with pytest.raises(ResearchError):
        article_id(value)


@pytest.mark.parametrize("source", ["pubmed", "europepmc", "pubtator"])
async def test_changed_response_shapes_do_not_become_negative_evidence(source):
    with pytest.raises(ResearchError) as caught:
        await Literature(HTTP({})).search_source(source, "BRAF", {}, 10)
    assert caught.value.code == "invalid_source_response"
