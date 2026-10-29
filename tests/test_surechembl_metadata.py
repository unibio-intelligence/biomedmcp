"""Current SureChEMBL metadata windows: source shape, permission scope and counts."""

from copy import deepcopy

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions


def window(query="ttl:ezetimibe", *, total=2, rows=None):
    return {
        "status": "OK",
        "error_message": "",
        "timestamp": "2026-10-11 17:22:16 +0000",
        "data": {
            "type": "CONTENT",
            "results": {
                "query": query,
                "total_hits": total,
                "documents": rows
                if rows is not None
                else [
                    {
                        "docId": "MX-2008011418-A",
                        "metadata": {
                            "pn": "MX-2008011418-A",
                            "pd": "20080922",
                            "titles": [{"titles": ["unreleased-source-text"]}],
                        },
                        "pa": "TEVA PHARMA",
                        "claims": "unreleased-claims",
                    },
                    {"docId": "CA-2644905-A1", "metadata": {"pd": "null"}, "pa": "null"},
                ],
            },
        },
    }


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def install(handler):
        calls = []

        def respond(request):
            calls.append(request)
            return httpx.Response(200, json=deepcopy(handler(request)))

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
        )
        return calls

    return install


async def test_metadata_search_current_post_route_projection_and_unknown_fields(wire):
    calls = wire(lambda request: window())
    result = await SourceAdapters().call("surechembl", "query_patents", {"query": "ttl:ezetimibe"})
    assert calls[0].method == "POST" and calls[0].url.path == "/api/search/content"
    assert dict(calls[0].url.params) == {"query": "ttl:ezetimibe", "page": "1", "itemsPerPage": "25"}
    assert result["records"][0]["publication_date"] == "2008-09-22"
    assert result["records"][1]["publication_date"] is None and result["records"][1]["assignee"] is None
    assert "unreleased" not in str(result)
    assert result["coverage"]["all_matching_records_acquired"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        [],
        {"status": "OK"},
        {"status": "OK", "data": None},
        {"status": "OK", "data": {}},
        {"status": "OK", "data": [], "error_message": "secret-sentinel"},
    ],
)
async def test_missing_or_wrong_envelope_not_empty(wire, payload):
    wire(lambda request: payload)
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "query_patents", {"query": "ttl:ezetimibe"})
    assert caught.value.code == "invalid_source_response"
    assert "secret-sentinel" not in str(caught.value)


async def test_application_error_does_not_leak_or_become_evidence(wire, caplog):
    wire(lambda request: {"status": "ERROR", "error_message": "credential-sentinel", "data": {}})
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "get_patent_statistics", {"query": "ttl:ezetimibe"})
    assert caught.value.code == "source_unavailable"
    assert "credential-sentinel" not in caplog.text + str(caught.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "query",
        "type",
        "total_bool",
        "total_negative",
        "total_small",
        "missing_documents",
        "null_documents",
        "duplicate",
        "id",
        "mismatch",
        "date",
        "date_bool",
        "assignee",
    ],
)
async def test_malformed_window_rejected_before_extraction(wire, mutation):
    payload = window()
    results = payload["data"]["results"]
    if mutation == "query":
        results["query"] = "different"
    elif mutation == "type":
        payload["data"]["type"] = "DOCUMENTS_FOR_STRUCTURES"
    elif mutation.startswith("total_"):
        results["total_hits"] = {"total_bool": True, "total_negative": -1, "total_small": 1}[mutation]
    elif mutation == "missing_documents":
        results.pop("documents")
    elif mutation == "null_documents":
        results["documents"] = None
    elif mutation == "duplicate":
        results["documents"][1] = results["documents"][0]
    elif mutation == "id":
        results["documents"][0]["docId"] = "wrong"
    elif mutation == "mismatch":
        results["documents"][0]["metadata"]["pn"] = "US-123-A1"
    elif mutation in {"date", "date_bool"}:
        results["documents"][0]["metadata"]["pd"] = "20260231" if mutation == "date" else True
    else:
        results["documents"][0]["pa"] = []
    wire(lambda request: payload)
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "query_patents", {"query": "ttl:ezetimibe"})
    assert caught.value.code in {"invalid_source_response", "identity_mismatch"}


