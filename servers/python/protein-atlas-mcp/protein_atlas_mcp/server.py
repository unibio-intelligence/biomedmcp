"""Protein Atlas MCP Server - Optimized Python Implementation.

Provides access to Human Protein Atlas expression and localization data.
"""

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.hpa_records import ensembl_gene, source_record
import asyncio
import json
import re
from typing import Optional, Literal, List
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query Human Protein Atlas",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("protein-atlas")
BASE_URL = "https://www.proteinatlas.org"


async def atlas_api_request(endpoint: str, params: Optional[dict] = None) -> dict:
    """Make request to Protein Atlas API."""
    url = f"{BASE_URL}/{endpoint}"
    with provider_boundary("protein-atlas"):
        if not endpoint.endswith(".xml"):
            raise ResearchError(
                "source_unavailable",
                "Only reviewed exact-gene HPA XML evidence is supported; antibody and search-table response contracts remain unqualified.",
            )
        if endpoint.endswith(".xml"):
            ensembl_gene(endpoint[:-4])
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            if endpoint.endswith(".xml"):
                # A 200 login/error page or a different gene is not evidence.
                # Parsing a normal multi-MiB source record must not block MCP.
                return await asyncio.to_thread(source_record, response.text, endpoint[:-4])
            return {"data": response.text, "status": "success"}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def convert_gene_to_ensembl(gene_symbol: str) -> dict:
    """Convert gene symbol to Ensembl ID for use with other Protein Atlas tools.

    This is a helper tool to find the Ensembl ID for a given gene symbol,
    which is required by most Protein Atlas tools.

    Args:
        gene_symbol: Gene symbol (e.g., 'TP53', 'BRCA1', 'EGFR')

    Returns:
        Dictionary with gene_symbol, ensembl_id, and additional gene info

    Examples:
        # Get Ensembl ID for TP53
        gene_symbol="TP53"

        # Get Ensembl ID for BRCA1
        gene_symbol="BRCA1"
    """
    url = f"{BASE_URL}/search/{gene_symbol}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

        # Extract Ensembl ID from the HTML
        # Look for patterns like ENSG00000141510
        ensembl_pattern = r'ENSG\d{11}'
        matches = re.findall(ensembl_pattern, html)

        if matches:
            ensembl_id = matches[0]  # Take the first match
            return {
                "gene_symbol": gene_symbol,
                "ensembl_id": ensembl_id,
                "status": "success",
                "message": f"Found Ensembl ID for {gene_symbol}"
            }
        else:
            return {
                "gene_symbol": gene_symbol,
                "ensembl_id": None,
                "status": "not_found",
                "message": f"Could not find Ensembl ID for gene symbol: {gene_symbol}"
            }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def query_proteins(
    query: str,
    id_type: Literal["ensembl", "uniprot", "keyword"] = "ensembl",
    include_expression: bool = True,
    include_location: bool = True
) -> dict:
    """Query proteins by Ensembl ID, UniProt ID, or keyword search.

    Note: For gene symbols like 'TP53', use convert_gene_to_ensembl() first
    to get the Ensembl ID, or use id_type='keyword' to search.
    """
    endpoint = f"search/{query}" if id_type == "keyword" else f"{query}.xml"
    params = {} if id_type == "keyword" else {"format": "xml"}
    result = await atlas_api_request(endpoint, params)
    return {"query": query, "id_type": id_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_expression_data(
    ensembl_id: str,
    tissue_type: Literal["all", "tissue", "blood", "brain", "cancer"] = "all",
    expression_level: Optional[Literal["high", "medium", "low"]] = None
) -> dict:
    """Retrieve validated single-gene source XML for expression review.

    This retains the whole source document, not a normalized measurement
    table. Tissue/level selectors are reported as unapplied. Missing source
    annotations do not establish a measured negative result.

    Args:
        ensembl_id: Ensembl gene ID (e.g., 'ENSG00000141510' for TP53)
    """
    endpoint = f"{ensembl_id}.xml"
    params = {"format": "xml"}
    result = await atlas_api_request(endpoint, params)
    return {
        **result,
        "selection": {
            "tissue_type": tissue_type, "expression_level": expression_level,
            "applied": False, "scope": "whole_gene_source_xml",
        },
        "warnings": ["Source XML is retained without tissue/level filtering or normalized measurements."],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def analyze_localization(
    ensembl_id: str,
    include_reliability: bool = True,
    search_by_location: Optional[str] = None
) -> dict:
    """Retrieve validated source XML for subcellular annotation review.

    This does not compute localization or reliability scores. Requested
    selectors are reported explicitly as unapplied to the whole document.

    Args:
        ensembl_id: Ensembl gene ID (e.g., 'ENSG00000141510' for TP53)
    """
    endpoint = f"{ensembl_id}.xml"
    result = await atlas_api_request(endpoint)
    return {
        **result,
        "selection": {
            "include_reliability": include_reliability, "search_by_location": search_by_location,
            "applied": False, "scope": "whole_gene_source_xml",
        },
        "warnings": ["Source XML is retained without localization filtering or derived reliability scores."],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def analyze_disease_association(
    ensembl_id: str,
    analysis_type: Literal["pathology", "cancer_markers", "prognostic"] = "pathology"
) -> dict:
    """Analyze disease associations and cancer markers.

    Args:
        ensembl_id: Ensembl gene ID (e.g., 'ENSG00000141510' for TP53)
    """
    endpoint = f"{ensembl_id}.xml"
    result = await atlas_api_request(endpoint)
    return {"ensembl_id": ensembl_id, "analysis_type": analysis_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_antibody_info(antibody_id: str) -> dict:
    """Get antibody validation and reliability information."""
    endpoint = f"search/{antibody_id}.tsv"
    return await atlas_api_request(endpoint)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def advanced_search(
    search_params: dict,
    columns: Optional[List[str]] = None
) -> dict:
    """Advanced search with custom parameters and column selection."""
    endpoint = "search.tsv"
    params = {"format": "tsv", **search_params}
    return await atlas_api_request(endpoint, params)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def batch_protein_lookup(ensembl_ids: List[str], max_items: int = 50) -> dict:
    """Lookup multiple proteins in batch (max 50).

    Args:
        ensembl_ids: List of Ensembl gene IDs (e.g., ['ENSG00000141510', 'ENSG00000139618'])
    """
    results = []
    for ensembl_id in ensembl_ids[:max_items]:
        try:
            result = await query_proteins(ensembl_id, "ensembl", True, True)
            results.append({"ensembl_id": ensembl_id, "data": result, "success": True})
        except Exception as e:
            results.append({"ensembl_id": ensembl_id, "error": str(e), "success": False})
    return {"total": len(results), "results": results}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def compare_expression_profiles(ensembl_ids: List[str], tissue: Optional[str] = None) -> dict:
    """Retrieve each gene's source annotations for expression-profile review.

    Retains successful peers and explicit failures. No normalized quantitative
    comparison or tissue filtering is computed.

    Args:
        ensembl_ids: List of Ensembl gene IDs (e.g., ['ENSG00000141510', 'ENSG00000139618'])
    """
    if not 1 <= len(ensembl_ids) <= 10 or len(set(ensembl_ids)) != len(ensembl_ids):
        raise ResearchError("invalid_parameters", "Select 1–10 distinct human Ensembl genes.")
    for ensembl_id in ensembl_ids:
        ensembl_gene(ensembl_id)
    results = []
    outcomes = {}
    for ensembl_id in ensembl_ids:
        try:
            result = await get_expression_data(ensembl_id, "all", None)
            results.append({"ensembl_id": ensembl_id, "expression": result})
            outcomes[ensembl_id] = {"outcome": "data"}
        except (ResearchError, ToolError) as e:
            # Each failure is explicit, does not replace successful peers, and
            # prevents this partial comparison from entering the healthy cache.
            error = e.as_dict() if isinstance(e, ResearchError) else json.loads(str(e))
            results.append({"ensembl_id": ensembl_id, "error": error})
            outcomes[ensembl_id] = {"outcome": "error", "error": error}
    return {
        "comparison": "source_annotations", "ensembl_ids": ensembl_ids, "results": results,
        "section_outcomes": outcomes,
        "warnings": [
            "Source XML annotations are retained; no normalized quantitative comparison is computed."
        ] + (["The tissue selector is not applied to the retained source XML."] if tissue else []),
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_protein_classes(include_members: bool = False) -> dict:
    """Get protein classification and family information."""
    endpoint = "search/protein_classes.tsv"
    return await atlas_api_request(endpoint)
