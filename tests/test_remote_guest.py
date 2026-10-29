import time

import httpx
import pytest

from biomedmcp.remote_guest import COOKIE, expiry, transport


@pytest.mark.parametrize("other", ["https://public.example/other", "https://public.example:8443/mcp",
                                   "https://other.example/mcp"])
async def test_cli_guest_cookie_survives_new_clients_but_stays_endpoint_scoped(monkeypatch, other):
    cookie = "a" * 64 + "." + str(int(time.time()) + 3600) + "." + "b" * 64
    seen = []

    async def respond(request):
        seen.append(request.headers.get("cookie", ""))
        return httpx.Response(200, headers={"Set-Cookie": f"{COOKIE}={cookie}; Secure; HttpOnly; Path=/"})

    original = httpx.AsyncClient
    monkeypatch.setattr("biomedmcp.remote_guest.httpx.AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    endpoint = "https://public.example/mcp"
    for url in (endpoint, endpoint, other):
        remote = await transport(url)
        async with remote.httpx_client_factory() as client:
            await client.post(url)
    assert seen == ["", f"{COOKIE}={cookie}", ""]


async def test_unrelated_or_insecure_cookies_are_not_retained(monkeypatch):
    cookie = "a" * 64 + "." + str(int(time.time()) + 3600) + "." + "b" * 64
    seen = []

    async def respond(request):
        seen.append(request.headers.get("cookie", ""))
        return httpx.Response(200, headers=[("Set-Cookie", f"{COOKIE}={cookie}; Path=/"),
                                           ("Set-Cookie", "other=unrelated; Secure; Path=/")])

    original = httpx.AsyncClient
    monkeypatch.setattr("biomedmcp.remote_guest.httpx.AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    for _ in range(2):
        remote = await transport("https://public.example/mcp")
        async with remote.httpx_client_factory() as client:
            await client.post(remote.url)
    assert seen == ["", ""]


def test_invalid_and_expired_guest_state_is_ignored():
    assert expiry(None) is None
    assert expiry("not-a-cookie") is None
    for timestamp in (int(time.time()) - 1, int(time.time()) + 172800):
        assert expiry("a" * 64 + "." + str(timestamp) + "." + "b" * 64) is None


@pytest.mark.parametrize("redirect", ["https://sub.public.example/other", "https://public.example:8443/mcp",
                                      "https://public.example/other", "http://public.example/mcp"])
async def test_guest_cookie_is_never_forwarded_by_redirect(monkeypatch, redirect):
    cookie = "a" * 64 + "." + str(int(time.time()) + 3600) + "." + "b" * 64
    endpoint = "https://public.example/mcp"
    seen = []
    redirecting = False

    async def respond(request):
        seen.append((str(request.url), request.headers.get("cookie", "")))
        if redirecting and str(request.url) == endpoint:
            return httpx.Response(307, headers={"Location": redirect})
        return httpx.Response(200, headers={"Set-Cookie": f"{COOKIE}={cookie}; Secure; Path=/"})

    original = httpx.AsyncClient
    monkeypatch.setattr("biomedmcp.remote_guest.httpx.AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    first = await transport(endpoint)
    async with first.httpx_client_factory() as client:
        await client.post(endpoint)
    redirecting = True
    second = await transport(endpoint)
    async with second.httpx_client_factory(follow_redirects=True) as client:
        await client.post(endpoint)
    assert seen == [(endpoint, ""), (endpoint, f"{COOKIE}={cookie}"), (redirect, "")]
