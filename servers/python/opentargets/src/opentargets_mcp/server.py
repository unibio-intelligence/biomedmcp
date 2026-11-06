"""Open Targets Platform MCP adapter: target, disease, drug and genetics evidence."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from biomedmcp.errors import provider_tool_boundary

from . import __version__
from .queries import OpenTargetsClient
from .tools.unified import UnifiedTools

READ_ONLY_ANNOTATIONS = ToolAnnotations(title="Query Open Targets", read_only_hint=True, open_world_hint=True)
mcp = FastMCP("opentargets", version=__version__)
CLIENT = OpenTargetsClient()
TOOLS = UnifiedTools()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("opentargets")
async def get_entity(
    entity_type: Annotated[str, Field(description='"target", "disease" or "drug".')],
    entity_id: Annotated[str, Field(description="Ensembl gene ID, EFO/MONDO disease ID or ChEMBL drug ID.")],
    sections: Annotated[
        list[str] | None,
        Field(
            description="target: identity, biology, safety, tractability (one validated record), alternative_genes, "
            "interactions, tep; disease: identity, targets, phenotypes, otar_projects; drug: identity, "
            "mechanisms_of_action, indications, adverse_events, cross_references. Default: the identity record."
        ),
    ] = None,
    include_associations: Annotated[
        bool, Field(description="Targets only: also acquire associated diseases.")
    ] = False,
    association_limit: Annotated[
        int, Field(description="Rows per association or adverse-event window (1-100).")
    ] = 10,
) -> dict:
    """One Open Targets entity record with independently acquired optional sections.

    A failed optional section is reported in section_outcomes and never becomes an empty result.
    """
    return await TOOLS.get_entity(
        CLIENT, entity_type, entity_id, sections, include_associations, association_limit
    )


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("opentargets")
async def search_drugs(
    query: Annotated[str, Field(description="Drug name, synonym or trade name text.")],
    limit: Annotated[int, Field(description="Maximum hits (1-100).")] = 10,
) -> dict:
    """Text search restricted to drug entities, returning ChEMBL identifiers for exact follow-up calls."""
    return await TOOLS.search_drugs(CLIENT, query, limit)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("opentargets")
async def analyze_advanced(
    analysis_type: Annotated[
        str,
        Field(
            description="compare: the same aspects for 2-10 targets; similar: annotation Jaccard overlap for one "
            "target against its literature-model candidates; validate: annotation and candidate counts for one "
            "target, optionally with a disease pair; prioritize: direct disease associations ranked by their "
            "genetic_association component; metadata: API and data release versions."
        ),
    ],
    entity_ids: Annotated[
        list[str], Field(description="Human Ensembl gene IDs; empty for metadata or discovery.")
    ],
    disease_id: Annotated[
        str | None, Field(description="Disease ID for validate (optional) and prioritize.")
    ] = None,
    similarity_criteria: Annotated[
        str, Field(description="similar only: pathways, diseases, go_terms or interactions.")
    ] = "pathways",
    comparison_aspects: Annotated[
        list[str] | None,
        Field(description="compare only: tractability, safety, diseases, pathways. Default: all."),
    ] = None,
    threshold: Annotated[float, Field(description="similar only: minimum annotation Jaccard (0-1).")] = 0.5,
    limit: Annotated[int, Field(description="similar/prioritize only: rows displayed (1-100).")] = 10,
) -> dict:
    """Bounded multi-target analyses; parameters a mode does not consume must keep their defaults."""
    return await TOOLS.analyze_advanced(
        CLIENT,
        analysis_type,
        entity_ids,
        disease_id,
        similarity_criteria,
        comparison_aspects,
        threshold,
        limit,
    )


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("opentargets")
async def analyze_association(
    source_id: Annotated[
        str, Field(description="Target Ensembl ID, disease ID or ChEMBL ID depending on the mode.")
    ],
    association_type: Annotated[
        str,
        Field(
            description="target-disease: indexed pair score plus one evidence window (source_id=target, "
            "target_id=disease); drug-target: mechanism rows and targets; drug-disease: indications; "
            "discover-opportunities: disease targets ranked by genetic_association score."
        ),
    ] = "target-disease",
    target_id: Annotated[str | None, Field(description="Disease ID for target-disease.")] = None,
    evidence_types: Annotated[
        list[str] | None,
        Field(description="target-disease: keep only these datatype IDs, e.g. genetic_association."),
    ] = None,
    filters: Annotated[
        dict | None, Field(description='discover-opportunities: {"min_score": x} on the genetic component.')
    ] = None,
    min_score: Annotated[
        float, Field(description="Minimum score for displayed evidence or ranked targets.")
    ] = 0.0,
    limit: Annotated[int, Field(description="Evidence or ranking rows (1-100).")] = 20,
    include_biomarkers: Annotated[
        bool, Field(description="target-disease: list biomarker annotations.")
    ] = True,
    ranking_strategy: Annotated[
        str | None, Field(description='discover-opportunities: "genetic_evidence".')
    ] = None,
    evidence_cursor: Annotated[
        str | None,
        Field(description="target-disease: continuation issued by the service; submit it unchanged."),
    ] = None,
) -> dict:
    """Pair, drug and discovery associations; unconsumed parameters are rejected before any request."""
    return await TOOLS.analyze_association(
        CLIENT,
        source_id,
        association_type,
        target_id,
        evidence_types,
        filters,
        min_score,
        limit,
        include_biomarkers,
        ranking_strategy,
        evidence_cursor,
    )


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("opentargets")
async def query_genetics(
    query_type: Annotated[str, Field(description="variant, study or credible_set.")],
    variant_id: Annotated[str | None, Field(description="variant: chromosome_position_ref_alt.")] = None,
    study_id: Annotated[str | None, Field(description="study: one GWAS or QTL study ID.")] = None,
    credible_set_id: Annotated[str | None, Field(description="credible_set: one study-locus ID.")] = None,
    gene_id: Annotated[
        str | None, Field(description="study: discover studies linked to one Ensembl gene.")
    ] = None,
    disease_id: Annotated[
        str | None, Field(description="study: discover studies indexed to one disease.")
    ] = None,
    include_credible_sets: Annotated[bool, Field(description="Add one window of fine-mapped loci.")] = False,
    include_evidences: Annotated[
        bool, Field(description="variant: add one window of linked evidence.")
    ] = False,
    include_functional_consequences: Annotated[
        bool, Field(description="variant: transcript and effect predictions.")
    ] = True,
    include_pharmacogenomics: Annotated[
        bool, Field(description="variant: pharmacogenomics annotations.")
    ] = False,
    limit: Annotated[int, Field(description="Window size for loci, evidence or studies (1-100).")] = 25,
    page_index: Annotated[int, Field(description="Zero-based source page for loci or studies.")] = 0,
    evidence_cursor: Annotated[
        str | None, Field(description="variant evidence continuation; submit unchanged.")
    ] = None,
) -> dict:
    """Variant, study and credible-set records with bounded, separately paged relations.

    Exactly one selector is required; windows and flags a mode does not consume must keep their defaults.
    """
    return await TOOLS.query_genetics(
        CLIENT,
        query_type,
        variant_id,
        study_id,
        credible_set_id,
        gene_id,
        disease_id,
        include_credible_sets,
        include_evidences,
        include_functional_consequences,
        include_pharmacogenomics,
        limit,
        page_index,
        evidence_cursor,
    )
