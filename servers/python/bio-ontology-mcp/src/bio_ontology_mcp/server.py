"""BioPortal (NCBO) MCP server: ontology inventory, class pages and mapping assertions.

The credential is read from BIOONTOLOGY_API_KEY and travels only in the
Authorization header. Provider payloads are shape-checked before they are
returned so that a malformed answer is never mistaken for evidence.
"""

import os
from typing import Annotated, Any
from urllib.parse import quote

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary, provider_tool_boundary

try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query BioPortal", read_only_hint=True, open_world_hint=True
    )
except ImportError:  # pragma: no cover
    READ_ONLY_ANNOTATIONS = None

from . import __version__

SOURCE = "bio-ontology"
API_BASE = "https://data.bioontology.org"
TIMEOUT = 30.0
# Tests may pin the credential here; otherwise the environment is consulted per request.
BIOONTOLOGY_API_KEY: str | None = None
MAPPING_NOTE = (
    "Each row is a mapping assertion between classes; equivalence is not assumed. "
    "Read `source` and `process` to see which procedure produced it."
)

mcp = FastMCP("bio-ontology", version=__version__)

Acronym = Annotated[
    str,
    Field(
        description="BioPortal ontology acronym such as GO, NCIT or SNOMEDCT.",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$",
    ),
]
Page = Annotated[int, Field(description="1-based provider page.", ge=1, le=10000)]
PageSize = Annotated[int, Field(description="Rows per page, at most 25.", ge=1, le=25)]


def _api_key() -> str:
    key = BIOONTOLOGY_API_KEY or os.environ.get("BIOONTOLOGY_API_KEY")
    if not key:
        raise ResearchError(
            "source_unavailable",
            "BIOONTOLOGY_API_KEY is not configured; set it in the server environment.",
        )
    return key


async def make_request(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET a BioPortal resource and return its decoded JSON body.

    Failures leave here as framework errors that carry only a classification,
    never the URL, body or credential.
    """
    with provider_boundary(SOURCE):
        headers = {"Authorization": f"apikey token={_api_key()}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(API_BASE + path, params=params or {}, headers=headers)
            response.raise_for_status()
            return response.json()


def _invalid() -> ResearchError:
    return ResearchError(
        "invalid_source_response", "BioPortal returned a payload outside the expected shape."
    )


def _rows(value: Any) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise _invalid()
    return value


def _paged(value: Any, page: int) -> dict:
    if not isinstance(value, dict) or value.get("error") or "collection" not in value:
        raise _invalid()
    rows = _rows(value["collection"])
    page_count = value.get("pageCount")
    if page_count is not None and not isinstance(page_count, int):
        raise _invalid()
    more = page_count is not None and page < page_count
    return {
        "collection": rows,
        "page": page,
        "page_count": page_count,
        "next_page": page + 1 if more else None,
    }


def _slice(rows: list, page: int, pagesize: int) -> tuple[list, int | None]:
    start = (page - 1) * pagesize
    window = rows[start : start + pagesize]
    return window, page + 1 if start + pagesize < len(rows) else None


def _class_path(ontology: str, class_id: str) -> str:
    return f"/ontologies/{ontology}/classes/{quote(class_id, safe='')}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary(SOURCE)
async def search_ontologies(
    query: Annotated[
        str | None,
        Field(
            description="Substring matched case-insensitively against acronym and name.",
            min_length=1,
            max_length=200,
        ),
    ] = None,
    include_views: Annotated[
        bool | None, Field(description="Also list ontology views (subsets) when true.")
    ] = None,
    limit: Annotated[int, Field(description="Rows to return, at most 25.", ge=1, le=25)] = 25,
    offset: Annotated[int, Field(description="Rows to skip in the filtered list.", ge=0, le=10000)] = 0,
) -> dict:
    """List the ontologies hosted on BioPortal, narrowed by acronym or name.

    This reads the ontology inventory, not terms inside ontologies. Filtering
    and offset/limit windowing happen locally over the full inventory.
    """
    params = {"include_views": "true"} if include_views else {}
    rows = _rows(await make_request("/ontologies", params))
    if query:
        needle = query.lower()
        rows = [
            row
            for row in rows
            if needle in str(row.get("acronym", "")).lower() or needle in str(row.get("name", "")).lower()
        ]
    window = rows[offset : offset + limit]
    return {
        "query": query,
        "collection": window,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if offset + limit < len(rows) else None,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary(SOURCE)
async def get_ontology_classes(ontology: Acronym, page: Page = 1, pagesize: PageSize = 25) -> dict:
    """Page through the classes of one ontology as BioPortal serves them.

    Rows keep their original `@id` URI and `prefLabel`; the provider decides
    the ordering, so continue with `next_page` rather than re-sorting.
    """
    value = await make_request(f"/ontologies/{ontology}/classes", {"page": page, "pagesize": pagesize})
    return {"ontology": ontology, **_paged(value, page)}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary(SOURCE)
async def get_class_info(
    ontology: Acronym,
    class_id: Annotated[
        str,
        Field(
            description="Full class URI exactly as the ontology defines it.", min_length=1, max_length=2048
        ),
    ],
    include: Annotated[
        str | None,
        Field(
            description="Attribute names to request, joined with commas, e.g. prefLabel,definition,parents."
        ),
    ] = None,
) -> dict:
    """Fetch one class record from one ontology by its exact URI.

    The URI is percent-encoded into the request path; the returned record is
    the provider's own representation, including `@id`.
    """
    params = {"include": include} if include else {}
    value = await make_request(_class_path(ontology, class_id), params)
    if not isinstance(value, dict) or value.get("error") or "@id" not in value:
        raise _invalid()
    return value


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary(SOURCE)
async def get_mappings(
    ontology: Acronym,
    class_id: Annotated[
        str | None,
        Field(
            description="Restrict to mappings of this class URI; omit for the whole ontology.",
            min_length=1,
            max_length=2048,
        ),
    ] = None,
    page: Page = 1,
    pagesize: PageSize = 25,
) -> dict:
    """Retrieve mapping assertions for an ontology, or for one class in it.

    Whole-ontology mappings are paged by the provider; per-class mappings
    arrive as one list and are windowed locally. `missing_process_count`
    tells how many returned rows lack a generating process.
    """
    if class_id:
        rows, next_page = _slice(
            _rows(await make_request(_class_path(ontology, class_id) + "/mappings")), page, pagesize
        )
        result = {"collection": rows, "page": page, "page_count": None, "next_page": next_page}
    else:
        value = await make_request(f"/ontologies/{ontology}/mappings", {"page": page, "pagesize": pagesize})
        result = _paged(value, page)
    if not all(isinstance(row.get("classes"), list) for row in result["collection"]):
        raise _invalid()
    return {
        "ontology": ontology,
        "class_id": class_id,
        **result,
        "missing_process_count": sum(1 for row in result["collection"] if not row.get("process")),
        "interpretation": MAPPING_NOTE,
    }
