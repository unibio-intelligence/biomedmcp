"""Execute repaired retained routes through their real offline MCP adapters."""

from urllib.parse import parse_qs

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError

CLASS = "http://example.org/ontology/C_1"
CLASS_ROW = {"@id": CLASS, "prefLabel": "First class"}
GENE = {
    "query": "BRAF",
    "_id": "673",
    "symbol": "BRAF",
    "taxid": 9606,
    "entrezgene": 673,
    "ensembl": {"gene": "ENSG00000157764"},
    "HGNC": "1097",
}
ANTIBODY = {"abId": 3753073, "abName": "BRCA1 antibody", "epitope": None}
MAPPING = {
    "classes": [CLASS_ROW, {"@id": "http://example.org/other/C_2"}],
    "source": "LOOM",
    "process": {"name": "lexical matching"},
}
CASES = [
    ("mygene", "map_gene_ids", {"gene_ids": ["BRAF"], "input_namespace": "symbol"}, [GENE]),
    ("bio-ontology", "search_ontologies", {"query": "gene"}, [{"acronym": "GO", "name": "Gene Ontology"}]),
    (
        "bio-ontology",
        "get_ontology_classes",
        {"ontology": "GO", "pagesize": 1},
        {"collection": [CLASS_ROW], "page": 1, "pageCount": 2},
    ),
    ("bio-ontology", "get_class_info", {"ontology": "GO", "class_id": CLASS}, CLASS_ROW),
    (
        "bio-ontology",
        "get_mappings",
        {"ontology": "GO", "class_id": CLASS, "pagesize": 1},
        [MAPPING, {**MAPPING, "process": None}],
    ),
    (
        "bio-ontology",
        "get_mappings",
        {"ontology": "GO", "pagesize": 1},
        {"collection": [MAPPING], "page": 1, "pageCount": 2},
    ),
    (
        "antibody-registry",
        "query_antibody",
        {"query_type": "search", "query": "BRCA1", "limit": 1},
        {"items": [ANTIBODY], "page": 1, "totalElements": 2},
    ),
    (
        "antibody-registry",
        "query_antibody",
        {"query_type": "details", "query": "RRID:AB_3753073"},
        [ANTIBODY],
    ),
]


@pytest.fixture
def adapter_http(monkeypatch):
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", "synthetic-canonical-key")
    monkeypatch.delenv("BIOPORTAL_API_KEY", raising=False)
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "antibody-registry")
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters()

    return install


@pytest.mark.parametrize("source,operation,params,payload", CASES)
async def test_repaired_operations_preserve_records_and_provider_contract(
    adapter_http, source, operation, params, payload
):
    requests = []

    def handler(request):
        requests.append(request)
        if source == "mygene":
            assert request.method == "POST"
            assert request.url.path == "/v3/query"
            assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
            body = parse_qs(request.content.decode())
            assert body["q"] == ["BRAF"] and body["scopes"] == ["symbol"]
            assert body["species"] == ["9606"]
            assert "ensembl.gene" in body["fields"][0]
        if source == "bio-ontology":
            assert request.headers["authorization"] == "apikey token=synthetic-canonical-key"
            assert "apikey" not in request.url.params
            assert "synthetic-canonical-key" not in str(request.url)
            if "class_id" in params:
                assert "http%3A%2F%2Fexample.org%2Fontology%2FC_1" in request.url.raw_path.decode()
        if source == "antibody-registry":
            assert request.url.host == "www.antibodyregistry.org"
            assert request.method == "GET"
        return httpx.Response(200, json=payload)

    result = await adapter_http(handler).call(source, operation, params)
    assert len(requests) == 1
    if operation == "map_gene_ids":
        assert result["mappings"][0]["status"] == "resolved"
        identity = result["mappings"][0]["candidates"][0]
        assert identity["species"] == 9606 and identity["entrez_id"] == "673"
        assert identity["ensembl_ids"] == ["ENSG00000157764"]
    elif operation == "get_class_info":
        assert result["@id"] == CLASS
    elif operation == "query_antibody":
        assert result["items"] == [ANTIBODY]
        assert result["items"][0]["epitope"] is None
        if params["query_type"] == "search":
            assert result["next_page"] == 2
        else:
            assert result["identity_status"] == "exact"
    else:
        expected = payload[:1] if operation == "get_mappings" and isinstance(payload, list) else payload
        assert result["collection"] == (expected if isinstance(expected, list) else expected["collection"])
        if operation in {"get_ontology_classes", "get_mappings"}:
            assert result["next_page"] == 2
        if operation == "get_mappings":
            assert "equivalence is not assumed" in result["interpretation"]


