"""Reproduced defects in the examples formerly supplied to agents."""

import pytest
from native_helpers import HTTP, JATS

from biomedmcp.dispatch import prepare
from biomedmcp.domain import ResearchService
from biomedmcp.native.literature import article_id


async def test_advertised_qualified_pmid_fulltext_reaches_europepmc_without_retry():
    http = HTTP({"resultList": {"result": [{"id": "123", "source": "MED", "pmcid": "PMC123"}]}}, JATS)
    service = ResearchService(http=http)
    args = {"entity": "article", "id": "PMID:123", "sections": ["fulltext"]}
    run = await prepare(service, "get", args, scope="example-test")
    assert http.calls == []
    result = await run()
    assert result.outcome == "data"
    assert result.sections["fulltext"].data["pmcid"] == "PMC123"
    assert len(http.calls) == 2
    assert http.calls[0][2]["params"]["query"] == 'EXT_ID:"123"'
    assert http.calls[1][1].endswith("/PMC123/fullTextXML")


@pytest.mark.parametrize(
    "identifier,expected", [("PMID:123", ("pmid", "123")), ("pmid:123", ("pmid", "123"))]
)
def test_qualified_pmid_has_explicit_namespace(identifier, expected):
    assert article_id(identifier) == expected


@pytest.mark.parametrize("identifier", ["PMID:PMC123", "PMID:10.1234/x", "PMID:", "PMID:123/456"])
def test_qualified_pmid_does_not_guess_other_namespaces(identifier):
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        article_id(identifier)
    assert caught.value.code == "invalid_identifier"


async def test_qualified_pmid_author_relation_retains_pubmed_ownership():
    from native_helpers import PUBMED

    from biomedmcp.contracts import Entity

    http = HTTP(PUBMED)
    result = await ResearchService(http=http).relate(
        Entity.article, "PMID:123", "authors", scope="example-test"
    )
    assert result.outcome == "data"
    assert result.provenance[0].source == "pubmed"
    assert http.calls[0][2]["params"]["id"] == "123"
