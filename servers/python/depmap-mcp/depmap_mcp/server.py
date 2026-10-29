#!/usr/bin/env python3
"""DepMap MCP Server - Cancer Dependency Map gene dependencies.

Provides access to the Cancer Dependency Map (DepMap) API for exploring
gene dependencies, CRISPR screens, drug sensitivities, and cancer cell line data.
"""

import asyncio
from biomedmcp import transport as httpx
from fastmcp import FastMCP

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query DepMap",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Create FastMCP server
mcp = FastMCP("depmap")

# DepMap API base URL
API_BASE = "https://depmap.org/portal/api/v1"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_gene_dependencies(
    gene_symbol: str,
    lineage: str = None,
    effect_threshold: float = -0.5,
    limit: int = 50
) -> dict:
    """
    Search for cell lines dependent on a specific gene.

    Args:
        gene_symbol: Gene symbol (e.g., "TP53", "EGFR")
        lineage: Cancer lineage to filter by (e.g., "lung", "breast")
        effect_threshold: CRISPR effect threshold (more negative = stronger dependency)
        limit: Maximum cell lines to return

    Returns:
        Cell lines with dependency scores and metadata

    Examples:
        search_gene_dependencies(gene_symbol="TP53")
        search_gene_dependencies(gene_symbol="EGFR", lineage="lung", effect_threshold=-1.0)
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search for gene
        url = f"{API_BASE}/genes/search"
        params = {"q": gene_symbol, "limit": 1}
        response = await client.get(url, params=params)
        response.raise_for_status()
        genes = response.json()

        if not genes:
            return {"error": f"Gene {gene_symbol} not found"}

        gene_id = genes[0]["gene_id"]

        # Get dependencies for this gene
        url = f"{API_BASE}/genes/{gene_id}/dependencies"
        params = {"limit": limit}
        if lineage:
            params["lineage"] = lineage

        response = await client.get(url, params=params)
        response.raise_for_status()
        dependencies = response.json()

        # Filter by effect threshold
        filtered = [
            dep for dep in dependencies
            if dep.get("dependency_score", 0) <= effect_threshold
        ]

        return {
            "gene": gene_symbol,
            "gene_id": gene_id,
            "lineage_filter": lineage,
            "threshold": effect_threshold,
            "dependent_cell_lines": filtered[:limit]
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_cell_lines(
    lineage: str = None,
    disease: str = None,
    primary_site: str = None,
    limit: int = 50
) -> dict:
    """
    Search for cancer cell lines by lineage, disease, or tissue.

    Args:
        lineage: Cancer lineage (e.g., "lung", "breast", "colorectal")
        disease: Disease name (e.g., "adenocarcinoma")
        primary_site: Primary tumor site
        limit: Maximum results

    Returns:
        List of matching cell lines with metadata

    Examples:
        search_cell_lines(lineage="lung")
        search_cell_lines(disease="adenocarcinoma", primary_site="lung")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/cell_lines"
        params = {"limit": limit}

        if lineage:
            params["lineage"] = lineage
        if disease:
            params["disease"] = disease
        if primary_site:
            params["primary_site"] = primary_site

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return {
            "filters": {
                "lineage": lineage,
                "disease": disease,
                "primary_site": primary_site
            },
            "cell_lines": data
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_cell_line_info(
    cell_line_name: str
) -> dict:
    """
    Get detailed information about a specific cell line.

    Args:
        cell_line_name: Cell line name (e.g., "A549", "MCF7")

    Returns:
        Cell line metadata including lineage, disease, mutations, and dependencies

    Examples:
        get_cell_line_info(cell_line_name="A549")
        get_cell_line_info(cell_line_name="MCF7")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search for cell line
        url = f"{API_BASE}/cell_lines/search"
        params = {"q": cell_line_name, "limit": 1}
        response = await client.get(url, params=params)
        response.raise_for_status()
        results = response.json()

        if not results:
            return {"error": f"Cell line {cell_line_name} not found"}

        cell_line_id = results[0]["depmap_id"]

        # Get detailed info
        url = f"{API_BASE}/cell_lines/{cell_line_id}"
        response = await client.get(url)
        response.raise_for_status()

        return response.json()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_gene_effect_profile(
    gene_symbol: str,
    dataset: str = "Chronos_Combined"
) -> dict:
    """
    Get gene effect profile across all cell lines.

    Args:
        gene_symbol: Gene symbol (e.g., "TP53")
        dataset: CRISPR dataset (default: "Chronos_Combined")
                Options: "Chronos_Combined", "Achilles"

    Returns:
        Gene effect scores across cell lines

    Examples:
        get_gene_effect_profile(gene_symbol="TP53")
        get_gene_effect_profile(gene_symbol="EGFR", dataset="Achilles")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search for gene
        url = f"{API_BASE}/genes/search"
        params = {"q": gene_symbol, "limit": 1}
        response = await client.get(url, params=params)
        response.raise_for_status()
        genes = response.json()

        if not genes:
            return {"error": f"Gene {gene_symbol} not found"}

        gene_id = genes[0]["gene_id"]

        # Get effect profile
        url = f"{API_BASE}/genes/{gene_id}/effect_profile"
        params = {"dataset": dataset}
        response = await client.get(url, params=params)
        response.raise_for_status()

        return {
            "gene": gene_symbol,
            "gene_id": gene_id,
            "dataset": dataset,
            "profile": response.json()
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def find_selective_dependencies(
    lineage: str,
    effect_threshold: float = -1.0,
    selectivity_threshold: float = 0.3,
    limit: int = 20
) -> dict:
    """
    Find genes selectively essential in a specific cancer lineage.

    Args:
        lineage: Cancer lineage (e.g., "lung", "breast")
        effect_threshold: Dependency score threshold (more negative = stronger)
        selectivity_threshold: Selectivity score (higher = more selective)
        limit: Maximum genes to return

    Returns:
        Genes with selective dependencies in the specified lineage

    Examples:
        find_selective_dependencies(lineage="lung")
        find_selective_dependencies(lineage="breast", effect_threshold=-1.5)
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/genes/selective_dependencies"
        params = {
            "lineage": lineage,
            "effect_threshold": effect_threshold,
            "selectivity_threshold": selectivity_threshold,
            "limit": limit
        }
        response = await client.get(url, params=params)
        response.raise_for_status()

        return {
            "lineage": lineage,
            "thresholds": {
                "effect": effect_threshold,
                "selectivity": selectivity_threshold
            },
            "selective_genes": response.json()
        }


def main():
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
