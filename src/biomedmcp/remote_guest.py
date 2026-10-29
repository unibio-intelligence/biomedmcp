"""Retain only a hosted guest cookie in the existing protected CLI state."""

import re
import time
from http.cookiejar import Cookie

import httpx
from fastmcp.client.transports import StreamableHttpTransport

from .errors import ResearchError
from .local_state import LocalState
from .runtime import digest

COOKIE = "__Host-biomedmcp_guest"


def expiry(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}\.[0-9]{1,12}\.[a-f0-9]{64}", value):
        return None
    expires = int(value.split(".")[1])
    return expires if time.time() < expires <= time.time() + 86401 else None


async def transport(url):
    endpoint = httpx.URL(url)
    if endpoint.username or endpoint.password:
        raise ResearchError("invalid_parameters", "MCP URLs must not contain credentials.")
    if endpoint.scheme != "https":
        return StreamableHttpTransport(url)
    state = await LocalState.open()
    key = "remote-guest:" + digest(str(endpoint))
    saved = await state.get(key)

    async def remember(response):
        # Never persist OAuth tokens, arbitrary cookies, or another endpoint's response.
        if response.request.url != endpoint:
            return
        for cookie in response.cookies.jar:
            expires = expiry(cookie.value)
            if cookie.name == COOKIE and cookie.secure and cookie.path == "/" and expires:
                await state.put(key, cookie.value, max(1, expires - time.time()))

    async def restrict(request):
        if request.url != endpoint:
            # CookieJar's host-only handling also permits subdomains/other ports.
            # Redirects must never carry this endpoint's guest identity elsewhere.
            values = [part.strip() for value in request.headers.get_list("cookie")
                      for part in value.split(";") if part.strip().split("=", 1)[0] != COOKIE]
            request.headers.pop("cookie", None)
            if values:
                request.headers["cookie"] = "; ".join(values)

    def factory(**kwargs):
        instance = httpx.AsyncClient(**kwargs)
        if expires := expiry(saved):
            instance.cookies.jar.set_cookie(Cookie(
                version=0, name=COOKIE, value=saved, port=None, port_specified=False,
                domain=endpoint.host, domain_specified=False, domain_initial_dot=False,
                path="/", path_specified=True, secure=True, expires=expires,
                discard=False, comment=None, comment_url=None, rest={"HttpOnly": None}, rfc2109=False,
            ))
        instance.event_hooks["response"].append(remember)
        instance.event_hooks["request"].append(restrict)
        return instance

    return StreamableHttpTransport(url, httpx_client_factory=factory)
