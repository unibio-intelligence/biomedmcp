"""SureChEMBL jobs resume through the shared account/query-scoped cursor store."""

import json

from ..errors import ResearchError
from ..runtime import digest
from . import REVISION


class SearchContinuation:
    operation = "search_similar_structures"
    label = "SureChEMBL search"
    cache_prefix = "surechembl-search-page:"

    def __init__(self, runtime):
        self.runtime = runtime

    @staticmethod
    def binding(params):
        return {
            "source": "surechembl",
            "operation": SearchContinuation.operation,
            "implementation": REVISION,
            "smiles": params["smiles"],
            "threshold": float(params.get("similarity_threshold", 0.85)),
            "limit": params.get("limit", 50),
        }

    def preflight(self, params, scope):
        cursor = params.get("search_cursor")
        return self.runtime.cursors.decode(cursor, query=self.binding(params), scope=scope) if cursor else 0

    async def resume(self, params, scope, position):
        cursor = params.get("search_cursor")
        if cursor is None:
            return dict(params), {"windows": 0, "scanned": 0, "last_page": 0, "hash": None}
        state = await self.runtime.cache.get(self.cache_prefix + digest(cursor))
        if state is None:
            raise ResearchError(
                "expired_cursor", "SureChEMBL continuation expired; restart the original request."
            )
        from surechembl_mcp.contracts import job_control

        if (
            not isinstance(state, dict)
            or type(state.get("windows")) is not int
            or state["windows"] != position
            or not 1 <= position < 64
            or type(state.get("scanned")) is not int
            or not 0 <= state["scanned"] < 1000
            or type(state.get("last_page")) is not int
            or not 0 <= state["last_page"] <= position
        ):
            raise ResearchError("cache_invalid_data", "Stored source search continuation is invalid.")
        try:
            control = job_control(state.get("after"))
            if control["hash"] != state.get("hash") or control["page"] != state["last_page"] + 1:
                raise ValueError("control")
        except (ResearchError, ValueError):
            raise ResearchError(
                "cache_invalid_data", "Stored source search continuation is invalid."
            ) from None
        return {**params, "search_cursor": state["after"]}, state

    @staticmethod
    def partial(payload, reason):
        payload.setdefault("section_outcomes", {})["continuation"] = {"outcome": "partial", "sources": []}
        payload["coverage"]["continuation_status"] = reason

    @staticmethod
    def boundary(payload, state):
        page = payload.get("_provider_pages", {}).get("surechembl_search")
        if page is None:
            return None
        if state["windows"] + 1 >= 64 or state["scanned"] + page["raw_count"] >= 1000:
            return "scan_limit"
        return None

    async def issue(self, payload, params, scope, state, freshness):
        page = payload.get("_provider_pages", {}).get("surechembl_search")
        if page is None:
            return [], None
        reason = self.boundary(payload, state)
        if reason:
            return [], reason
        from surechembl_mcp.contracts import job_control

        control = job_control(page["next_token"])
        if (
            state["hash"] is not None
            and control["hash"] != state["hash"]
            or page["last_page"] < state["last_page"]
            or control["page"] != page["last_page"] + 1
        ):
            raise ResearchError(
                "invalid_source_response", "Source search continuation changed its identity or window."
            )
        cursor = self.runtime.cursors.encode(
            query=self.binding(params), scope=scope, offset=state["windows"] + 1
        )
        try:
            stored = await self.runtime.cache.put(
                self.cache_prefix + digest(cursor),
                {
                    "after": json.dumps(control),
                    "hash": control["hash"],
                    "last_page": page["last_page"],
                    "windows": state["windows"] + 1,
                    "scanned": state["scanned"] + page["raw_count"],
                },
                3600,
            )
        except ResearchError as error:
            if error.code != "cache_unavailable":
                raise
            return [], "cache_unavailable"
        if not stored:
            return [], "storage_limit"
        return [
            {
                "tool": "query_source",
                "arguments": {
                    "source": "surechembl",
                    "operation": self.operation,
                    "params": {**params, "search_cursor": cursor},
                    "freshness": freshness,
                },
            }
        ], None
