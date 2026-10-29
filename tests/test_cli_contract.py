import json

import pytest
from fastmcp import Client
from test_research_contracts import Adapters

from biomedmcp import cli
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server


def test_installed_package_and_commands_use_biomedmcp():
    from importlib.metadata import distribution

    package = distribution("biomedmcp")
    commands = {
        entry.name: entry.value
        for entry in package.entry_points
        if entry.group == "console_scripts"
    }
    assert commands == {
        "biomedmcp": "biomedmcp.cli:main",
        "biomedmcp-server": "biomedmcp.mcp.server:main",
    }
    assert all(callable(entry.load()) for entry in package.entry_points)


@pytest.mark.asyncio
async def test_cli_and_mcp_preserve_gene_identity_sections_and_provenance(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setattr(
        cli, "ResearchService", lambda **kwargs: ResearchService(adapters=Adapters(), **kwargs)
    )
    params = {"entity": "gene", "id": "BRAF", "sections": []}
    local = await cli.execute("get", params)
    service = ResearchService(adapters=Adapters())
    async with Client(create_server(service=service)) as client:
        hosted = (await client.call_tool("get", params)).data
    for value in (local, hosted):
        assert value["outcome"] == "data"
        assert value["sections"]["record"]["data"]["symbol"] == "BRAF"
        assert value["provenance"]
    # Independent accounts/processes mint distinct expiring recovery handles;
    # scientific identity, values and service evidence IDs must still agree.
    assert {
        name: {key: [warning.split(" Retrieved:")[0] for warning in value] if key == "warnings" else value
               for key, value in section.items() if key != "recovery"}
        for name, section in local["sections"].items()
    } == {
        name: {key: [warning.split(" Retrieved:")[0] for warning in value] if key == "warnings" else value
               for key, value in section.items() if key != "recovery"}
        for name, section in hosted["sections"].items()
    }
    for value in (local, hosted):
        assert value["sections"]["record"]["recovery"]["snapshot_status"] == "available"


@pytest.mark.asyncio
async def test_cli_json_stdout_excludes_provider_diagnostics(monkeypatch, capsys):
    import structlog

    from biomedmcp import transport
    from biomedmcp.runtime import ProviderRuntime

    previous = structlog.get_config().copy()
    transport.configure()

    async def fetch():
        return {"ok": True}

    await ProviderRuntime().invoke("fixture", {}, fetch, scope="test")
    captured = capsys.readouterr()
    assert captured.out == ""
    structlog.configure(**previous)
    diagnostics = [json.loads(line) for line in captured.err.splitlines()]
    assert [event["event"] for event in diagnostics] == ["provider_result", "provider_waiter"]
    assert diagnostics[0]["flight_id"] == diagnostics[1]["flight_id"]
    assert all(event["outcome"] == "data" for event in diagnostics)


async def test_explicit_login_requests_oauth_challenge_on_optional_auth_server(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, target, **options):
            captured.update(target=target, options=options)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def list_tools(self):
            return []

    monkeypatch.delenv("UBI_PUBLIC_TOKEN", raising=False)
    monkeypatch.setattr("fastmcp.Client", Client)
    assert await cli.execute("tools", {}, url="https://public.example/mcp", login=True) == []
    assert captured["target"].url == "https://public.example/mcp"
    assert captured["target"].headers == {"X-Biomedmcp-Require-Login": "1"}
    oauth = captured["options"]["auth"]
    assert oauth._client_id == oauth._client_metadata_url == "https://public.example/.well-known/biomedmcp-cli-client.json"
    assert oauth._callback_host == "127.0.0.1" and oauth._callback_port == 8765
    assert oauth._scopes is None  # Discover the resource's exact scope subset; do not force openid.
