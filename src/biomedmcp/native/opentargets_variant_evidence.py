"""Variant evidence windows retain source measurements and privately scoped cursors."""

import math

from ..errors import ResearchError
from ..runtime import digest
from . import REVISION
from .opentargets_workflows import checked_credible_rows, checked_window, gene
from .shapes import invalid_shape


def cursor_parameter(value):
    if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 8192):
        raise ResearchError("invalid_parameters", "Use the returned bounded evidence continuation.")


def window(payload, identifier, limit, after=None):
    variant = payload["variant"]
    page = variant["evidences"]
    rows = page["rows"]
    following = page["cursor"]
    if (
        variant["id"] != identifier
        or len(rows) > limit
        or len(rows) > page["count"]
        or len({row["id"] for row in rows}) != len(rows)
    ):
        invalid_shape()
    if following is not None and (
        not isinstance(following, str) or not 1 <= len(following) <= 8192 or following == after
    ):
        invalid_shape()
    for row in rows:
        gene(row["target"]["id"], returned=True)
        mantissa, exponent = row["pValueMantissa"], row["pValueExponent"]
        if (
            mantissa is not None
            and exponent is not None
            and (mantissa < 0 or mantissa > 0 and math.log10(mantissa) + exponent > 0)
        ):
            invalid_shape()
        odds = row["oddsRatio"]
        low, high = row["oddsRatioConfidenceIntervalLower"], row["oddsRatioConfidenceIntervalUpper"]
        beta_low, beta_high = row["betaConfidenceIntervalLower"], row["betaConfidenceIntervalUpper"]
        if (
            any(value is not None and value < 0 for value in (odds, low, high))
            or low is not None
            and high is not None
            and low > high
            or beta_low is not None
            and beta_high is not None
            and beta_low > beta_high
        ):
            invalid_shape()
    missing_cursor = after is None and following is None and page["count"] > len(rows)
    result = {
        "record_type": "opentargets_variant_evidence_window",
        "variant": {**variant, "evidences": {key: value for key, value in page.items() if key != "cursor"}},
        "coverage": {
            "provider_total": page["count"],
            "acquired_rows": len(rows),
            "requested_page_size": limit,
            "has_continuation": following is not None,
            "exhaustive": after is None and following is None and page["count"] == len(rows),
            "continuation_status": "provider_token"
            if following is not None
            else "unavailable"
            if missing_cursor
            else "terminal",
        },
        "method": {
            "name": "Retain distinct evidence records selected by the source variant.evidences relation.",
            "inputs": ["/variant/evidences/rows"],
            "variant_relation_basis": "Exact source variant root; the selected evidence projection does not independently report a coordinate/build-qualified allele.",
        },
        "warnings": [
            "Reported association score, beta/interval, odds ratio/interval and p-value fields retain separate source meanings. Missing measurements remain null; no standard error, effect, interval or causal confidence is inferred.",
            "Source variant linkage is not an independently qualified genome-build/allele assertion. Conflicting source records remain distinct.",
            "Coverage applies to this source window; a terminal continuation does not summarize earlier pages. Empty windows do not establish biological absence. Live data are unpinned.",
        ],
    }
    if missing_cursor:
        result["warnings"].append(
            "The first source window is incomplete and has no continuation token; omitted evidence is unavailable."
        )
    if following is not None:
        result["_provider_page"] = {"next_token": following, "raw_count": len(rows)}
    return result, "partial" if missing_cursor else "data"


def credible_window(payload, identifier, limit, page_index):
    variant = payload["variant"]
    if variant["id"] != identifier:
        invalid_shape()
    page = variant["credibleSets"]
    rows = checked_credible_rows(page, limit)
    for row in rows:
        if (
            row["standardError"] is not None
            and row["standardError"] < 0
            or any(row[key] is not None and not 0 <= row[key] <= 1 for key in ("purityMeanR2", "purityMinR2"))
            or row["purityMeanR2"] is not None
            and row["purityMinR2"] is not None
            and row["purityMinR2"] > row["purityMeanR2"]
        ):
            invalid_shape()
    coverage, following = checked_window(page, limit, page_index)
    return {
        "record_type": "opentargets_variant_credible_sets",
        "variant": variant,
        "records": rows,
        "coverage": coverage,
        "continuation_page": following,
        "method": {
            "name": "Retain the source variant.credibleSets relation and each locus's independently reported lead variant and study.",
            "inputs": ["/variant/credibleSets/rows"],
            "variant_relation_basis": "Source locus membership; a locus lead variant may differ from the requested variant. No causal or posterior probability is inferred.",
        },
        "warnings": [
            "Coverage applies to this source window. Missing study or lead-variant metadata remains null; live data are unpinned."
        ],
    }


