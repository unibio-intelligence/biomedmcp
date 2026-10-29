"""
Unified GTEx MCP Tools - Consolidates 17 tools into 5 flexible, parameter-driven tools.

This module provides high-level tools with universal gene name support and
parameter-based routing to underlying GTEx API client methods.
"""

from typing import Any

from fastmcp.exceptions import ToolError

from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.expression_records import expression_window
from biomedmcp.qtl_records import gene_identity, qtl_record
from biomedmcp.runtime import digest

from .config import DEFAULT_DATASET_ID
from .gtex_client import GTExClient
from .identity import GENOME_BUILD, release_parameters, variant_selector
from .pagination import collect, page_parameters


class UnifiedGTExTools:
    """
    Five unified tools that replace all 17 granular GTEx tools through parameter-based flexibility.
    All gene-related tools accept both gene symbols and GENCODE IDs.
    """

    def __init__(self, client: GTExClient):
        self.client = client

    async def _gene_window(self, fetch, gencode_id, dataset_id, **options):
        return {
            **await collect(fetch, **options),
            "gene_identity": {
                "gencode_id": gencode_id,
                "dataset_id": dataset_id,
                "gencode_version": release_parameters(dataset_id)["gencodeVersion"],
                "genome_build": GENOME_BUILD,
            },
        }

    async def _resolve_variant(self, identifier, dataset_id):
        selector = variant_selector(identifier)
        result = await self.client.get_variant_info(identifier, dataset_id, page=0, limit=25)
        if result["paging_info"]["totalNumberOfItems"] > len(result["data"]):
            raise ToolError("GTEx variant identity requires a complete reference result.")
        field, expected = next(iter(selector.items()))
        matches = [row for row in result["data"] if row[field] == expected]
        identities = {row["variantId"] for row in matches}
        if len(identities) != 1:
            raise ToolError("GTEx variant identity is unavailable or ambiguous for this release.")
        row = matches[0]
        return {
            "variant_id": row["variantId"],
            "snp_id": row["snpId"] or None,
            "dataset_id": dataset_id,
            "genome_build": GENOME_BUILD,
            "chromosome": row["chromosome"],
            "position": row["pos"],
            "reference": row["ref"],
            "alternate": row["alt"],
        }

    async def _resolve_gene_id(self, gene_identifier: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
        """
        Resolve gene identifier to GENCODE ID.

        Validate symbols and stable/versioned identifiers against the selected
        release, and require one exact matching GENCODE identity.

        Args:
            gene_identifier: Either a gene symbol (e.g., 'BRCA1') or GENCODE ID (e.g., 'ENSG00000012048.22')
            dataset_id: GTEx dataset identifier

        Returns:
            GENCODE ID (e.g., 'ENSG00000012048.22')

        Raises:
            ToolError: If gene cannot be found
        """
        result = await self.client.get_gene_info(gene_id=gene_identifier, dataset_id=dataset_id)
        if result["paging_info"]["totalNumberOfItems"] > len(result["data"]):
            raise ToolError("GTEx gene identity requires a complete reference result.")
        candidates = {
            row["gencodeId"]
            for row in result["data"]
            if gene_identifier == row["gencodeId"]
            or ("." not in gene_identifier and gene_identifier == row["gencodeId"].split(".")[0])
            or gene_identifier.casefold() == row["geneSymbol"].casefold()
            or (gene_identifier.isdecimal() and gene_identifier == str(row.get("entrezGeneId")))
        }
        if len(candidates) != 1:
            raise ToolError("GTEx gene identity is unavailable or ambiguous for this release.")
        return candidates.pop()

    # =========================================================================
    # TOOL 1: QUERY_EXPRESSION
    # =========================================================================

    async def query_expression(
        self,
        query_type: str,
        gene_id: str | None = None,
        tissue_id: str | None = None,
        limit: int = 50,
        dataset_id: str = DEFAULT_DATASET_ID,
        page: int = 0,
    ) -> dict[str, Any]:
        """
        Query gene expression data across tissues.

        This tool replaces:
        - get_median_gene_expression
        - get_gene_expression
        - get_top_expressed_genes
        - list_tissues

        Args:
            query_type: Type of expression query:
                - "gene_median": Get median expression of a gene across all tissues
                - "gene_tissue": Get detailed expression of a gene in a specific tissue
                - "top_genes": Get most highly expressed genes in a tissue
                - "list_tissues": List all available GTEx tissues
            gene_id: Gene identifier - accepts BOTH:
                - Gene symbol (e.g., 'BRCA1', 'TP53') - automatically converted
                - GENCODE ID, checked against the selected release
                Required for: gene_median, gene_tissue
            tissue_id: Tissue identifier (e.g., 'Brain_Cortex', 'Liver', 'Whole_Blood')
                Required for: gene_tissue, top_genes
            limit: Maximum number of genes to return (for top_genes, default: 50, max: 100)
            dataset_id: GTEx dataset identifier (default: 'gtex_v10')

        Returns:
            Expression data based on query_type

        Examples:
            # Get median expression across all tissues using gene symbol
            query_expression(query_type="gene_median", gene_id="BRCA1")

            # Get detailed expression in brain using GENCODE ID
            query_expression(query_type="gene_tissue", gene_id="ENSG00000012048.22", tissue_id="Brain_Cortex")

            # Get top 20 expressed genes in liver
            query_expression(query_type="top_genes", tissue_id="Liver", limit=20)

            # List all available tissues
            query_expression(query_type="list_tissues")
        """
        try:
            page_parameters(page, limit)
            if query_type == "gene_median":
                if not gene_id:
                    raise ToolError("gene_id required for gene_median query_type")

                # Resolve gene symbol to GENCODE ID
                gencode_id = await self._resolve_gene_id(gene_id, dataset_id)
                return expression_window(
                    await self._gene_window(
                        lambda **window: self.client.get_median_gene_expression(
                            gencode_id, dataset_id, **window
                        ),
                        gencode_id=gencode_id,
                        dataset_id=dataset_id,
                        page=page,
                        limit=limit,
                    ),
                    query_type,
                )

            elif query_type == "gene_tissue":
                if not gene_id:
                    raise ToolError("gene_id required for gene_tissue query_type")
                if not tissue_id:
                    raise ToolError("tissue_id required for gene_tissue query_type")

                # Resolve gene symbol to GENCODE ID
                gencode_id = await self._resolve_gene_id(gene_id, dataset_id)
                return expression_window(
                    await self._gene_window(
                        lambda **window: self.client.get_gene_expression(
                            gencode_id, tissue_id, dataset_id, **window
                        ),
                        gencode_id=gencode_id,
                        dataset_id=dataset_id,
                        page=page,
                        limit=limit,
                    ),
                    query_type,
                )

            elif query_type == "top_genes":
                if not tissue_id:
                    raise ToolError("tissue_id required for top_genes query_type")

                return await collect(
                    lambda **window: self.client.get_top_expressed_genes(tissue_id, dataset_id, **window),
                    page=page,
                    limit=limit,
                )

            elif query_type == "list_tissues":
                return await collect(
                    lambda **window: self.client.list_tissues(dataset_id, **window), page=page, limit=limit
                )

            else:
                raise ToolError(
                    f"Invalid query_type: {query_type}. "
                    "Must be 'gene_median', 'gene_tissue', 'top_genes', or 'list_tissues'"
                )

        except ResearchError:
            with provider_boundary("gtex"):
                raise
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize unexpected adapter failures before MCP logging
            raise ToolError("GTEx could not complete the operation.") from None

    # =========================================================================
    # TOOL 2: QUERY_QTL
    # =========================================================================

    async def query_qtl(
        self,
        qtl_type: str,
        analysis_mode: str,
        tissue_id: str,
        gene_id: str | None = None,
        variant_id: str | None = None,
        p_value_threshold: float | None = None,
        limit: int = 50,
        dataset_id: str = DEFAULT_DATASET_ID,
        phenotype_id: str | None = None,
        page: int = 0,
    ) -> dict[str, Any]:
        """
        Query QTL (Quantitative Trait Loci) data - both eQTL and sQTL.

        This tool replaces:
        - get_eqtl_genes
        - get_single_tissue_eqtls
        - get_sqtl_genes
        - get_metasoft_results
        - calculate_dynamic_eqtl
        - calculate_dynamic_sqtl

        Args:
            qtl_type: Type of QTL analysis:
                - "eqtl": Expression QTL (genetic variants affecting gene expression)
                - "sqtl": Splicing QTL (genetic variants affecting splicing)
            analysis_mode: Analysis mode:
                - "genes_list": Get list of genes with QTL associations in tissue
                - "gene_associations": Get QTL associations for a specific gene
                - "metasoft": Multi-tissue eQTL analysis for gene-variant pair (eQTL only)
                - "dynamic": On-demand QTL calculation for gene-variant pair
            tissue_id: Tissue identifier (e.g., 'Whole_Blood', 'Brain_Cortex', 'Liver')
                Required for all modes
            gene_id: Gene identifier - accepts BOTH:
                - Gene symbol (e.g., 'BRCA1', 'TP53') - automatically converted
                - GENCODE ID, checked against the selected release
                Required for: gene_associations, metasoft, dynamic
            variant_id: Variant identifier (rsID or explicit GRCh38 GTEx ID ending in _b38)
                Optional for: gene_associations
                Required for: metasoft, dynamic
            p_value_threshold: P-value threshold for filtering (optional, for genes_list mode)
            limit: Maximum results to return (default: 50)
            dataset_id: GTEx dataset identifier (default: 'gtex_v10')

        Returns:
            QTL data based on qtl_type and analysis_mode

        Examples:
            # Get all eQTL genes in whole blood
            query_qtl(qtl_type="eqtl", analysis_mode="genes_list", tissue_id="Whole_Blood")

            # Get eQTL associations for BRCA1 using gene symbol
            query_qtl(qtl_type="eqtl", analysis_mode="gene_associations",
                     tissue_id="Whole_Blood", gene_id="BRCA1")

            # Multi-tissue eQTL analysis using GENCODE ID
            query_qtl(qtl_type="eqtl", analysis_mode="metasoft",
                     tissue_id="Whole_Blood", gene_id="ENSG00000012048.22",
                     variant_id="rs1234567")

            # Dynamic sQTL calculation for gene-variant pair
            query_qtl(qtl_type="sqtl", analysis_mode="dynamic",
                     tissue_id="Muscle_Skeletal", gene_id="TP53", variant_id="rs1234567")
        """
        try:
            page_parameters(page, limit)
            if qtl_type not in ["eqtl", "sqtl"]:
                raise ToolError(f"Invalid qtl_type: {qtl_type}. Must be 'eqtl' or 'sqtl'")

            variant_identity = None
            if variant_id:
                variant_identity = await self._resolve_variant(variant_id, dataset_id)
                variant_id = variant_identity["variant_id"]

            async def qtl_window(*args, **kwargs):
                identity = gene_identity(kwargs["gencode_id"], dataset_id)
                result = await self._gene_window(
                    *args,
                    **kwargs,
                    annotate=lambda row, **locator: qtl_record(
                        row,
                        qtl_type=qtl_type,
                        mode=analysis_mode,
                        dataset=dataset_id,
                        gene=identity,
                        variant=variant_identity,
                        tissue=tissue_id,
                        **locator,
                    ),
                )
                if variant_identity:
                    result["variant_identity"] = variant_identity
                return result

            if analysis_mode == "genes_list":
                getter = self.client.get_eqtl_genes if qtl_type == "eqtl" else self.client.get_sqtl_genes
                return await collect(
                    lambda **window: getter(tissue_id, dataset_id, **window),
                    page=page,
                    limit=limit,
                    threshold=p_value_threshold,
                    annotate=lambda row, **locator: qtl_record(
                        row,
                        qtl_type=qtl_type,
                        mode=analysis_mode,
                        dataset=dataset_id,
                        tissue=tissue_id,
                        **locator,
                    ),
                )

            elif analysis_mode == "gene_associations":
                # Get QTL associations for specific gene
                if not gene_id:
                    raise ToolError("gene_id required for gene_associations mode")

                # Resolve gene symbol to GENCODE ID
                gencode_id = await self._resolve_gene_id(gene_id, dataset_id)
                getter = (
                    self.client.get_single_tissue_eqtls
                    if qtl_type == "eqtl"
                    else self.client.get_single_tissue_sqtls
                )
                return await qtl_window(
                    lambda **window: getter(gencode_id, tissue_id, dataset_id, variant_id, **window),
                    gencode_id=gencode_id,
                    dataset_id=dataset_id,
                    page=page,
                    limit=limit,
                    threshold=p_value_threshold,
                )

            elif analysis_mode == "metasoft":
                # Multi-tissue eQTL analysis
                if not gene_id or not variant_id:
                    raise ToolError("gene_id and variant_id required for metasoft mode")

                if qtl_type != "eqtl":
                    raise ToolError("metasoft mode only available for eQTL")

                # Resolve gene symbol to GENCODE ID
                gencode_id = await self._resolve_gene_id(gene_id, dataset_id)
                return await qtl_window(
                    lambda **window: self.client.get_metasoft_results(
                        gencode_id, variant_id, dataset_id, **window
                    ),
                    gencode_id=gencode_id,
                    dataset_id=dataset_id,
                    page=page,
                    limit=limit,
                    threshold=p_value_threshold,
                    measure="metaP",
                )

            elif analysis_mode == "dynamic":
                if page:
                    raise ToolError("Dynamic QTL is a single calculation without provider pages.")
                # On-demand QTL calculation
                if not gene_id or not variant_id:
                    raise ToolError("gene_id and variant_id required for dynamic mode")

                # Resolve gene symbol to GENCODE ID
                gencode_id = await self._resolve_gene_id(gene_id, dataset_id)

                phenotype_qualification = None
                if qtl_type == "eqtl":
                    result = await self.client.calculate_dynamic_eqtl(
                        gencode_id, variant_id, tissue_id, dataset_id
                    )
                else:  # sqtl
                    if not phenotype_id:
                        raise ToolError("Dynamic sQTL requires phenotype_id from a qualified association.")
                    # A LeafCutter phenotype is an intron, not a gene ID. Verify
                    # the provider's gene/intron association before joining it.
                    found = False
                    for index in range(10):
                        reference = await self.client.get_single_tissue_sqtls(
                            gencode_id, tissue_id, dataset_id, variant_id, page=index
                        )
                        for row_index, row in enumerate(reference["data"]):
                            if row["phenotypeId"] == phenotype_id:
                                phenotype_qualification = qtl_record(
                                    row,
                                    qtl_type="sqtl",
                                    mode="gene_associations",
                                    dataset=dataset_id,
                                    gene=gene_identity(gencode_id, dataset_id),
                                    variant=variant_identity,
                                    tissue=tissue_id,
                                    page=reference["paging_info"]["page"],
                                    row_index=row_index,
                                    response_sha256=digest(reference),
                                )
                                found = True
                                break
                        if found:
                            break
                        if index + 1 >= reference["paging_info"]["numberOfPages"]:
                            break
                    if not found:
                        raise ToolError(
                            "GTEx could not qualify this gene/intron association within the lookup budget."
                        )
                    result = await self.client.calculate_dynamic_sqtl(
                        phenotype_id, variant_id, tissue_id, dataset_id
                    )
                return {
                    "records": [
                        qtl_record(
                            result,
                            qtl_type=qtl_type,
                            mode="dynamic",
                            dataset=dataset_id,
                            gene=gene_identity(gencode_id, dataset_id),
                            variant=variant_identity,
                            tissue=tissue_id,
                            response_sha256=digest(result),
                            phenotype_qualification=phenotype_qualification,
                        )
                    ],
                    "gene_identity": gene_identity(gencode_id, dataset_id),
                    "variant_identity": variant_identity,
                    "measurement_fields": {"error": "standard error", "data": "paired donor measurements"},
                    "significance": None
                    if p_value_threshold is None
                    else {
                        "measure": "pValue",
                        "threshold": p_value_threshold,
                        "meets_threshold": result["pValue"] <= p_value_threshold,
                        "scope": "calculated result retained regardless of significance",
                    },
                }

            else:
                raise ToolError(
                    f"Invalid analysis_mode: {analysis_mode}. "
                    "Must be 'genes_list', 'gene_associations', 'metasoft', or 'dynamic'"
                )

        except ResearchError:
            with provider_boundary("gtex"):
                raise
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize unexpected adapter failures before MCP logging
            raise ToolError("GTEx could not complete the operation.") from None

    # =========================================================================
    # TOOL 3: GET_ANNOTATION
    # =========================================================================

    async def get_annotation(
        self,
        entity_type: str,
        entity_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        page: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        """
        Get genomic annotation information for genes, transcripts, exons, or variants.

        This tool replaces:
        - get_gene_info
        - get_transcript_info
        - get_exon_info
        - get_variant_info

        Args:
            entity_type: Type of genomic entity:
                - "gene": Gene annotation (coordinates, name, metadata)
                - "transcript": Transcript annotation (coordinates, exon structure)
                - "exon": Exon annotation (coordinates, parent gene/transcript)
                - "variant": Variant annotation (position, alleles, annotations)
            entity_id: Entity identifier:
                - For genes: Gene symbol (e.g., 'BRCA1') OR GENCODE ID (e.g., 'ENSG00000012048.22')
                - For transcripts: Parent gene symbol or GENCODE gene ID
                - For exons: Parent gene symbol or GENCODE gene ID
                - For variants: Variant ID (rsID like 'rs123456' or chr_pos_ref_alt format)
            dataset_id: GTEx dataset identifier (default: 'gtex_v10')

        Returns:
            Annotation data based on entity_type

        Examples:
            # Get gene annotation using gene symbol
            get_annotation(entity_type="gene", entity_id="BRCA1")

            # Get gene annotation using GENCODE ID
            get_annotation(entity_type="gene", entity_id="ENSG00000012048.22")

            # Get transcript annotation
            get_annotation(entity_type="transcript", entity_id="BRAF")

            # Get exon annotation
            get_annotation(entity_type="exon", entity_id="BRAF")

            # Get variant annotation
            get_annotation(entity_type="variant", entity_id="rs1234567")
        """
        try:
            page_parameters(page, limit)
            if entity_type in {"gene", "transcript", "exon"}:
                gencode_id = await self._resolve_gene_id(entity_id, dataset_id)
                getter = {
                    "gene": self.client.get_gene_info,
                    "transcript": self.client.get_transcript_info,
                    "exon": self.client.get_exon_info,
                }[entity_type]
                return await self._gene_window(
                    lambda **window: getter(gencode_id, dataset_id, **window),
                    gencode_id,
                    dataset_id,
                    page=page,
                    limit=limit,
                )

            elif entity_type == "variant":
                return await collect(
                    lambda **window: self.client.get_variant_info(entity_id, dataset_id, **window),
                    page=page,
                    limit=limit,
                )

            else:
                raise ToolError(
                    f"Invalid entity_type: {entity_type}. Must be 'gene', 'transcript', 'exon', or 'variant'"
                )

        except ResearchError:
            with provider_boundary("gtex"):
                raise
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize unexpected adapter failures before MCP logging
            raise ToolError("GTEx could not complete the operation.") from None

    # =========================================================================
    # TOOL 4: GET_METADATA
    # =========================================================================

    async def get_metadata(
        self, info_type: str, dataset_id: str = DEFAULT_DATASET_ID, page: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        """
        Get GTEx system metadata including service info and tissues.

        This tool replaces:
        - get_service_info
        - get_dataset_info
        - list_tissues

        Args:
            info_type: Type of metadata to retrieve:
                - "service": GTEx API service information and version
                - "dataset": GTEx dataset metadata
                - "tissues": List all available GTEx tissues
            dataset_id: GTEx dataset identifier (default: 'gtex_v10')
                Used for: tissues query

        Returns:
            Metadata based on info_type

        Examples:
            # Get API service information
            get_metadata(info_type="service")

            # List all available tissues
            get_metadata(info_type="tissues")
        """
        try:
            page_parameters(page, limit)
            if info_type != "tissues" and page:
                raise ToolError("Service and dataset metadata have no provider pages.")
            if info_type == "service":
                return await self.client.get_service_info()

            elif info_type == "dataset":
                return {"data": await self.client.get_dataset_info(dataset_id)}

            elif info_type == "tissues":
                return await collect(
                    lambda **window: self.client.list_tissues(dataset_id, **window), page=page, limit=limit
                )

            else:
                raise ToolError(f"Invalid info_type: {info_type}. Must be 'service', 'dataset', or 'tissues'")

        except ResearchError:
            with provider_boundary("gtex"):
                raise
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize unexpected adapter failures before MCP logging
            raise ToolError("GTEx could not complete the operation.") from None

    # =========================================================================
    # TOOL 5: GET_SAMPLE
    # =========================================================================

    async def get_sample(
        self, sample_id: str, dataset_id: str = DEFAULT_DATASET_ID, page: int = 0, limit: int = 25
    ) -> dict[str, Any]:
        """
        Get information about a specific GTEx biobank sample.

        This tool replaces:
        - get_sample_info

        Args:
            sample_id: GTEx sample identifier (e.g., 'GTEX-1117F-0003-SM-58Q7G')
            dataset_id: GTEx dataset identifier (default: 'gtex_v10')

        Returns:
            Sample metadata including tissue type, subject information, etc.

        Example:
            get_sample(sample_id="GTEX-1117F-0003-SM-58Q7G")
        """
        try:
            return await collect(
                lambda **window: self.client.get_sample_info(sample_id, dataset_id, **window),
                page=page,
                limit=limit,
            )

        except ResearchError:
            with provider_boundary("gtex"):
                raise
        except ToolError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize unexpected adapter failures before MCP logging
            raise ToolError("GTEx could not complete the operation.") from None
