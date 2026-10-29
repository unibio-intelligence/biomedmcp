import pytest
from native_helpers import HTTP
from test_research_contracts import Adapters

from biomedmcp.errors import ResearchError
from biomedmcp.native.providers import NativeProviders


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,value",
    [
        (family, value)
        for family in ["ols", "gwas", "ncbi", "epmc", "cpic"]
        for value in [
            {},
            None,
            [],
            {"error": "application failure"},
            {"response": None},
            {"resultList": {"result": "wrong"}},
        ]
        if not (family == "cpic" and value == [])
    ],
)
async def test_malformed_source_shapes_cannot_be_healthy_empty(family, value):
    providers = NativeProviders(Adapters(), HTTP(value))
    with pytest.raises(ResearchError) as caught:
        if family == "ols":
            await providers.search("phenotype", "ols", "test", {}, 10, 0)
        elif family == "gwas":
            await providers.gwas("BRAF")
        elif family == "ncbi":
            await providers.ncbi_summary("gtr", "test")
        elif family == "epmc":
            await providers.literature.get("10.1234/test", "europepmc")
        else:
            await providers.pgx("CYP2D6", "interactions")
    assert caught.value.code == "invalid_source_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,value",
    [
        ("ols", {"response": {"docs": [], "numFound": 0, "start": 0}}),
        (
            "gwas",
            {
                "_embedded": {"associations": []},
                "page": {"size": 10, "totalElements": 0, "totalPages": 0, "number": 0},
            },
        ),
        ("gwas", {"page": {"size": 10, "totalElements": 0, "totalPages": 0, "number": 0}}),
        ("ncbi", {"esearchresult": {"idlist": []}}),
        ("epmc", {"resultList": {"result": []}}),
        ("cpic", []),
    ],
)
async def test_explicit_empty_source_collections_are_valid(family, value):
    providers = NativeProviders(Adapters(), HTTP(value))
    if family == "ols":
        result = await providers.search("phenotype", "ols", "test", {}, 10, 0)
    elif family == "gwas":
        result = await providers.gwas("BRAF")
    elif family == "ncbi":
        result = await providers.ncbi_summary("gtr", "test")
    elif family == "epmc":
        result = await providers.literature.get("10.1234/test", "europepmc")
    else:
        result = await providers.pgx("CYP2D6", "interactions")
    if family == "ols":
        assert result["records"] == [] and result["_provider_page"]["exhausted"]
    else:
        assert result == ({} if family == "epmc" else [])


@pytest.mark.asyncio
async def test_malformed_response_is_never_cached_as_healthy_empty():
    from biomedmcp.contracts import SearchRequest
    from biomedmcp.domain import ResearchService

    http = HTTP({}, {"response": {"docs": [], "numFound": 0, "start": 0}})
    service = ResearchService(http=http)
    request = SearchRequest(entity="phenotype", query="test")
    bad = await service.search(request, scope="local")
    assert bad.outcome == "error"
    assert next(iter(bad.sections.values())).error["code"] == "invalid_source_response"
    good = await service.search(request, scope="local")
    assert good.outcome == "empty"
    assert len(http.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["pubmed", "europepmc", "pubtator", "litsense2"])
@pytest.mark.parametrize("value", [{}, None, {"data": None}, {"results": [None]}])
async def test_literature_search_malformed_collections(source, value):
    from biomedmcp.native.literature import Literature

    with pytest.raises(ResearchError) as caught:
        await Literature(HTTP(value)).search_source(source, "BRAF", {}, 10)
    assert caught.value.code == "invalid_source_response"
