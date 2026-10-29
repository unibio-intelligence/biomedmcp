"""Provider-free scientific requests for HTTP boundary qualification."""

import json

from biomedmcp.domain import ResearchService
from biomedmcp.mcp.http_security import REQUEST_BYTES
from biomedmcp.mcp.server import create_server


class SyntheticLiterature:
    def __init__(self):
        self.calls = 0

    async def get(self, url, **kwargs):
        assert url == "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        self.calls += 1
        return {
            "hitCount": 1,
            "resultList": {
                "result": [{"id": "123", "source": "MED", "title": "Synthetic evidence", "isRetracted": "N"}]
            },
        }


def maximum_batch():
    filters = {key: [chr(65 + i) * 256 for i in range(5)] for key in ("disease", "drug", "author", "journal")}
    filters["source"] = "europepmc"
    calls = [
        {
            "operation": "literature_search",
            "arguments": {"query": str(i) + "q" * 511, "filters": filters, "limit": 25},
        }
        for i in range(10)
    ]
    value = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "batch", "arguments": {"calls": calls}},
    }
    raw = json.dumps(value, separators=(",", ":")).encode()
    assert len(raw) <= REQUEST_BYTES
    return raw + b" " * (REQUEST_BYTES - len(raw))


def create_app():
    provider = SyntheticLiterature()
    service = ResearchService(http=provider)
    server = create_server(service=service)
    return server.http_app(stateless_http=True, json_response=True), provider


def assert_batch(response):
    assert response["result"]["isError"] is False
    data = response["result"]["structuredContent"]
    assert data["outcome"] == "data"
    assert len(data["results"]) == 10
    for item in data["results"]:
        assert item["outcome"] == "data"
        assert item["records"][0]["pmid"] == "123"
        assert item["provenance"][0]["source"] == "europepmc"
