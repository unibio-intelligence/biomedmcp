"""UniProt MCP Server - Optimized Python Implementation.

Provides access to UniProt protein database with composite tools.
"""

import json
import re as _re
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary, provider_tool_boundary
from biomedmcp.pagination import numeric_total, page_payload

from .annotations import COMPARISON_FIELDS, EVOLUTION_FIELDS, comparison, evolution, preflight
from .shapes import protein, proteins

# UniProt canonical accession pattern (e.g. P38398, Q12864)
_UNIPROT_ACC_RE = _re.compile(
    r"^(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-[1-9][0-9]*)?$"
)
# Gene symbol heuristic: all-caps letters/digits/hyphens, no spaces, 2-20 chars
_GENE_SYMBOL_RE = _re.compile(r"^[A-Z][A-Z0-9\-]{1,19}$")

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query UniProt",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("uniprot")
BASE_URL = "https://rest.uniprot.org"
# Explicit supported feature columns; UniProt rejects the former ft_* wildcard.
FEATURE_FIELDS = (
    "ft_var_seq",
    "ft_variant",
    "ft_non_cons",
    "ft_non_std",
    "ft_non_ter",
    "ft_conflict",
    "ft_unsure",
    "ft_act_site",
    "ft_binding",
    "ft_dna_bind",
    "ft_site",
    "ft_mutagen",
    "ft_intramem",
    "ft_topo_dom",
    "ft_transmem",
    "ft_chain",
    "ft_crosslnk",
    "ft_disulfid",
    "ft_carbohyd",
    "ft_init_met",
    "ft_lipid",
    "ft_mod_res",
    "ft_peptide",
    "ft_propep",
    "ft_signal",
    "ft_transit",
    "ft_strand",
    "ft_helix",
    "ft_turn",
    "ft_coiled",
    "ft_compbias",
    "ft_domain",
    "ft_motif",
    "ft_region",
    "ft_repeat",
    "ft_zn_fing",
)


async def uniprot_api_request(endpoint: str, params: dict | None = None) -> dict:
    """Make request to UniProt API."""
    url = f"{BASE_URL}/{endpoint}"
    params = dict(params or {})
    json_format = params.get("format", "json") == "json"
    if json_format and params.get("fields"):
        # Every projection retains a citable identity for response validation.
        params["fields"] = ",".join(dict.fromkeys(["accession", *params["fields"].split(",")]))
    with provider_boundary("uniprot"):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            if not json_format:
                return {"data": response.text}
            value = response.json()
            required = "sequence" in params.get("fields", "").split(",")
            if endpoint == "uniprotkb/search":
                proteins(value, require_sequence=required)
            elif endpoint.startswith("uniprotkb/") and endpoint != "uniprotkb/stream":
                protein(value, expected=endpoint.split("/")[1], require_sequence=required)
                release = response.headers.get("x-uniprot-release", "")
                value["source_release"] = release if _re.fullmatch(r"[0-9]{4}_[0-9]{2}", release) else None
            return value


