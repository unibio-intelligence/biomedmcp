"""SureChEMBL MCP Server - Optimized Python Implementation.

Provides access to SureChEMBL patent chemistry database.
"""

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary, provider_tool_boundary

from .contracts import (
    DOCUMENT_ID,
    MAX_PAGE,
    annotation_workers,
    checked_job_metadata,
    checked_job_status,
    content_window,
    envelope,
    job_control,
    job_hash,
    normalized_document,
    patent_annotations,
    pending_search,
    preflight,
    requested_document,
    statistics,
    structure_window,
)

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query SureChEMBL",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("surechembl")
BASE_URL = "https://www.surechembl.org/api"


async def surechembl_api_request(
    endpoint: str, params: dict | None = None, *, method="GET", body=None
) -> dict:
    """Validate the source envelope before any retained adapter extracts evidence."""
    import re

    modern = (
        method == "POST"
        and endpoint in {"search/content", "search/structure"}
        or method == "GET"
        and re.fullmatch(
            r"(?:search/[0-9a-f-]{36}(?:/(?:status|results))?|document/[A-Z]{2}-[A-Z0-9]+-[A-Z][0-9]?/contents|document/identifier/normalized/[A-Z0-9-]+)",
            endpoint,
        )
    )
    if not modern:
        raise ResearchError(
            "source_unavailable",
            "This SureChEMBL operation remains unavailable until its current source route and eligible response projection are implemented.",
        )
    with provider_boundary("surechembl"):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                f"{BASE_URL}/{endpoint}",
                params=params or {},
                json=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
                if endpoint == "search/content"
                else None,
            )
            response.raise_for_status()
            value = response.json()
            if not endpoint.endswith("/status"):
                envelope(value)
            return value


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def query_patents(
    query: Annotated[str, Field(min_length=1, max_length=2000)],
    query_type: Literal["keyword", "patent_number", "family", "content"] = "keyword",
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    page: Annotated[int, Field(ge=1, le=MAX_PAGE)] = 1,
) -> dict:
    """Search SureChEMBL document metadata. Underlying patent text is unreleased."""
    preflight("query_patents", {"query_type": query_type, "page": page, "limit": limit})
    if query_type != "keyword":
        raise ResearchError(
            "source_unavailable",
            "Exact document and family retrieval requires a qualified current source contract; use an explicit metadata search query.",
        )
    result = await surechembl_api_request(
        "search/content", {"query": query, "page": page, "itemsPerPage": limit}, method="POST"
    )
    return content_window(result, query, page, limit)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def query_chemicals(
    query: str, id_type: Literal["name", "smiles", "inchi", "chemical_id"] = "name", limit: int = 25
) -> dict:
    """Query chemicals by name, structure, or ID."""
    if id_type == "chemical_id":
        endpoint = f"chemical/{query}"
        result = await surechembl_api_request(endpoint)
    elif id_type == "smiles":
        endpoint = "search/chemical"
        params = {"smiles": query, "limit": limit}
        result = await surechembl_api_request(endpoint, params)
    elif id_type == "inchi":
        endpoint = "search/chemical"
        params = {"inchi": query, "limit": limit}
        result = await surechembl_api_request(endpoint, params)
    else:
        endpoint = "search/chemical"
        params = {"q": query, "limit": limit}
        result = await surechembl_api_request(endpoint, params)

    return {"query": query, "id_type": id_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def get_chemical_image(
    chemical_id: str, width: int = 300, height: int = 300, image_format: Literal["svg", "png"] = "svg"
) -> dict:
    """Get chemical structure image."""
    endpoint = f"chemical/{chemical_id}/image"
    params = {"w": width, "h": height, "format": image_format}

    result = await surechembl_api_request(endpoint, params)
    return {"chemical_id": chemical_id, "format": image_format, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def get_chemical_properties(chemical_id: str) -> dict:
    """Get chemical properties and descriptors."""
    endpoint = f"chemical/{chemical_id}/properties"
    result = await surechembl_api_request(endpoint)
    return {"chemical_id": chemical_id, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def export_chemicals(
    query: str,
    output_format: Literal["csv", "xml", "sdf"] = "csv",
    output_type: Literal["compounds", "patents", "both"] = "compounds",
    limit: int = 1000,
) -> dict:
    """Export chemical data in bulk."""
    endpoint = "export/chemicals"
    params = {"q": query, "format": output_format, "type": output_type, "limit": limit}

    result = await surechembl_api_request(endpoint, params)
    return {"query": query, "format": output_format, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def analyze_patent_chemistry(
    patent_number: Annotated[str, Field(min_length=3, max_length=64)],
    analysis_type: Literal["frequency", "categories", "annotations"] = "annotations",
) -> dict:
    """Retrieve source-derived annotation identifiers/positions, category counts or identifier-membership counts. Underlying patent text is excluded; selected sections are not exhaustive chemistry."""
    requested_document(patent_number)
    normalized = patent_number
    if not DOCUMENT_ID.fullmatch(normalized):
        resolved = await surechembl_api_request(f"document/identifier/normalized/{patent_number}")
        normalized = normalized_document(resolved, patent_number)
    source = await surechembl_api_request(f"document/{normalized}/contents", {"annotated": "true"})
    return await annotation_workers.run(patent_annotations, source, patent_number, normalized, analysis_type)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def get_chemical_frequency(chemical_id: str, time_range: str | None = None) -> dict:
    """Get frequency of chemical across patents."""
    endpoint = f"chemical/{chemical_id}/frequency"
    params = {}
    if time_range:
        params["range"] = time_range

    result = await surechembl_api_request(endpoint, params)
    return {"chemical_id": chemical_id, "time_range": time_range, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def search_similar_structures(
    smiles: Annotated[str, Field(min_length=1, max_length=8192)],
    similarity_threshold: Annotated[float, Field(ge=0.5, le=1)] = 0.85,
    limit: Annotated[int, Field(ge=1, le=100)] = 50,
    search_cursor: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve source Tanimoto similarity windows. Resume the returned signed action for queued searches or more pages; no bioactivity inference."""
    preflight(
        "search_similar_structures",
        {
            "smiles": smiles,
            "similarity_threshold": similarity_threshold,
            "limit": limit,
            "search_cursor": search_cursor,
        },
    )
    if search_cursor is None:
        started = await surechembl_api_request(
            "search/structure",
            method="POST",
            body={
                "StructureSearchRequest": {
                    "struct": smiles,
                    "structSearchType": "similarity",
                    "options": f"DISSIMILARITY={1 - float(similarity_threshold):.17g}",
                    "docSectionFilter": "",
                    "chemTermFilter": "",
                    "query": "",
                    "maxResults": limit,
                }
            },
        )
        data = envelope(started)
        if not isinstance(data, dict):
            from biomedmcp.native.shapes import invalid_shape

            invalid_shape()
        control = {"hash": job_hash(data.get("hash")), "page": 1}
    else:
        control = job_control(search_cursor)
    metadata = await surechembl_api_request(f"search/{control['hash']}")
    checked_job_metadata(metadata, smiles)
    status = await surechembl_api_request(f"search/{control['hash']}/status")
    state, count = checked_job_status(status)
    if state != "finished":
        return pending_search(control, smiles, similarity_threshold, state, limit)
    result = await surechembl_api_request(
        f"search/{control['hash']}/results", {"page": control["page"], "max_results": limit}
    )
    payload = structure_window(result, smiles, similarity_threshold, limit, control)
    if count != payload["coverage"]["provider_total"]:
        payload["warnings"].append(
            "Source completion count and result-window total differ; live observations are retained separately."
        )
        payload["completion_result_count"] = count
        payload["section_outcomes"] = {"source_counts": {"outcome": "partial", "sources": ["surechembl"]}}
    return payload


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("surechembl")
async def get_patent_statistics(
    query: Annotated[str, Field(min_length=1, max_length=2000)],
    group_by: Literal["year", "assignee", "class"] = "year",
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    page: Annotated[int, Field(ge=1, le=MAX_PAGE)] = 1,
) -> dict:
    """Count acquired document metadata by publication year or assignee, preserving missingness, window denominators and continuation. Classification is not reported by this response contract."""
    preflight("get_patent_statistics", {"page": page, "limit": limit})
    window = await query_patents(query, limit=limit, page=page)
    return statistics(window, group_by)
