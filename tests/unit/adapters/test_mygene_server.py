import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp.exceptions import ToolError
from mygene_mcp.client import MyGeneClient
from mygene_mcp.server import mcp

BRAF = {
    "_id": "673",
    "symbol": "BRAF",
    "taxid": 9606,
    "entrezgene": 673,
    "ensembl": {"gene": "ENSG00000157764"},
    "HGNC": "1097",
}


def error_code(failure: ToolError) -> str:
    return json.loads(str(failure))["code"]


def respond(payload, status=200):
    return lambda request: httpx.Response(status, json=payload)


async def test_query_genes_sends_documented_parameters_and_returns_envelope(mocked):
    call = mocked(mcp, respond({"hits": [BRAF], "total": 1, "took": 2}))
    result = await call("query_genes", query="BRAF", fields="symbol,taxid", species="9606", limit=5, from_=10)
    request = mocked.requests[0]
    assert request.method == "GET" and request.url.host == "mygene.info" and request.url.path == "/v3/query"
    assert dict(request.url.params) == {
        "q": "BRAF",
        "fields": "symbol,taxid",
        "species": "9606",
        "size": "5",
        "from": "10",
    }
    assert result["hits"][0]["symbol"] == "BRAF" and result["total"] == 1


async def test_map_gene_ids_posts_one_batch_and_qualifies_identity(mocked):
    call = mocked(mcp, respond([{**BRAF, "query": "BRAF"}, {"query": "NOPE", "notfound": True}]))
    result = await call("map_gene_ids", gene_ids=["BRAF", "NOPE", "BRAF"], input_namespace="symbol")
    body = parse_qs(mocked.requests[0].content.decode())
    assert mocked.requests[0].method == "POST" and mocked.requests[0].url.path == "/v3/query"
    assert body["q"] == ["BRAF,NOPE"] and body["scopes"] == ["symbol"] and body["species"] == ["9606"]
    assert "ensembl.gene" in body["fields"][0]
    assert result["status"] == "partial" and result["total_input"] == 3 and result["unique_inputs"] == 2
    resolved, missing = result["mappings"]
    assert resolved["status"] == "resolved" and resolved["candidates"][0] == {
        "symbol": "BRAF",
        "species": 9606,
        "source_record_id": "673",
        "entrez_id": "673",
        "ensembl_ids": ["ENSG00000157764"],
        "hgnc_id": "HGNC:1097",
    }
    assert missing == {"query": "NOPE", "status": "not_found", "candidates": []}
    assert result["unmapped_ids"] == ["NOPE"]


async def test_map_gene_ids_keeps_ambiguity_as_candidates(mocked):
    rows = [{**BRAF, "query": "BRAF"}, {**BRAF, "query": "BRAF", "_id": "674", "entrezgene": 674}]
    result = await mocked(mcp, respond(rows))("map_gene_ids", gene_ids=["BRAF"])
    assert result["mappings"][0]["status"] == "ambiguous" and len(result["mappings"][0]["candidates"]) == 2


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{**BRAF, "query": "BRAF", "taxid": 10090}],
        [{**BRAF, "query": "OTHER"}],
        [{**BRAF, "query": "BRAF", "symbol": "X"}],
    ],
)
async def test_map_gene_ids_rejects_missing_foreign_or_unqualified_rows(mocked, rows):
    with pytest.raises(ToolError) as failure:
        await mocked(mcp, respond(rows))("map_gene_ids", gene_ids=["BRAF"], species=9606)
    assert error_code(failure.value) == "invalid_source_response"


async def test_compare_genes_tabulates_requested_fields(mocked):
    rows = [{**BRAF, "query": "BRAF", "name": "B-Raf"}, {"query": "ENSG1", "notfound": True}]
    result = await mocked(mcp, respond(rows))(
        "compare_genes", gene_ids=["BRAF", "ENSG1"], fields="symbol,ensembl.gene"
    )
    assert parse_qs(mocked.requests[0].content.decode())["scopes"] == ["symbol,entrezgene,ensembl.gene"]
    assert result["not_found"] == ["ENSG1"] and result["ambiguous"] == []
    assert result["comparison"] == {
        "symbol": {"BRAF": ["BRAF"]},
        "ensembl.gene": {"BRAF": ["ENSG00000157764"]},
    }


@pytest.mark.parametrize(
    "status,body,code", [(503, "down", "source_unavailable"), (200, "not json", "invalid_source_response")]
)
async def test_provider_failures_are_sanitized(mocked, status, body, code):
    mocked(mcp, lambda request: httpx.Response(status, text=body))
    with pytest.raises(ToolError) as failure:
        await MyGeneClient().get("query", {"q": "BRAF"})
    assert error_code(failure.value) == code and body not in str(failure.value)
    assert failure.value.__cause__ is None


async def test_client_cache_serves_valid_entries_and_evicts_invalid_ones(mocked):
    bodies = iter([{"hits": [BRAF]}, {"error": "bad"}])
    mocked(mcp, lambda request: httpx.Response(200, json=next(bodies)))
    client = MyGeneClient(rate_limit=None)
    first = await client.get("query", {"q": "BRAF"})
    first["hits"].clear()
    assert (await client.get("query", {"q": "BRAF"}))["hits"] == [BRAF] and len(mocked.requests) == 1
    client.clear_cache()
    with pytest.raises(ToolError):
        await client.get("query", {"q": "BRAF"})
    assert not client._cache
