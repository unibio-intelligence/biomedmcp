"""Offline fixtures: synthetic HTTP through the biomedmcp transport shim, no licensing scopes."""

import httpx
import pytest
from fastmcp import Client

from biomedmcp import source_licensing, transport


@pytest.fixture
def mocked(monkeypatch):
    """Install a request handler and return a tool runner plus the captured requests."""
    monkeypatch.setattr(source_licensing, "operation_allowed", lambda source, operation: True)
    original = httpx.AsyncClient
    requests = []

    def install(server, handler):
        def route(request):
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(route))
        )

        async def call(name, **params):
            async with Client(server) as client:
                return (await client.call_tool(name, params)).data

        return call

    install.requests = requests
    return install