@pytest.mark.parametrize("source,operation,params,payload", CASES)
@pytest.mark.parametrize("failure", ["malformed", "connect", "503", "json"])
async def test_repaired_provider_failures_never_return_negative_evidence(
    adapter_http, caplog, capsys, source, operation, params, payload, failure
):
    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError("synthetic-canonical-key", request=request)
        if failure == "json":
            return httpx.Response(200, text="synthetic-canonical-key")
        return httpx.Response(503 if failure == "503" else 200, json={"error": "synthetic-canonical-key"})

    with pytest.raises(ResearchError) as caught:
        await adapter_http(handler).call(source, operation, params)
    assert caught.value.code == (
        "source_unavailable" if failure in {"connect", "503"} else "invalid_source_response"
    )
    assert "synthetic-canonical-key" not in str(caught.value) + caplog.text
    captured = capsys.readouterr()
    assert "synthetic-canonical-key" not in captured.out + captured.err


@pytest.mark.parametrize(
    "rows,status",
    [
        ([GENE, {**GENE, "_id": "674", "entrezgene": 674}], "ambiguous"),
        ([{"query": "BRAF", "notfound": True}], "not_found"),
    ],
)
async def test_mapping_preserves_ambiguity_and_explicit_source_missingness(adapter_http, rows, status):
    adapter = adapter_http(lambda request: httpx.Response(200, json=rows))
    result = await adapter.call("mygene", "map_gene_ids", CASES[0][2])
    assert result["mappings"][0]["status"] == status
    assert len(result["mappings"][0]["candidates"]) == (2 if status == "ambiguous" else 0)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{**GENE, "taxid": 10090}],
        [{**GENE, "symbol": "OTHER"}],
        [{**GENE, "query": "OTHER"}],
        [GENE, {"query": "BRAF", "notfound": True}],
    ],
)
async def test_mapping_incomplete_or_unqualified_identity_fails(adapter_http, rows):
    adapter = adapter_http(lambda request: httpx.Response(200, json=rows))
    with pytest.raises(ResearchError):
        await adapter.call("mygene", "map_gene_ids", CASES[0][2])


async def test_antibody_redirect_does_not_replace_requested_identity(adapter_http):
    adapter = adapter_http(lambda request: httpx.Response(200, json=[ANTIBODY]))
    result = await adapter.call(
        "antibody-registry", "query_antibody", {"query_type": "details", "query": "AB_1"}
    )
    assert result["requested_rrid"] == "RRID:AB_1"
    assert result["identity_status"] == "provider_redirect"
    assert result["items"][0]["abId"] == 3753073


async def test_canonical_bioontology_credential_required_and_antibody_default_enabled(monkeypatch):
    monkeypatch.delenv("BIOONTOLOGY_API_KEY", raising=False)
    monkeypatch.setenv("BIOPORTAL_API_KEY", "obsolete-name")
    monkeypatch.delenv("UBI_LICENSED_SOURCES", raising=False)
    adapters = SourceAdapters()
    assert not adapters.availability("bio-ontology")[0]
    assert adapters.availability("antibody-registry")[0]
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", "canonical-name")
    assert adapters.availability("bio-ontology")[0]


@pytest.mark.parametrize(
    "source,operation,params",
    [
        ("mygene", "map_gene_ids", {"gene_ids": ["BRAF"] * 26, "input_namespace": "symbol"}),
        ("bio-ontology", "get_ontology_classes", {"ontology": "../users"}),
        ("bio-ontology", "get_mappings", {"ontology": "GO", "pagesize": 26}),
        ("antibody-registry", "query_antibody", {"query_type": "search", "query": "x", "limit": 26}),
    ],
)
async def test_repaired_schema_bounds_reject_before_io(adapter_http, source, operation, params):
    def forbidden(request):
        pytest.fail("Invalid input must not perform provider HTTP")

    with pytest.raises(ResearchError) as caught:
        await adapter_http(forbidden).call(source, operation, params)
    assert caught.value.code == "invalid_parameters"


