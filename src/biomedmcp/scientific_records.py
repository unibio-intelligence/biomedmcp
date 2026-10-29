"""Typed public literature metadata and independent source assertions.

Identity is bibliographic: it never implies an organism or experimental cohort.
Original retained source fields remain data through the open record extension.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ResearchError

LiteratureSource = Literal["pubmed", "europepmc", "pubtator", "litsense2", "openalex"]


class BibliographicIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    namespace: Literal["pmid", "pmcid", "doi", "europepmc", "openalex"]
    source: LiteratureSource
    value: str = Field(min_length=1, max_length=512)
    evidence_ids: list[str] = Field(default_factory=list)


class LiteratureAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["retraction", "open_access", "citation_count"]
    source: LiteratureSource
    value: bool | int | None
    missingness: Literal["reported", "not_supplied"]
    unit: Literal["flag", "citations"]
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def meaning(self):
        if (self.value is None) != (self.missingness == "not_supplied"):
            raise ValueError("Assertion missingness must match the supplied value")
        if self.kind == "citation_count":
            if self.unit != "citations" or (
                self.value is not None and (type(self.value) is not int or self.value < 0)
            ):
                raise ValueError("Citation counts are nonnegative integer source counts")
        elif self.unit != "flag" or (self.value is not None and type(self.value) is not bool):
            raise ValueError("Retraction and access assertions are nullable flags")
        return self


class LiteratureRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    record_type: Literal["literature"] = "literature"
    identities: list[BibliographicIdentity] = Field(min_length=1, max_length=64)
    content_scope: Literal["bibliographic", "provider_excerpt", "sentence_excerpt"]
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    date: str | None = None
    authors: list[str | None] = Field(default_factory=list)
    author_completeness: Literal["complete", "source_limited"] = "source_limited"
    citation_count: int | None = Field(default=None, ge=0)
    is_open_access: bool | None = None
    is_retracted: bool | None = None
    source_assertions: list[LiteratureAssertion]


def literature_record(row: dict, source: LiteratureSource, *, provider_identity=None) -> dict:
    import re
    from datetime import UTC, date, datetime

    supplied = row.get("date")
    status = "not_supplied"
    if isinstance(supplied, str):
        match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", supplied)
        status = "unparsed"
        if match:
            try:
                year, month, day = match.groups()
                parsed = date(int(year), int(month or 1), int(day or 1))
                today = datetime.now(UTC).date()
                status = "future_dated" if parsed > today else "valid"
            except ValueError:
                status = "invalid_calendar_date"
    row = {
        **row,
        "date_validation": {
            "status": status,
            "interpretation": "Provider publication date; future issue dates can be legitimate and are not proof of publication.",
        },
    }
    identities = []
    for field, namespace in (
        ("pmid", "pmid"),
        ("pmcid", "pmcid"),
        ("doi", "doi"),
        ("openalex_id", "openalex"),
    ):
        value = row.get(field)
        if value is not None:
            identities.append({"namespace": namespace, "value": value, "source": source})
    if not identities and provider_identity:
        identities.append({"namespace": "europepmc", "value": provider_identity, "source": source})
    assertions = []
    for kind, field, unit in (
        ("retraction", "is_retracted", "flag"),
        ("open_access", "is_open_access", "flag"),
        ("citation_count", "citation_count", "citations"),
    ):
        value = row.get(field)
        assertions.append(
            {
                "kind": kind,
                "source": source,
                "value": value,
                "missingness": "not_supplied" if value is None else "reported",
                "unit": unit,
            }
        )
    try:
        return LiteratureRecord.model_validate(
            {
                **row,
                "record_type": "literature",
                "identities": identities,
                "content_scope": "sentence_excerpt"
                if source == "litsense2"
                else "provider_excerpt"
                if source == "pubtator"
                else "bibliographic",
                "source_assertions": assertions,
            }
        ).model_dump(mode="json")
    except ValidationError:
        raise ResearchError(
            "invalid_source_response", "Provider literature metadata violates its scientific record contract."
        ) from None


def source_count(value, *, decimal_text=False):
    if value is None:
        return None
    if decimal_text and isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    if type(value) is not int or value < 0:
        raise ResearchError(
            "invalid_source_response", "Provider citation count is not a nonnegative integer."
        )
    return value


def source_pmid(value):
    # These sentence/excerpt APIs may encode a PMID as a JSON integer.
    # Booleans, compound values and arbitrary strings are never identities.
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return value
    raise ResearchError("invalid_source_response", "Provider article identity is not a PMID.")


def epmc_flag(value):
    if value is None:
        return None
    if not isinstance(value, str) or value not in {"Y", "N"}:
        raise ResearchError(
            "invalid_source_response", "Provider literature flag violates its source contract."
        )
    return value == "Y"