@pytest.mark.parametrize("group_by", ["year", "assignee", "class"])
async def test_statistics_window_denominators_missingness_and_methods(wire, group_by):
    wire(lambda request: window(total=50))
    result = await SourceAdapters().call(
        "surechembl", "get_patent_statistics", {"query": "ttl:ezetimibe", "group_by": group_by}
    )
    assert (
        result["denominator"]["total"] == 2
        and result["denominator"]["provider_matching_document_total"] == 50
    )
    assert result["denominator"]["missing_group"] == (2 if group_by == "class" else 1)
    assert result["population_statistics_status"] == "partial"
    assert result["_provider_page"]["next_offset"] == 25 and not result["_provider_page"]["exhausted"]
    assert "no deduplication into patent families" in result["method"]
    if group_by == "class":
        assert result["groups"] == []
    else:
        assert result["groups"][0]["count_within_window"] == 1
        assert result["groups"][0]["input_locators"][0].startswith("/records/0/")


async def test_actual_mcp_continuation_keeps_query_filters_and_evidence(wire):
    first_row = window()["data"]["results"]["documents"][0]
    second_row = {**first_row, "docId": "CA-2644905-A1", "metadata": {"pd": "20070913"}}
    calls = wire(
        lambda request: window(total=2, rows=[first_row if request.url.params["page"] == "1" else second_row])
    )
    params = {
        "source": "surechembl",
        "operation": "get_patent_statistics",
        "params": {"query": "ttl:ezetimibe", "group_by": "year", "limit": 1},
    }
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        first = (await client.call_tool("query_source", params)).data
        action = first["next_actions"][0]
        assert action["arguments"]["params"] == {**params["params"], "page": 2}
        second = (await client.call_tool(action["tool"], action["arguments"])).data
    assert first["outcome"] == second["outcome"] == "partial"
    assert first["provenance"] and second["provenance"]
    assert [r.url.params["page"] for r in calls] == ["1", "2"]
    assert second["next_actions"] == []


async def test_content_permission_hold_before_http(wire):
    calls = wire(lambda request: window())
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call(
            "surechembl", "query_patents", {"query": "US-123-A1", "query_type": "content"}
        )
    assert caught.value.code == "source_license_unavailable" and calls == []


async def test_explicit_empty_window_and_complete_zero_source_population(wire):
    wire(lambda request: window(total=0, rows=[]))
    result = await SourceAdapters().call("surechembl", "get_patent_statistics", {"query": "ttl:ezetimibe"})
    assert result["denominator"]["total"] == 0 and result["denominator"]["missing_group"] == 0
    assert result["groups"] == [] and result["population_statistics_status"] == "complete"
    assert result["_provider_page"]["exhausted"]


async def test_final_supported_page_retains_acquired_evidence_as_partial(wire):
    payload = window(total=100001, rows=[window()["data"]["results"]["documents"][0]])
    wire(lambda request: payload)
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "surechembl",
                    "operation": "get_patent_statistics",
                    "params": {"query": "ttl:ezetimibe", "page": 100000, "limit": 1},
                },
            )
        ).data
    assert result["outcome"] == "partial" and result["provenance"]
    assert result["sections"]["surechembl"]["data"]["records"]
    assert result["next_actions"] == []


@pytest.mark.parametrize(
    "operation,params",
    [
        ("query_chemicals", {"query": "aspirin"}),
    ],
)
async def test_retired_unprojected_routes_do_not_release_unknown_content(wire, operation, params):
    calls = wire(lambda request: {"status": "OK", "data": {"contents": "unreleased-source-text"}})
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", operation, params)
    assert caught.value.code == "source_unavailable" and calls == []
