"""Official alternative routes must retain identity, release and failure semantics."""

import io
import json
import zipfile
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError

EBI = "/ebisearch/ws/rest/reactome"
ENTRY = {
    "id": "109581",
    "source": "reactome",
    "fields": {
        "stid": ["R-HSA-109581"],
        "name": ["Apoptosis"],
        "species": ["Homo sapiens"],
        "type": ["Pathway"],
        "description": ["Cell death"],
    },
}
INDEX = {
    "domains": [
        {
            "id": "reactome",
            "indexInfos": [
                {"name": "Release version", "value": "97"},
                {"name": "Last modification date", "value": "observed-index-date"},
            ],
        }
    ]
}
PRODUCT = {
    "approval_date": "20010101",
    "product_number": "001",
    "products": [
        {
            "application_number": "021462",
            "application_type": "N",
            "application_name": "EXAMPLE",
            "application_full_name": "EXAMPLE INC",
            "brand_name": "GLEEVEC",
            "dosage_form": "TABLET",
            "route": "ORAL",
            "active_ingredients": [{"name": "IMATINIB MESYLATE", "strength": "100MG"}],
            "therapeutic_equivalence_codes": ["AB"],
            "reference_listed_drug": True,
            "reference_standard": False,
            "marketing_status": "HUMAN PRESCRIPTION DRUG",
        }
    ],
    "patents": [{"patent_number": "12345", "expiration_date": "20300101"}],
    "exclusivity": [{"exclusivity_code": "NCE", "exclusivity_expiration_date": "20290101"}],
}


def archive(records=None, total=1):
    contents = io.BytesIO()
    with zipfile.ZipFile(contents, "w") as handle:
        handle.writestr(
            "drug-orangebook-0001-of-0001.json",
            json.dumps(
                {
                    "meta": {"last_updated": "2026-10-16", "results": {"total": total}},
                    "results": [PRODUCT] if records is None else records,
                }
            ),
        )
    return contents.getvalue()


@pytest.fixture
def routes(monkeypatch):
    original = httpx.AsyncClient
    state = {
        "requests": [],
        "search": {"hitCount": 1, "entries": [ENTRY]},
        "bulk": archive(),
        "media_status": 404,
    }

    def respond(request):
        state["requests"].append(request)
        if request.url.host == "reactome.org":
            return httpx.Response(500, json={"messages": ["Solr exception"]})
        if request.url.host == "www.ebi.ac.uk":
            assert request.url.path == EBI
            return httpx.Response(200, json=state["search"] if "query" in request.url.params else INDEX)
        if request.url.host == "www.fda.gov":
            return httpx.Response(state["media_status"])
        assert request.url.host == "download.open.fda.gov"
        return httpx.Response(200, content=state["bulk"])

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    return state


async def test_reactome_search_uses_official_index_despite_solr_outage(routes):
    result = await SourceAdapters().call("reactome", "search_pathways", {"query": "apoptosis", "limit": 2})
    assert result["records"][0]["id"] == "R-HSA-109581"
    assert result["total"] == 1 and result["exhausted"] is True
    assert result["search_index"]["release_version"] == "97"
    assert result["search_endpoint"] == "https://www.ebi.ac.uk" + EBI
    assert not any(r.url.host == "reactome.org" for r in routes["requests"])


@pytest.mark.parametrize("term", ["melanoma) OR type:Protein OR (", '" OR species:mouse', "type 2 diabetes"])
async def test_reactome_query_cannot_override_scope(routes, term):
    await SourceAdapters().call("reactome", "search_pathways", {"query": term})
    request = next(r for r in routes["requests"] if "query" in r.url.params)
    assert request.url.params["query"].endswith(' AND type:Pathway AND species:"Homo sapiens"')
    assert request.url.params["start"] == "0"
    if term.startswith('"'):
        assert request.url.params["query"].startswith('("\\" OR species:mouse")')


@pytest.mark.parametrize(
    "change",
    [
        {"source": "other"},
        {"id": "99"},
        {"fields": {**ENTRY["fields"], "species": ["Mus musculus"]}},
        {"fields": {**ENTRY["fields"], "type": ["Reaction"]}},
        {"fields": {**ENTRY["fields"], "stid": []}},
    ],
)
async def test_reactome_index_rejects_foreign_identity(routes, change):
    routes["search"] = {"hitCount": 1, "entries": [{**ENTRY, **change}]}
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("reactome", "search_pathways", {"query": "apoptosis"})
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "operation,params,key",
    [
        ("search_products", {"ingredient": "imatinib"}, "results"),
        ("get_therapeutic_equivalence", {"application_number": "NDA021462"}, "products"),
        ("search_generic_equivalents", {"ingredient": "imatinib"}, "generics"),
        ("get_patent_info", {"application_number": "NDA021462"}, "patents"),
        ("get_exclusivity_info", {"application_number": "NDA021462"}, "exclusivity"),
    ],
)
async def test_fda_404_uses_complete_official_json_export(routes, operation, params, key):
    result = await SourceAdapters().call("orange-book", operation, params)
    assert result[key]
    assert result["source_release"]["last_updated"] == "2026-10-16"
    assert result["source_release"]["format"] == "openfda-orangebook-json"
    assert result["source_release"]["records"] == 1


