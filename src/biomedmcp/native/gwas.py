"""GWAS Catalog v2 selected association projection and explicit provider windows."""

import math
import re
from decimal import Decimal
from typing import Annotated
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import ResearchError
from ..pagination import page_payload
from .shapes import invalid_shape

BASE = "https://www.ebi.ac.uk/gwas/rest/api/v2/associations"
Text = Annotated[str, Field(min_length=1, max_length=4096)]


class SourceModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def no_application_error(cls, value):
        if isinstance(value, dict) and (
            value.get("error") or value.get("errors") or value.get("success") is False
        ):
            raise ValueError("Source application error")
        return value


class Trait(SourceModel):
    efo_id: Text
    efo_trait: Text


class Allele(SourceModel):
    rs_id: Text
    effect_allele: Text


class Association(SourceModel):
    association_id: int = Field(gt=0)
    accession_id: str = Field(pattern=r"^GCST[0-9]+$")
    p_value: float | None = Field(ge=0, le=1)
    pvalue_mantissa: int | None = Field(default=None, gt=0, le=2147483647)
    pvalue_exponent: int | None = Field(default=None, ge=-10000, le=0)
    multi_snp_haplotype: bool | None = None
    snp_interaction: bool | None = None
    efo_traits: list[Trait] | None = None
    bg_efo_traits: list[Trait] | None = None
    snp_allele: list[Allele] | None = None
    mapped_genes: list[Text] | None = None
    reported_trait: list[Text] | None = None
    locations: list[Text] | None = None
    snp_effect_allele: list[Text] | None = None
    risk_frequency: str | None = None
    pvalue_description: str | None = None
    beta: str | None = None
    range: str | None = None
    description: str | None = None
    beta_unit: str | None = None
    beta_direction: str | None = None
    or_value: str | None = None
    first_author: str | None = None
    pubmed_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    beta_num: float | None = None
    or_per_copy_num: float | None = Field(default=None, gt=0)
    ci_lower: float | None = None
    ci_upper: float | None = None


def object_(value):
    if (
        not isinstance(value, dict)
        or value.get("error")
        or value.get("errors")
        or value.get("success") is False
    ):
        invalid_shape()
    return value


def links(value):
    if "_links" in value and "links" in value:
        invalid_shape()
    if "_links" in value:
        raw = object_(value["_links"])
        result = {}
        for rel, item in raw.items():
            if (
                not isinstance(rel, str)
                or not isinstance(item, dict)
                or not isinstance(item.get("href"), str)
            ):
                invalid_shape()
            result[rel] = item["href"]
        return result
    if "links" in value:
        if not isinstance(value["links"], list):
            invalid_shape()
        result = {}
        for item in value["links"]:
            object_(item)
            if (
                not isinstance(item.get("rel"), str)
                or not isinstance(item.get("href"), str)
                or item["rel"] in result
            ):
                invalid_shape()
            result[item["rel"]] = item["href"]
        return result
    return {}


def url_(value, path):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        invalid_shape()
    try:
        parsed = urlsplit(value)
    except ValueError:
        invalid_shape()
    if parsed.scheme != "https" or parsed.netloc != "www.ebi.ac.uk" or parsed.path != path or parsed.fragment:
        invalid_shape()
    return parsed


def record(raw, *, requested_id=None, rs_id=None):
    object_(raw)
    try:
        model = Association.model_validate(raw)
        projection = model.model_dump(exclude_unset=True)
        row = {key: value for key, value in projection.items() if key in Association.model_fields}
        source_fields = {
            key: value for key, value in projection.items() if key not in Association.model_fields
        }
    except ValidationError:
        invalid_shape()
    identity = str(row["association_id"])
    if requested_id is not None and identity != requested_id:
        invalid_shape()
    if rs_id is not None and not any(a["rs_id"] == rs_id for a in row.get("snp_allele") or []):
        invalid_shape()
    source_links = links(raw)
    if "self" in source_links:
        parsed = url_(source_links["self"], "/gwas/rest/api/v2/associations/" + identity)
        if parsed.query:
            invalid_shape()
    low, high = row.get("ci_lower"), row.get("ci_upper")
    if low is not None and high is not None and low > high:
        invalid_shape()
    mantissa, exponent = row.get("pvalue_mantissa"), row.get("pvalue_exponent")
    if (mantissa is None) != (exponent is None):
        invalid_shape()
    component = Decimal(mantissa).scaleb(exponent) if mantissa is not None else None
    if component is not None and not 0 < component <= 1:
        invalid_shape()
    number = row["p_value"]
    value = Decimal(str(number)) if number is not None and number > 0 else None
    status = (
        "reported" if value is not None else "not_reported" if number is None else "precision_unavailable"
    )
    if component is not None:
        if number is None:
            value, status = component, "reported_components"
        elif number == 0 and float(component) == 0:
            value, status = component, "float_underflow"
        elif not math.isclose(float(component), number, rel_tol=1e-12, abs_tol=0):
            value, status = None, "conflicting_representations"
    return {
        **row,
        **({"source_fields": source_fields} if source_fields else {}),
        "id": identity,
        "url": BASE + "/" + identity,
        "p_value_status": status,
        "p_value_decimal": str(value) if value is not None else None,
        "p_value_components_decimal": str(component) if component is not None else None,
    }


