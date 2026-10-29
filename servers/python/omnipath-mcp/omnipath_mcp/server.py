#!/usr/bin/env python3
"""OmniPath MCP Server - Protein interactions and signaling pathways.

Provides access to the OmniPath database for protein-protein interactions,
signaling pathways, enzyme-substrate relationships, ligand-receptor interactions,
and transcription factor regulation.
"""

import asyncio
from biomedmcp import transport as httpx
from fastmcp import FastMCP

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query OmniPath",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Create FastMCP server
mcp = FastMCP("omnipath")

# OmniPath API base URL
API_BASE = "https://omnipathdb.org"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_interactions(
    proteins: str = None,
    sources: str = None,
    types: str = None,
    datasets: str = None,
    limit: int = 500
) -> dict:
    """
    Get protein-protein interactions from OmniPath.

    Args:
        proteins: Protein gene symbols or UniProt IDs (comma-separated for multiple)
        sources: Data sources to include (e.g., "SignaLink,PhosphoSite")
        types: Interaction types (e.g., "post_translational", "transcriptional")
        datasets: Datasets to query (e.g., "omnipath", "kinaseextra", "ligrecextra")
        limit: Maximum interactions to return (default: 500)

    Returns:
        List of protein-protein interactions with directionality and sources

    Examples:
        get_interactions(proteins="TP53")
        get_interactions(proteins="EGFR,ERBB2", types="post_translational")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/interactions"
        params = {"format": "json"}

        if proteins:
            params["proteins"] = proteins
        if sources:
            params["sources"] = sources
        if types:
            params["types"] = types
        if datasets:
            params["datasets"] = datasets

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Limit results
        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "interactions": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_enzyme_substrate(
    enzyme: str = None,
    substrate: str = None,
    modification: str = None,
    limit: int = 500
) -> dict:
    """
    Get enzyme-substrate relationships (phosphorylation, ubiquitination, etc.).

    Args:
        enzyme: Enzyme gene symbol or UniProt ID
        substrate: Substrate gene symbol or UniProt ID
        modification: Modification type (e.g., "phosphorylation", "ubiquitination")
        limit: Maximum results

    Returns:
        Enzyme-substrate relationships with modification sites and residues

    Examples:
        get_enzyme_substrate(enzyme="CDK1")
        get_enzyme_substrate(substrate="TP53", modification="phosphorylation")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/enzsub"
        params = {"format": "json"}

        if enzyme:
            params["enzymes"] = enzyme
        if substrate:
            params["substrates"] = substrate
        if modification:
            params["modifications"] = modification

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "relationships": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_ligand_receptor(
    ligand: str = None,
    receptor: str = None,
    sources: str = None,
    limit: int = 500
) -> dict:
    """
    Get ligand-receptor interactions for cell communication.

    Args:
        ligand: Ligand gene symbol
        receptor: Receptor gene symbol
        sources: Data sources (e.g., "CellPhoneDB,CellChatDB")
        limit: Maximum interactions

    Returns:
        Ligand-receptor pairs with annotations and sources

    Examples:
        get_ligand_receptor(ligand="VEGFA")
        get_ligand_receptor(receptor="EGFR")
        get_ligand_receptor(ligand="IL6", receptor="IL6R")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/intercell"
        params = {"format": "json", "categories": "ligand,receptor"}

        if ligand:
            params["proteins"] = ligand
        if receptor:
            params["proteins"] = receptor if not ligand else f"{ligand},{receptor}"
        if sources:
            params["sources"] = sources

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "ligand_receptor_pairs": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_tf_targets(
    transcription_factor: str = None,
    target: str = None,
    dorothea_confidence: str = None,
    limit: int = 500
) -> dict:
    """
    Get transcription factor regulatory relationships.

    Args:
        transcription_factor: TF gene symbol (e.g., "TP53", "MYC")
        target: Target gene symbol
        dorothea_confidence: DoRothEA confidence level ("A", "B", "C", "D", "E")
        limit: Maximum results

    Returns:
        TF-target gene relationships with confidence scores

    Examples:
        get_tf_targets(transcription_factor="TP53")
        get_tf_targets(target="CDKN1A", dorothea_confidence="A")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/tf_target"
        params = {"format": "json"}

        if transcription_factor:
            params["tfs"] = transcription_factor
        if target:
            params["targets"] = target
        if dorothea_confidence:
            params["dorothea_levels"] = dorothea_confidence

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "tf_target_pairs": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_mirna_targets(
    mirna: str = None,
    target: str = None,
    limit: int = 500
) -> dict:
    """
    Get miRNA-target gene relationships.

    Args:
        mirna: miRNA identifier (e.g., "hsa-miR-21")
        target: Target gene symbol
        limit: Maximum results

    Returns:
        miRNA-target relationships with evidence

    Examples:
        get_mirna_targets(mirna="hsa-miR-21")
        get_mirna_targets(target="PTEN")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/mirna_target"
        params = {"format": "json"}

        if mirna:
            params["mirnas"] = mirna
        if target:
            params["targets"] = target

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "mirna_target_pairs": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_complexes(
    protein: str = None,
    sources: str = None,
    limit: int = 100
) -> dict:
    """
    Get protein complex information.

    Args:
        protein: Protein gene symbol to find complexes for
        sources: Data sources (e.g., "CORUM,ComplexPortal")
        limit: Maximum complexes

    Returns:
        Protein complexes with member proteins

    Examples:
        get_complexes(protein="TP53")
        get_complexes(protein="BRCA1", sources="CORUM")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/complexes"
        params = {"format": "json"}

        if protein:
            params["proteins"] = protein
        if sources:
            params["sources"] = sources

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = data[:limit] if isinstance(data, list) else data

        return {
            "query": params,
            "count": len(results) if isinstance(results, list) else 1,
            "complexes": results
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_annotations(
    protein: str,
    annotation_type: str = None
) -> dict:
    """
    Get protein annotations and classifications.

    Args:
        protein: Protein gene symbol or UniProt ID
        annotation_type: Annotation type (e.g., "pathway", "function", "location")

    Returns:
        Protein annotations from multiple databases

    Examples:
        get_annotations(protein="EGFR")
        get_annotations(protein="TP53", annotation_type="pathway")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{API_BASE}/annotations"
        params = {"format": "json", "proteins": protein}

        if annotation_type:
            params["types"] = annotation_type

        response = await client.get(url, params=params)
        response.raise_for_status()

        return {
            "protein": protein,
            "annotations": response.json()
        }


def main():
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
