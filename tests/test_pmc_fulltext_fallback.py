"""The connector pilot's Europe PMC outage must not hide available PMC text."""

import pytest
from native_helpers import HTTP, JATS, PUBMED

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.literature import Literature


def paper(accession="123", count=120):
    body = "".join(f"<p>Result {i}.</p>" for i in range(1, count + 1))
    return (
        '<pmc-articleset><article><front><article-meta>'
        f'<article-id pub-id-type="pmc">{accession}</article-id>'
        '<permissions><license><license-p>Article-specific terms</license-p></license></permissions>'
        f'</article-meta></front><body>{body}</body></article></pmc-articleset>'
    )


def request(**updates):
    return {"entity": "article", "id": "PMC123", "sections": ["fulltext"],
            "section_parameters": {"fulltext": {"view": "lines"}}, **updates}


async def test_outage_fallback_has_ncbi_evidence_and_pins_following_window():
    wire = HTTP(ResearchError("source_unavailable", "Synthetic HTTP 500"), paper(), paper())
    service = ResearchService(http=wire)
    result = await execute(service, "get", request(), scope="pilot")
    section = result.sections["fulltext"]
    assert section.data["lines"][0] == {"number": 1, "text": "Result 1."}
    assert len(section.data["lines"]) == 100
    assert section.data["license"] == "Article-specific terms"
    assert result.provenance[0].source == "pmc"
    assert result.receipt.sources == ["europepmc", "pmc"]
    assert any("source_unavailable" in w and "NCBI PMC" in w for w in section.warnings)
    action = result.next_actions[0]
    assert action["arguments"]["sources"] == ["pmc"]
    second = await execute(service, action["tool"], action["arguments"], scope="pilot")
    assert second.sections["fulltext"].data["lines"][0]["number"] == 101
    assert len(wire.calls) == 3
    assert wire.calls[1][2]["params"]["db"] == "pmc"
    assert wire.calls[1][2]["params"]["id"] == "123"


async def test_explicit_europepmc_does_not_silently_change_sources():
    wire = HTTP(ResearchError("source_unavailable", "Synthetic outage"))
    result = await execute(ResearchService(http=wire), "get", request(sources=["europepmc"]), scope="pilot")
    assert result.sections["fulltext"].error["code"] == "source_unavailable"
    assert len(wire.calls) == 1 and not result.provenance


@pytest.mark.parametrize("code", ["source_access_denied", "source_connection_rejected", "invalid_source_response"])
async def test_access_and_validation_failures_are_not_hidden_by_fallback(code):
    wire = HTTP(ResearchError(code, "Synthetic failure"))
    result = await execute(ResearchService(http=wire), "get", request(), scope="pilot")
    assert result.sections["fulltext"].error["code"] == code
    assert len(wire.calls) == 1


async def test_both_providers_unavailable_is_not_empty_evidence():
    wire = HTTP(ResearchError("source_unavailable", "First outage"),
                ResearchError("source_unavailable", "Second outage"))
    result = await execute(ResearchService(http=wire), "get", request(), scope="pilot")
    assert result.sections["fulltext"].outcome == "unavailable"
    assert not result.provenance
    assert result.receipt.sources == ["europepmc", "pmc"]


@pytest.mark.parametrize("xml,code", [
    (paper("456"), "identity_mismatch"),
    (JATS, "identity_mismatch"),
    ("<pmc-articleset/>", "invalid_source_response"),
    ("<pmc-articleset>" + JATS + JATS + "</pmc-articleset>", "invalid_source_response"),
    (('<article><front><article-meta><article-id pub-id-type="pmc">123</article-id>'
      '</article-meta></front></article>'), "source_unavailable"),
])
async def test_ncbi_requires_one_matching_full_article(xml, code):
    with pytest.raises(ResearchError) as error:
        await Literature(HTTP(xml)).fulltext("PMC123", source="pmc")
    assert error.value.code == code


async def test_native_ncbi_pmid_bridge_and_continuation_keep_identity():
    wire = HTTP(PUBMED, paper(), paper())
    service = ResearchService(http=wire)
    result = await execute(service, "get", request(id="PMID:123", sources=["pmc", "pubmed"]), scope="pilot")
    assert result.provenance[0].sources == ["pmc", "pubmed"]
    action = result.next_actions[0]
    assert action["arguments"]["id"] == "PMC123"
    assert action["arguments"]["sources"] == ["pmc"]
    following = await execute(service, action["tool"], action["arguments"], scope="pilot")
    assert following.sections["fulltext"].data["lines"][0]["number"] == 101


async def test_ncbi_assets_are_metadata_and_keep_the_actual_source():
    xml = JATS.replace('<article-meta>', '<article-meta><article-id pub-id-type="pmc">123</article-id>')
    data = await Literature(HTTP(xml)).fulltext("PMC123", view="assets", source="pmc")
    assert data["assets"][0]["source"] == "pmc"
    assert data["assets"][0]["retrieval"] == "metadata_only"


@pytest.mark.source_permissions
async def test_public_pmc_read_retains_article_specific_permissions():
    from biomedmcp.source_licensing import review

    result = await execute(ResearchService(http=HTTP(paper())), "get", request(sources=["pmc"]), scope="pilot")
    assert result.provenance[0].source == "pmc"
    assert review("pmc")["license"] == "article_specific"
    assert review("ncbi")["license"] == "LicenseRef-NCBI-PublicData"
    assert any("article_specific" in w for w in result.sections["fulltext"].warnings)
