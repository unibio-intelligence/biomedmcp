"""GTEx MCP Server - Provides access to GTEx Portal API v2 data via 5 unified tools."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .config import DEFAULT_DATASET_ID
from .gtex_client import GTExClient
from .unified import UnifiedGTExTools

ProviderPageIndex = Annotated[
    int, Field(ge=0, le=100000, description="Zero-based provider page; follow next_actions.")
]
ResultLimit = Annotated[
    int, Field(ge=1, le=100, description="Requested maximum; acquired pages fit the 25-row public budget.")
]

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query GTEx",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Global client instance
client = GTExClient()
unified = UnifiedGTExTools(client)

# Initialize FastMCP server
mcp = FastMCP(
    "GTEx Portal API",
    instructions="""
    GTEx (Genotype-Tissue Expression) Portal API for gene expression and QTL data.

    IMPORTANT: All gene-related tools accept BOTH gene symbols and GENCODE IDs:
    - Gene symbols (e.g., 'BRCA1', 'TP53') - automatically converted to GENCODE IDs
    - GENCODE IDs are checked against the selected GTEx release

    Use get_metadata(info_type="tissues") to get valid tissue identifiers.
    """,
)


# ============================================================================
# UNIFIED TOOL 1: QUERY_EXPRESSION
# ============================================================================


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def query_expression(
    query_type: str,
    gene_id: str | None = None,
    tissue_id: str | None = None,
    limit: ResultLimit = 50,
    dataset_id: str = DEFAULT_DATASET_ID,
    page: ProviderPageIndex = 0,
) -> dict:
    """
    Query gene expression data across tissues.

    Args:
        query_type: Expression query type:
            - "gene_median": Median expression of a gene across all tissues
            - "gene_tissue": Detailed expression of a gene in specific tissue
            - "top_genes": Most highly expressed genes in a tissue
            - "list_tissues": List all available tissues
        gene_id: Gene symbol (e.g., 'BRCA1') OR GENCODE ID (e.g., 'ENSG00000012048.22')
            Required for: gene_median, gene_tissue
        tissue_id: Tissue identifier (e.g., 'Brain_Cortex', 'Liver', 'Whole_Blood')
            Required for: gene_tissue, top_genes
        limit: Max genes to return for top_genes (default: 50, max: 100)
        page: Zero-based GTEx provider page; follow public next_actions for later windows.
        dataset_id: GTEx dataset (default: 'gtex_v10')

    Returns:
        Expression data based on query_type

    Examples:
        query_expression(query_type="gene_median", gene_id="BRCA1")
        query_expression(query_type="gene_tissue", gene_id="TP53", tissue_id="Brain_Cortex")
        query_expression(query_type="top_genes", tissue_id="Liver", limit=20)
        query_expression(query_type="list_tissues")
    """
    return await unified.query_expression(query_type, gene_id, tissue_id, limit, dataset_id, page)


# ============================================================================
# UNIFIED TOOL 2: QUERY_QTL
# ============================================================================


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def query_qtl(
    qtl_type: str,
    analysis_mode: str,
    tissue_id: str,
    gene_id: str | None = None,
    variant_id: str | None = None,
    p_value_threshold: float | None = None,
    limit: ResultLimit = 50,
    dataset_id: str = DEFAULT_DATASET_ID,
    phenotype_id: str | None = None,
    page: ProviderPageIndex = 0,
) -> dict:
    """
    Query QTL (Quantitative Trait Loci) data - eQTL and sQTL.

    Args:
        qtl_type: QTL type - "eqtl" (expression) or "sqtl" (splicing)
        analysis_mode: Analysis mode:
            - "genes_list": Get genes with QTL associations in tissue
            - "gene_associations": Get QTL associations for specific gene
            - "metasoft": Multi-tissue eQTL analysis (eQTL only)
            - "dynamic": On-demand QTL calculation
        tissue_id: Tissue identifier (e.g., 'Whole_Blood', 'Brain_Cortex')
        gene_id: Gene symbol (e.g., 'BRCA1') OR GENCODE ID (e.g., 'ENSG00000012048.22')
            Required for: gene_associations, metasoft, dynamic
        variant_id: Variant ID for metasoft/dynamic modes
        p_value_threshold: Threshold for genes_list mode
        limit: Max results to return (default: 50)
        page: Zero-based GTEx provider page; follow public next_actions for later windows.
        dataset_id: GTEx dataset (default: 'gtex_v10')
        phenotype_id: Intron identifier from a gene-associated sQTL record; required for dynamic sQTL.

    Returns:
        QTL data based on qtl_type and analysis_mode

    Examples:
        query_qtl(qtl_type="eqtl", analysis_mode="genes_list", tissue_id="Whole_Blood")
        query_qtl(qtl_type="eqtl", analysis_mode="gene_associations", tissue_id="Whole_Blood", gene_id="BRCA1")
        query_qtl(qtl_type="eqtl", analysis_mode="metasoft", tissue_id="Whole_Blood", gene_id="TP53", variant_id="rs1234567")
        query_qtl(qtl_type="sqtl", analysis_mode="dynamic", tissue_id="Muscle_Skeletal", gene_id="BRCA1", variant_id="rs1234567")
    """
    return await unified.query_qtl(
        qtl_type,
        analysis_mode,
        tissue_id,
        gene_id,
        variant_id,
        p_value_threshold,
        limit,
        dataset_id,
        phenotype_id,
        page,
    )


# ============================================================================
# UNIFIED TOOL 3: GET_ANNOTATION
# ============================================================================


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_annotation(
    entity_type: str,
    entity_id: str,
    dataset_id: str = DEFAULT_DATASET_ID,
    page: ProviderPageIndex = 0,
    limit: ResultLimit = 25,
) -> dict:
    """
    Get genomic annotation for genes, transcripts, exons, or variants.

    Args:
        entity_type: Entity type - "gene", "transcript", "exon", or "variant"
        entity_id: Entity identifier:
            - For genes: Gene symbol (e.g., 'BRCA1') OR GENCODE ID
            - For transcripts/exons: Parent gene symbol or GENCODE gene ID
            - For variants: rsID or GRCh38 GTEx variant ID ending in _b38
        dataset_id: GTEx dataset (default: 'gtex_v10')

    Returns:
        Annotation data including coordinates, names, and metadata

    Examples:
        get_annotation(entity_type="gene", entity_id="BRCA1")
        get_annotation(entity_type="transcript", entity_id="BRAF")
        get_annotation(entity_type="exon", entity_id="BRAF")
        get_annotation(entity_type="variant", entity_id="rs1234567")
    """
    return await unified.get_annotation(entity_type, entity_id, dataset_id, page, limit)


# ============================================================================
# UNIFIED TOOL 4: GET_METADATA
# ============================================================================


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_metadata(
    info_type: str, dataset_id: str = DEFAULT_DATASET_ID, page: ProviderPageIndex = 0, limit: ResultLimit = 25
) -> dict:
    """
    Get GTEx system metadata.

    Args:
        info_type: Metadata type:
            - "service": API service information and version
            - "dataset": Dataset release metadata
            - "tissues": List all available GTEx tissues
        dataset_id: GTEx dataset (default: 'gtex_v10')

    Returns:
        Metadata based on info_type

    Examples:
        get_metadata(info_type="service")
        get_metadata(info_type="dataset")
        get_metadata(info_type="tissues")
    """
    return await unified.get_metadata(info_type, dataset_id, page, limit)


# ============================================================================
# UNIFIED TOOL 5: GET_SAMPLE
# ============================================================================


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_sample(
    sample_id: str, dataset_id: str = DEFAULT_DATASET_ID, page: ProviderPageIndex = 0, limit: ResultLimit = 25
) -> dict:
    """
    Get information about a specific GTEx biobank sample.

    Args:
        sample_id: GTEx sample ID (e.g., 'GTEX-1117F-0003-SM-58Q7G')
        dataset_id: GTEx dataset (default: 'gtex_v10')

    Returns:
        Sample metadata including tissue type and subject information

    Example:
        get_sample(sample_id="GTEX-1117F-0003-SM-58Q7G")
    """
    return await unified.get_sample(sample_id, dataset_id, page, limit)


# Run the server
if __name__ == "__main__":
    mcp.run()
