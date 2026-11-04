"""Canonical public operation contracts; native service methods remain internal primitives."""

from __future__ import annotations

from copy import deepcopy
from functools import cache
from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, create_model, model_validator

from .contracts import (
    Entity,
    Freshness,
    FulltextWindow,
    GetRequest,
    RelateRequest,
    ResolveRequest,
    SearchFilters,
    SearchRequest,
    SourceRequest,
    StrictModel,
    WorkflowRequest,
)
from .domain import SEARCH_FILTERS, WORKFLOWS
from .examples import description as example_description
from .extensions import StudyRequest
from .native.catalog import ADVANCED, RECORD_OWNER, RELATIONS, SEARCH_SOURCES, SECTION_DEPENDENCIES, SECTIONS
from .pagination import MAX_PROVIDER_PAGE

SEARCH_TASKS = {"article": "search_literature", "trial": "search_trials"}
GET_TASKS = {"variant": "get_variant_evidence"}
# Public verb_object tool names over native primitives. Native follow-up
# actions are translated here; superseded names are not accepted as aliases.
PUBLIC_TOOLS = {
    "search": "search_records",
    "get": "get_record",
    "resolve": "resolve_entity",
    "relate": "find_related",
    "research": "build_dossier",
    "query_source": "query_source",
    "study_analysis": "analyze_study",
}
NATIVE_OPERATIONS = {public: native for native, public in PUBLIC_TOOLS.items()}
STUDY_ANALYSES = {
    "gene_profile": "query",
    "mutation_cohort": "cohort",
    "survival": "survival",
    "compare": "compare",
    "co_occurrence": "co_occurrence",
    "filter_cohort": "filter",
    "top_mutated": "top_mutated",
}
RETIRED_WORKFLOWS = {
    "literature_review": "search_literature",
    "patent_landscape": "search_records",
    "study_summary": "search_records",
}
WORKFLOW_NAMES = {"variant_dossier": "variant_evidence"}


def fields_model(name, origin, names):
    return create_model(
        name,
        __base__=StrictModel,
        **{
            key: (origin.model_fields[key].annotation, deepcopy(origin.model_fields[key]))
            for key in sorted(names)
        },
    )


LiteratureFilters = fields_model("LiteratureFilters", SearchFilters, SEARCH_FILTERS["article"])
TrialFilters = fields_model("TrialFilters", SearchFilters, SEARCH_FILTERS["trial"])
ordinary_kinds = tuple(k for k, sources in SEARCH_SOURCES.items() if sources and k not in SEARCH_TASKS)
ordinary_fields = set().union(*(SEARCH_FILTERS[k] for k in ordinary_kinds))
RecordFilters = fields_model("RecordFilters", SearchFilters, ordinary_fields)


class SearchBase(StrictModel):
    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=10, ge=1, le=25)
    cursor: str | None = Field(
        default=None, max_length=2048, description="next_cursor from the previous page."
    )
    output: Literal["summary", "full"] = Field(
        default="summary",
        description="summary trims excerpts; full keeps source fields. Omitted evidence stays recoverable.",
    )
    freshness: Freshness = Field(default="cached_if_fresh", description="fresh bypasses the cache.")


class LiteratureSearch(SearchBase):
    filters: LiteratureFilters = Field(default_factory=LiteratureFilters)

    @model_validator(mode="after")
    def date_range(self):
        if self.filters.date_from and self.filters.date_to and self.filters.date_from > self.filters.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class TrialSearch(SearchBase):
    filters: TrialFilters = Field(default_factory=TrialFilters)


class RecordSearch(SearchBase):
    entity: Literal[ordinary_kinds]
    filters: RecordFilters = Field(default_factory=RecordFilters)

    @model_validator(mode="after")
    def supported_filters(self):
        unused = self.filters.model_fields_set - SEARCH_FILTERS[self.entity]
        if unused:
            raise ValueError(f"Unsupported {self.entity} filters: {', '.join(sorted(unused))}")
        return self


# Encode the entity-dependent constraints in the advertised schema as well as runtime validation.
RecordSearch.model_config["json_schema_extra"] = {
    "allOf": [
        {
            "if": {"properties": {"entity": {"const": kind}}, "required": ["entity"]},
            "then": {"properties": {"filters": {"propertyNames": {"enum": sorted(SEARCH_FILTERS[kind])}}}},
        }
        for kind in ordinary_kinds
    ]
}