def parameters(limit, offset):
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or offset < 0
        or offset % limit
    ):
        raise ResearchError(
            "invalid_parameters", "GWAS windows require a limit of 1–100 and an aligned offset."
        )
    return {"size": limit, "page": offset // limit, "sort": "p_value", "direction": "asc"}


def query(focus, filters, limit, offset):
    params = parameters(limit, offset)
    for field in ("gene", "trait"):
        if filters.get(field) is not None and (
            not isinstance(filters[field], str) or not filters[field].strip()
        ):
            raise ResearchError("invalid_parameters", "GWAS gene/trait filters require nonempty text.")
    threshold = filters.get("p_value")
    if threshold is not None and (
        type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1
    ):
        raise ResearchError("invalid_parameters", "GWAS p-value threshold must be finite and in (0,1].")
    if re.fullmatch(r"rs\d+", focus):
        if not re.fullmatch(r"rs[1-9]\d*", focus):
            raise ResearchError("invalid_identifier", "Use a canonical positive dbSNP rsID.")
        params["rs_id"] = focus
    if filters.get("trait"):
        params["efo_trait"] = filters["trait"]
        params["show_child_trait"] = "false"
    if filters.get("gene") or not (params.get("rs_id") or params.get("efo_trait")):
        params["mapped_gene"] = filters.get("gene") or focus
        params["extended_geneset"] = "false"
    return params


def window(data, params, threshold=None):
    object_(data)
    meta = object_(data.get("page"))
    documented = "content" in data
    keys = (
        ("size", "total_elements", "total_pages", "number")
        if documented
        else ("size", "totalElements", "totalPages", "number")
    )
    if any(type(meta.get(k)) is not int or meta[k] < 0 for k in keys):
        invalid_shape()
    size, total, pages, number = (meta[k] for k in keys)
    if size != params["size"] or number != params["page"] or pages != (total + size - 1) // size:
        invalid_shape()
    expected_count = max(0, min(size, total - number * size))
    if documented:
        if "_embedded" in data or "associations" in data:
            invalid_shape()
        raw = data["content"]
    elif "_embedded" in data:
        raw = object_(data["_embedded"]).get("associations")
    else:
        if "associations" in data or expected_count:
            invalid_shape()
        raw = []
    if not isinstance(raw, list) or len(raw) != expected_count:
        invalid_shape()
    source_links = links(data)
    for rel in ("self", "next", "prev", "first", "last"):
        if rel not in source_links:
            continue
        parsed = url_(source_links[rel], "/gwas/rest/api/v2/associations")
        values = parse_qs(parsed.query, keep_blank_values=True)
        expected_page = {
            "self": number,
            "next": number + 1,
            "prev": number - 1,
            "first": 0,
            "last": max(0, pages - 1),
        }[rel]
        wanted = {**params, "page": expected_page}
        if rel == "next" and expected_page >= pages or rel == "prev" and expected_page < 0:
            invalid_shape()
        if any(len(v) != 1 for v in values.values()) or any(
            values.get(k) != [str(v)] for k, v in wanted.items()
        ):
            invalid_shape()
        if set(values) - set(wanted):
            invalid_shape()
    rows = [record(r, rs_id=params.get("rs_id")) for r in raw]
    if len({r["id"] for r in rows}) != len(rows):
        invalid_shape()
    unknown = sum(r["p_value_decimal"] is None for r in rows)
    conflicting = sum(r["p_value_status"] == "conflicting_representations" for r in rows)
    if threshold is not None:
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
            raise ResearchError("invalid_parameters", "GWAS p-value threshold must be finite and in (0,1].")
        threshold_decimal = Decimal(str(threshold))
        rows = [
            r
            for r in rows
            if r["p_value_decimal"] is None or Decimal(r["p_value_decimal"]) <= threshold_decimal
        ]
    exhausted = number + 1 >= pages
    partial = conflicting > 0 or threshold is not None and unknown > 0
    payload = page_payload(
        rows,
        raw_count=len(raw),
        total=total,
        exhausted=exhausted,
        next_offset=None if exhausted else (number + 1) * size,
        filtered_count=len(raw) - len(rows),
        filtering={"p_value": len(raw) - len(rows), "p_value_unavailable": unknown},
        exhaustion_basis="total",
    )
    payload["coverage"] = {
        "api": "GWAS Catalog v2",
        "source_offset": number * size,
        "raw_window_count": len(raw),
        "total_source_associations": total,
        "provider_window_exhausted": exhausted,
        "p_value_unavailable": unknown,
        "conflicting_p_value_representations": conflicting,
        "collection": "literature_curated_top_associations",
        "assembly": "not_qualified",
        "interpretation": "Catalog associations are not causal, clinical or experimental variant-effect classifications; mapped genes do not establish causal target genes.",
    }
    if partial:
        payload["section_outcomes"] = {"p_value_interpretation": {"outcome": "partial"}}
        payload["warnings"] = [
            "Unknown or conflicting p-values are retained; they are not classified as failing the significance threshold."
        ]
    return payload
