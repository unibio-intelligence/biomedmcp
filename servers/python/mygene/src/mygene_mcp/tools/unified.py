"""
Unified MyGene MCP Tools - Consolidates 26 tools into 5 flexible, parameter-driven tools.

This module provides high-level tools that intelligently route to underlying implementations
based on parameters, reducing tool count while maintaining full functionality.
"""
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from ..client import MyGeneClient


class UnifiedTools:
    """
    Five unified tools that replace all 26+ granular tools through parameter-based flexibility.
    Each tool is extensively documented to enable successful agent interaction.
    """

    async def map_gene_ids(
        self,
        client: MyGeneClient,
        gene_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(min_length=1, max_length=25)],
        input_namespace: Literal["symbol", "entrezgene", "ensembl.gene"],
        species: Annotated[int, Field(gt=0)] = 9606,
    ) -> dict[str, Any]:
        """Map up to 25 exact gene identifiers within one taxonomy ID.

        Return qualified candidate identities independently for each input, with
        resolved, ambiguous or not_found status. No fuzzy/alias selection or
        cross-species joins. A provider failure never means not_found.
        """
        from .mapping import map_gene_ids

        return await map_gene_ids(client, gene_ids, input_namespace, species)

    def __init__(self):
        # Import dependencies lazily to avoid circular imports
        from .query import QueryApi
        from .annotation import AnnotationApi
        from .batch import BatchApi
        from .pathway import PathwayApi
        from .go import GOApi
        from .expression import ExpressionApi
        from .disease import DiseaseApi
        from .chemical import ChemicalApi
        from .variant import VariantApi
        from .homology import HomologyApi
        from .interval import IntervalApi
        from .advanced import AdvancedQueryApi
        from .metadata import MetadataApi
        from .export import ExportApi

        self._query = QueryApi()
        self._annotation = AnnotationApi()
        self._batch = BatchApi()
        self._pathway = PathwayApi()
        self._go = GOApi()
        self._expression = ExpressionApi()
        self._disease = DiseaseApi()
        self._chemical = ChemicalApi()
        self._variant = VariantApi()
        self._homology = HomologyApi()
        self._interval = IntervalApi()
        self._advanced = AdvancedQueryApi()
        self._metadata = MetadataApi()
        self._export = ExportApi()

    # =========================================================================
    # TOOL 1: QUERY_GENES
    # =========================================================================

    async def query_genes(
        self,
        client: MyGeneClient,
        query: str,
        fields: Optional[str] = "symbol,name,taxid,entrezgene",
        species: Optional[str] = None,
        limit: int = 10,
        facets: Optional[str] = None,
        operation: str = "search",
        field_queries: Optional[Dict[str, str]] = None,
        operator: str = "AND",
        from_: Optional[int] = None,
        sort: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Universal gene search and querying with flexible search modes.

        This tool replaces:
        - query_genes
        - search_by_field
        - get_field_statistics

        Args:
            query (str): Search term (gene symbol, name, wildcards like "CDK*", or fielded query like "go.MF:kinase")
            fields (str): Comma-separated fields to return (default: "symbol,name,taxid,entrezgene")
            species (str, optional): Filter by species (e.g., "human", "mouse", or taxonomy ID like "9606")
            limit (int): Maximum results to return (1-1000, default: 10)
            facets (str, optional): Facet fields for aggregation (e.g., "type_of_gene,taxid")
            operation (str): Query mode - "search" (default), "field_search", or "field_stats"
                - "search": General text search with wildcards and boolean operators
                - "field_search": Search specific fields with boolean logic
                - "field_stats": Get statistics for a specific field
            field_queries (dict, optional): For field_search mode - field-value pairs
                Example: {"interpro": "IPR000001", "pfam": "PF00001"}
            operator (str): Boolean operator for field_search - "AND" or "OR" (default: "AND")
            from_ (int, optional): Starting result offset for pagination
            sort (str, optional): Sort order for results

        Returns:
            dict: Gene search results with hits, total count, and optional facets

        Examples:
            # Basic gene search
            query="CDK2"

            # Wildcard search with species filter
            query="cyclin*", species="human", limit=20

            # Boolean query with facets
            query="go.MF:kinase AND taxid:9606", facets="type_of_gene"

            # Field-specific search
            operation="field_search", field_queries={"interpro": "IPR000001", "pfam": "PF00001"}, operator="AND"

            # Get field statistics
            operation="field_stats", query="type_of_gene", limit=100, species="human"
        """
        if operation == "field_search":
            if not field_queries:
                return {"error": "field_queries required for field_search operation"}

            return await self._query.search_by_field(
                client=client,
                field_queries=field_queries,
                operator=operator,
                fields=fields,
                species=species,
                size=limit
            )

        elif operation == "field_stats":
            # Use query as the field name for statistics
            return await self._query.get_field_statistics(
                client=client,
                field=query,
                size=limit,
                species=species
            )

        else:  # operation == "search"
            return await self._query.query_genes(
                client=client,
                q=query,
                fields=fields,
                species=species,
                size=limit,
                from_=from_,
                sort=sort,
                facets=facets,
                facet_size=10 if facets else None
            )

    # =========================================================================
    # TOOL 2: GET_GENE
    # =========================================================================

    async def get_gene(
        self,
        client: MyGeneClient,
        gene_id: str,
        sections: Optional[List[str]] = None,
        species: Optional[str] = None,
        batch_mode: bool = False,
        gene_ids: Optional[List[str]] = None,
        scopes: Optional[str] = "entrezgene,ensemblgene,symbol"
    ) -> Dict[str, Any]:
        """
        Retrieve comprehensive gene information with flexible depth control.

        This tool replaces:
        - get_gene_annotation
        - get_genes_batch
        - query_genes_batch

        Args:
            gene_id (str): Gene identifier (Entrez like "1017", Ensembl like "ENSG00000123374", or symbol like "CDK2")
            sections (list of str, optional): Data sections to include. Pass as an ARRAY, not a JSON string.
                Default: None (returns basic identity info)
                IMPORTANT: Pass ["identity", "pathways"] NOT "[\"identity\", \"pathways\"]"

                Available sections:
                - "identity": Basic gene information (symbol, name, taxonomy, genomic location)
                - "genomic": Genomic details (chromosome, position, strand, exons)
                - "pathways": Pathway annotations from KEGG, Reactome, WikiPathways, etc.
                - "go_terms": Gene Ontology annotations (BP, MF, CC) with evidence codes
                - "expression": Expression data from HPA, GTEx, BioGPS
                - "disease": Disease associations from DisGeNET, ClinVar, OMIM
                - "drugs": Drug/chemical interactions from PharmGKB, DrugBank, ChEMBL
                - "variants": Genetic variants from ClinVar, SNPeff, GRASP
                - "homology": Ortholog information across species
                - "interactions": Protein-protein interactions
                - "literature": Publications and citations
                - "all": All available data sections

            species (str, optional): Species filter for resolving ambiguous IDs
            batch_mode (bool): Enable batch mode for multiple genes (default: False)
            gene_ids (list of str, optional): For batch mode - list of gene IDs (up to 1000)
                Example: ["CDK2", "TP53", "EGFR"]
                IMPORTANT: Pass ["CDK2", "TP53"] NOT "[\"CDK2\", \"TP53\"]"
            scopes (str): For batch mode - fields to search (default: "entrezgene,ensemblgene,symbol")

        Returns:
            dict: Comprehensive gene profile with requested data sections

        Examples:
            # Basic gene info
            gene_id="CDK2"

            # Gene with specific sections (sections is an array)
            gene_id="TP53", sections=["identity", "pathways", "disease"]

            # Get all available data
            gene_id="ENSG00000141510", sections=["all"]

            # Batch mode for multiple genes (gene_ids is an array)
            batch_mode=True, gene_ids=["CDK2", "TP53", "EGFR"], sections=["identity", "pathways"]

            # Batch query with specific scopes
            batch_mode=True, gene_ids=["1017", "7157", "1956"], scopes="entrezgene", sections=["identity", "disease"]
        """
        if batch_mode:
            if not gene_ids:
                return {"error": "gene_ids required for batch_mode"}

            # Determine if this is a query (with scopes) or annotation batch
            if scopes and scopes != "entrezgene,ensemblgene,symbol":
                # Query batch - search with scopes
                result = await self._batch.query_genes_batch(
                    client=client,
                    gene_ids=gene_ids,
                    scopes=scopes,
                    fields=self._build_fields_from_sections(sections),
                    species=species
                )
            else:
                # Annotation batch - direct ID lookup
                result = await self._batch.get_genes_batch(
                    client=client,
                    gene_ids=gene_ids,
                    fields=self._build_fields_from_sections(sections),
                    species=species
                )

            return result

        else:
            # Single gene annotation
            return await self._get_single_gene(
                client=client,
                gene_id=gene_id,
                sections=sections,
                species=species
            )

    async def _get_single_gene(
        self,
        client: MyGeneClient,
        gene_id: str,
        sections: Optional[List[str]],
        species: Optional[str]
    ) -> Dict[str, Any]:
        """Internal handler for single gene queries."""
        # Build fields based on requested sections
        fields = self._build_fields_from_sections(sections)

        # Get base annotation
        result = await self._annotation.get_gene_annotation(
            client=client,
            gene_id=gene_id,
            fields=fields,
            species=species
        )

        # If specific sections requested, organize the response
        if sections and result.get("success"):
            gene_data = result.get("gene", {})
            organized = {
                "success": True,
                "gene_id": gene_id,
                "sections": {}
            }

            if "identity" in sections or "all" in sections:
                organized["sections"]["identity"] = {
                    "symbol": gene_data.get("symbol"),
                    "name": gene_data.get("name"),
                    "entrezgene": gene_data.get("entrezgene"),
                    "ensembl": gene_data.get("ensembl"),
                    "taxid": gene_data.get("taxid"),
                    "type_of_gene": gene_data.get("type_of_gene")
                }

            if "genomic" in sections or "all" in sections:
                organized["sections"]["genomic"] = {
                    "genomic_pos": gene_data.get("genomic_pos"),
                    "genomic_pos_hg19": gene_data.get("genomic_pos_hg19"),
                    "exons": gene_data.get("exons"),
                    "refseq": gene_data.get("refseq")
                }

            if "pathways" in sections or "all" in sections:
                organized["sections"]["pathways"] = gene_data.get("pathway", {})

            if "go_terms" in sections or "all" in sections:
                organized["sections"]["go_terms"] = gene_data.get("go", {})

            if "expression" in sections or "all" in sections:
                organized["sections"]["expression"] = {
                    "hpa": gene_data.get("hpa"),
                    "gtex": gene_data.get("gtex"),
                    "biogps": gene_data.get("biogps")
                }

            if "disease" in sections or "all" in sections:
                organized["sections"]["disease"] = {
                    "disgenet": gene_data.get("disgenet"),
                    "clinvar": gene_data.get("clinvar"),
                    "omim": gene_data.get("omim")
                }

            if "drugs" in sections or "all" in sections:
                organized["sections"]["drugs"] = {
                    "pharmgkb": gene_data.get("pharmgkb"),
                    "drugbank": gene_data.get("drugbank"),
                    "chembl": gene_data.get("chembl"),
                    "chebi": gene_data.get("chebi")
                }

            if "variants" in sections or "all" in sections:
                organized["sections"]["variants"] = {
                    "clinvar": gene_data.get("clinvar"),
                    "snpeff": gene_data.get("snpeff"),
                    "grasp": gene_data.get("grasp")
                }

            if "homology" in sections or "all" in sections:
                organized["sections"]["homology"] = {
                    "homologene": gene_data.get("homologene"),
                    "pantherdb": gene_data.get("pantherdb")
                }

            return organized

        return result

    def _build_fields_from_sections(self, sections: Optional[List[str]]) -> Optional[str]:
        """Build comma-separated fields string from section names."""
        if not sections:
            return "symbol,name,taxid,entrezgene"

        if "all" in sections:
            return None  # Return all fields

        field_map = {
            "identity": ["symbol", "name", "entrezgene", "ensembl", "taxid", "type_of_gene"],
            "genomic": ["genomic_pos", "genomic_pos_hg19", "exons", "refseq"],
            "pathways": ["pathway"],
            "go_terms": ["go"],
            "expression": ["hpa", "gtex", "biogps", "exac"],
            "disease": ["disgenet", "clinvar", "omim"],
            "drugs": ["pharmgkb", "drugbank", "chembl", "chebi"],
            "variants": ["clinvar", "snpeff", "grasp"],
            "homology": ["homologene", "pantherdb"],
            "interactions": ["ppi"],
            "literature": ["generif", "pmid"]
        }

        fields_set = set()
        for section in sections:
            if section in field_map:
                fields_set.update(field_map[section])

        # Always include basic identity fields
        fields_set.update(["symbol", "name", "entrezgene"])

        return ",".join(sorted(fields_set))

    # =========================================================================
    # TOOL 3: ANALYZE_GENE_CONTEXT
    # =========================================================================

    async def analyze_gene_context(
        self,
        client: MyGeneClient,
        gene_id: str,
        context_type: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        sources: Optional[List[str]] = None,
        species: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze gene biological context including pathways, GO terms, expression, and associations.

        This tool replaces:
        - get_gene_pathways, query_genes_by_pathway
        - get_gene_go_annotations, query_genes_by_go_term
        - get_gene_expression_profile, query_genes_by_expression
        - get_gene_disease_associations, query_genes_by_disease
        - get_gene_chemical_interactions, query_genes_by_chemical
        - get_gene_variants

        Args:
            gene_id (str): Gene identifier (Entrez, Ensembl, or symbol)
            context_type (str): Type of biological context to analyze:
                - "pathways": Pathway membership and biological processes
                - "go_terms": Gene Ontology annotations with evidence
                - "expression": Expression patterns across tissues/cell types
                - "disease": Disease associations and clinical significance
                - "drugs": Drug/chemical interactions and pharmacology
                - "variants": Genetic variants and their effects
            filters (dict, optional): Context-specific filters as a dict object
                For pathways: {"pathway_id": "hsa04110", "source": "kegg"}
                For GO: {"aspect": "BP", "evidence_codes": ["EXP", "IDA"]}
                For expression: {"tissue": "brain", "dataset": "gtex"}
                For disease: {"clinical_significance": "Pathogenic"}
                For variants: {"variant_type": "single nucleotide variant"}
            limit (int): Maximum results for query operations (1-1000, default: 10)
            sources (list of str, optional): Filter by specific data sources. Pass as an ARRAY.
                For pathways: ["kegg", "reactome", "wikipathways"]
                For disease: ["disgenet", "clinvar", "omim"]
                For drugs: ["pharmgkb", "drugbank", "chembl"]
                IMPORTANT: Pass ["kegg", "reactome"] NOT "[\"kegg\", \"reactome\"]"
            species (str, optional): Species filter for queries (default: "human")

        Returns:
            dict: Biological context analysis with annotations and associations

        Examples:
            # Get all pathways for a gene
            gene_id="TP53", context_type="pathways"

            # Get pathways from specific sources (sources is an array)
            gene_id="CDK2", context_type="pathways", sources=["kegg", "reactome"]

            # Get GO annotations with evidence filtering
            gene_id="EGFR", context_type="go_terms", filters={"aspect": "BP", "evidence_codes": ["EXP"]}

            # Get expression profile across tissues
            gene_id="BRCA1", context_type="expression"

            # Get disease associations from specific sources (sources is an array)
            gene_id="APOE", context_type="disease", sources=["disgenet", "clinvar"]

            # Get drug interactions
            gene_id="CYP2D6", context_type="drugs", sources=["pharmgkb", "drugbank"]

            # Get variants with clinical significance filter
            gene_id="CFTR", context_type="variants", filters={"clinical_significance": "Pathogenic"}
        """
        filters = filters or {}

        if context_type == "pathways":
            return await self._pathway.get_gene_pathways(
                client=client,
                gene_id=gene_id,
                sources=sources
            )

        elif context_type == "go_terms":
            return await self._go.get_gene_go_annotations(
                client=client,
                gene_id=gene_id,
                aspect=filters.get("aspect"),
                evidence_codes=filters.get("evidence_codes")
            )

        elif context_type == "expression":
            return await self._expression.get_gene_expression_profile(
                client=client,
                gene_id=gene_id,
                datasets=sources
            )

        elif context_type == "disease":
            return await self._disease.get_gene_disease_associations(
                client=client,
                gene_id=gene_id,
                sources=sources
            )

        elif context_type == "drugs":
            return await self._chemical.get_gene_chemical_interactions(
                client=client,
                gene_id=gene_id,
                sources=sources
            )

        elif context_type == "variants":
            return await self._variant.get_gene_variants(
                client=client,
                gene_id=gene_id,
                variant_type=filters.get("variant_type"),
                clinical_significance=filters.get("clinical_significance")
            )

        else:
            return {"error": f"Invalid context_type: {context_type}"}

    # =========================================================================
    # TOOL 4: COMPARE_GENES
    # =========================================================================

    async def compare_genes(
        self,
        client: MyGeneClient,
        operation: str,
        gene_id: Optional[str] = None,
        gene_symbol: Optional[str] = None,
        chromosome: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        target_species: Optional[List[str]] = None,
        species_list: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        species: Optional[str] = "human",
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Gene comparison, homology analysis, and genomic interval queries.

        This tool replaces:
        - get_gene_orthologs
        - query_homologous_genes
        - query_genes_by_interval

        Args:
            operation (str): Type of comparison operation:
                - "orthologs": Find orthologous genes across species
                - "homology": Find homologous genes with same symbol across species
                - "interval": Query genes in a genomic region
            gene_id (str, optional): Gene identifier for ortholog queries
            gene_symbol (str, optional): Gene symbol for homology queries
            chromosome (str, optional): Chromosome for interval queries (e.g., "1", "X", "chr1")
            start (int, optional): Start position for interval queries
            end (int, optional): End position for interval queries
            target_species (list of str, optional): Target species for ortholog queries. Pass as an ARRAY.
                Examples: ["human", "mouse", "rat"] or ["9606", "10090"]
                IMPORTANT: Pass ["human", "mouse"] NOT "[\"human\", \"mouse\"]"
            species_list (list of str, optional): Species list for homology queries. Pass as an ARRAY.
                Examples: ["human", "mouse", "rat"]
            sources (list of str, optional): Homology data sources. Pass as an ARRAY.
                Options: ["homologene", "ensembl", "pantherdb"]
                IMPORTANT: Pass ["homologene", "ensembl"] NOT "[\"homologene\", \"ensembl\"]"
            species (str): Species for interval queries (default: "human")
            limit (int): Maximum results to return (1-1000, default: 10)

        Returns:
            dict: Comparison results based on operation type

        Examples:
            # Get orthologs across species (target_species is an array)
            operation="orthologs", gene_id="CDK2", target_species=["mouse", "rat"]

            # Get orthologs from specific sources (sources is an array)
            operation="orthologs", gene_id="TP53", sources=["homologene", "ensembl"]

            # Find homologous genes across species (species_list is an array)
            operation="homology", gene_symbol="TP53", species_list=["human", "mouse", "rat"]

            # Query genes in genomic interval
            operation="interval", chromosome="17", start=7571719, end=7590868, species="human"

            # Query interval without 'chr' prefix
            operation="interval", chromosome="1", start=100000, end=200000
        """
        if operation == "orthologs":
            if not gene_id:
                return {"error": "gene_id required for orthologs operation"}

            return await self._homology.get_gene_orthologs(
                client=client,
                gene_id=gene_id,
                target_species=target_species,
                sources=sources
            )

        elif operation == "homology":
            if not gene_symbol or not species_list:
                return {"error": "gene_symbol and species_list required for homology operation"}

            return await self._homology.query_homologous_genes(
                client=client,
                gene_symbol=gene_symbol,
                species_list=species_list,
                size=limit
            )

        elif operation == "interval":
            if chromosome is None or start is None or end is None:
                return {"error": "chromosome, start, and end required for interval operation"}

            return await self._interval.query_genes_by_interval(
                client=client,
                chr=chromosome,
                start=start,
                end=end,
                species=species,
                size=limit
            )

        else:
            return {"error": f"Invalid operation: {operation}"}

    # =========================================================================
    # TOOL 5: BATCH_OPERATIONS
    # =========================================================================

    async def batch_operations(
        self,
        client: MyGeneClient,
        operation: str,
        gene_ids: List[str],
        format: str = "json",
        fields: Optional[List[str]] = None,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Batch operations including export, advanced queries, and metadata retrieval.

        This tool replaces:
        - export_gene_list
        - build_complex_query
        - query_with_filters
        - get_mygene_metadata
        - get_available_fields
        - get_species_list

        Args:
            operation (str): Type of batch operation:
                - "export": Export gene data in various formats
                - "complex_query": Build complex boolean queries
                - "filtered_query": Query with predefined filters
                - "metadata": Get MyGene.info API metadata
                - "available_fields": List all available fields
                - "species_list": Get supported species
            gene_ids (list of str): List of gene IDs for export operation. Pass as an ARRAY.
                Example: ["CDK2", "TP53", "EGFR"]
                IMPORTANT: Pass ["CDK2", "TP53"] NOT "[\"CDK2\", \"TP53\"]"
            format (str): Export format - "json", "tsv", "csv", or "xml" (default: "json")
            fields (list of str, optional): Fields to include in export. Pass as an ARRAY.
                Example: ["symbol", "name", "pathway", "go"]
                IMPORTANT: Pass ["symbol", "name"] NOT "[\"symbol\", \"name\"]"
            query (str, optional): Base query string for query operations
            filters (dict, optional): Filter criteria as a dict object
                For complex_query: {"must": [{"field": "go.BP", "value": "GO:0006468"}]}
                For filtered_query: {"type_of_gene": ["protein-coding"], "chromosome": ["1", "2"]}
            limit (int): Maximum results for query operations (1-1000, default: 10)

        Returns:
            dict or str: Operation results - formatted data for export, query results, or metadata

        Examples:
            # Export genes to TSV (gene_ids and fields are arrays)
            operation="export", gene_ids=["CDK2", "TP53", "EGFR"], format="tsv", fields=["symbol", "name", "pathway"]

            # Export to JSON with all fields
            operation="export", gene_ids=["1017", "7157"], format="json"

            # Complex boolean query with filters
            operation="complex_query", query="kinase", filters={"must": [{"field": "taxid", "value": "9606"}]}, limit=20

            # Filtered query (filters is a dict with arrays)
            operation="filtered_query", query="CDK", filters={"type_of_gene": ["protein-coding"], "chromosome": ["1"]}, limit=15

            # Get API metadata
            operation="metadata", gene_ids=[]

            # Get available fields
            operation="available_fields", gene_ids=[]

            # Get species list
            operation="species_list", gene_ids=[]
        """
        if operation == "export":
            if not gene_ids:
                return {"error": "gene_ids required for export operation"}

            result = await self._export.export_gene_list(
                client=client,
                gene_ids=gene_ids,
                format=format,
                fields=fields
            )

            # Return as string for non-JSON formats
            if format != "json":
                return {"success": True, "format": format, "data": result}

            return {"success": True, "format": format, "data": result}

        elif operation == "complex_query":
            filters = filters or {}
            return await self._advanced.build_complex_query(
                client=client,
                must=filters.get("must"),
                should=filters.get("should"),
                must_not=filters.get("must_not"),
                filters=filters.get("filters"),
                aggregations=filters.get("aggregations"),
                size=limit
            )

        elif operation == "filtered_query":
            if not query:
                return {"error": "query required for filtered_query operation"}

            filters = filters or {}
            return await self._advanced.query_with_filters(
                client=client,
                q=query,
                type_of_gene=filters.get("type_of_gene"),
                chromosome=filters.get("chromosome"),
                taxid=filters.get("taxid"),
                ensembl_gene_exists=filters.get("ensembl_gene_exists"),
                refseq_exists=filters.get("refseq_exists"),
                has_go_annotation=filters.get("has_go_annotation"),
                has_pathway_annotation=filters.get("has_pathway_annotation"),
                size=limit
            )

        elif operation == "metadata":
            return await self._metadata.get_mygene_metadata(client)

        elif operation == "available_fields":
            return await self._metadata.get_available_fields(client)

        elif operation == "species_list":
            return await self._metadata.get_species_list(client)

        else:
            return {"error": f"Invalid operation: {operation}"}