class ExpressionParameters(StrictModel):
    tissue_id: str | None = Field(
        default=None, max_length=128, description="GTEx tissue, e.g. Liver; required for gene_tissue."
    )
    query_type: Literal["gene_median", "gene_tissue"] = "gene_median"
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE, description="Zero-based page.")


class QTLParameters(StrictModel):
    tissue_id: str = Field(min_length=1, max_length=128, description="GTEx tissue, e.g. Liver.")
    analysis_mode: Literal["gene_associations", "metasoft", "dynamic"] = "gene_associations"
    variant_id: str | None = Field(default=None, max_length=128)
    phenotype_id: str | None = Field(default=None, min_length=1, max_length=128)
    p_value_threshold: float = Field(default=0.05, gt=0, le=1)
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE, description="Zero-based page.")


class GeneAnnotationParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE, description="Zero-based page.")


class FulltextParameters(FulltextWindow):
    """One-based inclusive lines, end >= start, up to 100. Defaults: 1–100."""


class AssetParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0, le=10000)


class CivicParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=25, description="CIViC page size; maximum 25.")
    collection: Literal["evidenceItems", "assertions"] | None = Field(
        default=None, description="Required with cursor."
    )
    cursor: str | None = Field(
        default=None, min_length=1, max_length=2048, description="Continuation from a previous CIViC page."
    )

    @model_validator(mode="after")
    def continuation_collection(self):
        if self.cursor is not None and self.collection is None:
            raise ValueError("CIViC continuation requires one collection")
        return self


class InterProParameters(StrictModel):
    limit: int = Field(default=25, ge=1, le=25, strict=True)
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)


class RecordParameters(StrictModel):
    expression: ExpressionParameters | None = None
    eqtl: QTLParameters | None = None
    sqtl: QTLParameters | None = None
    transcripts: GeneAnnotationParameters | None = None
    exons: GeneAnnotationParameters | None = None
    genetics: GeneAnnotationParameters | None = None
    fulltext: FulltextParameters | None = None
    assets: AssetParameters | None = None
    civic: CivicParameters | None = None
    domains: InterProParameters | None = None
    complexes: InterProParameters | None = None


get_kinds = tuple(k for k in RECORD_OWNER if k not in GET_TASKS)
record_sections = tuple(sorted({"record"} | set().union(*(set(SECTIONS[k]) for k in get_kinds))))


class RecordGet(StrictModel):
    entity: Literal[get_kinds]
    id: str = Field(
        min_length=1,
        max_length=512,
        description="Exact ID, e.g. PCSK9, PMID:123, NCT04368728, MONDO:0007750, Q8NBP7, R-HSA-109581 or an InChIKey.",
    )
    sections: list[Literal[record_sections]] = Field(
        default_factory=list,
        max_length=12,
        description="Empty returns the base record; get_capabilities(entity=...) lists sections.",
    )
    sources: list[str] = Field(
        default_factory=list, max_length=12, description="Restrict lookups to these source IDs."
    )
    species: int = Field(default=9606, gt=0, description="NCBI taxon ID; 9606 is human.")
    source_versions: dict[str, str] = Field(
        default_factory=dict, max_length=8, description="Pin releases as {source: version}."
    )
    section_parameters: RecordParameters = Field(
        default_factory=RecordParameters, description="Options keyed by requested section."
    )
    freshness: Freshness = Field(default="cached_if_fresh", description="fresh bypasses the cache.")

    @model_validator(mode="after")
    def entity_sections(self):
        if set(self.sections) - {"record"} - set(SECTIONS[self.entity]):
            from pydantic import ValidationError

            raise ValidationError.from_exception_data(
                type(self).__name__,
                [
                    {
                        "type": "value_error",
                        "loc": ("sections",),
                        "input": None,
                        "ctx": {"error": ValueError("Unsupported entity section")},
                    }
                ],
            )
        return self


RecordGet.model_config["json_schema_extra"] = {
    "allOf": [
        {
            "if": {"properties": {"entity": {"const": kind}}, "required": ["entity"]},
            "then": {"properties": {"sections": {"items": {"enum": ["record", *SECTIONS[kind]]}}}},
        }
        for kind in get_kinds
    ]
}


class CohortReference(StrictModel):
    molecular_profile_id: str = Field(
        min_length=1, max_length=200, description="cBioPortal molecular profile ID."
    )
    sample_list_id: str = Field(min_length=1, max_length=200, description="cBioPortal sample list ID.")


