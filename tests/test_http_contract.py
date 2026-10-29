import asyncio
import socket
from contextlib import nullcontext

import httpx
import pytest
import uvicorn
from fastmcp import Client

from biomedmcp.local_boundary import AuthSettings
from biomedmcp.mcp.server import create_server


@pytest.mark.asyncio
async def test_stateless_http_negotiation_and_reconnect(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")

    class Service:
        async def capabilities(self, **kw):
            return {"product": "biomedmcp"}

    server = create_server(service=Service(), settings=AuthSettings("local", "http://localhost"))
    app = server.http_app(stateless_http=True)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    port = sock.getsockname()[1]
    runner = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    runner.capture_signals = nullcontext
    task = asyncio.create_task(runner.serve(sockets=[sock]))
    try:
        for _ in range(300):
            if runner.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert runner.started
        for _ in range(2):
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                assert await client.list_tools()
                result = await client.call_tool("capabilities", {})
                assert result.data["product"] == "biomedmcp"
        async with httpx.AsyncClient() as client:
            assert (await client.get(f"http://127.0.0.1:{port}/readyz")).status_code == 200
            response = await client.post(
                f"http://127.0.0.1:{port}/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "qualification", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200
            assert "mcp-session-id" not in response.headers
    finally:
        runner.should_exit = True
        await asyncio.wait_for(task, 10)
