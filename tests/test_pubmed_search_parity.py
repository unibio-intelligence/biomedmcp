"""Provider-order comparisons must isolate PubMed from federation/reranking."""

import pytest
from native_helpers import HTTP

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService

XML = "<PubmedArticleSet>" + "".join(
    f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
    f"<ArticleTitle>{title}</ArticleTitle><PublicationTypeList>"
    "<PublicationType>Journal Article</PublicationType></PublicationTypeList>"
    "</Article></MedlineCitation></PubmedArticle>"
    for pmid, title in [("101", "Editorial background"), ("102", "BRAF V600E melanoma")]
) + "</PubmedArticleSet>"


@pytest.mark.parametrize("mode,expected", [("provider", ["101", "102"]), ("hybrid", ["102", "101"])])
async def test_same_pubmed_window_can_be_preserved_or_explicitly_reranked(mode, expected):
    wire = HTTP({"esearchresult": {"count": "2", "idlist": ["101", "102"]}}, XML)
    result = await execute(ResearchService(http=wire), "literature_search", {
        "query": "BRAF V600E melanoma", "limit": 10,
        "filters": {"source": "pubmed", "sort": "relevance", "ranking_mode": mode},
    }, scope="parity")
    assert [r["pmid"] for r in result.records] == expected
    assert result.query["execution"]["ranking"] == mode
    assert result.receipt.sources == ["pubmed"]
    params = wire.calls[0][2]["params"]
    assert params["term"] == "(BRAF V600E melanoma)" and params["sort"] == "relevance"
    assert params["retmax"] == 10 and params["retstart"] == 0
    assert wire.calls[1][2]["params"]["id"] == "101,102"
