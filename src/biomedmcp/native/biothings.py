"""Minimum MyChem/MyDisease acquisition contracts, not biological qualification.

The aggregators mix underlying data permissions. These checks do not grant access
or establish that an omitted annotation is a negative scientific measurement.
"""

import asyncio
import hashlib
import json
import math
import re
from copy import deepcopy
from time import monotonic

from .. import transport
from ..errors import ResearchError, provider_boundary
from .annotation_permissions import projection as permission_projection


def invalid():
    raise ResearchError("invalid_source_response", "The annotation source returned an invalid response.")


def _json(value, depth=0):
    if depth > 64:
        invalid()
    if isinstance(value, float) and not math.isfinite(value):
        invalid()
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                invalid()
            _json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json(item, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        invalid()


def record(value):
    if not isinstance(value, dict) or "error" in value or value.get("success") is False:
        invalid()
    if not isinstance(value.get("_id"), str) or not value["_id"].strip():
        invalid()
    _json(value)
    return value


def selected_fields(row, request):
    fields = (request or {}).get("fields", "")
    if not isinstance(fields, str):
        return
    for path in fields.split(","):
        if path in {"gene", "causal_gene", "hpo", "phenotype_related_to_disease"}:
            for node in objects(row.get(path)):
                key = "hpo_id" if path in {"hpo", "phenotype_related_to_disease"} else "symbol"
                if key in node and node[key] is not None:
                    if not isinstance(node[key], str):
                        invalid()
                    if key == "hpo_id" and not re.fullmatch(r"HP:[0-9]{7}", node[key]):
                        invalid()
        elif "." in path:
            field_values(row, path)


def response_contract(method, endpoint, value, request=None):
    """Validate the endpoint envelope before storage, including explicit missingness."""
    _json(value)
    if method == "GET" and endpoint == "query":
        if not isinstance(value, dict) or "error" in value or value.get("success") is False:
            invalid()
        total = value.get("total")
        if type(total) is not int or total < 0:
            invalid()
        hits = value.get("hits")
        # The documented size=0 facet envelope may omit hits.
        if hits is None and (request or {}).get("size") == 0 and isinstance(value.get("facets"), dict):
            hits = []
        if not isinstance(hits, list) or len(hits) > total:
            invalid()
        offset = (request or {}).get("from", 0)
        size = (request or {}).get("size", 10)
        if not hits and total > 0 and type(offset) is int and offset < total and size != 0:
            invalid()
        for hit in hits:
            record(hit)
            selected_fields(hit, request)
        for name in ("took", "max_score"):
            item = value.get(name)
            if item is not None and (type(item) not in (int, float) or item < 0):
                invalid()
    elif method == "GET" and endpoint.startswith(("chem/", "disease/")):
        record(value)
        selected_fields(value, request)
    elif method == "POST" and endpoint in {"query", "chem", "disease"}:
        if not isinstance(value, list):
            invalid()
        for item in value:
            if not isinstance(item, dict) or "error" in item or item.get("success") is False:
                invalid()
            if not isinstance(item.get("query"), str) or not item["query"].strip():
                invalid()
            if "notfound" in item and type(item["notfound"]) is not bool:
                invalid()
            if item.get("notfound") is True:
                if "_id" in item:
                    invalid()
            else:
                record(item)
                selected_fields(item, request)
        requested = (request or {}).get("q" if endpoint == "query" else "ids")
        if requested is not None:
            ids = requested if isinstance(requested, list) else requested.split(",")
            by_query = {identifier: [] for identifier in ids}
            for item in value:
                if item["query"] not in by_query:
                    invalid()
                by_query[item["query"]].append(item)
            if any(
                not rows or (len(rows) > 1 and any(row.get("notfound") is True for row in rows))
                for rows in by_query.values()
            ):
                invalid()
    elif method == "GET" and endpoint in {"metadata", "metadata/fields"}:
        if not isinstance(value, dict) or not value or "error" in value or value.get("success") is False:
            invalid()
    else:
        raise ResearchError("unsupported_operation", "This annotation endpoint has no acquisition contract.")
    return value


def objects(value):
    """Accept source object or repeated source objects; never drop malformed members."""
    if value is None:
        return []
    rows = value if isinstance(value, list) else [value]
    if any(not isinstance(row, dict) for row in rows):
        invalid()
    return rows


def field_values(value, path):
    parts = path.split(".")
    if value is None:
        return []
    if isinstance(value, list):
        if any(not isinstance(row, dict) for row in value):
            invalid()
        return [item for row in value for item in field_values(row, path)]
    if not isinstance(value, dict):
        invalid()
    child = value.get(parts[0])
    if len(parts) > 1:
        return field_values(child, ".".join(parts[1:]))
    if child is None:
        return []
    values = child if isinstance(child, list) else [child]
    if parts[0] in {
        "inchikey",
        "cid",
        "molecule_chembl_id",
        "unii",
        "id",
        "mondo",
        "orphanet",
        "doid",
        "cui",
        "cas_number",
        "cas",
        "hpo_id",
        "inchi",
        "smiles",
        "canonical",
        "pref_name",
        "name",
        "synonyms",
    } and any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in values):
        invalid()
    return values


def attribution(row, locator):
    return {
        "locator": locator,
        "record_id": row["_id"],
        "record_sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "source_release": None,
        "interpretation": "reported_annotation",
    }


