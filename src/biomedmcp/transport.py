"""Shared public egress: reusable connections, DNS checks, bounds and budgets.

Adapters import this httpx-compatible module. Auth and private platform clients
continue to use ordinary httpx and cannot enter this public-only connection pool.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import os
import random
import socket
import ssl
import sys
from contextlib import contextmanager
from datetime import UTC
from email.utils import parsedate_to_datetime
from time import monotonic, time
from urllib.parse import parse_qs, urlsplit

import anyio
import httpcore
import httpx as _httpx
import structlog
from httpcore._backends.auto import AutoBackend

from .errors import ResearchError
from .runtime import ProviderBudget, operation_deadline, remaining_budget

RESTRICTED_HOSTS = {
    "rest.kegg.jp": "kegg",
    "ddinter.scbdd.com": "ddinter",
    "www.antibodyregistry.org": "antibody-registry",
    "api.disgenet.com": "disgenet",
    "www.oncokb.org": "oncokb",
}
_RATES = {"ncbi": 3, "gtex": 2, "opentargets": 2, "epo": 1, "nih-reporter": 1}
_budget = ProviderBudget()
_transport = None
RETRY_STATUSES = {429, 502, 503, 504}
READ_POST_ROUTES = {
    ("mygene.info", "/v3/query"),
    ("mygene.info", "/v3/gene"),
    ("mychem.info", "/v1/query"),
    ("mychem.info", "/v1/chem"),
    ("mydisease.info", "/v1/query"),
    ("mydisease.info", "/v1/disease"),
    ("api.reporter.nih.gov", "/v2/projects/search"),
}


class RejectedConnection(_httpx.ConnectError):
    """A DNS/TLS policy rejection is not a transient connection failure."""


def response_byte_limit(request):
    # Current GenCC versioned downloads exceed the ordinary 24 MB budget.
    # Only this fixed read route receives 32 MiB; every stream still counts
    # actual bytes and shares the existing request deadline and admission.
    if (request.method == "GET" and request.url.scheme == "https"
            and request.url.netloc == b"thegencc.org"
            and request.url.path == "/download/action/submissions-export-csv"
            and list(request.url.params.multi_items()) == [("format", "new")]):
        return 33_554_432
    return 24_000_000


def replay_body(request):
    try:
        body = request.content
    except _httpx.RequestNotRead:
        return None
    if any(key in request.url.params for key in ("scroll_id", "_scroll_id", "fetch_all")):
        return None
    if request.method in {"GET", "HEAD"}:
        return body if not body else None
    if (
        request.method == "POST"
        and (request.url.host, request.url.path) in READ_POST_ROUTES
        and len(body) <= 65536
    ):
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        try:
            payload = (
                json.loads(body)
                if kind == "application/json"
                else parse_qs(body.decode())
                if kind == "application/x-www-form-urlencoded"
                else None
            )
        except (ValueError, UnicodeError, RecursionError):
            return None
        if not isinstance(payload, dict) or any(
            key in payload for key in ("scroll_id", "_scroll_id", "fetch_all")
        ):
            return None
        key = (
            "criteria"
            if request.url.host == "api.reporter.nih.gov"
            else "q"
            if request.url.path.endswith("/query")
            else "ids"
        )
        value = payload.get(key)
        if (key == "criteria" and not isinstance(value, dict)) or (
            key != "criteria"
            and not (
                isinstance(value, str)
                and value
                or isinstance(value, list)
                and value
                and all(isinstance(item, (str, int)) and not isinstance(item, bool) for item in value)
            )
        ):
            return None
        return body
    return None


def retry_delay(headers, *, now=None):
    """Never shorten a provider's minimum wait or retry a malformed wait."""
    value = headers.get("retry-after")
    if value is None:
        return random.uniform(0.25, 0.5)
    value = value.strip()
    if not value or len(value) > 128:
        return math.inf
    if value.isascii() and value.isdecimal():
        return float(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return math.inf
        delay = max(0, date.astimezone(UTC).timestamp() - (time() if now is None else now))
        return delay if math.isfinite(delay) else math.inf
    except (TypeError, ValueError, OverflowError):
        return math.inf


# httpcore has no HTTPError base class. Map the pinned hierarchy at both
# request and stream boundaries, without exposing its URL/body-bearing cause.
CORE_ERRORS = {
    getattr(httpcore, name): getattr(_httpx, name)
    for name in (
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        "LocalProtocolError",
        "ProxyError",
        "NetworkError",
        "ProtocolError",
    )
}


@contextmanager
def map_core_errors():
    try:
        yield
    except tuple(CORE_ERRORS) as exc:
        cause = exc
        for _ in range(6):
            if isinstance(cause, ssl.SSLCertVerificationError):
                raise RejectedConnection("Provider TLS certificate verification failed.") from None
            cause = cause.__cause__ or cause.__context__
            if cause is None:
                break
        mapped = CORE_ERRORS.get(type(exc))
        if mapped is None:
            mapped = next(value for base, value in CORE_ERRORS.items() if isinstance(exc, base))
        raise mapped(f"Provider transport failed ({type(exc).__name__}).") from None


def source_for_host(host):
    if host.endswith(".ncbi.nlm.nih.gov") or host == "ncbi.nlm.nih.gov":
        return "ncbi"
    return {
        "gtexportal.org": "gtex",
        "api.platform.opentargets.org": "opentargets",
        "ops.epo.org": "epo",
        "api.reporter.nih.gov": "nih-reporter",
    }.get(host, host)


def validate_url(url):
    parsed = urlsplit(str(url))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ResearchError("source_url_rejected", "Public providers require HTTPS on the standard port.")
    host = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ResearchError("source_url_rejected", "Private network destinations are forbidden.")
    except ValueError:
        pass
    if host in {"localhost", "metadata.google.internal"} or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ResearchError("source_url_rejected", "Private network destinations are forbidden.")
    restricted = RESTRICTED_HOSTS.get(host)
    enabled = set(filter(None, os.getenv("UBI_LICENSED_SOURCES", "").split(",")))
    if restricted == "antibody-registry":
        from .source_licensing import require_operation

        require_operation(restricted, "query_antibody")
    elif restricted and restricted not in enabled:
        raise ResearchError(
            "source_restricted", f"{restricted} requires an explicitly qualified access mode."
        )
    return host


async def admit(url):
    host = validate_url(url)
    source = source_for_host(host)
    rate = _RATES.get(source, 3)
    from .provider_credentials import active_credentials, provider_for_host

    context, provider = active_credentials.get(), provider_for_host(host)
    if context is not None and provider is not None:
        context.value(provider)
        # Shared admission must be last, so private waiters cannot synchronize
        # a later burst after consuming their earlier global admission.
        await _budget.acquire(context.pacing(provider), requests_per_second=rate)
    # Keep NCBI's conservative shared budget even when a key is configured.
    await _budget.acquire(source, requests_per_second=rate)


class PublicNetworkBackend(AutoBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ceiling = 30 if timeout is None else timeout
        deadline = min(monotonic() + ceiling, operation_deadline.get() or math.inf)
        if deadline <= monotonic():
            raise _httpx.ConnectTimeout("The complete DNS/TCP deadline elapsed.")
        try:
            async with asyncio.timeout_at(deadline):
                try:
                    addresses = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                except OSError:
                    raise _httpx.ConnectError("Provider DNS lookup failed.") from None
                ips = list(dict.fromkeys(item[4][0] for item in addresses))
                if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                    raise RejectedConnection("Provider DNS resolved to a forbidden address")
                # Check the entire DNS answer before any connection. Only the
                # validated IPs are attempted; httpcore retains the TLS hostname.
                ips = ips[:4]
                for index, ip in enumerate(ips):
                    try:
                        return await super().connect_tcp(
                            ip,
                            port,
                            max(0.001, (deadline - monotonic()) / (len(ips) - index)),
                            local_address,
                            socket_options,
                        )
                    except (httpcore.ConnectError, httpcore.ConnectTimeout):
                        if index == len(ips) - 1:
                            raise
        except TimeoutError:
            raise _httpx.ConnectTimeout("The complete DNS/TCP deadline elapsed.") from None


class BoundedStream(_httpx.AsyncByteStream):
    def __init__(self, stream, limit=24_000_000, *, deadline=None, patterns=()):
        self.stream, self.limit, self.deadline = stream, limit, deadline
        self.patterns = patterns

    async def __aiter__(self):
        from .provider_credentials import reject_echo

        total = 0
        tail = b""
        retained = max((len(p) for p in self.patterns), default=1) - 1
        try:
            async with asyncio.timeout_at(self.deadline):
                with map_core_errors():
                    async for chunk in self.stream:
                        total += len(chunk)
                        if total > self.limit:
                            await self.aclose()
                            raise _httpx.ReadError("Provider response exceeded its byte budget")
                        pending = tail + chunk
                        reject_echo(pending, self.patterns)
                        if retained:
                            if len(pending) > retained:
                                yield pending[:-retained]
                            tail = pending[-retained:]
                        else:
                            yield pending
                    if tail:
                        yield tail
        except TimeoutError:
            raise _httpx.ReadTimeout("The complete provider response deadline elapsed.") from None

    async def aclose(self):
        with map_core_errors():
            await self.stream.aclose()


class PublicTransport(_httpx.AsyncBaseTransport):
    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            max_connections=24,
            max_keepalive_connections=16,
            network_backend=PublicNetworkBackend(),
            retries=0,
        )

    async def handle_async_request(self, request):
        # One automatic retry at most. Pool retries remain disabled so every
        # attempt re-enters shared pacing and cannot bypass DNS/TLS checks.
        timeout = request.extensions.get("timeout", {})
        ceiling = max(
            (value for value in timeout.values() if isinstance(value, (int, float)) and value >= 0),
            default=30,
        )
        deadline = min(monotonic() + ceiling, operation_deadline.get() or math.inf)
        body = replay_body(request)
        for attempt in range(2 if body is not None else 1):
            if monotonic() >= deadline:
                raise ResearchError(
                    "operation_timeout",
                    "The complete public egress deadline elapsed; no absence can be inferred.",
                    retryable=True,
                )
            delay = None
            try:
                async with asyncio.timeout_at(deadline):
                    response = await self.send_once(request, deadline=deadline, body=body)
            except (
                _httpx.ConnectError,
                _httpx.ConnectTimeout,
                _httpx.ReadTimeout,
                _httpx.RemoteProtocolError,
            ) as exc:
                from .telemetry import active_observation

                observation = active_observation.get()
                if observation and isinstance(exc, (_httpx.ConnectTimeout, _httpx.ReadTimeout)):
                    observation.http_timeout_attempts += 1
                if attempt or body is None or isinstance(exc, RejectedConnection):
                    raise
                delay = retry_delay({})
                if monotonic() + delay + 0.05 >= deadline:
                    raise
            except TimeoutError:
                raise ResearchError(
                    "operation_timeout",
                    "The complete public egress deadline elapsed; no absence can be inferred.",
                    retryable=True,
                ) from None
            else:
                from .telemetry import active_observation

                observation = active_observation.get()
                if observation and response.status_code == 429:
                    observation.http_429 += 1
                response.extensions["ubi_attempts"] = attempt + 1
                if attempt or body is None or response.status_code not in RETRY_STATUSES:
                    return response
                delay = retry_delay(response.headers)
                if monotonic() + delay + 0.05 >= deadline:
                    return response
                await response.aclose()
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.sleep(delay)
            except TimeoutError:
                raise ResearchError(
                    "operation_timeout",
                    "The complete public egress deadline elapsed; no absence can be inferred.",
                    retryable=True,
                ) from None

    async def send_once(self, request, *, deadline, body):
        from .provider_credentials import active_credentials, reject_echo, wire_parts

        wire_url, wire_headers = wire_parts(request)
        await admit(str(request.url))
        request.headers["accept-encoding"] = "identity"
        remaining = max(0.001, deadline - monotonic())
        extensions = {
            **request.extensions,
            "timeout": {
                name: min(value, remaining) if isinstance(value, (int, float)) else remaining
                for name, value in request.extensions.get("timeout", {}).items()
            },
        }
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=wire_url.raw_scheme,
                host=wire_url.raw_host,
                port=wire_url.port,
                target=wire_url.raw_path,
            ),
            headers=[(k, v) for k, v in wire_headers if k.lower() != b"accept-encoding"]
            + [(b"accept-encoding", b"identity")],
            content=request.stream if body is None else _httpx.ByteStream(body),
            extensions=extensions,
        )
        with map_core_errors():
            response = await self.pool.handle_async_request(core_request)
            context = active_credentials.get()
            patterns = context.patterns if context is not None else ()
            try:
                reject_echo(b"\n".join(k + b":" + v for k, v in response.headers), patterns)
            except ResearchError:
                await response.aclose()
                raise
            encoding = next((v for k, v in response.headers if k.lower() == b"content-encoding"), b"identity")
            if encoding.lower() not in {b"", b"identity"}:
                await response.aclose()
                raise _httpx.ReadError("Provider ignored the bounded identity-encoding request")
            return _httpx.Response(
                response.status,
                headers=response.headers,
                stream=BoundedStream(response.stream, limit=response_byte_limit(request),
                                     deadline=deadline, patterns=patterns),
                extensions=response.extensions,
            )

    async def aclose(self):
        # Individual adapters borrow this pool; application shutdown owns it.
        pass

    async def shutdown(self):
        await self.pool.aclose()


class AsyncClient(_httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        global _transport
        if _transport is None:
            _transport = PublicTransport()
        kwargs.setdefault("transport", _transport)
        kwargs["trust_env"] = False
        timeout = kwargs.get("timeout", 30)
        if isinstance(timeout, (int, float)):
            kwargs["timeout"] = 0 if timeout == 0 else remaining_budget(timeout)
        elif isinstance(timeout, _httpx.Timeout):
            kwargs["timeout"] = _httpx.Timeout(
                **{
                    name: 0
                    if getattr(timeout, name) == 0
                    else remaining_budget(30 if getattr(timeout, name) is None else getattr(timeout, name))
                    for name in ("connect", "read", "write", "pool")
                }
            )
        else:
            kwargs["timeout"] = remaining_budget(30)
        kwargs.setdefault("max_redirects", 5)
        super().__init__(*args, **kwargs)


def configure(*, redis=None):
    from .logging_safety import install_log_redaction, redact_event

    install_log_redaction()
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    global _budget
    _budget = ProviderBudget(redis)


async def shutdown():
    global _transport
    if _transport is not None:
        await _transport.shutdown()
        _transport = None


def __getattr__(name):
    return getattr(_httpx, name)
