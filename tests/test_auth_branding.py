"""Real SDK presentation and callback contracts retain their security behavior."""

import httpx
import pytest
from fastmcp.client.oauth_callback import create_oauth_callback_server
from fastmcp.utilities.ui import FASTMCP_LOGO_URL

from biomedmcp.auth_branding import LOGO_URL, AuthBranding
from biomedmcp.oauth import BioMedOAuth


@pytest.mark.parametrize("content_type,size", [(b"text/html", 0), (b"text/html", 270_000), (b"application/json", 0)])
async def test_bounded_presentation_keeps_security_headers_and_non_html(content_type, size):
    body = (f'<html><head><title>FastMCP OAuth</title></head><body><img src="{FASTMCP_LOGO_URL}" '
            'alt="FastMCP" class="logo" /><form><input name="csrf_token" value="fixture" /></form>'
            '</body></html>').encode() + b" " * size
    headers = [(b"content-type", content_type), (b"content-length", str(len(body)).encode()),
               (b"content-security-policy", b"default-src 'none'; style-src 'unsafe-inline'; img-src data:"),
               (b"set-cookie", b"fixture=one; Secure; HttpOnly"),
               (b"set-cookie", b"fixture2=two; Secure; HttpOnly"), (b"x-frame-options", b"DENY")]

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 400, "headers": headers})
        for start, end, more in [(0, 10, True), (10, len(body), False)]:
            await send({"type": "http.response.body", "body": body[start:end], "more_body": more})

    messages = []

    async def send(message):
        messages.append(message)

    await AuthBranding(app)({"type": "http"}, None, send)
    returned = b"".join(m.get("body", b"") for m in messages)
    assert messages[0]["status"] == 400
    assert [h for h in messages[0]["headers"] if h[0] != b"content-length"] == [
        h for h in headers if h[0] != b"content-length"
    ]
    assert int(dict(messages[0]["headers"])[b"content-length"]) == len(returned)
    assert b'name="csrf_token" value="fixture"' in returned
    if content_type == b"text/html" and not size:
        assert LOGO_URL.encode() in returned and FASTMCP_LOGO_URL.encode() not in returned
        assert b"BioMed MCP" in returned and b'id="biomed-auth-theme"' in returned
    else:
        assert returned == body


async def test_cli_callback_uses_sdk_first_response_state_and_issuer_with_product_brand(monkeypatch):
    import biomedmcp.oauth as module

    pages = []

    def factory(**kwargs):
        server = create_oauth_callback_server(**kwargs)

        async def serve():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(server.config.app),
                                         base_url="http://127.0.0.1") as client:
                pages.append(await client.get("/callback", params={
                    "code": "synthetic-first", "state": "synthetic-state", "iss": "https://issuer.example/",
                }))
                await client.get("/callback", params={"code": "synthetic-second", "state": "wrong"})

        server.serve = serve
        return server

    monkeypatch.setattr(module, "create_oauth_callback_server", factory)
    oauth = BioMedOAuth("https://public.example/mcp", callback_port=8765)
    result = await oauth.callback_handler()
    assert (result.code, result.state, result.iss) == (
        "synthetic-first", "synthetic-state", "https://issuer.example/",
    )
    response = pages[0]
    assert response.status_code == 200
    assert LOGO_URL in response.text and FASTMCP_LOGO_URL not in response.text
    assert "BioMed MCP" in response.text and "Authentication successful" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert int(response.headers["content-length"]) == len(response.content)