class VariantContinuation:
    """Reuse the public runtime's signed, account-scoped, expiring cursor store."""

    operation = "query_genetics"
    page_key = "variant_evidence"
    cache_prefix = "opentargets-variant-page:"
    label = "Variant evidence"

    def __init__(self, runtime):
        self.runtime = runtime

    @classmethod
    def binding(cls, params):
        return {
            "source": "opentargets",
            "operation": cls.operation,
            "implementation": REVISION,
            "params": {key: value for key, value in params.items() if key != "evidence_cursor"},
        }

    def preflight(self, params, scope):
        cursor = params.get("evidence_cursor")
        cursor_parameter(cursor)
        return self.runtime.cursors.decode(cursor, query=self.binding(params), scope=scope) if cursor else 0

    async def resume(self, params, scope, position):
        cursor = params.get("evidence_cursor")
        if cursor is None:
            return dict(params), {"windows": 0, "scanned": 0, "seen": []}
        state = await self.runtime.cache.get(self.cache_prefix + digest(cursor))
        if state is None:
            raise ResearchError("expired_cursor", f"{self.label} continuation expired; restart the request.")
        if (
            not isinstance(state, dict)
            or type(state.get("windows")) is not int
            or state["windows"] != position
            or not 1 <= position < 64
            or type(state.get("scanned")) is not int
            or not 0 <= state["scanned"] < 1000
            or not isinstance(state.get("after"), str)
            or not 1 <= len(state["after"]) <= 8192
            or not isinstance(state.get("seen"), list)
            or len(state["seen"]) != position
            or any(not isinstance(value, str) or len(value) != 64 for value in state["seen"])
            or any(character not in "0123456789abcdef" for value in state["seen"] for character in value)
            or len(set(state["seen"])) != position
            or digest(state["after"]) != state["seen"][-1]
        ):
            raise ResearchError(
                "cache_invalid_data",
                f"Stored {self.label.lower()} continuation is invalid; restart the request.",
            )
        return {**params, "evidence_cursor": state["after"]}, state

    async def issue(self, payload, params, scope, state, freshness):
        page = payload.get("_provider_pages", {}).get(self.page_key)
        if page is None:
            return [], None
        count, windows = state["scanned"] + page["raw_count"], state["windows"] + 1
        token_hash = digest(page["next_token"])
        reason = self.boundary(payload, state)
        if reason is not None:
            return [], reason
        cursor = self.runtime.cursors.encode(query=self.binding(params), scope=scope, offset=windows)
        try:
            stored = await self.runtime.cache.put(
                self.cache_prefix + digest(cursor),
                {
                    "after": page["next_token"],
                    "scanned": count,
                    "windows": windows,
                    "seen": [*state["seen"], token_hash],
                },
                3600,
            )
        except ResearchError as error:
            if error.code != "cache_unavailable":
                raise
            return [], "cache_unavailable"
        if not stored:
            return [], "storage_limit"
        action = {
            "tool": "query_source",
            "arguments": {
                "source": "opentargets",
                "operation": self.operation,
                "params": {**params, "evidence_cursor": cursor},
                "freshness": freshness,
            },
        }
        return [action], None

    @classmethod
    def boundary(cls, payload, state):
        page = payload.get("_provider_pages", {}).get(cls.page_key)
        if page is None:
            return None
        if digest(page["next_token"]) in state["seen"]:
            return "provider_cycle"
        if state["scanned"] + page["raw_count"] >= 1000 or state["windows"] + 1 >= 64:
            return "scan_limit"
        return None
