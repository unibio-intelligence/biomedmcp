"""Bounded public website reads; no vendor links are followed."""

import re

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.source_licensing import require_operation

BASE_URL = "https://www.antibodyregistry.org"


class UnifiedAntibodyTools:
    async def query_antibody(self, query_type, query, limit=25, page=1):
        with provider_boundary("antibody-registry"):
            require_operation("antibody-registry", "query_antibody")
            if (
                query_type not in {"search", "details"}
                or not isinstance(query, str)
                or not 1 <= len(query) <= 200
            ):
                raise ResearchError(
                    "invalid_parameters", "Use search text or an antibody registry identifier."
                )
            if (
                type(limit) is not int
                or not 1 <= limit <= 25
                or type(page) is not int
                or not 1 <= page <= 10000
            ):
                raise ResearchError("invalid_parameters", "Invalid antibody page bounds.")
            params = None
            if query_type == "search":
                path = "/api/fts-antibodies"
                params = {"q": query, "page": page, "size": limit}
            else:
                match = re.fullmatch(r"(?:RRID:)?(?:AB_)?([1-9][0-9]{0,15})", query)
                if not match:
                    raise ResearchError("invalid_parameters", "Invalid antibody registry identifier.")
                identifier = match.group(1)
                path = "/api/antibodies/" + identifier
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(BASE_URL + path, params=params)
                response.raise_for_status()
                data = response.json()
            if query_type == "search":
                if (
                    not isinstance(data, dict)
                    or not isinstance(data.get("items"), list)
                    or type(data.get("page")) is not int
                    or data["page"] != page
                    or type(data.get("totalElements")) is not int
                    or data["totalElements"] < len(data["items"])
                    or len(data["items"]) > limit
                ):
                    raise ResearchError("invalid_source_response", "Invalid antibody search page.")
                records = data["items"]
                result = {**data, "next_page": page + 1 if page * limit < data["totalElements"] else None}
            else:
                if not isinstance(data, list) or len(data) > 25:
                    raise ResearchError("invalid_source_response", "Invalid antibody detail collection.")
                records = data
                result = {
                    "requested_rrid": "RRID:AB_" + identifier,
                    "items": records,
                    "identity_status": "not_found"
                    if not records
                    else "exact"
                    if all(str(row.get("abId")) == identifier for row in records if isinstance(row, dict))
                    else "provider_redirect",
                }
            for row in records:
                if (
                    not isinstance(row, dict)
                    or type(row.get("abId")) is not int
                    or row["abId"] <= 0
                    or not isinstance(row.get("abName"), str)
                ):
                    raise ResearchError("invalid_source_response", "Invalid antibody registry identity.")
            result["source"] = "antibody-registry"
            result["access_mode"] = "public website read endpoints; stable API support unqualified"
            result["scientific_limitations"] = (
                "Registry identity and annotations do not establish experimental binding, "
                "specificity or suitability. Missing annotation fields remain unknown."
            )
            return result