def mapping_inputs(input_ids, from_type, to_types, field_map):
    if (
        from_type not in field_map
        or not to_types
        or any(item not in field_map for item in to_types)
        or not input_ids
        or len(input_ids) > 1000
        or any(
            not isinstance(item, str) or not item.strip() or any(c.isspace() or c in ",+" for c in item)
            for item in input_ids
        )
    ):
        raise ResearchError(
            "invalid_parameters",
            "Use supported namespaces and 1–1000 literal identifiers without batch separators.",
        )


def mappings(rows, input_ids, from_type, to_types, field_map, missing_ok):
    response_contract("POST", "query", rows)
    grouped = {identifier: [] for identifier in dict.fromkeys(input_ids)}
    for row in rows:
        if row["query"] not in grouped:
            invalid()
        grouped[row["query"]].append(row)
    output = []
    for identifier, candidates in grouped.items():
        if not candidates or (
            any(row.get("notfound") is True for row in candidates) and len(candidates) != 1
        ):
            invalid()
        if candidates[0].get("notfound") is True:
            output.append({"input": identifier, "status": "not_found", "candidates": []})
            continue
        seen = set()
        resolved = []
        for row in candidates:
            if row["_id"] in seen:
                invalid()
            seen.add(row["_id"])
            values = {}
            for target in to_types:
                found = []
                paths = field_map[target].split(",")
                for path in paths:
                    for item in field_values(row, path):
                        if not isinstance(item, (str, int)) or isinstance(item, bool):
                            invalid()
                        if item not in found:
                            found.append(item)
                values[target] = found or None
            resolved.append({"id": row["_id"], "mappings": values, "provenance": attribution(row, "/query")})
        output.append(
            {
                "input": identifier,
                "status": "resolved" if len(resolved) == 1 else "ambiguous",
                "candidates": resolved,
            }
        )
    missing = [row["input"] for row in output if row["status"] == "not_found"]
    return {
        "success": True,
        "status": "partial"
        if missing
        or any(
            row["status"] == "ambiguous"
            or any(
                value is None for candidate in row["candidates"] for value in candidate["mappings"].values()
            )
            for row in output
        )
        else "complete",
        "from_type": from_type,
        "total_input": len(input_ids),
        "unique_inputs": len(grouped),
        "mappings": output,
        "unmapped_ids": missing,
        "missing_policy_satisfied": missing_ok or not missing,
        "limitations": [
            "Matches are source annotations; namespace, species and chemical identity require independent qualification."
        ],
    }


def scientific_status(payload, name):
    if payload.get("status") == "partial":
        payload["section_outcomes"] = {name: {"outcome": "partial"}}
    return payload


def partial_outcome(function):
    """Promote partialness from selected trusted projections to the scientific envelope."""
    from functools import wraps

    @wraps(function)
    async def controlled(*args, **kwargs):
        return scientific_status(await function(*args, **kwargs), function.__name__)

    return controlled


class CacheEntry:
    def __init__(self, data, ttl_seconds=3600):
        self.data = deepcopy(data)
        self.expires_at = monotonic() + ttl_seconds

    def is_expired(self):
        return monotonic() > self.expires_at


class BioThingsClient:
    """Shared, sanitized acquisition with embedded-content permission projections."""

    source = ""

    def __init__(self, base_url, timeout=30.0, cache_enabled=True, cache_ttl=3600, rate_limit=10):
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

    async def _request(self, method, endpoint, payload, use_cache):
        key = self._get_cache_key(method, endpoint, params=payload)
        with provider_boundary(self.source):
            entry = self._cache.get(key) if self.cache_enabled and use_cache else None
            if entry is not None and not entry.is_expired():
                try:
                    return permission_projection(
                        self.source, response_contract(method, endpoint, entry.data, payload)
                    )
                except ResearchError:
                    del self._cache[key]
                    raise
            if self.rate_limit:
                async with self._rate_lock:
                    delay = self._next_request - monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    self._next_request = monotonic() + 1.0 / self.rate_limit
            try:
                async with transport.AsyncClient() as client:
                    if method == "GET":
                        response = await client.get(
                            f"{self.base_url}/{endpoint}", params=payload, timeout=self.timeout
                        )
                    else:
                        form = {
                            name: ",".join(value) if isinstance(value, list) else value
                            for name, value in payload.items()
                        }
                        response = await client.post(
                            f"{self.base_url}/{endpoint}", data=form, timeout=self.timeout
                        )
                    response.raise_for_status()
                    data = permission_projection(
                        self.source, response_contract(method, endpoint, response.json(), payload)
                    )
            except (ResearchError, transport.HTTPError, ValueError):
                raise
            except Exception:  # noqa: BLE001 - acquisition errors must be sanitized before SDK logging.
                raise ResearchError(
                    "source_unavailable", "The annotation request could not be completed.", retryable=True
                ) from None
            if self.cache_enabled and use_cache:
                self._cache[key] = CacheEntry(data, self.cache_ttl)
            return deepcopy(data)

    async def get(self, endpoint, params=None):
        return await self._request("GET", endpoint, params, True)

    async def post(self, endpoint, json_data, use_cache=True):
        return await self._request("POST", endpoint, json_data, use_cache)

    async def close(self):
        return None
