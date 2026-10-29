import httpx
import pytest

from biomedmcp.local_boundary import AuthSettings
from biomedmcp.mcp.server import create_server


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["initialize", "tools/call"])
@pytest.mark.parametrize(
    "host,origin,status",
    [
        ("attacker.example", None, 421),
        ("localhost", "https://attacker.example", 403),
        ("localhost", None, 200),
        ("localhost:8000", "http://localhost:8000", 200),
        ("127.0.0.1:8000", None, 200),
        ("[::1]:8000", "http://[::1]:8000", 200),
    ],
)
async def test_host_origin_policy_for_all_http_apps(monkeypatch, method, host, origin, status):
    monkeypatch.setenv("UBI_PROFILE", "local")

    class Service:
        async def capabilities(self, **kw):
            return {"product": "biomedmcp"}

    server = create_server(service=Service(), settings=AuthSettings("local", "http://localhost"))
    app = server.http_app(stateless_http=True)
    headers = {
        "host": host,
        "accept": "application/json, text/event-stream",
        "x-forwarded-host": "localhost",
        "x-forwarded-proto": "https",
    }
    if origin:
        headers["origin"] = origin
    params = (
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}
        if method == "initialize"
        else {"name": "capabilities", "arguments": {}}
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client,
    ):
        response = await client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        )
    assert response.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "host,origin,status",
    [
        ("public.example", None, 200),
        ("public.example", "https://public.example", 200),
        ("public.example", "https://approved-client.example", 200),
        ("public.example", "https://attacker.example", 403),
        ("attacker.example", "https://public.example", 421),
    ],
)
async def test_hosted_proxy_trust_is_explicit(monkeypatch, host, origin, status):
    from types import SimpleNamespace

    from biomedmcp import local_boundary

    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setenv("UBI_CURSOR_KEY", "synthetic-signing-key-for-test-only-00000")
    monkeypatch.setenv("UBI_HTTP_ALLOWED_ORIGINS", "https://approved-client.example")
    boundary = SimpleNamespace(
        **{
            key: getattr(local_boundary, key)
            for key in [
                "AuthSettings",
                "current_context",
                "accounted",
                "dependencies_ready",
                "close_auth",
                "ServiceError",
            ]
        },
        build_auth=lambda settings: None,
        build_ledger=lambda profile: local_boundary.LocalLedger(),
    )
    server = create_server(
        service=object(), settings=AuthSettings("hosted", "https://public.example"), boundary=boundary
    )
    app = server.http_app(stateless_http=True, host_origin_protection=False)
    headers = {
        "host": host,
        "accept": "application/json, text/event-stream",
        "x-forwarded-host": "public.example",
        "x-forwarded-proto": "https",
    }
    if origin:
        headers["origin"] = origin
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://public.example"
        ) as client,
    ):
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
    assert response.status_code == status


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["declared", "chunked", "deep"])
async def test_ingress_rejects_before_mcp_and_does_not_echo_body(kind):
    from biomedmcp.mcp.http_security import JSON_DEPTH, REQUEST_BYTES, RequestBudget

    calls, reads, responses = [], [], []

    async def app(scope, receive, send):
        calls.append(True)

    headers = [(b"content-type", b"application/json")]
    if kind == "declared":
        headers.append((b"content-length", str(REQUEST_BYTES + 1).encode()))
    chunks = ([b"x" * 16_384] * 10) if kind != "deep" else [b"[" * (JSON_DEPTH + 1) + b"]" * (JSON_DEPTH + 1)]

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}

    async def send(message):
        responses.append(message)

    await RequestBudget(app)({"type": "http", "method": "POST", "headers": headers}, receive, send)
    assert not calls
    assert responses[0]["status"] == (400 if kind == "deep" else 413)
    assert len(reads) == (0 if kind == "declared" else 1 if kind == "deep" else 5)
    assert b"x" * 100 not in responses[1]["body"]


@pytest.mark.asyncio
async def test_maximum_bounded_json_and_quoted_braces_reach_application():
    from biomedmcp.mcp.http_security import REQUEST_BYTES, RequestBudget

    body = b'{"text":"' + b"{" * (REQUEST_BYTES - 11) + b'"}'
    calls = []

    async def app(scope, receive, send):
        message = await receive()
        assert message["body"] == body
        calls.append(True)

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        pytest.fail("Valid request rejected")

    await RequestBudget(app)(
        {"type": "http", "method": "POST", "headers": [(b"content-type", b"application/json")]}, receive, send
    )
    assert calls
