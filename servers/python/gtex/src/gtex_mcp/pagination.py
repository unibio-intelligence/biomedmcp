"""Bound GTEx acquisition while preserving raw windows and recoverable provider pages."""

from biomedmcp.errors import ResearchError
from biomedmcp.pagination import MAX_PROVIDER_PAGE, PAGE_LIMIT_WARNING, ProviderPage, page_continuation
from biomedmcp.runtime import digest

PUBLIC_ROW_LIMIT = 25
MAX_SCAN_PAGES = 3
MAX_PAGE = MAX_PROVIDER_PAGE


def page_parameters(page, limit):
    if type(page) is not int or not 0 <= page <= MAX_PAGE or type(limit) is not int or not 1 <= limit <= 100:
        raise ResearchError("invalid_parameters", "Use a bounded GTEx page and result limit.")
    return {"page": page, "limit": min(limit, PUBLIC_ROW_LIMIT)}


async def collect(fetch, *, page=0, limit=25, threshold=None, measure="pValue", annotate=None):
    options = page_parameters(page, limit)
    if threshold is not None and (type(threshold) not in (int, float) or not 0 < threshold <= 1):
        raise ResearchError(
            "invalid_parameters", "Use a finite p-value threshold greater than zero and at most one."
        )
    raw_count, filtered = 0, 0
    visited = []
    result = None
    visible = []
    more = False
    provider_size = None
    for index in range(page, min(page + MAX_SCAN_PAGES, MAX_PAGE + 1)):
        result = await fetch(**{**options, "page": index})
        paging = result["paging_info"]
        if provider_size is not None and paging["maxItemsPerPage"] != provider_size:
            raise ResearchError("invalid_source_response", "GTEx changed its page width during acquisition.")
        provider_size = paging["maxItemsPerPage"]
        options["limit"] = provider_size
        rows = result["data"]
        if annotate is not None:
            response_sha256 = digest(result)
            rows = [
                annotate(row, page=paging["page"], row_index=i, response_sha256=response_sha256)
                for i, row in enumerate(rows)
            ]
        raw_count += len(rows)
        visited.append(index)
        visible = rows if threshold is None else [row for row in rows if row[measure] <= threshold]
        filtered += len(rows) - len(visible)
        more = index + 1 < paging["numberOfPages"]
        # Only skip wholly filtered windows: consuming overflow from a partially
        # visible window would require retaining it in continuation state.
        if visible or not more:
            break
    paging = result["paging_info"]
    next_page = paging["page"] + 1 if more else None
    accessible_page, boundary = page_continuation(next_page)
    coverage = ProviderPage(
        raw_count=raw_count,
        filtered_count=filtered,
        filtering={"p_value": filtered} if threshold is not None else {},
        total=paging["totalNumberOfItems"],
        exhausted=not more,
        next_offset=next_page,
        exhaustion_basis="provider",
        sort_scope="provider",
    )
    output = {
        **result,
        "data": visible,
        "_provider_page": coverage.model_dump(),
        "coverage": {
            **coverage.public_metadata(),
            "position_unit": "provider_page",
            "start_page": page,
            "pages_fetched": visited,
            "next_page": accessible_page,
            **boundary,
            "requested_limit": limit,
            "effective_page_size": options["limit"],
            "p_value_filter": None
            if threshold is None
            else {"measure": measure, "maximum": threshold, "scope": "acquired provider windows"},
        },
    }
    if more:
        output["warnings"] = [
            PAGE_LIMIT_WARNING
            if boundary
            else "This is a bounded GTEx window; follow the provided continuation to retrieve later records."
        ]
    if boundary or not visible and more:
        output["section_outcomes"] = {"window": {"outcome": "partial", "sources": ["gtex"]}}
    return output
