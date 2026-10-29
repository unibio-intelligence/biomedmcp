"""Complete documented investigations and local connection routes, offline."""

import asyncio
import json
import socket
import sys
from contextlib import nullcontext

import pytest
import uvicorn
from fastmcp import Client

from biomedmcp import cli
from biomedmcp.domain import ResearchService
from biomedmcp.examples import by_id
from biomedmcp.mcp.server import create_server
from biomedmcp.onboarding import INVESTIGATIONS

pytest_plugins = ["test_public_examples"]


@pytest.mark.parametrize("investigation", INVESTIGATIONS, ids=lambda item: item["id"])
async def test_complete_documented_investigations_preserve_evidence_and_scientific_scope(
    example_service, investigation
):
    service, router = example_service
    results = {}
    async with Client(create_server(service=service)) as client:
        for identifier in investigation["steps"]:
            item = by_id(identifier)
            value = (await client.call_tool(item.operation, item.arguments)).data
            assert value["outcome"] == "data", value
            assert value["provenance"] and all(proof["source"] for proof in value["provenance"])
            assert not any(section.get("error") for section in value["sections"].values())
            results[identifier] = value
    if investigation["id"] == "target":
        for identifier in ("gene-tissue", "gene-eqtl"):
            value = results[identifier]
            assert value["query"]["species"] == 9606
            section = value["sections"]["expression" if identifier == "gene-tissue" else "eqtl"]
            assert all(
                row["geneSymbol"] == "LDLR" and row["gencodeId"] == "ENSG00000130164.13"
                for row in section["data"]["data"]
            )
        assert {"expression", "target_evidence", "diseases", "druggability"} <= set(
            results["target-dossier"]["sections"]
        )
        assert any(request.url.host == "gtexportal.org" for request in router.requests)
    elif investigation["id"] == "variant":
        identity = results["gene-articles"]["query"]["qualified_identity"]
        assert identity["symbol"] == "PCSK9" and identity["species"] == 9606
        assert any(request.url.host == "rest.uniprot.org" for request in router.requests)
    else:
        assert router.requests == []
        profile = results["study-profile"]["sections"]["study"]["data"]
        assert profile["total_samples"] == 4 and profile["unique_samples"] == 2
        assert profile["frequency"] == 0.5 and profile["denominator"] == "declared mutation-assayed samples"
        survival = results["study-survival"]["sections"]["study"]["data"]
        assert sum(group["n_patients"] for group in survival["groups"]) == 4
        pair = results["study-cooccurrence"]["sections"]["study"]["data"]["pairs"][0]
        assert [pair[key] for key in ("both", "a_only", "b_only", "neither")] == [0, 2, 1, 1]


async def test_documented_local_http_discovery_diagnosis_and_resource_routes(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    server = create_server(service=ResearchService())
    runner = uvicorn.Server(
        uvicorn.Config(server.http_app(stateless_http=True), log_level="error", access_log=False)
    )
    runner.capture_signals = nullcontext
    task = asyncio.create_task(runner.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not runner.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
        tools = await cli.execute("tools", {}, url=url)
        assert len(tools) == 13
        value = await cli.execute("diagnose", {"source": "gtex"}, url=url)
        assert value["diagnosis"][0]["health"] == "not_probed"
        resource = await cli.execute("read-resource", {"uri": "biomedmcp://guide"}, url=url)
        assert "guide" in json.dumps(resource).lower()
    finally:
        runner.should_exit = True
        await asyncio.wait_for(task, 10)


async def test_documented_stdio_launch_discovers_the_compact_interface():
    config = {
        "mcpServers": {
            "ubi": {
                "command": sys.executable,
                "args": ["-c", "from biomedmcp.mcp.server import main; main()", "--transport", "stdio"],
                "env": {"UBI_PROFILE": "local"},
            }
        }
    }
    async with Client(config) as client:
        assert len(await client.list_tools()) == 13
        result = await client.call_tool("capabilities", {"source": "gtex", "diagnose": True})
        assert result.data["diagnosis"][0]["health"] == "not_probed"
