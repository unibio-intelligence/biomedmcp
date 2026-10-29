"""Dated official trial contracts plus identity and scientific-domain checks."""

import json
import math
import re
from importlib.resources import files

from jsonschema import Draft202012Validator

from biomedmcp.errors import ResearchError

CONTRACT = json.loads(files("clinical_trials_mcp").joinpath("contracts.json").read_text())
PHASES = frozenset(CONTRACT["components"]["schemas"]["Phase"]["enum"])
STATUSES = frozenset(CONTRACT["components"]["schemas"]["Status"]["enum"])

VALIDATORS = {
    name: Draft202012Validator({**schema, "components": CONTRACT["components"]})
    for name, schema in CONTRACT["responses"].items()
}
REQUESTS = {
    name: Draft202012Validator({**schema, "components": CONTRACT["components"]})
    for name, schema in CONTRACT["requests"].items()
}


def invalid():
    raise ResearchError(
        "invalid_source_response", "ClinicalTrials.gov returned an invalid scientific response."
    )


def nct(value):
    if not isinstance(value, str) or not re.fullmatch(r"NCT\d{8}", value) or value == "NCT00000000":
        raise ResearchError("invalid_parameters", "Use a complete ClinicalTrials.gov NCT identifier.")
    return value


def validate_query_scope(queries, *, filtered):
    # The dated provider contract explicitly ignores filters for NCT-only
    # query parameters. Never silently return an unfiltered scientific scope.
    if filtered and any(
        isinstance(value, str)
        and re.fullmatch(
            r"\s*NCT0*[1-9]\d{0,7}(?:[\s,]+NCT0*[1-9]\d{0,7})*\s*", value, re.IGNORECASE
        )
        for value in queries
    ):
        raise ResearchError(
            "invalid_parameters",
            "ClinicalTrials.gov ignores filters for identifier-only queries; retrieve NCT records directly or use a topical search.",
        )


def validate_request(name, params):
    schema = CONTRACT["requests"][name]
    normalized = {
        key: re.split(r"[,|]", value)
        if schema["properties"].get(key, {}).get("type") == "array" and isinstance(value, str)
        else value
        for key, value in params.items()
    }
    if next(REQUESTS[name].iter_errors(normalized), None) is not None:
        raise ResearchError(
            "invalid_provider_request", "Trial acquisition parameters violate the provider contract."
        )
    if "pageSize" in params and (type(params["pageSize"]) is not int or not 1 <= params["pageSize"] <= 100):
        raise ResearchError("invalid_parameters", "Trial page size must be 1–100.")
    if "pageToken" in params and (
        not isinstance(params["pageToken"], str) or not 1 <= len(params["pageToken"]) <= 8192
    ):
        raise ResearchError("invalid_parameters", "Trial continuation token is invalid.")
    if name == "search":
        validate_query_scope(
            [value for key, value in params.items() if key.startswith("query.")],
            filtered=any(key.startswith(("filter.", "postFilter.")) for key in params),
        )


def scientific_values(value):
    if isinstance(value, dict):
        if any(key in value for key in ("error", "errors")):
            invalid()
        for key, item in value.items():
            if key == "count" and (type(item) is not int or item < 0):
                invalid()
            if key == "lat" and (type(item) not in (int, float) or not -90 <= item <= 90):
                invalid()
            if key == "lon" and (type(item) not in (int, float) or not -180 <= item <= 180):
                invalid()
            scientific_values(item)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and not item:
                invalid()
            scientific_values(item)
    elif isinstance(value, float) and not math.isfinite(value):
        invalid()


def validate_response(name, payload, *, params=None, requested_id=None):
    if next(VALIDATORS[name].iter_errors(payload), None) is not None:
        invalid()
    scientific_values(payload)
    rows = payload["studies"] if name == "search" else [payload]
    params = params or {}
    ids = []
    for row in rows:
        protocol = row.get("protocolSection")
        identity = protocol.get("identificationModule") if isinstance(protocol, dict) else None
        if not isinstance(identity, dict):
            invalid()
        try:
            canonical = nct(identity.get("nctId"))
            aliases = [nct(value) for value in identity.get("nctIdAliases", [])]
        except ResearchError:
            invalid()
        if requested_id is not None and requested_id not in [canonical, *aliases]:
            invalid()
        if name == "search":
            statuses = params.get("filter.overallStatus")
            if statuses:
                allowed = re.split(r"[,|]", statuses) if isinstance(statuses, str) else statuses
                if protocol.get("statusModule", {}).get("overallStatus") not in allowed:
                    invalid()
            phase = re.fullmatch(r"AREA\[Phase\](\w+)", params.get("filter.advanced", ""))
            if phase and phase[1] not in protocol.get("designModule", {}).get("phases", []):
                invalid()
        ids.append(canonical)
    if len(set(ids)) != len(ids):
        invalid()
    if name == "search":
        if len(rows) > params.get("pageSize", 100):
            invalid()
        total = payload.get("totalCount")
        if total is not None and (type(total) is not int or total < len(rows)):
            invalid()
        if total is not None and not params.get("pageToken"):
            has_next = "nextPageToken" in payload
            if has_next != (total > len(rows)):
                invalid()
        if "nextPageToken" in payload:
            token = payload["nextPageToken"]
            if not isinstance(token, str) or not 1 <= len(token) <= 8192 or token == params.get("pageToken"):
                invalid()
    return payload