@pytest.mark.parametrize(
    "namespace,query,species,row",
    [
        ("entrezgene", "673", 9606, GENE),
        ("ensembl.gene", "ENSG00000157764", 9606, GENE),
        ("symbol", "Braf", 10090, {"_id": "109880", "entrezgene": 109880, "symbol": "Braf", "taxid": 10090}),
    ],
)
async def test_mapping_namespaces_and_mouse_identity(adapter_http, namespace, query, species, row):
    def handler(request):
        body = parse_qs(request.content.decode())
        assert body["scopes"] == [namespace] and body["species"] == [str(species)]
        return httpx.Response(200, json=[{**row, "query": query}])

    result = await adapter_http(handler).call(
        "mygene", "map_gene_ids", {"gene_ids": [query], "input_namespace": namespace, "species": species}
    )
    assert result["mappings"][0]["status"] == "resolved"
    assert result["mappings"][0]["candidates"][0]["species"] == species


async def test_ontology_local_filter_and_mapping_continuation(adapter_http):
    def handler(request):
        if request.url.path.endswith("/mappings"):
            assert "page" not in request.url.params
            return httpx.Response(200, json=[MAPPING, {**MAPPING, "process": None}])
        assert "q" not in request.url.params
        return httpx.Response(
            200,
            json=[
                {"acronym": "GO", "name": "Gene Ontology"},
                {"acronym": "OTHER", "name": "Other Gene Ontology"},
                {"acronym": "NO", "name": "Unrelated"},
            ],
        )

    adapter = adapter_http(handler)
    first = await adapter.call("bio-ontology", "search_ontologies", {"query": "gene", "limit": 1})
    assert first["total"] == 2 and first["next_offset"] == 1
    second = await adapter.call(
        "bio-ontology", "search_ontologies", {"query": "gene", "limit": 1, "offset": first["next_offset"]}
    )
    assert second["collection"][0]["acronym"] == "OTHER" and second["next_offset"] is None
    mappings = await adapter.call(
        "bio-ontology", "get_mappings", {"ontology": "GO", "class_id": CLASS, "page": 2, "pagesize": 1}
    )
    assert mappings["collection"][0]["process"] is None
    assert mappings["missing_process_count"] == 1 and mappings["next_page"] is None


@pytest.mark.parametrize(
    "source,operation,params,payload",
    [
        ("mygene", "map_gene_ids", CASES[0][2], [{"query": "BRAF", "notfound": True}]),
        (
            "bio-ontology",
            "get_ontology_classes",
            {"ontology": "GO"},
            {"collection": [], "page": 1, "pageCount": 0},
        ),
        ("bio-ontology", "get_mappings", {"ontology": "GO", "class_id": CLASS}, []),
        (
            "antibody-registry",
            "query_antibody",
            {"query_type": "search", "query": "unknown"},
            {"items": [], "page": 1, "totalElements": 0},
        ),
        ("antibody-registry", "query_antibody", {"query_type": "details", "query": "AB_1"}, []),
    ],
)
async def test_explicit_valid_empty_responses_are_distinct_from_failure(
    adapter_http, source, operation, params, payload
):
    result = await adapter_http(lambda request: httpx.Response(200, json=payload)).call(
        source, operation, params
    )
    assert isinstance(result, dict)


@pytest.mark.parametrize("source,operation,params,payload", CASES)
async def test_repaired_route_executes_through_public_mcp(
    adapter_http, monkeypatch, source, operation, params, payload
):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    adapter = adapter_http(lambda request: httpx.Response(200, json=payload))
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        capabilities = (await client.call_tool("capabilities", {"source": source})).data
        assert operation in {tool["name"] for tool in capabilities["operations"]}
        result = (
            await client.call_tool(
                "query_source", {"source": source, "operation": operation, "params": params}
            )
        ).data
    assert result["outcome"] == "data"
    assert result["sections"][source]["data"]
    assert result["provenance"]
