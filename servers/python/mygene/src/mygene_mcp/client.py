"""Small MyGene.info HTTP client with envelope validation and a TTL cache.

Every response is checked against the documented BioThings envelope before it is
cached or returned. Provider bodies never reach error messages: failures leave
through ``biomedmcp.errors.provider_boundary`` as sanitized ``ToolError``s.
"""

import asyncio
import hashlib
import json
from copy import deepcopy
from time import monotonic

from biomedmcp import transport
from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.native.biothings import CacheEntry, invalid, record

BASE_URL = "https://mygene.info/v3"


def validate_envelope(method, endpoint, value, request=None):
    """Accept only the documented MyGene query, annotation and metadata shapes."""
    if method == "GET" and endpoint == "query":
        if not isinstance(value, dict) or "error" in value or value.get("success") is False:
            invalid()
        hits = value.get("hits")
        if not isinstance(hits, list):
            invalid()
        total = value.get("total")
        if total is not None and (type(total) is not int or total < 0 or len(hits) > total):
            invalid()
        for hit in hits:
            record(hit)
    elif method == "GET" and endpoint.startswith("gene/"):
        record(value)
    elif method == "POST" and endpoint in {"query", "gene"}:
        if not isinstance(value, list):
            invalid()
        requested = (request or {}).get("q" if endpoint == "query" else "ids")
        allowed = set(requested if isinstance(requested, list) else (requested or "").split(","))
        for row in value:
            if not isinstance(row, dict) or "error" in row or row.get("success") is False:
                invalid()
            if not isinstance(row.get("query"), str) or not row["query"].strip():
                invalid()
            if requested is not None and row["query"] not in allowed:
                invalid()
            if "notfound" in row and type(row["notfound"]) is not bool:
                invalid()
            if row.get("notfound") is True:
                if "_id" in row:
                    invalid()
            else:
                record(row)
    elif method == "GET" and endpoint in {"metadata", "metadata/fields"}:
        if not isinstance(value, dict) or not value or "error" in value:
            invalid()
    else:
        raise ResearchError("unsupported_operation", "This MyGene endpoint has no acquisition contract.")
    return value


class MyGeneClient:
    source = "mygene"

    def __init__(self, base_url=BASE_URL, timeout=30.0, cache_enabled=True, cache_ttl=3600, rate_limit=10):
        self.base_url, self.timeout = base_url, timeout
        self.cache_enabled, self.cache_ttl, self.rate_limit = cache_enabled, cache_ttl, rate_limit
        self._cache = {}
        self._rate_lock = asyncio.Lock()
        self._next_request = 0.0

    def _get_cache_key(self, method, endpoint, params=None, data=None):
        return hashlib.sha256(
            json.dumps([method, endpoint, params, data], sort_keys=True).encode()
        ).hexdigest()

    def clear_cache(self):
        self._cache.clear()

    async def _throttle(self):
        if not self.rate_limit:
            return
        async with self._rate_lock:
            delay = self._next_request - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request = monotonic() + 1.0 / self.rate_limit

    async def _request(self, method, endpoint, payload, use_cache):
        key = self._get_cache_key(method, endpoint, params=payload)
        with provider_boundary(self.source):
            entry = self._cache.get(key) if self.cache_enabled and use_cache else None
            if entry is not None and not entry.is_expired():
                try:
                    return deepcopy(validate_envelope(method, endpoint, entry.data, payload))
                except ResearchError:
                    del self._cache[key]
                    raise
            await self._throttle()
            url = f"{self.base_url}/{endpoint}"
            try:
                async with transport.AsyncClient() as client:
                    if method == "GET":
                        response = await client.get(url, params=payload, timeout=self.timeout)
                    else:
                        form = {
                            name: ",".join(map(str, value)) if isinstance(value, list) else value
                            for name, value in (payload or {}).items()
                        }
                        response = await client.post(url, data=form, timeout=self.timeout)
                    response.raise_for_status()
                    data = validate_envelope(method, endpoint, response.json(), payload)
            except (ResearchError, transport.HTTPError, ValueError):
                raise
            except Exception:  # noqa: BLE001 - never leak transport internals to SDK logs.
                raise ResearchError(
                    "source_unavailable", "The MyGene request could not be completed.", retryable=True
                ) from None
            if self.cache_enabled and use_cache:
                self._cache[key] = CacheEntry(data, self.cache_ttl)
            return deepcopy(data)

    async def get(self, endpoint, params=None):
        return await self._request("GET", endpoint, params, True)

    async def post(self, endpoint, json_data, use_cache=True):
        return await self._request("POST", endpoint, json_data, use_cache)
