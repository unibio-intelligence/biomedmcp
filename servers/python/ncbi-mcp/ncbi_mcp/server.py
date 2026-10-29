"""Retained NCBI acquisition behind the canonical biomedmcp source contract.

Assembly and annotation routes use the documented Datasets v2 contract.
Other retained operations require separate provider and scientific qualification.
"""

import os
from typing import Annotated, Optional, Literal, List, Dict, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary

from .datasets import (
    assembly_plan,
    association_plan,
    genome_plan,
    qualified_page,
    quality_projection,
    search_plan,
    taxonomy_plan,
)

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query NCBI",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("ncbi")

# Base URL and configuration
BASE_URL = os.getenv("NCBI_BASE_URL", "https://api.ncbi.nlm.nih.gov/datasets/v2")
API_KEY = os.getenv("NCBI_API_KEY")
TIMEOUT = int(os.getenv("NCBI_TIMEOUT", "30"))


async def api_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> dict:
    """Make API request to NCBI Datasets API with error handling.

    Args:
        method: HTTP method (GET or POST)
        endpoint: API endpoint path
        params: Query parameters
        json_data: JSON body for POST requests

    Returns:
        API response as dictionary
    """
    headers = {
        "User-Agent": "NCBI-Datasets-MCP-Server/2.0.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if API_KEY:
        headers["api-key"] = API_KEY

    with provider_boundary("ncbi"):
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            url = f"{BASE_URL}/{endpoint}"

            if method.upper() == "GET":
                response = await client.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                response = await client.post(url, params=params, json=json_data, headers=headers)
            else:
                raise ValueError("Unsupported HTTP method.")

            response.raise_for_status()
            return response.json()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_ncbi_data(
    query: Annotated[str, Field(min_length=1, max_length=512)],
    data_type: Literal["genomes", "assemblies", "taxonomy"] = "genomes",
    organism: Annotated[str, Field(min_length=1, max_length=512)] | None = None,
    tax_id: Annotated[int, Field(ge=1)] | None = None,
    chromosome: Optional[str] = None,
    assembly_level: Optional[Literal["complete_genome", "chromosome", "scaffold", "contig"]] = None,
    assembly_source: Optional[Literal["refseq", "genbank", "all"]] = "all",
    feature_type: Optional[Literal["CDS", "gene", "rRNA", "tRNA", "ncRNA", "all"]] = None,
    rank: Optional[str] = None,
    max_results: Annotated[int, Field(ge=1, le=25)] = 25,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Search NCBI dataset records; assembly discovery uses documented bounded report pages.

    Args:
        query: A taxon/name or exact accession for assemblies; search text within an explicit taxon
        data_type: Type of data to search for
        organism: Filter by organism name
        tax_id: Filter by NCBI taxonomy ID
        chromosome: Filter by chromosome name (for genes/features)
        assembly_level: Filter assemblies by completion level
        assembly_source: Assembly source filter (refseq, genbank, or all)
        feature_type: Type of genomic feature to search for
        rank: Taxonomic rank filter (for taxonomy searches)
        max_results: Maximum number of records per page (1-25)
        page_token: Page token for pagination

    Returns:
        Qualified assembly records and provider continuation, including actual organism identities.
        Other retained data types require separate current-provider qualification.
    """
    plan = search_plan(
        {
            "query": query,
            "data_type": data_type,
            "organism": organism,
            "tax_id": tax_id,
            "chromosome": chromosome,
            "assembly_level": assembly_level,
            "assembly_source": assembly_source,
            "feature_type": feature_type,
            "rank": rank,
            "max_results": max_results,
            "page_token": page_token,
        }
    )
    if plan is not None:
        response = await api_request("GET", plan["endpoint"], params=plan["params"])
        with provider_boundary("ncbi"):
            result = qualified_page(response, plan)
        return {
            **result,
            "data_type": data_type,
            "query": query,
            "url": BASE_URL + "/" + plan["endpoint"],
        }
    raise ResearchError("unsupported_operation", "Select a documented assembly or taxonomy search.")


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_genome_data(
    accession: Annotated[str, Field(pattern=r"^GC[AF]_[0-9]+\.[0-9]+$", max_length=40)],
    info_type: Literal["full", "summary", "annotation"] = "full",
    include_annotation: bool = True,
    chromosome: Annotated[str, Field(min_length=1, max_length=64)] | None = None,
    start_position: Annotated[int, Field(ge=1, le=1000000000000)] | None = None,
    end_position: Annotated[int, Field(ge=1, le=1000000000000)] | None = None,
    symbols: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=128)]],
        Field(min_length=1, max_length=25),
    ]
    | None = None,
    gene_types: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=64)]],
        Field(min_length=1, max_length=25),
    ]
    | None = None,
    page_size: Annotated[int, Field(ge=1, le=25)] = 25,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve an exact assembly report or a bounded page of documented annotation records.

    Args:
        accession: Exact versioned GCF_ or GCA_ assembly accession
        info_type: Full metadata, a metadata summary or annotation feature records
        include_annotation: Include annotation metadata in full/summary reports
        chromosome: Chromosome name or sequence accession, for annotation only
        start_position: Provider-native region start; requires chromosome and end_position
        end_position: Provider-native region stop; no coordinate offset conversion is applied
        symbols: Exact case-sensitive gene symbols, for annotation only
        gene_types: Provider gene locus types, such as protein-coding, for annotation only
        page_size: Annotation page limit (1-25); exact assembly metadata retrieves one record
        page_token: Resume a provider window with the same parameters

    Returns:
        Qualified records with actual assembly/annotation identity, raw provider fields and pagination.
        Missing annotations are not inferred to be absent measurements. Full genome sequences are not fetched.
    """
    plan = genome_plan(
        {
            "accession": accession,
            "info_type": info_type,
            "include_annotation": include_annotation,
            "chromosome": chromosome,
            "start_position": start_position,
            "end_position": end_position,
            "symbols": symbols,
            "gene_types": gene_types,
            "page_size": page_size,
            "page_token": page_token,
        }
    )
    response = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        result = qualified_page(
            response,
            plan,
            include_annotation=include_annotation,
            summary=info_type == "summary",
        )
    return {**result, "info_type": info_type, "url": BASE_URL + "/" + plan["endpoint"]}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_taxonomy_data(
    tax_id: Annotated[int, Field(ge=1)] | None = None,
    organism: Annotated[str, Field(min_length=1, max_length=512)] | None = None,
    info_type: Literal["info", "organism", "lineage"] = "info",
    include_lineage: bool = True,
    include_synonyms: bool = False,
    format: Literal["json", "text"] = "json",
    page_size: Annotated[int, Field(ge=1, le=25)] = 25,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
    genome_page_size: Annotated[int, Field(ge=1, le=25)] = 10,
    genome_page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
    names_page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve qualified taxonomy, ancestor TaxIDs, names and optional genome assembly pages.

    Args:
        tax_id: Exact positive TaxID; select this or organism, never both
        organism: One scientific/common taxon name; ambiguous matches do not join genome evidence
        info_type: Metadata, lineage, or taxonomy with an associated genome page
        include_lineage: Include provider ancestor IDs and named-rank classification; lineage mode always includes them
        include_synonyms: Retrieve the provider name report without inventing absent synonyms
        format: Retain structured evidence; text also adds a TaxID lineage presentation
        page_size: Taxonomy page size, 1-25
        page_token: Resume the primary taxonomy report
        genome_page_size: Associated assembly page size, 1-25
        genome_page_token: Resume the organism-mode assembly page
        names_page_token: Resume the optional name report
    """
    plan = taxonomy_plan(
        {
            "tax_id": tax_id,
            "organism": organism,
            "page_size": page_size,
            "page_token": page_token,
        }
    )
    response = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        result = qualified_page(response, plan)
    result.update(info_type=info_type, url=BASE_URL + "/" + plan["endpoint"])
    rows = result["records"]
    if len(rows) != 1 or (tax_id is None and result["_provider_page"]["continuation"]):
        if rows:
            result["resolution"] = "ambiguous"
        return result
    node = rows[0]["taxonomy"]
    identity = node["tax_id"]
    result["tax_id"] = identity
    result["section_outcomes"] = {}
    if include_lineage or info_type == "lineage":
        available = "parents" in node or identity == 1
        result["lineage"] = {
            "outcome": "data" if available else "unavailable",
            "ancestor_tax_ids": node.get("parents", []) if available else None,
            "classification": node.get("classification", {}),
            "interpretation": "Provider ancestor TaxIDs; named-rank classification is a separate subset. No phylogenetic distances are inferred.",
        }
        result["section_outcomes"]["lineage"] = result["lineage"]["outcome"]
        if format == "text":
            result["text"] = "Ancestor TaxIDs: " + (
                " -> ".join(map(str, node.get("parents", []) + [identity])) if available else "unavailable"
            )
    result["_provider_pages"] = {}
    secondary = []
    if include_synonyms:
        secondary.append(
            (
                "names",
                "names_page_token",
                taxonomy_plan(
                    {
                        "tax_id": identity,
                        "page_size": page_size,
                        "page_token": names_page_token,
                    },
                    names=True,
                ),
            )
        )
    if info_type == "organism":
        secondary.append(
            (
                "available_genomes",
                "genome_page_token",
                search_plan(
                    {
                        "query": str(identity),
                        "tax_id": identity,
                        "max_results": genome_page_size,
                        "page_token": genome_page_token,
                    }
                ),
            )
        )
    for field, token_parameter, extra_plan in secondary:
        try:
            response = await api_request("GET", extra_plan["endpoint"], params=extra_plan["params"])
            with provider_boundary("ncbi"):
                extra = qualified_page(response, extra_plan)
            result["_provider_pages"][token_parameter] = extra.pop("_provider_page")
            result[field] = extra
            result["section_outcomes"][field] = (
                "data"
                if extra["records"]
                else "partial"
                if not extra["pagination"]["accessible_window_exhausted"]
                else "empty"
            )
        except (ResearchError, ToolError):
            result[field] = {
                "outcome": "error",
                "records": None,
                "message": "NCBI could not supply this requested evidence section.",
            }
            result["section_outcomes"][field] = "error"
    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_assembly_data(
    assembly_accession: Annotated[str, Field(pattern=r"^GC[AF]_[0-9]+\.[0-9]+$", max_length=40)],
    report_type: Literal["info", "stats", "quality", "sequence_report", "annotation_report"] = "info",
    include_annotation: bool = True,
    include_checkm: bool = True,
    include_busco: bool = True,
    include_contamination: bool = True,
    page_size: Annotated[int, Field(ge=1, le=25)] = 25,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve documented exact-assembly metadata, statistics, quality or feature reports.

    Args:
        assembly_accession: Exact versioned GCF_ or GCA_ assembly
        report_type: Assembly metadata/stats/quality, sequence metadata, or annotation records
        include_annotation: Retain annotation metadata for info/stats
        include_checkm: Include available CheckM marker-completeness measurements for quality
        include_busco: Include available annotation BUSCO measurements with lineage/version and raw scale
        include_contamination: Include available CheckM contamination estimates; absence is unavailable
        page_size: Feature/sequence page limit, 1-25; metadata retrieves one exact record
        page_token: Resume the same report and assembly
    """
    args = {
        "assembly_accession": assembly_accession,
        "report_type": report_type,
        "page_size": page_size,
        "page_token": page_token,
    }
    plan = assembly_plan(args)
    response = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        result = qualified_page(
            response,
            plan,
            include_annotation=include_annotation if report_type != "quality" else True,
        )
        if result["records"] and report_type == "quality":
            metrics = quality_projection(
                result["records"][0],
                {
                    "include_checkm": include_checkm,
                    "include_busco": include_busco,
                    "include_contamination": include_contamination,
                },
            )
            result["quality_metrics"] = metrics
            result["section_outcomes"] = {name: metric["outcome"] for name, metric in metrics.items()}
        if result["records"] and report_type == "stats":
            stats = result["records"][0].get("assembly_stats")
            result["statistics"] = stats
            result["section_outcomes"] = {"statistics": "data" if stats else "unavailable"}
    return {
        **result,
        "report_type": report_type,
        "url": BASE_URL + "/" + plan["endpoint"],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_protein_info(
    protein_accession: str,
    include_sequence: bool = True,
    include_domains: bool = True,
    include_structure: bool = False,
) -> dict:
    """Get detailed information for a specific protein.

    Args:
        protein_accession: Protein accession number
        include_sequence: Include protein sequence
        include_domains: Include domain information
        include_structure: Include structure information

    Returns:
        Protein information with optional sequence and structure data

    Examples:
        >>> # Get protein info with sequence and domains
        >>> get_protein_info("NP_000537.3")

        >>> # Get protein info with structure
        >>> get_protein_info("NP_000537.3", include_structure=True)
    """
    params = {
        "include_sequence": include_sequence,
        "include_domains": include_domains,
        "include_structure": include_structure,
    }

    result = await api_request("GET", f"protein/accession/{protein_accession}", params=params)

    return {"protein_accession": protein_accession, "data": result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_virus_info(
    accession: Annotated[str, Field(min_length=1, max_length=64)],
    tax_id: Annotated[int, Field(gt=0, strict=True)] | None = None,
) -> dict:
    """Retrieve a versioned viral nucleotide record's reported metadata.

    The report preserves collection/annotation fields and unknown measurements;
    it does not download nucleotide/protein sequences or infer transmission.
    """
    from .gene_reports import virus_plan, virus_report

    arguments = {"accession": accession, "tax_id": tax_id}
    plan = virus_plan(arguments)
    raw = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        return virus_report(raw, arguments, plan, base_url=BASE_URL)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def download_genome_data(
    accession: str,
    include_annotation: bool = True,
    file_format: Literal["fasta", "genbank", "gff3", "gtf", "all"] = "all",
) -> dict:
    """Get download URLs and information for genome data files.

    Args:
        accession: Genome assembly accession
        include_annotation: Include annotation files
        file_format: File format filter

    Returns:
        Download URLs and file information

    Examples:
        >>> # Get all download URLs
        >>> download_genome_data("GCF_000001405.40")

        >>> # Get only FASTA files
        >>> download_genome_data("GCF_000001405.40", file_format="fasta")
    """
    params = {}

    if include_annotation:
        params["include_annotation_type"] = "GENOME_GFF,GENOME_GBFF"

    if file_format != "all":
        format_mapping = {
            "fasta": "GENOME_FASTA",
            "genbank": "GENOME_GBFF",
            "gff3": "GENOME_GFF",
            "gtf": "GENOME_GTF",
        }
        params["include_annotation_type"] = format_mapping[file_format]

    result = await api_request("GET", f"genome/accession/{accession}/download", params=params)

    return {"accession": accession, "file_format": file_format, "download_info": result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def find_orthologs(
    gene_id: Annotated[int, Field(gt=0, strict=True)],
    source_tax_id: Annotated[int, Field(gt=0, strict=True)],
    target_tax_ids: Annotated[
        List[Annotated[int, Field(gt=0, strict=True)]], Field(min_length=1, max_length=25)
    ],
    max_results: Annotated[int, Field(ge=1, le=25, strict=True)] = 10,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve NCBI-inferred ortholog annotations for an exact, species-qualified GeneID.

    Source identity is independently checked. Exact target taxa are selected after
    validating every returned row. Provider continuation survives filtering.
    Reported orthology is not sequence identity, functional equivalence or an
    experimentally demonstrated relationship. No similarity threshold is inferred.
    """
    from .gene_reports import ortholog_plans, ortholog_report

    arguments = {
        "gene_id": gene_id,
        "source_tax_id": source_tax_id,
        "target_tax_ids": target_tax_ids,
        "max_results": max_results,
        "page_token": page_token,
    }
    anchor, plan = ortholog_plans(arguments)
    source = await api_request("GET", anchor["endpoint"], params=anchor["params"])
    with provider_boundary("ncbi"):
        from .gene_reports import source_identity

        identity = source_identity(source, arguments, anchor)
    raw = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        return ortholog_report(raw, identity, arguments, plan, base_url=BASE_URL)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_sequence_data(
    accession: str,
    sequence_type: Literal["genomic", "transcript", "protein", "all"] = "all",
    format: Literal["fasta", "genbank", "json"] = "fasta",
    start_position: Optional[int] = None,
    end_position: Optional[int] = None,
    strand: Literal["plus", "minus", "both"] = "plus",
) -> dict:
    """Retrieve sequence data for genomes, genes, or proteins.

    Args:
        accession: Sequence accession number
        sequence_type: Type of sequence to retrieve
        format: Output format
        start_position: Start position for subsequence
        end_position: End position for subsequence
        strand: DNA strand

    Returns:
        Sequence data in requested format

    Examples:
        >>> # Get genomic sequence in FASTA format
        >>> get_sequence_data("NC_000001.11", sequence_type="genomic")

        >>> # Get subsequence
        >>> get_sequence_data("NC_000001.11", start_position=1000000,
        ...                   end_position=2000000)
    """
    params = {"format": format}

    if sequence_type != "all":
        params["sequence_type"] = sequence_type
    if start_position:
        params["start"] = start_position
    if end_position:
        params["end"] = end_position
    if strand != "plus":
        params["strand"] = strand

    result = await api_request("GET", f"sequence/accession/{accession}", params=params)

    return {"accession": accession, "sequence_type": sequence_type, "format": format, "sequence_data": result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def blast_search(
    query_sequence: str,
    database: Literal["nr", "nt", "refseq_genomic", "refseq_protein"] = "nr",
    program: Optional[Literal["blastn", "blastp", "blastx", "tblastn", "tblastx"]] = None,
    max_hits: int = 50,
    evalue_threshold: float = 0.001,
    organism_filter: Optional[str] = None,
) -> dict:
    """Perform BLAST search against NCBI databases.

    Args:
        query_sequence: Query sequence in FASTA format
        database: Target database
        program: BLAST program (auto-detected if not specified)
        max_hits: Maximum number of hits (1-500)
        evalue_threshold: E-value threshold
        organism_filter: Restrict search to specific organism

    Returns:
        BLAST search results

    Examples:
        >>> # BLAST protein sequence
        >>> blast_search("MKFLKFSLLTAVLLSVVFAFSSCGDDDDTISQIRQQQ...", database="nr")

        >>> # BLAST with organism filter
        >>> blast_search("ATCGATCGATCG...", database="nt",
        ...              organism_filter="Homo sapiens")
    """
    if max_hits < 1 or max_hits > 500:
        raise ValueError("max_hits must be between 1 and 500")

    request_data = {
        "query": query_sequence,
        "database": database,
        "max_hits": max_hits,
        "evalue": evalue_threshold,
    }

    if program:
        request_data["program"] = program
    if organism_filter:
        request_data["organism"] = organism_filter

    result = await api_request("POST", "blast/search", json_data=request_data)

    return {
        "database": database,
        "program": program or "auto",
        "max_hits": max_hits,
        "evalue_threshold": evalue_threshold,
        "blast_results": result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_project_sample(
    accession: Annotated[str, Field(min_length=1, max_length=40)],
    search_type: Literal["bioproject", "biosample"] = "bioproject",
    data_type: Literal["genomes", "assemblies"] = "genomes",
    include_metadata: bool = True,
    include_related: bool = False,
    max_results: Annotated[int, Field(ge=1, le=25)] = 25,
    page_token: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Retrieve genome assembly associations for one BioProject or BioSample.

    Args:
        accession: PRJNA/PRJEB/PRJDB project or SAMN/SAMEA/SAMD sample accession
        search_type: Project or sample association
        data_type: Genome assembly records; no gene or universal-repository search is implied
        include_metadata: Retain provider assembly/sample/annotation metadata
        include_related: Retain related project lineage and linked assembly references when supplied
        max_results: Provider assembly page size, 1-25
        page_token: Resume the same accession and parameters
    """
    plan = association_plan(
        {
            "accession": accession,
            "search_type": search_type,
            "data_type": data_type,
            "max_results": max_results,
            "page_token": page_token,
        }
    )
    response = await api_request("GET", plan["endpoint"], params=plan["params"])
    with provider_boundary("ncbi"):
        result = qualified_page(response, plan)
    if not include_metadata:
        result["records"] = [
            {
                key: value
                for key, value in row.items()
                if key in {"accession", "current_accession", "paired_accession", "organism"}
            }
            for row in result["records"]
        ]
    if include_related:
        result["related_references"] = [
            {
                "assembly_accession": row["accession"],
                "bioproject_lineage": row.get("assembly_info", {}).get("bioproject_lineage"),
                "linked_assemblies": row.get("assembly_info", {}).get("linked_assemblies"),
            }
            for row in response.get("reports", [])
        ]
    return {
        **result,
        "association_accession": accession,
        "search_type": search_type,
        "data_type": data_type,
        "url": BASE_URL + "/" + plan["endpoint"],
    }
