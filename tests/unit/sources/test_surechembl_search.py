"""SureChEMBL asynchronous source searches: validated science and signed resume."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.runtime import ProviderRuntime, ResultCache

pytestmark = pytest.mark.source_permissions
HASH = "d9d90597-bb56-4ea7-91d5-9c0a665fab13"
PARAMS = {"smiles": "CCO", "similarity_threshold": 0.85, "limit": 1}


def response(data, status="OK"):
    return {"status": status, "data": data, "error_message": ""}


def query(smiles="CCO"):
    return {
        "structure": smiles,
        "structure_format": "SMILES",
        "search_type": "SIMILARITY",
        "dataset": "",
        "query": "",
        "chem_term_filter": "",
        "doc_section_filter": None,
    }


def result(page=1, *, total=2):
    return response(
        {
            "type": "STRUCTURE",
            "query": query(),
            "pagination": {"current_page": page, "num_pages": total, "max_results": 1, "start_on": page},
            "results": {
                "total_hits": total,
                "structures": [
                    {
                        "id": str(page),
                        "chemical_id": str(page),
                        "smiles": "CCO",
                        "similarity": "1.0",
                        "global_frequency": 0,
                    }
                ]
                if total
                else [],
            },
        }
    )


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def install(*, pending=False, mutation=None):
        statuses = 0

        def handler(request):
            nonlocal statuses
            calls.append(request)
            path = request.url.path
            if path == "/api/search/structure":
                payload = response({"hash": HASH})
            elif path.endswith("/status"):
                statuses += 1
                payload = (
                    response({"message": "Searching finished.", "resultCount": 2})
                    if not pending or statuses > 1
                    else response({}, "QUEUED")
                )
            elif path.endswith("/results"):
                payload = result(int(request.url.params["page"]))
            else:
                payload = response({"type": "STRUCTURE", "query": json.dumps(query())})
            if mutation:
                payload = mutation(request, payload)
            return httpx.Response(200, json=deepcopy(payload))

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return calls

    return install


async def test_actual_mcp_pending_to_ready_and_next_page_submit_once(wire):
    calls = wire(pending=True)
    request = {"source": "surechembl", "operation": "search_similar_structures", "params": PARAMS}
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        pending = (await client.call_tool("query_source", request)).data
        ready = (await client.call_tool("query_source", pending["next_actions"][0]["arguments"])).data
        last = (await client.call_tool("query_source", ready["next_actions"][0]["arguments"])).data
    assert pending["outcome"] == "partial"
    assert pending["sections"]["surechembl"]["data"]["coverage"]["provider_total"] is None
    assert ready["sections"]["surechembl"]["data"]["records"][0]["chemical_id"] == "SCHEMBL1"
    assert last["sections"]["surechembl"]["data"]["records"][0]["chemical_id"] == "SCHEMBL2"
    assert last["next_actions"] == []
    submissions = [r for r in calls if r.method == "POST"]
    assert len(submissions) == 1
    body = json.loads(submissions[0].content)["StructureSearchRequest"]
    assert body["struct"] == "CCO" and body["structSearchType"] == "similarity"
    assert float(body["options"].split("=")[1]) == pytest.approx(0.15)
    assert HASH not in str(ready["sections"]["surechembl"]["data"])
    assert HASH not in str(pending["next_actions"])


@pytest.mark.parametrize("change", ["account", "smiles", "threshold", "limit", "tamper"])
async def test_resume_bound_to_account_science_parameters_and_signature(wire, change):
    calls = wire()
    service = ResearchService(adapters=SourceAdapters())
    first = await service.source("surechembl", "search_similar_structures", PARAMS, scope="account-a")
    params = dict(first.next_actions[0]["arguments"]["params"])
    if change == "smiles":
        params["smiles"] = "CCC"
    elif change == "threshold":
        params["similarity_threshold"] = 0.9
    elif change == "limit":
        params["limit"] = 2
    elif change == "tamper":
        cursor = params["search_cursor"]
        params["search_cursor"] = ("y" if cursor.startswith("x") else "x") + cursor[1:]
        assert params["search_cursor"] != cursor
    count = len(calls)
    with pytest.raises(ResearchError) as caught:
        await service.source(
            "surechembl",
            "search_similar_structures",
            params,
            scope="account-b" if change == "account" else "account-a",
        )
    assert caught.value.code == "invalid_cursor" and len(calls) == count


async def test_shared_store_resumes_on_second_runtime_without_new_job(wire):
    calls = wire()
    store = ResultCache()
    first_service = ResearchService(
        adapters=SourceAdapters(), runtime=ProviderRuntime(cache=store, cursor_key=b"s" * 32)
    )
    second_service = ResearchService(
        adapters=SourceAdapters(), runtime=ProviderRuntime(cache=store, cursor_key=b"s" * 32)
    )
    first = await first_service.source("surechembl", "search_similar_structures", PARAMS, scope="account-a")
    second = await second_service.source(
        "surechembl",
        "search_similar_structures",
        first.next_actions[0]["arguments"]["params"],
        scope="account-a",
    )
    assert second.sections["surechembl"].data["records"][0]["chemical_id"] == "SCHEMBL2"
    assert len([r for r in calls if r.method == "POST"]) == 1


@pytest.mark.parametrize(
    "kind",
    [
        "bad_hash",
        "wrong_structure",
        "wrong_method",
        "extra_filter",
        "status_unknown",
        "score_nan",
        "score_below_threshold",
        "wrong_page",
        "duplicate",
        "bad_count",
        "wrong_compound",
        "bad_compound_properties",
    ],
)
async def test_malformed_job_or_results_fail_not_empty(wire, kind):
    def mutate(request, payload):
        data = payload["data"]
        path = request.url.path
        if kind == "bad_hash" and path == "/api/search/structure":
            data["hash"] = "../untrusted"
        if path == f"/api/search/{HASH}":
            value = json.loads(data["query"])
            if kind == "wrong_structure":
                value["structure"] = "CCC"
            elif kind == "wrong_method":
                value["search_type"] = "SUBSTRUCTURE"
            elif kind == "extra_filter":
                value["chem_term_filter"] = "other"
            data["query"] = json.dumps(value)
        if kind == "status_unknown" and path.endswith("/status"):
            payload["status"] = "UNKNOWN"
        if path.endswith("/results"):
            row = data["results"]["structures"][0]
            if kind == "score_nan":
                row["similarity"] = "NaN"
            elif kind == "score_below_threshold":
                row["similarity"] = "0.8"
            elif kind == "wrong_page":
                data["pagination"]["current_page"] = 3
            elif kind == "duplicate":
                data["results"]["structures"].append(row)
            elif kind == "bad_count":
                data["results"]["total_hits"] = True
            elif kind == "wrong_compound":
                row["id"] = "different"
            elif kind == "bad_compound_properties":
                row["qed_weighted"] = 1.1
        return payload

    wire(mutation=mutate)
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "search_similar_structures", PARAMS)
    assert caught.value.code in {"invalid_source_response", "identity_mismatch"}


async def test_cursor_store_loss_is_expired_before_network(wire):
    calls = wire()
    runtime = ProviderRuntime(cursor_key=b"s" * 32)
    service = ResearchService(adapters=SourceAdapters(), runtime=runtime)
    first = await service.source("surechembl", "search_similar_structures", PARAMS, scope="a")
    params = first.next_actions[0]["arguments"]["params"]
    runtime.cache.values.clear()
    count = len(calls)
    with pytest.raises(ResearchError) as caught:
        await service.source("surechembl", "search_similar_structures", params, scope="a")
    assert caught.value.code == "expired_cursor" and len(calls) == count
