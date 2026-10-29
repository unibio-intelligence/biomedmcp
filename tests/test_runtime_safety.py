import asyncio
import socket

import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.contracts import ResearchResult, Section
from biomedmcp.errors import ResearchError
from biomedmcp.local_boundary import AuthSettings
from biomedmcp.mcp.server import create_server
from biomedmcp.runtime import ProviderRuntime


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://localhost",
        "https://host.internal",
        "https://user:pass@example.org",
        "https://example.org:444",
        "file:///etc/passwd",
        "https://rest.kegg.jp/info/kegg",
    ],
)
def test_egress_rejects_unqualified_destination(url, monkeypatch):
    monkeypatch.delenv("UBI_LICENSED_SOURCES", raising=False)
    with pytest.raises(ResearchError):
        transport.validate_url(url)


@pytest.mark.asyncio
async def test_dns_answers_checked_before_connect(monkeypatch):
    async def lookup(*a, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ]

    monkeypatch.setattr(transport.anyio, "getaddrinfo", lookup)
    with pytest.raises(transport.ConnectError, match="forbidden"):
        await transport.PublicNetworkBackend().connect_tcp("provider.example", 443)


@pytest.mark.asyncio
async def test_stream_budget_closes_upstream():
    class Stream:
        closed = False

        async def __aiter__(self):
            yield b"12345"
            yield b"67890"

        async def aclose(self):
            self.closed = True

    stream = Stream()
    with pytest.raises(transport.ReadError):
        [chunk async for chunk in transport.BoundedStream(stream, limit=7)]
    assert stream.closed


@pytest.mark.asyncio
async def test_coalescing_cancellation_and_caller_isolation():
    runtime = ProviderRuntime()
    calls = []
    gate = asyncio.Event()

    async def fetch():
        calls.append(1)
        await gate.wait()
        return {"records": [{"id": "a"}]}

    a = asyncio.create_task(runtime.invoke("x", {}, fetch, scope="alice"))
    b = asyncio.create_task(runtime.invoke("x", {}, fetch, scope="alice"))
    c = asyncio.create_task(runtime.invoke("x", {}, fetch, scope="bob"))
    for _ in range(5):
        await asyncio.sleep(0)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    gate.set()
    await asyncio.gather(b, c)
    assert len(calls) == 2
    assert (await runtime.invoke("x", {}, fetch, scope="alice"))[1] is True
    assert runtime.flights == {}


@pytest.mark.asyncio
async def test_failure_is_not_cached_as_empty_evidence():
    runtime = ProviderRuntime()
    calls = []

    async def fetch():
        calls.append(1)
        return {"error": "provider outage"}

    for _ in range(2):
        with pytest.raises(ResearchError):
            await runtime.invoke("x", {}, fetch, scope="alice")
    assert len(calls) == 2


@pytest.mark.parametrize("status", ["partial", "degraded"])
async def test_incomplete_nested_evidence_does_not_enter_healthy_cache(status):
    runtime = ProviderRuntime()
    calls = []

    async def fetch():
        calls.append(1)
        return {
            "records": [{"id": "synthetic-retained"}],
            "section_outcomes": {"nested": {"outcome": status}},
        }

    for _ in range(2):
        record, cached = await runtime.invoke("x", {}, fetch, scope="alice")
        assert not cached and record["payload"]["records"][0]["id"] == "synthetic-retained"
    assert len(calls) == 2


def test_response_budget_preserves_provenance_and_explicit_omission():
    result = ResearchResult(
        outcome="data", sections={str(i): Section(outcome="data", data="x" * 50000) for i in range(10)}
    )
    assert len(result.model_dump_json().encode()) <= 120000
    assert result.truncated
    assert any(section.truncated for section in result.sections.values())


@pytest.mark.asyncio
async def test_public_mcp_surface_and_account_context(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")

    class Service:
        async def capabilities(self, **kw):
            return {"product": "biomedmcp"}

    server = create_server(service=Service(), settings=AuthSettings("local", "http://localhost"))
    async with Client(server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == {
            "literature_search",
            "trial_search",
            "variant_evidence",
            "study_analysis",
            "search",
            "get",
            "resolve",
            "relate",
            "research",
            "batch",
            "capabilities",
            "query_source",
            "quota",
        }
        assert all(t.annotations.read_only_hint for t in tools)
        assert (await client.call_tool("capabilities", {})).data["product"] == "biomedmcp"