def safe_error(exc):
    """Nested peer failures retain controlled classification, never raw causes."""
    if isinstance(exc, ResearchError):
        return exc.as_dict()
    if isinstance(exc, ToolError):
        try:
            value = json.loads(str(exc))
            if value.get("code") in {
                "invalid_source_response",
                "identity_mismatch",
                "source_not_found",
                "source_unavailable",
                "source_rate_limited",
                "source_authentication_failed",
                "source_access_denied",
                "source_connection_rejected",
            }:
                return ResearchError(
                    value["code"],
                    "UniProt could not retrieve this protein.",
                    retryable=value.get("retryable") is True,
                ).as_dict()
        except (ValueError, TypeError, AttributeError):
            pass
    return ResearchError(
        "source_unavailable", "UniProt could not retrieve this protein.", retryable=True
    ).as_dict()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def query_proteins(
    query: str,
    query_type: Literal["accession", "gene", "organism", "keyword", "advanced"] = "accession",
    include_sequence: bool = False,
    include_features: bool = False,
    output_format: Literal["json", "fasta", "tsv", "xml"] = "json",
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    fields: list[str] | None = None,
    offset: Annotated[int, Field(ge=0, le=1000)] = 0,
    page_cursor: Annotated[str, Field(min_length=1, max_length=8192)] | None = None,
) -> dict:
    """Query UniProt proteins with flexible search options."""
    # Auto-detect query_type when the default "accession" was not explicitly
    # set and the query doesn't look like a real UniProt accession.
    if query_type == "accession" and not _UNIPROT_ACC_RE.match(query):
        if " " in query or ":" in query or "AND" in query or "OR" in query:
            query_type = "advanced"
        elif _GENE_SYMBOL_RE.match(query):
            query_type = "gene"
        else:
            query_type = "keyword"

    if query_type == "accession":
        endpoint = f"uniprotkb/{query}"
        params = {"format": output_format}
    else:
        endpoint = "uniprotkb/search"
        if query_type == "gene":
            # Use gene_exact + restrict to human to get the canonical entry
            search_query = f"gene_exact:{query} AND organism_id:9606"
        elif query_type == "organism":
            search_query = f"organism:{query}"
        else:
            search_query = query

        params = {"query": search_query, "format": output_format, "size": limit}

    selected_fields = list(fields or [])
    if output_format == "json" and not selected_fields:
        selected_fields = [
            "accession",
            "id",
            "protein_name",
            "gene_names",
            "organism_name",
            "length",
            "reviewed",
        ]
    if include_sequence:
        selected_fields.append("sequence")
    if include_features:
        selected_fields.extend(FEATURE_FIELDS)
    if selected_fields and output_format in {"json", "tsv"}:
        if output_format == "json":
            selected_fields.insert(0, "accession")
        params["fields"] = ",".join(dict.fromkeys(selected_fields))

    if (offset or page_cursor) and (query_type == "accession" or output_format != "json"):
        raise ResearchError("unsupported_cursor", "Pagination requires a JSON protein search.")
    if offset and not page_cursor:
        raise ResearchError("unsupported_cursor", "UniProt requires its returned opaque cursor.")
    if query_type != "accession" and output_format == "json":
        if page_cursor:
            params["cursor"] = page_cursor
        with provider_boundary("uniprot"):
            async with httpx.AsyncClient(timeout=30) as client:
                url = f"{BASE_URL}/{endpoint}"
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                rows = proteins(payload, require_sequence=include_sequence)
                link = response.links.get("next", {}).get("url")
                cursor = None
                if link:
                    # Never follow an arbitrary provider-supplied host or path.
                    from urllib.parse import parse_qs, urlparse

                    target = urlparse(link)
                    if (
                        target.scheme != "https"
                        or target.netloc != "rest.uniprot.org"
                        or target.path != "/uniprotkb/search"
                    ):
                        raise ValueError("Invalid UniProt continuation")
                    cursor = parse_qs(target.query).get("cursor", [None])[0]
                    if not cursor:
                        raise ValueError("Missing UniProt cursor")
                packed = page_payload(
                    rows,
                    raw_count=len(rows),
                    exhausted=cursor is None,
                    continuation=cursor,
                    total=numeric_total(response.headers.get("x-total-results")),
                )
                result = {"results": packed["records"], "_provider_page": packed["_provider_page"]}
    else:
        result = await uniprot_api_request(endpoint, params)
    return {"query": query, "query_type": query_type, **result}