class VariantParameters(StrictModel):
    cbioportal: CohortReference | None = None
    civic: CivicParameters | None = None
    gwas: GeneAnnotationParameters | None = None


variant_sections = ("record", *SECTIONS["variant"])


class VariantEvidence(StrictModel):
    id: str = Field(
        min_length=1,
        max_length=512,
        description="rsID, gene + protein change (PCSK9 R46L), HGVS or chr:pos:ref:alt.",
    )
    assembly: Literal["grch37", "grch38"] | None = Field(
        default=None, description="Genome build for coordinate IDs."
    )
    sections: list[Literal[variant_sections]] = Field(
        default_factory=lambda: ["clinvar", "population", "civic"], max_length=12
    )
    sources: list[str] = Field(
        default_factory=list, max_length=12, description="Restrict lookups to these source IDs."
    )
    section_parameters: VariantParameters = Field(
        default_factory=VariantParameters, description="Options keyed by requested section."
    )
    freshness: Freshness = Field(default="cached_if_fresh", description="fresh bypasses the cache.")


# Each analysis has only its meaningful parameters; no arbitrary study parameter bag.
study_fields = {
    "query": {"gene", "type"},
    "cohort": {"gene"},
    "survival": {"gene", "endpoint"},
    "compare": {"gene", "target", "type"},
    "co_occurrence": {"genes"},
    "top_mutated": {"limit"},
    "filter": {"mutated", "amplified", "deleted", "cancer_type", "expression_above", "expression_below"},
}
study_models = []
for analysis, names in study_fields.items():
    fields = {
        k: (StudyRequest.model_fields[k].annotation, deepcopy(StudyRequest.model_fields[k]))
        for k in sorted(names | {"study", "chart"})
    }
    for key in names & {"gene", "target"}:
        fields[key] = (str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$"))
    if analysis == "co_occurrence":
        fields["genes"] = (list[str], Field(min_length=2, max_length=10))
    if analysis == "compare":
        fields["type"] = (Literal["expression", "mutations"], "mutations")
    public_analysis = next(name for name, native in STUDY_ANALYSES.items() if native == analysis)
    fields["analysis"] = (Literal[public_analysis], ...)
    study_models.append(
        create_model("Study" + analysis.title().replace("_", ""), __base__=StrictModel, **fields)
    )
StudyAnalysis = Annotated[Union[tuple(study_models)], Field(discriminator="analysis")]  # noqa: UP007 -- runtime-generated union


workflow_names = tuple(k for k in WORKFLOWS if k not in RETIRED_WORKFLOWS and k != "variant_evidence") + (
    "variant_dossier",
)


class DossierParameters(RecordParameters):
    cbioportal: CohortReference | None = None


dossier_sections = tuple(
    sorted({"record"} | set().union(*(set(SECTIONS[WORKFLOWS[name][0]]) for name in WORKFLOWS)))
)


class ResearchWorkflow(WorkflowRequest):
    workflow: Literal[workflow_names]
    sections: list[Literal[dossier_sections]] | None = Field(
        default=None, max_length=12, description="Replace the workflow's default sections."
    )
    section_parameters: DossierParameters = Field(
        default_factory=DossierParameters, description="Options keyed by requested section."
    )


class PublicSource(SourceRequest):
    source: Literal[tuple(k for k in ADVANCED if k != "study")]


MODELS = {
    "search_records": RecordSearch,
    "get_record": RecordGet,
    "search_literature": LiteratureSearch,
    "search_trials": TrialSearch,
    "get_variant_evidence": VariantEvidence,
    "analyze_study": StudyAnalysis,
    "resolve_entity": ResolveRequest,
    "find_related": RelateRequest,
    "build_dossier": ResearchWorkflow,
    "query_source": PublicSource,
}
ADAPTERS = {name: TypeAdapter(model) for name, model in MODELS.items()}
# Lead with domain keywords (clients rank deferred tools by name and
# description), then say when to route elsewhere. Codex truncates plugin tool
# descriptions at 1,000 bytes, including the appended example.
TITLES = {
    "search_records": "Search biomedical records",
    "get_record": "Get record and evidence sections",
    "search_literature": "Search literature",
    "search_trials": "Search clinical trials",
    "get_variant_evidence": "Get variant evidence",
    "analyze_study": "Analyze genomics study",
    "resolve_entity": "Resolve identifiers",
    "find_related": "Find related records",
    "build_dossier": "Build research dossier",
    "query_source": "Query source directly",
}
BASE_DESCRIPTIONS = {
    "search_records": "Search genes, proteins, drugs, diseases, phenotypes, pathways, variants, pharmacogenomics, GWAS, diagnostics, adverse events, studies, patents or authors by text; returns IDs for get_record (variants: get_variant_evidence). Papers: search_literature. Trials: search_trials. Patent search is chemistry-linked (SureChEMBL); assignee/inventor/CPC search is query_source(source=patents).",
    "get_record": "Fetch one record by ID with optional evidence sections, e.g. gene expression/eqtl/diseases/druggability, drug label/safety, article fulltext, trial eligibility, protein domains/structures. Variants: get_variant_evidence. List an entity's sections with get_capabilities(entity=...).",
    "search_literature": "Search papers across PubMed, Europe PMC, PubTator and LitSense with date, author, journal, article-type and open-access filters. Deduplicates across sources and reports each source's outcome. Read abstracts or full text with get_record(entity=article).",
    "search_trials": "Search clinical trials (ClinicalTrials.gov, NCI) by condition, intervention, phase and recruitment status. Read arms, eligibility or outcomes with get_record(entity=trial). Does not assess an individual's eligibility.",
    "get_variant_evidence": "Get evidence for one variant (rsID, gene + protein change, HGVS or chr:pos:ref:alt). Defaults: ClinVar, gnomAD population, CIViC; add predictions (AlphaMissense), eve, cosmic, oncokb, hotspots, gwas or cbioportal. Ambiguous assembly or transcript is reported, not guessed; predictions keep source and uncertainty.",
    "analyze_study": "Analyze an installed public cancer genomics study: gene_profile, mutation_cohort, survival, compare, co_occurrence, filter_cohort, top_mutated. List installed studies with get_capabilities(source=study); ubi_synthetic is invented demo data. Report sample denominators and exclusions. Private data analysis uses the Ubi platform.",
    "resolve_entity": "Map a name, alias or ambiguous identifier to exact species-qualified IDs before joining evidence. Returns candidates when ambiguous; a provider match score alone is not identity. Skip when you already hold an exact ID.",
    "find_related": "List records linked to one record. gene/drug/disease: articles, trials. variant: articles, structure. article: citations, references, recommendations, authors, entities. author: articles. Record attributes are get_record sections, not relations.",
    "build_dossier": "Build a multi-section dossier in one call: verified identity, default record sections and top related papers, with citations and per-source outcomes. Workflows: target_dossier, model_input_bundle (gene), drug_review, disease_landscape, pathway_review, variant_dossier, negative_evidence (bounded literature check; never proves absence). Add sections with get_record.",
    "query_source": "Run a source-specific operation that other tools do not cover, e.g. ChEMBL bioactivities, Ensembl coordinates, PDB structure quality, OmniPath interactions, NCBI Datasets genomes, ncbi-records for GenBank/GEO/SRA. Read get_capabilities(source=...) for operations and params first.",
}

DESCRIPTIONS = {name: example_description(text, name) for name, text in BASE_DESCRIPTIONS.items()}


def schema(operation):
    from .schema_utils import compact_nullable
    from .utility_contracts import UTILITY_MODELS

    def compact(value):
        if isinstance(value, dict):
            # Enum/const already constrain type. Remove only proven redundant
            # keywords; runtime defaults and validation remain unchanged.
            from jsonschema import Draft202012Validator

            constrained = value.get("enum", [value["const"]] if "const" in value else None)
            redundant_type = (
                constrained is not None
                and "type" in value
                and all(Draft202012Validator({"type": value["type"]}).is_valid(item) for item in constrained)
            )
            return {
                key: compact(item)
                for key, item in value.items()
                if key != "title" and not (key == "type" and redundant_type)
            }
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    value = compact(
        UTILITY_MODELS[operation].model_json_schema()
        if operation in UTILITY_MODELS
        else ADAPTERS[operation].json_schema()
    )
    value["type"] = "object"
    return compact_nullable(value, omit_null_defaults=True)


def native_request(operation, model):
    """Translate one public contract to the existing scientific primitive."""
    data = model.model_dump(exclude_none=True)
    if operation in SEARCH_TASKS.values():
        entity = next(k for k, v in SEARCH_TASKS.items() if v == operation)
        return "search", SearchRequest(entity=entity, **data)
    if operation == "search_records":
        return "search", SearchRequest(**data)
    if operation == "get_record":
        return "get", GetRequest(**data)
    if operation == "get_variant_evidence":
        return "get", GetRequest(entity=Entity.variant, **data)
    if operation == "analyze_study":
        analysis = STUDY_ANALYSES[data.pop("analysis")]
        return "query_source", SourceRequest(source="study", operation=analysis, params=data)
    if operation == "build_dossier":
        data["workflow"] = WORKFLOW_NAMES.get(data["workflow"], data["workflow"])
        return "research", WorkflowRequest(**data)
    return NATIVE_OPERATIONS[operation], model


def canonical_action(action):
    action = deepcopy(action)
    params = action.get("arguments", action)
    tool = PUBLIC_TOOLS.get(action.get("tool"), action.get("tool"))
    if "tool" in action:
        action["tool"] = tool
    entity = params.get("entity")
    replacement = (
        SEARCH_TASKS.get(entity)
        if tool == "search_records"
        else GET_TASKS.get(entity)
        if tool == "get_record"
        else None
    )
    if replacement:
        action["tool"] = replacement
        params.pop("entity", None)
        if replacement == "get_variant_evidence":
            params.pop("species", None)
            if not params.get("source_versions"):
                params.pop("source_versions", None)
    return action


@cache
def action_validator(tool):
    from jsonschema import Draft202012Validator

    return Draft202012Validator(schema(tool))


def validated_action(action):
    """Canonicalize a service request and reject executable/schema extensions."""
    from pydantic import ValidationError

    from .errors import ResearchError

    try:
        if not isinstance(action, dict) or set(action) != {"tool", "arguments"}:
            raise ValueError
        if not isinstance(action["tool"], str) or not isinstance(action["arguments"], dict):
            raise TypeError
        value = canonical_action(action)
        ADAPTERS[value["tool"]].validate_python(value["arguments"])
        if not action_validator(value["tool"]).is_valid(value["arguments"]):
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError, ValidationError):
        # Never include the rejected operation, argument names or source text.
        raise ResearchError("invalid_output", "The service generated an invalid follow-up request.") from None


