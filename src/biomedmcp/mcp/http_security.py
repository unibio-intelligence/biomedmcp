"""HTTP trust and input bounds shared by direct, ASGI and hosted entry points."""

import asyncio
import math
import os
from urllib.parse import urlsplit

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from ..http_telemetry import HTTPObservation

REQUEST_BYTES = 65_536
JSON_DEPTH = 32
REQUEST_CONCURRENCY = 32
BODY_TIMEOUT_SECONDS = 10
HTTP_CONNECTIONS = 128


def trust_policy(settings):
    if settings.profile == "local":
        return ["localhost", "127.0.0.1", "[::1]"], []
    public = urlsplit(settings.resource)
    if public.scheme != "https" or not public.hostname or public.username or public.password:
        raise ValueError("Hosted HTTP requires a qualified HTTPS resource URL.")
    hosts = [public.netloc]
    origins = [f"{public.scheme}://{public.netloc}"]
    extra_hosts = list(filter(None, os.getenv("UBI_HTTP_ALLOWED_HOSTS", "").split(",")))
    extra_origins = list(filter(None, os.getenv("UBI_HTTP_ALLOWED_ORIGINS", "").split(",")))
    for host in extra_hosts:
        parsed = urlsplit("https://" + host)
        if (
            "*" in host
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("Trusted HTTP hosts must be explicit host[:port] entries.")
    for origin in extra_origins:
        parsed = urlsplit(origin)
        if (
            "*" in origin
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("Trusted HTTP origins must be explicit HTTPS origins.")
    return hosts + extra_hosts, origins + extra_origins


def depth_exceeded(body):
    depth, quoted, escaped = 0, False, False
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            if depth > JSON_DEPTH:
                return True
        elif char in (93, 125):
            depth -= 1
    return False


class RequestBudget:
    def __init__(self, app, *, max_active=REQUEST_CONCURRENCY, body_timeout=BODY_TIMEOUT_SECONDS):
        if type(max_active) is not int or max_active < 1:
            raise ValueError("HTTP admission requires a positive integer limit.")
        if type(body_timeout) not in (int, float) or not math.isfinite(body_timeout) or body_timeout <= 0:
            raise ValueError("HTTP body reading requires a finite positive deadline.")
        self.app = app
        self.max_active = max_active
        self.body_timeout = body_timeout
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)

        async def reject(status, code):
            response = JSONResponse(
                {
                    "error": {
                        "code": code,
                        "message": "HTTP input cannot be accepted within the supported request budget.",
                        "retryable": status in {408, 503},
                    }
                },
                status_code=status,
                headers={"Retry-After": "1"} if status == 503 else None,
            )
            await response(scope, receive, send)

        lengths = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
        try:
            if len(lengths) > 1 or (lengths and int(lengths[0]) < 0):
                return await reject(400, "invalid_content_length")
            if lengths and int(lengths[0]) > REQUEST_BYTES:
                return await reject(413, "request_too_large")
        except ValueError:
            return await reject(400, "invalid_content_length")
        # Each ASGI worker runs on one event loop. No await separates checking
        # and taking admission; excess readers never queue or retain a body.
        if self.active >= self.max_active:
            return await reject(503, "request_capacity_exceeded")
        self.active += 1
        try:
            await self.accepted(scope, receive, send, reject)
        finally:
            self.active -= 1

    async def accepted(self, scope, receive, send, reject):
        body = bytearray()
        too_large = False
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > REQUEST_BYTES:
                        too_large = True
                        break
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await reject(408, "request_body_timeout")
        if too_large:
            return await reject(413, "request_too_large")
        json_content = any(
            key.lower() == b"content-type"
            and b"application/json" in [part.strip() for part in value.lower().split(b";", 1)[0].split(b",")]
            for key, value in scope.get("headers", [])
        )
        if json_content and depth_exceeded(body):
            return await reject(400, "request_too_deep")
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class PublicMCP(FastMCP):
    """Apply policy on construction of every HTTP app, including ASGI users."""

    def http_app(self, *args, **kwargs):
        kwargs["host_origin_protection"] = True
        kwargs["allowed_hosts"] = self.http_trusted_hosts
        kwargs["allowed_origins"] = self.http_trusted_origins
        kwargs["middleware"] = [Middleware(RequestBudget), *(kwargs.get("middleware") or [])]
        app = super().http_app(*args, **kwargs)
        # Observe the outer HTTP app, including SDK Host/Origin and auth denials.
        # Preserve the Starlette router/lifespan used by hosted composition.
        app.add_middleware(HTTPObservation)
        return app

    async def run_http_async(self, *args, **kwargs):
        configuration = dict(kwargs.get("uvicorn_config") or {})
        limit = configuration.get("limit_concurrency")
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("HTTP connection concurrency requires a positive integer limit.")
        configuration["limit_concurrency"] = min(limit or HTTP_CONNECTIONS, HTTP_CONNECTIONS)
        kwargs["uvicorn_config"] = configuration
        return await super().run_http_async(*args, **kwargs)
