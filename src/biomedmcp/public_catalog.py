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

SEARCH_TASKS = {"article": "literature_search", "trial": "trial_search"}
GET_TASKS = {"variant": "variant_evidence"}
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
    "literature_review": "literature_search",
    "patent_landscape": "search",
    "study_summary": "search",
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
    cursor: str | None = Field(default=None, max_length=2048)
    output: Literal["summary", "full"] = Field(
        default="summary",
        description="Summary bounds record excerpts; full retains source fields within the response budget. Omitted evidence has recovery resources.",
    )
    freshness: Freshness = "cached_if_fresh"


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
    tissue_id: str | None = Field(default=None, max_length=128)
    query_type: Literal["gene_median", "gene_tissue"] = "gene_median"
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE)


class QTLParameters(StrictModel):
    tissue_id: str = Field(min_length=1, max_length=128)
    analysis_mode: Literal["gene_associations", "metasoft", "dynamic"] = "gene_associations"
    variant_id: str | None = Field(default=None, max_length=128)
    phenotype_id: str | None = Field(default=None, min_length=1, max_length=128)
    p_value_threshold: float = Field(default=0.05, gt=0, le=1)
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE)


class GeneAnnotationParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=0, ge=0, le=MAX_PROVIDER_PAGE)


class FulltextParameters(FulltextWindow):
    """One-based inclusive lines, end >= start, up to 100. Defaults: 1–100."""


class AssetParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0, le=10000)


class CivicParameters(StrictModel):
    limit: int = Field(default=10, ge=1, le=25)
    collection: Literal["evidenceItems", "assertions"] | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=2048)

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
    id: str = Field(min_length=1, max_length=512)
    sections: list[Literal[record_sections]] = Field(default_factory=list, max_length=12)
    sources: list[str] = Field(default_factory=list, max_length=12)
    species: int = Field(default=9606, gt=0)
    source_versions: dict[str, str] = Field(default_factory=dict, max_length=8)
    section_parameters: RecordParameters = Field(default_factory=RecordParameters)
    freshness: Freshness = "cached_if_fresh"

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
    molecular_profile_id: str = Field(min_length=1, max_length=200)
    sample_list_id: str = Field(min_length=1, max_length=200)


class VariantParameters(StrictModel):
    cbioportal: CohortReference | None = None
    civic: CivicParameters | None = None
    gwas: GeneAnnotationParameters | None = None


variant_sections = ("record", *SECTIONS["variant"])


class VariantEvidence(StrictModel):
    id: str = Field(min_length=1, max_length=512)
    assembly: Literal["grch37", "grch38"] | None = None
    sections: list[Literal[variant_sections]] = Field(
        default_factory=lambda: ["clinvar", "population", "civic"], max_length=12
    )
    sources: list[str] = Field(default_factory=list, max_length=12)
    section_parameters: VariantParameters = Field(default_factory=VariantParameters)
    freshness: Freshness = "cached_if_fresh"


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


class ResearchWorkflow(WorkflowRequest):
    workflow: Literal[workflow_names]
    section_parameters: DossierParameters = Field(default_factory=DossierParameters)


class PublicSource(SourceRequest):
    source: Literal[tuple(k for k in ADVANCED if k != "study")]