# Add examples to query_proteins docstring
query_proteins.__doc__ = """Query UniProt proteins with flexible search options.

Args:
    query: Protein accession, gene name, organism, or search term
    query_type: Type of search
    include_sequence: Include full protein sequence
    include_features: Include feature annotations
    output_format: Output format
    fields: Optional UniProt field names. JSON defaults to a compact projection.
    limit: Maximum results (1-100)

Returns:
    Protein information matching query

Examples:
    >>> # Query by accession
    >>> await query_proteins("P04637", query_type="accession")
    # Returns p53 tumor suppressor protein

    >>> # Search by gene name
    >>> await query_proteins("TP53", query_type="gene", limit=5)
    # Returns proteins for TP53 gene

    >>> # Search in specific organism
    >>> await query_proteins("insulin", query_type="keyword", limit=10)
"""


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def analyze_evolution(
    accession: str,
    analysis_type: Literal[
        "similarity_annotations", "orthology_references", "phylogeny_references"
    ] = "similarity_annotations",
) -> dict:
    """Retrieve UniProt similarity annotations or external orthology/phylogeny references; no relationship or tree inference."""
    preflight("analyze_evolution", {"accession": accession})
    result = await uniprot_api_request(
        f"uniprotkb/{accession}",
        {"format": "json", "fields": "id,organism_id," + EVOLUTION_FIELDS[analysis_type]},
    )
    return evolution(result, accession, analysis_type)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def analyze_structure_function(
    accession: str,
    analysis_type: Literal["structure", "domains", "variants", "composition"] = "structure",
    include_predictions: bool = True,
) -> dict:
    """Analyze protein structure, domains, variants, and composition."""
    fields = {
        "structure": "ft_strand,ft_helix,ft_turn,xref_pdb,xref_alphafolddb",
        "domains": "ft_domain,ft_region,ft_motif,xref_pfam,xref_interpro",
        "variants": "ft_variant,ft_mutagen,cc_polymorphism",
        "composition": "sequence,mass,length",
    }

    endpoint = f"uniprotkb/{accession}"
    params = {"format": "json", "fields": fields.get(analysis_type, fields["structure"])}

    result = await uniprot_api_request(endpoint, params)
    return {"accession": accession, "analysis_type": analysis_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def analyze_biological_context(
    accession: str,
    context_type: Literal["pathways", "interactions", "function", "localization"] = "pathways",
    include_go_terms: bool = True,
) -> dict:
    """Analyze biological pathways, interactions, function, and localization."""
    fields = {
        "pathways": "xref_reactome,xref_kegg,xref_biocyc",
        "interactions": "cc_interaction,xref_string,xref_intact",
        "function": "cc_function,cc_catalytic_activity,cc_cofactor",
        "localization": "cc_subcellular_location,ft_intramem,ft_topo_dom",
    }

    endpoint = f"uniprotkb/{accession}"
    params = {"format": "json", "fields": fields.get(context_type, fields["pathways"])}

    if include_go_terms:
        params["fields"] += ",go,go_p,go_c,go_f"

    result = await uniprot_api_request(endpoint, params)
    return {"accession": accession, "context_type": context_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def advanced_search(
    search_query: str, filters: dict | None = None, reviewed_only: bool = False, limit: int = 25
) -> dict:
    """Advanced search with custom filters."""
    endpoint = "uniprotkb/search"
    query = search_query

    if reviewed_only:
        query += " AND reviewed:true"

    if filters:
        for key, value in filters.items():
            query += f" AND {key}:{value}"

    params = {"query": query, "format": "json", "size": limit}
    result = await uniprot_api_request(endpoint, params)
    return {"search_query": search_query, "filters": filters, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def batch_protein_lookup(
    accessions: list[str],
    include_sequence: bool = False,
    output_format: Literal["json", "fasta", "tsv"] = "json",
) -> dict:
    """Lookup multiple proteins in batch (max 100)."""
    results = []
    for acc in accessions[:100]:
        try:
            result = await query_proteins(acc, "accession", include_sequence, False, output_format, 1)
            results.append({"accession": acc, "data": result, "success": True})
        except (ResearchError, ToolError) as e:
            results.append({"accession": acc, "error": safe_error(e), "success": False})
    return {
        "total": len(results),
        "results": results,
        "section_outcomes": {
            r["accession"]: {
                "outcome": "data" if r["success"] else "unavailable",
                "sources": ["uniprot"] if r["success"] else [],
            }
            for r in results
        },
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def get_metadata(
    accession: str, metadata_type: Literal["xrefs", "literature", "confidence", "all"] = "all"
) -> dict:
    """Get cross-references, literature, and annotation confidence."""
    fields = {
        "xrefs": "xref_*",
        "literature": "lit_pubmed_id,absorption,kinetics,ph_dependence,redox_potential,temp_dependence",
        "confidence": "annotation_score,protein_existence",
        "all": "xref_*,lit_pubmed_id,annotation_score,protein_existence",
    }

    endpoint = f"uniprotkb/{accession}"
    params = {"format": "json", "fields": fields.get(metadata_type, fields["all"])}
    if metadata_type in {"xrefs", "all"}:
        # A full JSON entry contains all cross-references. xref_* is not a
        # supported field selector; the transport still bounds the response.
        params.pop("fields")

    result = await uniprot_api_request(endpoint, params)
    return {"accession": accession, "metadata_type": metadata_type, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def export_protein_data(
    accessions: list[str],
    output_format: Literal["fasta", "gff", "genbank", "embl", "tsv"] = "fasta",
    fields: list[str] | None = None,
) -> dict:
    """Export protein data in various formats."""
    endpoint = "uniprotkb/stream"
    query = " OR ".join([f"accession:{acc}" for acc in accessions[:1000]])

    params = {"query": query, "format": output_format}
    if fields and output_format == "tsv":
        params["fields"] = ",".join(fields)

    result = await uniprot_api_request(endpoint, params)
    return {"format": output_format, "count": len(accessions), **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def validate_accession(accession: str) -> dict:
    """Validate UniProt accession and check entry status."""
    endpoint = f"uniprotkb/{accession}"
    params = {"format": "json", "fields": "accession,protein_name,organism_name,reviewed"}

    result = await uniprot_api_request(endpoint, params)
    return {"accession": accession, "valid": True, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def get_taxonomy_info(organism: str, search_by: Literal["name", "taxon_id"] = "name") -> dict:
    """Get organism taxonomy information."""
    endpoint = "taxonomy/search" if search_by == "name" else f"taxonomy/{organism}"
    params = {"query": f"name:{organism}", "format": "json"} if search_by == "name" else {"format": "json"}

    result = await uniprot_api_request(endpoint, params)
    return {"organism": organism, "search_by": search_by, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("uniprot")
async def compare_proteins(
    accessions: Annotated[list[str], Field(min_length=2, max_length=5)],
    comparison_type: Literal["sequence", "function", "structure"] = "sequence",
) -> dict:
    """Compare exact sequences, literal FUNCTION annotations, or PDB reference IDs for 2–5 distinct UniProt accessions. Retain failed peers and input locators; no alignment or structural equivalence inference."""
    preflight("compare_proteins", {"accessions": accessions})
    results = []
    for accession in accessions:
        try:
            record = await uniprot_api_request(
                f"uniprotkb/{accession}",
                {"format": "json", "fields": "id,organism_id," + COMPARISON_FIELDS[comparison_type]},
            )
            results.append({"accession": accession, "data": record})
        except (ResearchError, ToolError) as exc:
            results.append({"accession": accession, "error": safe_error(exc)})
    return comparison(results, accessions, comparison_type)
