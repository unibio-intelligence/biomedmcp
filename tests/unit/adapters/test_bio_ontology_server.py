"""Offline contract tests for the BioPortal adapter; HTTP is mocked at the transport."""

import json

import httpx
import pytest
from bio_ontology_mcp import server
from fastmcp import Client
from fastmcp.exceptions import ToolError

from biomedmcp import transport

KEY = "synthetic-bioportal-test-key"
CLASS = "http://example.org/onto/C_7"
MAPPING = {
    "classes": [{"@id": CLASS}, {"@id": "http://example.org/other/X"}],
    "source": "LOOM",
    "process": {},
}


@pytest.fixture
def mock_http(monkeypatch):
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", KEY)
    original = httpx.AsyncClient
    seen = []

    def install(handler):
        def recording(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(recording))
        )
        return seen

    return install


async def call(name, **params):
    async with Client(server.mcp) as client:
        return (await client.call_tool(name, params)).data


async def test_tool_inventory_and_version():
    async with Client(server.mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"search_ontologies", "get_ontology_classes", "get_class_info", "get_mappings"}
    assert server.mcp.version == server.__version__


async def test_key_travels_only_in_the_authorization_header(mock_http):
    seen = mock_http(lambda request: httpx.Response(200, json=[{"acronym": "GO", "name": "Gene Ontology"}]))
    result = await call("search_ontologies", query="go")
    request = seen[0]
    assert request.headers["authorization"] == f"apikey token={KEY}"
    assert KEY not in str(request.url) and request.url.path == "/ontologies"
    assert "include_views" not in request.url.params
    assert result["collection"][0]["acronym"] == "GO" and result["next_offset"] is None


async def test_missing_key_fails_before_any_http(monkeypatch):
    monkeypatch.delenv("BIOONTOLOGY_API_KEY", raising=False)
    monkeypatch.setattr(server, "BIOONTOLOGY_API_KEY", None)
    monkeypatch.setattr(transport.AsyncClient, "request", lambda *a, **k: pytest.fail("HTTP attempted"))
    with pytest.raises(ToolError) as caught:
        await call("get_ontology_classes", ontology="GO")
    assert json.loads(str(caught.value))["code"] == "source_unavailable"


async def test_ontology_filter_windows_locally(mock_http):
    rows = [{"acronym": "GO", "name": "Gene Ontology"}, {"acronym": "HP", "name": "Human Phenotype"}]
    seen = mock_http(lambda request: httpx.Response(200, json=rows))
    first = await call("search_ontologies", include_views=True, limit=1)
    assert seen[0].url.params["include_views"] == "true"
    assert first["total"] == 2 and first["next_offset"] == 1
    second = await call("search_ontologies", limit=1, offset=1)
    assert second["collection"] == rows[1:] and second["next_offset"] is None
    assert (await call("search_ontologies", query="phenotype"))["collection"] == rows[1:]


async def test_class_uri_is_percent_encoded_and_include_forwarded(mock_http):
    seen = mock_http(lambda request: httpx.Response(200, json={"@id": CLASS, "prefLabel": "Seven"}))
    result = await call("get_class_info", ontology="GO", class_id=CLASS, include="prefLabel,definition")
    assert "/classes/http%3A%2F%2Fexample.org%2Fonto%2FC_7" in seen[0].url.raw_path.decode()
    assert seen[0].url.params["include"] == "prefLabel,definition"
    assert result == {"@id": CLASS, "prefLabel": "Seven"}


async def test_provider_paged_classes_and_mappings(mock_http):
    page = {"collection": [MAPPING], "page": 3, "pageCount": 3}
    seen = mock_http(lambda request: httpx.Response(200, json=page))
    classes = await call("get_ontology_classes", ontology="GO", page=3, pagesize=5)
    assert seen[0].url.params["page"] == "3" and seen[0].url.params["pagesize"] == "5"
    assert classes["page_count"] == 3 and classes["next_page"] is None
    mappings = await call("get_mappings", ontology="GO", page=3)
    assert seen[1].url.path == "/ontologies/GO/mappings"
    assert (
        mappings["missing_process_count"] == 1 and "equivalence is not assumed" in mappings["interpretation"]
    )


async def test_class_mappings_are_windowed_locally(mock_http):
    rows = [MAPPING, {**MAPPING, "process": {"name": "cui"}}, {**MAPPING, "process": None}]
    seen = mock_http(lambda request: httpx.Response(200, json=rows))
    first = await call("get_mappings", ontology="GO", class_id=CLASS, pagesize=2)
    assert seen[0].url.path.endswith("/mappings") and "page" not in seen[0].url.params
    assert len(first["collection"]) == 2 and first["next_page"] == 2 and first["missing_process_count"] == 1
    last = await call("get_mappings", ontology="GO", class_id=CLASS, page=2, pagesize=2)
    assert last["collection"] == rows[2:] and last["next_page"] is None


@pytest.mark.parametrize(
    "name,params,payload",
    [
        ("search_ontologies", {}, {"error": "not a list"}),
        ("get_ontology_classes", {"ontology": "GO"}, {"page": 1}),
        ("get_class_info", {"ontology": "GO", "class_id": CLASS}, {"prefLabel": "no id"}),
        ("get_mappings", {"ontology": "GO", "class_id": CLASS}, [{"source": "LOOM"}]),
    ],
)
async def test_unexpected_shapes_are_invalid_source_responses(mock_http, name, params, payload):
    mock_http(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ToolError) as caught:
        await call(name, **params)
    assert json.loads(str(caught.value))["code"] == "invalid_source_response"


@pytest.mark.parametrize("status,code", [(401, "source_authentication_failed"), (404, "source_not_found")])
async def test_http_failures_are_classified_without_echoing_the_body(mock_http, status, code):
    mock_http(lambda request: httpx.Response(status, json={"error": KEY}))
    with pytest.raises(ToolError) as caught:
        await call("get_class_info", ontology="GO", class_id=CLASS)
    error = json.loads(str(caught.value))
    assert error["code"] == code and KEY not in str(caught.value)