def operation_map():
    """Complete mapping of primitives to their single advertised owner."""
    rows = []
    for kind, sources in SEARCH_SOURCES.items():
        if sources:
            rows.append(
                {
                    "primitive": f"search/{kind}",
                    "tool": SEARCH_TASKS.get(kind, "search_records"),
                    "sources": sources,
                    "handler": "ResearchService.search",
                }
            )
    for kind, source in RECORD_OWNER.items():
        for section, owner in {"record": source, **SECTIONS[kind]}.items():
            rows.append(
                {
                    "primitive": f"get/{kind}/{section}",
                    "tool": GET_TASKS.get(kind, "get_record"),
                    "sources": [owner],
                    "identity_dependencies": sorted(SECTION_DEPENDENCIES.get((kind, section), set())),
                    **(
                        {
                            "conditional_identity_dependencies": {
                                "mygene": "Entrez inputs or composed gene enrichment"
                            }
                        }
                        if kind == "gene" and owner == "gtex"
                        else {
                            "conditional_identity_dependencies": {
                                "myvariant": "Non-protein identifiers require one exact allele and one gene/protein change"
                            }
                        }
                        if kind == "variant" and section == "civic"
                        else {}
                    ),
                    "handler": "ResearchService.get",
                }
            )
    for kind, relations in RELATIONS.items():
        for relation in relations:
            rows.append(
                {
                    "primitive": f"relate/{kind}/{relation}",
                    "tool": "find_related",
                    "handler": "ResearchService.relate",
                }
            )
    for source, operations in ADVANCED.items():
        for operation in sorted(operations):
            rows.append(
                {
                    "primitive": f"source/{source}/{operation}",
                    "tool": "analyze_study" if source == "study" else "query_source",
                    "sources": [source],
                    "handler": "ResearchService.source",
                }
            )
    for workflow in WORKFLOWS:
        rows.append(
            {
                "primitive": f"workflow/{workflow}",
                "tool": RETIRED_WORKFLOWS.get(workflow, "build_dossier"),
                "public_workflow": "variant_dossier" if workflow == "variant_evidence" else workflow,
                "retired_alias": workflow in RETIRED_WORKFLOWS,
                "handler": "ResearchService.research",
            }
        )
    return rows


