"""Scientific request/result contracts shared by MCP, CLI and application calls."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FulltextWindow(StrictModel):
    view: Literal["outline", "lines", "assets"] = "outline"
    start: int = Field(default=1, ge=1, le=100000)
    end: int = Field(default=100, ge=1, le=100000)

    @model_validator(mode="after")
    def line_bounds(self):
        if self.end < self.start or self.end - self.start >= 100:
            raise ValueError("Use an inclusive full-text range of at most 100 lines")
        return self


class Entity(StrEnum):
    gene = "gene"
    variant = "variant"
    article = "article"
    author = "author"
    trial = "trial"
    drug = "drug"
    disease = "disease"
    phenotype = "phenotype"
    protein = "protein"
    pathway = "pathway"
    pgx = "pgx"
    gwas = "gwas"
    diagnostic = "diagnostic"
    adverse_event = "adverse-event"
    study = "study"
    patent = "patent"
    sequence = "sequence"


Freshness = Literal["cached_if_fresh", "fresh"]
Outcome = Literal["data", "empty", "partial", "ambiguous", "unavailable", "not_applicable", "error"]
FilterText = Annotated[str, Field(min_length=1, max_length=256)]


class SearchFilters(StrictModel):
    gene: str | None = Field(default=None, max_length=128)
    disease: list[FilterText] = Field(default_factory=list, max_length=5)
    drug: list[FilterText] = Field(default_factory=list, max_length=5)
    source: str | None = Field(default=None, max_length=64)
    date_from: date | None = None
    date_to: date | None = None
    phase: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=64)
    open_access: bool | None = None
    no_preprints: bool | None = None
    sort: Literal["relevance", "date", "citations"] | None = None
    species: int = Field(default=9606, gt=0)
    author: list[FilterText] = Field(default_factory=list, max_length=5)
    journal: list[FilterText] = Field(default_factory=list, max_length=5)
    article_type: str | None = Field(default=None, max_length=64)
    ranking_mode: Literal["lexical", "provider", "hybrid"] | None = None
    hgvsp: str | None = Field(default=None, max_length=128)
    significance: str | None = Field(default=None, max_length=64)
    consequence: str | None = Field(default=None, max_length=64)
    max_frequency: float | None = Field(default=None, ge=0, le=1)
    revel_min: float | None = Field(default=None, ge=0, le=1)
    review_status: str | None = Field(default=None, max_length=64)
    reviewed: bool | None = None
    existence: int | None = Field(default=None, ge=1, le=5)
    p_value: float | None = Field(default=None, gt=0, le=1)
    trait: str | None = Field(default=None, max_length=256)
    cpic_level: str | None = Field(default=None, max_length=32)
    region: Literal["us", "eu", "who", "all"] | None = None
    product_type: Literal["finished_pharma", "api", "vaccine"] | None = None
    manufacturer: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class SearchRequest(StrictModel):
    output: Literal["summary", "full"] = "summary"
    entity: Entity
    query: str = Field(min_length=1, max_length=512)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=10, ge=1, le=25)
    cursor: str | None = Field(default=None, max_length=2048)
    freshness: Freshness = "cached_if_fresh"


class GetRequest(StrictModel):
    sources: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Restrict the entire provider plan, including identity resolution. Empty selects section owners. Explicit sections omit the default record.",
    )
    entity: Entity
    id: str = Field(min_length=1, max_length=512)
    sections: list[str] = Field(default_factory=list, max_length=12)
    assembly: Literal["grch37", "grch38"] | None = None
    species: int = Field(default=9606, gt=0)
    source_versions: dict[str, str] = Field(default_factory=dict, max_length=8)
    section_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=12)
    freshness: Freshness = "cached_if_fresh"

    @model_validator(mode="after")
    def unique_sections(self):
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("sections must be unique")
        if any(not section or len(section) > 64 for section in self.sections):
            raise ValueError("Invalid section name")
        return self


class ResolveRequest(StrictModel):
    query: str = Field(min_length=1, max_length=512)
    entity: Entity | None = None
    species: int = Field(default=9606, gt=0)
    assembly: Literal["grch37", "grch38"] | None = None


class RelateRequest(StrictModel):
    entity: Entity
    id: str = Field(min_length=1, max_length=512)
    relation: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=10, ge=1, le=25)
    species: int = Field(default=9606, gt=0)
    assembly: Literal["grch37", "grch38"] | None = None


class SourceRequest(StrictModel):
    source: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict, max_length=32)
    freshness: Freshness = "cached_if_fresh"


class WorkflowRequest(StrictModel):
    workflow: str = Field(min_length=1, max_length=64)
    focus: str = Field(min_length=1, max_length=512)
    sections: list[str] | None = Field(default=None, max_length=12)
    section_parameters: dict[str, dict[str, Any]] | None = Field(default=None, max_length=12)
    species: int = Field(default=9606, gt=0)
    assembly: Literal["grch37", "grch38"] | None = None


class BatchCall(StrictModel):
    operation: Literal[
        "search",
        "get",
        "literature_search",
        "trial_search",
        "variant_evidence",
        "study_analysis",
        "resolve",
        "relate",
        "query_source",
    ]
    arguments: dict[str, Any] = Field(max_length=16)


class VariantIdentity(StrictModel):
    gene: str
    assembly: str | None = None
    chromosome: str | None = None
    position: int | None = None
    reference: str | None = None
    alternate: str | None = None
    transcript: str | None = None
    hgvsc: str | None = None
    protein: str | None = None
    hgvsp: str | None = None

    def equivalent_to(self, other: VariantIdentity) -> bool:
        if self.gene != other.gene:
            return False
        # All shared identity fields must agree; disjoint arrays are never joined.
        left, right = self.model_dump(), other.model_dump()
        if any(left[k] is not None and right[k] is not None and left[k] != right[k] for k in left):
            return False
        for keys in (
            ("assembly", "chromosome", "position", "reference", "alternate"),
            ("transcript", "hgvsc"),
            ("protein", "hgvsp"),
        ):
            if all(left[k] is not None and right[k] is not None and left[k] == right[k] for k in keys):
                return True
        return False


class Provenance(StrictModel):
    evidence_id: str
    source: str
    sources: list[str] = Field(default_factory=list)
    processor: str | None = None
    record_id: str | None = None
    url: str | None = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_version: str | None = None
    content_hash: str
    cached: bool = False

    @field_validator("url")
    @classmethod
    def citation_locator(cls, value):
        from .content_boundary import safe_link

        return value if value is None or safe_link(value) else None


class Section(StrictModel):
    outcome: Outcome
    data: Any = None
    evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    truncated: bool = False
    recovery: dict[str, Any] = Field(default_factory=dict)


class EvidenceReceipt(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    implementation: str = Field(pattern=r"^biomedmcp/\d+\.\d+\.\d+$")
    operation: str = Field(
        pattern=r"^(search|get|literature_search|trial_search|variant_evidence|study_analysis|resolve|relate|research|query_source)$"
    )
    request: dict[str, Any] | None
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=64)
    completed_at: AwareDatetime
    request_redacted: bool
    request_omitted: bool
    time_dependent: bool
    reproduction: Literal["not_established"] = "not_established"

    @model_validator(mode="after")
    def bounded_request(self):
        import json

        if self.request_omitted != (self.request is None):
            raise ValueError("Omitted request flag must match request availability")
        if (
            self.request is not None
            and len(json.dumps(self.request, ensure_ascii=False, allow_nan=False).encode()) > 8192
        ):
            raise ValueError("Normalized request exceeds the receipt budget")
        return self


class ResearchResult(StrictModel):
    # Retain the exact composed rows/views before a byte-budget mutation. This
    # never enters discovery or wire output; dispatch stores a scoped snapshot.
    _omitted_evidence: dict | None = PrivateAttr(default=None)
    schema_version: Literal["1.0"] = "1.0"
    content_policy: Literal["data_only"] = "data_only"
    rejected_links: dict[str, str] = Field(default_factory=dict)
    entity: Entity | None = None
    outcome: Outcome
    records: list[dict[str, Any]] = Field(default_factory=list)
    sections: dict[str, Section] = Field(default_factory=dict)
    provenance: list[Provenance] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str | None = None
    truncated: bool = False
    query: dict[str, Any] = Field(default_factory=dict)
    receipt: EvidenceReceipt | None = None

    @model_validator(mode="after")
    def output_budget(self):
        import json

        def size():
            return len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False, allow_nan=False).encode())

        if size() <= 120000:
            return self
        if self._omitted_evidence is None:
            self._omitted_evidence = {
                "records": list(self.records),
                "sections": {name: section.data for name, section in self.sections.items()},
            }
        self.truncated = True
        warning = "Output budget reached. Read supplied evidence resources or select a narrower source query."
        if warning not in self.warnings:
            self.warnings.append(warning)
        omissions = self.query.setdefault("output_omissions", {})
        for key, value in {
            "records_before_budget": len(self.records),
            "records_removed": 0,
            "scope": "This composed result, not an exhaustive provider total.",
            "recovery": "Read source snapshots in section recovery metadata for the supporting acquired windows.",
        }.items():
            omissions.setdefault(key, value)
        # Preserve provenance, outcome and errors. Omission is explicit and never
        # changes an unavailable section into healthy empty evidence.
        ordered = sorted(
            self.sections.items(),
            key=lambda pair: len(json.dumps(pair[1].data, default=str)),
            reverse=True,
        )
        for name, section in ordered:
            if size() <= 120000:
                break
            if section.data is not None:
                section.recovery.setdefault(
                    "envelope_omitted",
                    {
                        "section": name,
                        "data_bytes": len(json.dumps(section.data, ensure_ascii=False, default=str).encode()),
                        "reason": "response_byte_budget",
                        "scope": "Bounded section view before envelope omission.",
                    },
                )
                section.data = {"omitted": "Section exceeds the response byte budget; request it separately."}
                section.truncated = True
        while self.records and size() > 120000:
            self.records.pop()
            omissions["records_removed"] += 1
        for section in self.sections.values():
            while size() > 120000 and section.recovery.get("omissions"):
                section.recovery["omissions"].pop()
                section.recovery["omissions_truncated"] = True
        if self.rejected_links and size() > 120000:
            self.warnings.append(
                "Unsafe link metadata exceeds the response budget; some source locators omitted."
            )
            while self.rejected_links and size() > 120000:
                self.rejected_links.pop(next(reversed(self.rejected_links)))
        if size() > 120000:
            from .errors import ResearchError

            raise ResearchError(
                "output_metadata_budget",
                "Scientific context exceeds the response budget; request fewer sections or a narrower source window.",
            )
        return self