MODELS = {
    "search": RecordSearch,
    "get": RecordGet,
    "literature_search": LiteratureSearch,
    "trial_search": TrialSearch,
    "variant_evidence": VariantEvidence,
    "study_analysis": StudyAnalysis,
    "resolve": ResolveRequest,
    "relate": RelateRequest,
    "research": ResearchWorkflow,
    "query_source": PublicSource,
}
ADAPTERS = {name: TypeAdapter(model) for name, model in MODELS.items()}
BASE_DESCRIPTIONS = {
    "search": "Find ordinary records with entity filters. Papers use literature_search; trials use trial_search.",
    "get": "Read ordinary records/evidence sections; variants use variant_evidence. Sources constrain all lookups and identity dependencies.",
    "literature_search": "Find papers with publication/topic/source filters; deduplicate evidence and retain source outcomes and opaque continuation.",
    "trial_search": "Find public clinical trials using disease/intervention and trial-specific filters. Does not determine individual clinical eligibility.",
    "variant_evidence": "Retrieve variant evidence with assembly/transcript ambiguity preserved. Defaults: ClinVar, population, CIViC. Request predictions for AlphaMissense, or eve for MIT-licensed EVE protein scores; computational predictions retain source and uncertainty.",
    "study_analysis": "Analyze an installed verified public study. Bundled ubi_synthetic is an invented demo; discover installed releases with capabilities(source=study). Report clinical and assayed samples separately, unique mutant samples, events and exclusions. Preserve input hashes and denominators. Private compute uses Ubi platform.",
    "resolve": "Resolve aliases/ambiguity before evidence joins. One exact species-qualified symbol/ID resolves; provider score alone never establishes identity. Retrieve known unambiguous identifiers directly.",
    "relate": "Traverse an evidence relationship. Relations: gene/drug/disease: articles,trials; variant: articles,structure; article: citations,references,recommendations,authors,entities; author: articles.",
    "research": "Dossiers retain citations/outcomes. Inspect capabilities and get further sections for completeness.",
    "query_source": "Run advanced source operations after checking capabilities/schema. Common tasks have dedicated tools.",
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
    if operation == "search":
        return "search", SearchRequest(**data)
    if operation == "get":
        return "get", GetRequest(**data)
    if operation == "variant_evidence":
        return "get", GetRequest(entity=Entity.variant, **data)
    if operation == "study_analysis":
        analysis = STUDY_ANALYSES[data.pop("analysis")]
        return "query_source", SourceRequest(source="study", operation=analysis, params=data)
    if operation == "research":
        data["workflow"] = WORKFLOW_NAMES.get(data["workflow"], data["workflow"])
        return operation, WorkflowRequest(**data)
    return operation, model


def canonical_action(action):
    action = deepcopy(action)
    params = action.get("arguments", action)
    tool = action.get("tool")
    entity = params.get("entity")
    replacement = (
        SEARCH_TASKS.get(entity) if tool == "search" else GET_TASKS.get(entity) if tool == "get" else None
    )
    if replacement:
        action["tool"] = replacement
        params.pop("entity", None)
        if replacement == "variant_evidence":
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
                    "tool": SEARCH_TASKS.get(kind, "search"),
                    "sources": sources,
                    "handler": "ResearchService.search",
                }
            )
    for kind, source in RECORD_OWNER.items():
        for section, owner in {"record": source, **SECTIONS[kind]}.items():
            rows.append(
                {
                    "primitive": f"get/{kind}/{section}",
                    "tool": GET_TASKS.get(kind, "get"),
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
                    "tool": "relate",
                    "handler": "ResearchService.relate",
                }
            )
    for source, operations in ADVANCED.items():
        for operation in sorted(operations):
            rows.append(
                {
                    "primitive": f"source/{source}/{operation}",
                    "tool": "study_analysis" if source == "study" else "query_source",
                    "sources": [source],
                    "handler": "ResearchService.source",
                }
            )
    for workflow in WORKFLOWS:
        rows.append(
            {
                "primitive": f"workflow/{workflow}",
                "tool": RETIRED_WORKFLOWS.get(workflow, "research"),
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
        value["canonical_routes"].append({"tool": "study_analysis", "analyses": list(STUDY_ANALYSES)})
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
            names.add(SEARCH_TASKS.get(kind, "search"))
        if kind in RECORD_OWNER:
            names.add(GET_TASKS.get(kind, "get"))
        value["schemas"] = {name: schema(name) for name in sorted(names)}
    value["routing"] = (
        "Scientific tasks own literature/trial discovery, variant evidence and study analysis. Search/get cover remaining reads; relate traverses identities; research composes declared dossiers; advanced sources expose distinct operations only."
    )
    value["tools"] = [{"name": name, "description": DESCRIPTIONS[name]} for name in MODELS]
    return value
