"""Antibody Registry MCP Server

A Model Context Protocol (MCP) server that provides access to the Antibody Registry database.
This server enables searching for antibodies and retrieving detailed information about specific antibodies.
"""

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from .unified import UnifiedAntibodyTools

# Import ToolAnnotations for compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query Antibody Registry",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Create the MCP server
mcp = FastMCP("antibody-registry")

# Create unified tools instance
unified = UnifiedAntibodyTools()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def query_antibody(
    query_type: Literal["search", "details"],
    query: Annotated[str, Field(min_length=1, max_length=200)],
    limit: Annotated[int, Field(ge=1, le=25)] = 25,
    page: Annotated[int, Field(ge=1, le=10000)] = 1,
) -> dict:
    """
    Query the Antibody Registry for antibodies or get details for a specific antibody.

    Args:
        query_type: Type of query - "search" or "details"
            - "search": Search for antibodies by gene symbol, protein name, or UniProt ID
            - "details": Get detailed information for a specific antibody by its ID
        query: Query string
            - For search: Gene symbol (e.g., 'BRCA1'), protein name, or UniProt ID (e.g., 'P38398')
            - For details: Antibody ID (e.g., '2722030') from the 'abId' field in search results
        limit: Maximum number of results per page (1-25, default: 25). Only for search queries.
        page: Page number for pagination (default: 1). Only for search queries.

    Returns:
        Search results or antibody details. Search results include page, totalElements, and items.

    Examples:
        query_antibody(query_type="search", query="BRCA1")
        query_antibody(query_type="search", query="BRCA1", limit=10, page=2)
        query_antibody(query_type="search", query="P38398")
        query_antibody(query_type="details", query="2722030")
    """
    return await unified.query_antibody(query_type, query, limit=limit, page=page)


def main():
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
