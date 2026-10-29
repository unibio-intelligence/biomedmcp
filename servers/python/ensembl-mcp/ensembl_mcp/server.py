"""Ensembl MCP Server - Optimized Python Implementation.

Provides access to Ensembl genome browser and annotations with composite tools.
"""

from typing import Literal

from fastmcp import FastMCP

from biomedmcp import transport as httpx
from biomedmcp.errors import invalid_parameters, provider_tool_boundary
from biomedmcp.native.shapes import collection, invalid_shape

from .contracts import (
    consequences,
    gene_tree,
    homology,
    identifier,
    lookup,
    mappings,
    overlap,
    preflight,
    project_assembly,
    project_species,
    sequences,
    species_name,
)

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query Ensembl",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("ensembl")

# Base URL for Ensembl REST API
BASE_URL = "https://rest.ensembl.org"


async def ensembl_api_request(
    endpoint: str, params: dict | None = None, content_type: str = "application/json"
) -> dict:
    """Make request to Ensembl REST API with error handling."""
    url = f"{BASE_URL}/{endpoint}"
    headers = {"Content-Type": content_type}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params or {}, headers=headers)
        response.raise_for_status()
        if "json" in content_type:
            return response.json()
        return {"data": response.text}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def query_genes(
    query: str,
    query_type: Literal["id", "name", "symbol"] = "symbol",
    species: str = "homo_sapiens",
    expand: bool = False,
    include_transcripts: bool = False,
) -> dict:
    """Query genes by ID, name, or symbol with optional transcript data.

    Args:
        query: Gene ID, name, or symbol (e.g., BRCA2, ENSG00000139618)
        query_type: Type of query (id for Ensembl ID, name/symbol for gene name)
        species: Species name (default: homo_sapiens)
        expand: Include expanded gene details
        include_transcripts: Include all transcripts for the gene

    Returns:
        Gene information with optional transcript data

    Examples:
        # Query BRCA2 gene by symbol
        "BRCA2", query_type="symbol", species="homo_sapiens"

        # Query by Ensembl ID with transcripts
        "ENSG00000139618", query_type="id", include_transcripts=True
    """
    preflight("query_genes", {"query": query, "query_type": query_type, "species": species})
    species = species_name(species)
    if query_type == "id":
        endpoint = f"lookup/id/{query.split('.')[0]}"
    else:
        endpoint = f"lookup/symbol/{species}/{query}"
    expanded = expand or include_transcripts
    result = lookup(
        await ensembl_api_request(endpoint, {"expand": int(expanded)}),
        species,
        expected=query if query_type == "id" else None,
        gene_only=True,
        expanded=expanded,
    )
    if include_transcripts:
        result["transcripts"] = result["Transcript"]
    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def get_sequences(
    gene_id: str,
    sequence_type: Literal["genomic", "cds", "cdna", "protein"] = "genomic",
    species: str = "homo_sapiens",
    output_format: Literal["json", "fasta"] = "json",
) -> dict:
    """Get DNA or protein sequences for genes and transcripts.

    Args:
        gene_id: Ensembl gene or transcript ID
        sequence_type: Type of sequence to retrieve
        species: Species name
        output_format: Output format (json or fasta)

    Returns:
        Sequence data in requested format

    Examples:
        # Get genomic sequence for BRCA2
        "ENSG00000139618", sequence_type="genomic"

        # Get protein sequence in FASTA format
        "ENSG00000139618", sequence_type="protein", output_format="fasta"
    """
    identifier(gene_id)
    species = species_name(species)
    identity = lookup(
        await ensembl_api_request(f"lookup/id/{gene_id.split('.')[0]}"), species, expected=gene_id
    )
    if identity["object_type"] == "Translation" and sequence_type != "protein":
        raise invalid_parameters()
    rows = sequences(
        await ensembl_api_request(
            f"sequence/id/{identity['id']}", {"type": sequence_type, "multiple_sequences": "1"}
        ),
        identity,
        sequence_type,
    )
    result = {
        "query": identity,
        "sequence_type": sequence_type,
        "output_format": output_format,
        "sequences": rows,
    }
    if output_format == "fasta":
        # Render from validated source records; never pass unvalidated FASTA.
        result["data"] = "".join(
            f">{r['id']}.{r['version']}\n"
            + "\n".join(r["seq"][i : i + 80] for i in range(0, len(r["seq"]), 80))
            + "\n"
            for r in rows
        )
        result["format_origin"] = "derived_from_validated_json"
    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def analyze_evolution(
    gene_id: str,
    analysis_type: Literal["homologs", "orthologs", "paralogs", "gene_tree"] = "homologs",
    target_species: str | None = None,
    sequence_type: Literal["protein", "cdna"] = "protein",
    species: str = "homo_sapiens",
) -> dict:
    """Analyze evolutionary relationships and gene trees.

    Args:
        gene_id: Ensembl gene ID
        analysis_type: Type of evolutionary analysis
        target_species: Target species for homology (optional)
        sequence_type: Sequence type for homology
        species: Species of the submitted gene

    Returns:
        Evolutionary analysis results
    """
    preflight(
        "analyze_evolution",
        {
            "gene_id": gene_id,
            "species": species,
            "analysis_type": analysis_type,
            "target_species": target_species,
        },
    )
    species = species_name(species)
    identity = lookup(
        await ensembl_api_request(f"lookup/id/{gene_id.split('.')[0]}"),
        species,
        expected=gene_id,
        gene_only=True,
    )
    if analysis_type == "gene_tree":
        result = gene_tree(
            await ensembl_api_request(
                f"genetree/member/id/{species}/{identity['id']}", {"sequence": sequence_type}
            ),
            identity,
        )
        return {
            "query": identity,
            "sequence_type": sequence_type,
            "source_sequence_semantics": "coding_dna" if sequence_type == "cdna" else "protein",
            "gene_tree": result,
        }
    target_species = species_name(target_species) if target_species else None
    params = {
        "type": {"homologs": "all", "orthologs": "orthologues", "paralogs": "paralogues"}[analysis_type],
        "sequence": sequence_type,
        "format": "full",
    }
    if target_species:
        params["target_species"] = target_species
    result = homology(
        await ensembl_api_request(f"homology/id/{species}/{identity['id']}", params),
        identity,
        analysis_type,
        target_species,
    )
    return {
        "query": identity,
        "sequence_type": sequence_type,
        "source_sequence_semantics": "coding_dna" if sequence_type == "cdna" else "protein",
        "homology": result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def analyze_variants(
    region_or_id: str,
    analysis_type: Literal["variants", "consequences"] = "variants",
    species: str = "homo_sapiens",
) -> dict:
    """Analyze genetic variants and their consequences.

    Args:
        region_or_id: Genomic region (chr:start-end) or variant ID
        analysis_type: Type of variant analysis
        species: Species name

    Returns:
        Variant data and consequences
    """
    preflight(
        "analyze_variants", {"region_or_id": region_or_id, "analysis_type": analysis_type, "species": species}
    )
    species = species_name(species)
    if analysis_type == "consequences":
        return {
            "species": species,
            "records": consequences(
                await ensembl_api_request(f"vep/{species}/id/{region_or_id}"), region_or_id
            ),
        }
    return {
        "species": species,
        "region": region_or_id,
        "records": overlap(
            await ensembl_api_request(f"overlap/region/{species}/{region_or_id}", {"feature": "variation"}),
            region_or_id,
            {"variation"},
        ),
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def get_regulatory_elements(
    region: str, element_type: Literal["regulatory", "motif", "both"] = "both", species: str = "homo_sapiens"
) -> dict:
    """Get regulatory features and motifs for a genomic region.

    Args:
        region: Genomic region (chr:start-end)
        element_type: Type of regulatory elements
        species: Species name

    Returns:
        Regulatory element data
    """
    preflight("get_regulatory_elements", {"region": region, "species": species})
    species = species_name(species)
    features = ["regulatory", "motif"] if element_type == "both" else [element_type]
    result = overlap(
        await ensembl_api_request(f"overlap/region/{species}/{region}", {"feature": features}),
        region,
        set(features),
    )
    return {"species": species, "region": region, "records": result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def get_genome_info(
    info_type: Literal["species", "assembly", "karyotype"] = "assembly", species: str = "homo_sapiens"
) -> dict:
    """Get genome assembly and species information.

    Args:
        info_type: Type of genome information
        species: Species name (not used for species list)

    Returns:
        Genome information
    """
    species = species_name(species)
    if info_type == "species":
        return project_species(await ensembl_api_request("info/species"))
    # Karyotype names are part of the assembly response. The extra path
    # component would request a sequence region literally named "karyotype".
    result = project_assembly(await ensembl_api_request(f"info/assembly/{species}"))
    if info_type == "karyotype":
        return {
            "species": species,
            "assembly_name": result["assembly_name"],
            "karyotype": result["karyotype"],
            "assembly": result,
        }
    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def get_xrefs(gene_id: str, external_db: str | None = None, species: str = "homo_sapiens") -> dict:
    """Get cross-references to external databases.

    Args:
        gene_id: Ensembl gene ID
        external_db: Filter by external database name (e.g., HGNC, UniProt)
        species: Species name

    Returns:
        Cross-reference data
    """
    preflight("get_xrefs", {"gene_id": gene_id, "species": species, "external_db": external_db})
    species = species_name(species)
    identity = lookup(
        await ensembl_api_request(f"lookup/id/{gene_id.split('.')[0]}"), species, expected=gene_id
    )
    endpoint = f"xrefs/id/{identity['id']}"
    params = {}
    if external_db:
        params["external_db"] = external_db

    rows = collection(await ensembl_api_request(endpoint, params), ())
    for row in rows:
        if any(not isinstance(row.get(key), str) or not row[key] for key in ("primary_id", "dbname")):
            invalid_shape()
        if external_db and row["dbname"] != external_db:
            invalid_shape()
    return {"query": identity, "records": rows}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def map_coordinates(
    region: str, source_assembly: str, target_assembly: str, species: str = "homo_sapiens"
) -> dict:
    """Map coordinates between genome assemblies.

    Args:
        region: Genomic region (chr:start-end)
        source_assembly: Source assembly name (e.g., GRCh37)
        target_assembly: Target assembly name (e.g., GRCh38)
        species: Species name

    Returns:
        Mapped coordinates
    """
    preflight(
        "map_coordinates",
        {
            "region": region,
            "source_assembly": source_assembly,
            "target_assembly": target_assembly,
            "species": species,
        },
    )
    species = species_name(species)
    endpoint = f"map/{species}/{source_assembly}/{region}/{target_assembly}"
    result = mappings(await ensembl_api_request(endpoint), region, source_assembly, target_assembly)
    return {
        "species": species,
        "region": region,
        "source_assembly": source_assembly,
        "target_assembly": target_assembly,
        **result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("ensembl")
async def batch_gene_lookup(gene_ids: list[str], species: str = "homo_sapiens", expand: bool = False) -> dict:
    """Lookup multiple genes in batch.

    Args:
        gene_ids: List of Ensembl gene IDs (max 1000)
        species: Species name
        expand: Include expanded details

    Returns:
        Batch lookup results
    """
    preflight("batch_gene_lookup", {"gene_ids": gene_ids, "species": species})
    species = species_name(species)
    endpoint = "lookup/id"
    params = {"species": species}
    if expand:
        params["expand"] = "1"

    # POST request for batch
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/{endpoint}",
            json={"ids": gene_ids},
            params=params,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict) or set(result) != set(gene_ids):
        invalid_shape()
    for gene_id, record in result.items():
        if record is not None:
            lookup(record, species, expected=gene_id, gene_only=True, expanded=expand)
    missing = [gene_id for gene_id, record in result.items() if record is None]
    return {
        "species": species,
        "records": [record for record in result.values() if record is not None],
        "source_response": result,
        "section_outcomes": {gene_id: {"outcome": "unavailable"} for gene_id in missing},
        "warnings": [
            "Null batch lookups do not distinguish a missing identifier from an upstream lookup failure."
        ]
        if missing
        else [],
    }
