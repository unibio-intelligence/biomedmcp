"""Neutral request-local credentials injected by a trusted hosting layer.

No storage, accounts, private imports or scientific credential parameters live
here. Without an injected context, public/local behavior remains unchanged.
"""
from __future__ import annotations

import html
import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from urllib.parse import quote, quote_plus

from .errors import ResearchError
from .source_licensing import availability

PROVIDERS = frozenset({"ncbi", "openfda"})
active_credentials = ContextVar("biomedmcp_provider_credentials", default=None)


class RequestCredentials:
    __slots__ = ("_blocked", "_pacing", "_values", "deadline", "partition", "patterns")

    def __init__(self, *, partition, deadline, values, pacing, blocked=()):
        if (not isinstance(partition, str) or not re.fullmatch(r"[a-zA-Z0-9:-]{1,160}", partition)
                or type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not isinstance(values, dict) or not isinstance(pacing, dict)
                or not set(values) <= PROVIDERS or set(pacing) != PROVIDERS
                or not set(blocked) <= PROVIDERS
                or any(not isinstance(v, str) or not 1 <= len(v) <= 4096
                       or any(not 33 <= ord(c) <= 126 for c in v) for v in values.values())
                or any(not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z0-9:-]{1,160}", v)
                       for v in pacing.values())):
            raise ValueError("Invalid internal provider credential context.")
        self.partition, self.deadline = partition, deadline
        self._values, self._pacing = MappingProxyType(dict(values)), MappingProxyType(dict(pacing))
        self._blocked = frozenset(blocked)
        self.patterns = tuple(sorted({form.encode() for value in values.values() for form in
            (value, quote(value, safe=""), quote_plus(value), html.escape(value),
             json.dumps(value)[1:-1])}, key=len, reverse=True))

    def __repr__(self):
        return "<RequestCredentials: wire values omitted>"

    def live(self):
        if time.monotonic() >= self.deadline:
            raise ResearchError("operation_timeout", "The authenticated credential deadline elapsed.", retryable=True)

    def value(self, provider):
        self.live()
        ready, _ = availability(provider)
        if provider in self._blocked or ready is not True:
            raise ResearchError("source_unreleased", "This source has no released permission projection.")
        return self._values.get(provider)

    def pacing(self, provider):
        self.live()
        return self._pacing[provider]


@contextmanager
def credential_context(value):
    if not isinstance(value, RequestCredentials):
        raise TypeError("A trusted credential snapshot is required.")
    value.live()
    token = active_credentials.set(value)
    try:
        yield
    finally:
        active_credentials.reset(token)


def cache_key(key):
    context = active_credentials.get()
    if context is None or key.startswith("{evidence}:"):
        return key
    context.live()
    return "credentials:" + context.partition + ":" + key


def coalescing_scope(scope):
    context = active_credentials.get()
    if context is None:
        return scope
    context.live()
    return [scope, context.partition]


def redaction_forms():
    context = active_credentials.get()
    return tuple(p.decode() for p in context.patterns) if context is not None else ()


def provider_for_host(host):
    if host in {"eutils.ncbi.nlm.nih.gov", "api.ncbi.nlm.nih.gov"}:
        return "ncbi"
    return "openfda" if host == "api.fda.gov" else None


def wire_parts(request):
    """Inject only into httpcore, never into the visible httpx request."""
    context = active_credentials.get()
    if context is None:
        return request.url, request.headers.raw
    context.live()
    provider = provider_for_host(request.url.host)
    if provider is None:
        return request.url, request.headers.raw
    # Replace cached adapter/operator credentials only in this request.
    request.url = request.url.copy_remove_param("api_key").copy_remove_param("api-key")
    for name in ("api-key", "x-api-key", "authorization"):
        request.headers.pop(name, None)
    value = context.value(provider)
    url, headers = request.url, list(request.headers.raw)
    if request.method != "GET" or url.scheme != "https" or url.port not in {None, 443}:
        raise ResearchError("source_url_rejected", "This credential context has no qualified wire route.")
    if value is None:
        return url, headers
    if provider == "openfda" and re.fullmatch(r"/(drug|device|food|animalandveterinary|tobacco)/[a-z0-9/_-]+\.json", url.path) or url.host == "eutils.ncbi.nlm.nih.gov" and re.fullmatch(
        r"/entrez/eutils/(esearch|esummary|efetch|elink|einfo|egquery|espell)\.fcgi", url.path
    ):
        url = url.copy_add_param("api_key", value)
    elif url.host == "api.ncbi.nlm.nih.gov" and url.path.startswith("/datasets/v2/"):
        headers.append((b"api-key", value.encode("ascii")))
    else:
        raise ResearchError("source_url_rejected", "This credential has no qualified wire route.")
    return url, headers


def reject_echo(value, patterns):
    if any(pattern in value for pattern in patterns):
        raise ResearchError("source_unavailable", "Provider response exposed credential material; evidence was withheld.", retryable=True)