def public_capabilities(value):
    value = deepcopy(value)
    value["schema_version"] = "1.0"
    if "canonical_routes" in value:
        value["canonical_routes"] = [canonical_action(route) for route in value["canonical_routes"]]
    if value.get("source") == "study":
        from .study_derivations import DERIVED_RECORDS
        from .study_metadata import StudyMetadataRecord
        from .study_records import StudyMeasurementRecord, StudyMutationProfileRecord

        value["record_schemas"] = {
            "study_metadata": StudyMetadataRecord.model_json_schema(),
            "study_measurements": StudyMeasurementRecord.model_json_schema(),
            "study_mutation_profile": StudyMutationProfileRecord.model_json_schema(),
            "study_derived": DERIVED_RECORDS.json_schema(),
        }
        value["operations"] = []
        value["canonical_routes"].append({"tool": "analyze_study", "analyses": list(STUDY_ANALYSES)})
    if value.get("source") == "gnomad":
        from .native.gnomad import VariantPopulationRecord

        value["record_schemas"] = {"variant_population": VariantPopulationRecord.model_json_schema()}
        value["record_validation"] = (
            "The field schema describes population records. Production validators also enforce allele identity, frequency arithmetic, missingness, source-input hashes, input pointers and outcomes. Bounded views can omit ancestry rows; recover the acquired snapshot using its evidence resources."
        )
    if value.get("source") == "gtex":
        from .expression_records import EXPRESSION_RECORDS
        from .qtl_records import PUBLIC_QTL_RECORDS

        value["record_schemas"] = {
            "expression": EXPRESSION_RECORDS.json_schema(),
            "qtl": PUBLIC_QTL_RECORDS.json_schema(),
        }
        value["record_validation"] = (
            "Gene median/tissue expression and five public QTL assertions have separate field schemas. QTL covers single-tissue eQTL/sQTL, eQTL MetaSoft and dynamic eQTL/sQTL gene sections. Production validators enforce qualified gene/allele/release, prefilter source hashes/page/row pointers, paired counts and retained dynamic sQTL gene/intron inputs. A dynamic release is labeled acquisition scope when absent from its source row. MetaSoft posterior and p-values remain distinct. Record and paired-value counts do not establish unique participants or missing measurements. Bounded arrays can be recovered through acquired evidence resources; preserve alignment within one snapshot."
        )
    if value.get("source") == "interpro":
        value["scientific_interpretation"] = (
            "Protein domains sections retain typed InterPro entries, verified accession/species/length, fragments, observed release and scoped get actions. Families/sites are not renamed domains. Variant structure maps predicted fragment overlaps and preserves partial failures; identical sequence releases and experimental variant effects are not established. See docs/interpro-matches.md."
        )
    if value.get("source") == "complexportal":
        value["scientific_interpretation"] = (
            "Free-text search hits are discovery, not membership counts. The complexes section verifies an exact UniProt participant and matching complex/participant species. Unknown species and isoform-only candidates remain unqualified. Source flags and nullable stoichiometry text do not establish experimental binding. Scoped get actions preserve raw offsets despite filtering/duplicates, with a 1000-candidate bound. Totals and sequence fingerprints are checked across continuation; search ordering/release remains time-dependent. See docs/complex-membership.md."
        )
    if value.get("source") == "reactome":
        value["scientific_interpretation"] = (
            "Search returns individual Pathway text matches with forced human/type filters and scoped continuation. Gene memberships use resolved symbols and explicit species through the UniProt mapping resource. Pathway events include subpathways and reactions; the genes section retains physical participants/reference entities, not an inferred gene list or pairwise interactions. Disease pathways are literal annotation text matches, not verified ontology/mechanistic associations. Diagrams return layout JSON or checked external image locators; current URLs are mutable, SVG remains untrusted, and omitted JSON fields use acquired evidence recovery. See docs/reactome-contracts.md."
        )
    if "workflows" in value:
        value["workflows"] = list(workflow_names)
    if "schemas" in value:
        kind = value["entity"]
        names = set()
        if SEARCH_SOURCES.get(kind):
            names.add(SEARCH_TASKS.get(kind, "search_records"))
        if kind in RECORD_OWNER:
            names.add(GET_TASKS.get(kind, "get_record"))
        value["schemas"] = {name: schema(name) for name in sorted(names)}
    value["routing"] = (
        "Papers: search_literature. Trials: search_trials. Variants: get_variant_evidence. Installed studies: analyze_study. Other records: search_records, then get_record. Linked records: find_related. Multi-section summaries: build_dossier. Source-specific operations only: query_source."
    )
    value["tools"] = [{"name": name, "description": DESCRIPTIONS[name]} for name in MODELS]
    return value