@pytest.mark.parametrize(
    "records,total",
    [
        ([], 1),
        ([PRODUCT], 2),
        ([PRODUCT, PRODUCT], 2),
        ([{}], 1),
        ([{**PRODUCT, "products": []}], 1),
        ([{**PRODUCT, "patents": "broken"}], 1),
    ],
)
async def test_fda_partial_or_malformed_export_is_not_absence(routes, records, total):
    routes["bulk"] = archive(records, total)
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("orange-book", "get_patent_info", {"application_number": "021462"})
    assert error.value.code == "invalid_source_response"


async def test_fda_access_denied_does_not_trigger_alternative(routes):
    routes["media_status"] = 403
    with pytest.raises(ResearchError):
        await SourceAdapters().call("orange-book", "search_products", {"ingredient": "imatinib"})
    assert len(routes["requests"]) == 1


async def test_fda_missing_strength_is_preserved_without_inventing_a_dose(routes):
    product = deepcopy(PRODUCT)
    del product["products"][0]["active_ingredients"][0]["strength"]
    routes["bulk"] = archive([product])
    result = await SourceAdapters().call("orange-book", "search_products", {"ingredient": "imatinib"})
    assert result["results"][0]["Strength"] == ""
    assert "strength" not in result["results"][0]["openfda_record"]["products"][0]["active_ingredients"][0]


@pytest.mark.parametrize(
    "source,operation,projection",
    [
        ("orange-book", "search_products", "orange-book-literal-products-v1"),
        ("reactome", "search_pathways", None),
    ],
)
async def test_provider_route_upgrade_does_not_reuse_old_projection(source, operation, projection):
    from biomedmcp.domain import ResearchService
    from biomedmcp.native import REVISION
    from biomedmcp.runtime import ProviderRuntime

    runtime = ProviderRuntime()
    key = {"operation": operation, "params": {}, "version": None, "implementation": REVISION}
    if projection:
        key["projection"] = projection
    await runtime.invoke(
        source, key, AsyncMock(return_value={"records": [{"id": "old-route"}]}), scope="audit"
    )
    adapters = SourceAdapters()
    adapters.call = AsyncMock(return_value={"records": [{"id": "current-route"}]})
    service = ResearchService(runtime=runtime, adapters=adapters)
    first, first_proof = await service._acquire(
        source, operation, {}, lambda: adapters.call(source, operation, {}), scope="audit"
    )
    assert first.data["records"][0]["id"] == "current-route"
    assert adapters.call.await_count == 1 and first_proof.cached is False
    second, second_proof = await service._acquire(
        source, operation, {}, lambda: adapters.call(source, operation, {}), scope="audit"
    )
    assert second.data == first.data
    assert adapters.call.await_count == 1 and second_proof.cached is True


async def test_legacy_contentservice_cursor_cannot_resume_in_ebi_ranking():
    from biomedmcp.contracts import SearchRequest
    from biomedmcp.domain import ResearchService
    from biomedmcp.native import REVISION

    service = ResearchService()
    request = SearchRequest(entity="pathway", query="apoptosis", limit=2)
    legacy_query = {
        **request.model_dump(mode="json", exclude={"cursor", "freshness"}),
        "implementation": REVISION,
        "contract": "2.0",
    }
    legacy_query["filters"].pop("species", None)
    cursor = service.runtime.cursors.encode(query=legacy_query, scope="audit", offset=2)
    with pytest.raises(ResearchError) as error:
        await service.search(request.model_copy(update={"cursor": cursor}), scope="audit", _plan_only=True)
    assert error.value.code == "invalid_cursor"


async def test_fda_wrong_export_member_is_a_shape_error_not_a_size_error(routes):
    contents = io.BytesIO()
    with zipfile.ZipFile(contents, "w") as handle:
        handle.writestr("unrelated.json", "{}")
    routes["bulk"] = contents.getvalue()
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("orange-book", "search_products", {"ingredient": "imatinib"})
    assert error.value.code == "invalid_source_response"
