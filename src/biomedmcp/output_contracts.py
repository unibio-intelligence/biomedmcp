"""Self-contained public wire schemas, shared by MCP and CLI consumers.

Selected scientific records have typed record families; other records remain
source-specific. These contracts also qualify the
envelope, evidence receipt, status, provenance, continuation and error boundary.
"""

from copy import deepcopy
from functools import cache
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .contracts import ResearchResult, StrictModel
from .errors import ResearchError
from .schema_utils import compact_nullable
from .scientific_records import LiteratureRecord
from .trial_records import TrialRecord

CATALOG_BYTE_BUDGET = 98304


class ErrorInfo(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    message: str
    retryable: bool
    correction: str
    fields: dict[str, str] = Field(default_factory=dict, max_length=8)


class ErrorResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    outcome: Literal["error"] = "error"
    error: ErrorInfo


class BatchResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    outcome: Literal["data", "partial", "error"]
    results: list[ResearchResult | ErrorResult] = Field(min_length=1, max_length=10)


class QuotaBucket(StrictModel):
    bucket: str
    limit: int
    remaining: int
    resets_at: str
    consumed: int | None = Field(default=None, ge=0)
    pending: int | None = Field(default=None, ge=0)
    uncertain: int | None = Field(default=None, ge=0)
    held: int | None = Field(default=None, ge=0)
    over_limit: int | None = Field(default=None, ge=0)


class QuotaResult(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    enabled: bool
    profile: str | None = None
    mode: str | None = None
    usage: int | None = None
    message: str | None = None
    tier: Literal["free", "pro", "enterprise", "admin"] | None = None
    tier_changes: Literal["immediate"] | None = None
    period_start: str | None = None
    buckets: list[QuotaBucket] = Field(default_factory=list)


class ToolSummary(StrictModel):
    name: str
    description: str


class CapabilityResult(BaseModel):
    # Source/entity capability documents contain source-specific schemas. Keep
    # those extensions while requiring the canonical public routing metadata.
    model_config = ConfigDict(extra="allow")
    schema_version: Literal["1.0"] = "1.0"
    routing: str
    tools: list[ToolSummary]


def _compact(value: Any) -> Any:
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: {name: _compact(schema) for name, schema in item.items()}
            if key in {"properties", "$defs"}
            else _compact(item)
            for key, item in value.items()
            if key not in {"title", "default", "description"}
            and not (key == "type" and ("const" in value or "enum" in value))
        }
    return value


@cache
def _output_schema(name: str) -> dict:
    model = {"batch": BatchResult, "capabilities": CapabilityResult, "quota": QuotaResult}.get(
        name, ResearchResult
    )
    value = _compact(TypeAdapter(model | ErrorResult).json_schema())
    value["type"] = "object"
    for definition in value.get("$defs", {}).values():
        if "schema_version" in definition.get("properties", {}):
            definition.setdefault("required", []).append("schema_version")
        if "content_policy" in definition.get("properties", {}):
            definition.setdefault("required", []).append("content_policy")
        if "outcome" in definition.get("properties", {}) and "outcome" not in definition.get("required", []):
            definition.setdefault("required", []).append("outcome")
    if "Section" in value.get("$defs", {}):
        value["$defs"]["Section"]["properties"]["error"] = {
            "anyOf": [{"$ref": "#/$defs/ErrorInfo"}, {"type": "null"}]
        }
    if "ResearchResult" in value.get("$defs", {}):
        result = value["$defs"]["ResearchResult"]
        result["properties"]["receipt"] = {"$ref": "#/$defs/EvidenceReceipt"}
        result.setdefault("required", []).append("receipt")
        value["$defs"]["EvidenceReceipt"].setdefault("required", []).append("reproduction")
        if name != "batch":
            value["$defs"]["EvidenceReceipt"]["properties"]["operation"] = {"const": name}
        if name in {"trial_search", "variant_evidence"}:
            value["$defs"]["Entity"]["enum"] = ["trial" if name == "trial_search" else "variant"]
        if name == "study_analysis":
            result["properties"]["entity"] = {"const": None}
            value["$defs"].pop("Entity", None)
        if name not in {"batch", "query_source", "study_analysis"}:
            result["properties"]["source"] = {"const": None}
    # Only these public operations can return bibliographic records. Keep each
    # advertised schema self-contained without copying unreachable families.
    if name in {"get", "resolve", "literature_search", "relate", "research", "batch"}:
        result = value["$defs"]["ResearchResult"]
        literature = _compact(LiteratureRecord.model_json_schema())
        literature.setdefault("required", []).append("record_type")
        value["$defs"].update(literature.pop("$defs", {}))
        value["$defs"]["LiteratureAssertion"]["allOf"] = [
            {
                "if": {"properties": {"kind": {"const": "citation_count"}}},
                "then": {
                    "properties": {
                        "unit": {"const": "citations"},
                        "value": {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}]},
                    }
                },
                "else": {
                    "properties": {
                        "unit": {"const": "flag"},
                        "value": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                    }
                },
            },
            {
                "if": {"properties": {"missingness": {"const": "not_supplied"}}},
                "then": {"properties": {"value": {"type": "null"}}},
                "else": {"properties": {"value": {"not": {"type": "null"}}}},
            },
        ]
        value["$defs"]["LiteratureRecord"] = literature
        tagged = {
            "if": {
                "type": "object",
                "required": ["record_type"],
                "properties": {"record_type": {"const": "literature"}},
            },
            "then": {"$ref": "#/$defs/LiteratureRecord"},
        }
        result["properties"]["records"]["items"]["allOf"] = [tagged]
        value["$defs"]["Section"]["properties"]["data"] = tagged
    if name in {"trial_search", "get", "resolve", "relate", "batch"}:
        result = value["$defs"]["ResearchResult"]
        trial = _compact(TrialRecord.model_json_schema())
        trial.setdefault("required", []).extend(["record_type", "assertion_type", "species"])
        value["$defs"].update(trial.pop("$defs", {}))
        value["$defs"]["TrialEnrollment"].setdefault("required", []).append("unit")
        value["$defs"]["TrialRecord"] = trial
        tagged = {
            "if": {
                "type": "object",
                "required": ["record_type"],
                "properties": {"record_type": {"const": "trial"}},
            },
            "then": {"$ref": "#/$defs/TrialRecord"},
        }
        result["properties"]["records"]["items"].setdefault("allOf", []).append(tagged)
        data = value["$defs"]["Section"]["properties"]["data"]
        value["$defs"]["Section"]["properties"]["data"] = {"allOf": [data, tagged]}
    # Nullable enum shorthand introduces redundant type assertions. Compact
    # once more so complete quota usage fits the existing discovery budget.
    value = _compact(compact_nullable(value))
    # Inline definitions referenced once. This is schema-equivalent and keeps
    # diagnostic field paths inside the existing discovery budget.
    from collections import Counter

    protected = {
        "ResearchResult",
        "EvidenceReceipt",
        "LiteratureRecord",
        "TrialRecord",
        "ErrorInfo",
        "Section",
    }
    while True:
        references = Counter()

        def count(item, references=references):
            if isinstance(item, dict):
                if "$ref" in item:
                    references[item["$ref"]] += 1
                for child in item.values():
                    count(child)
            elif isinstance(item, list):
                for child in item:
                    count(child)

        count(value)
        targets = {
            f"#/$defs/{key}": definition
            for key, definition in value.get("$defs", {}).items()
            if key not in protected and references[f"#/$defs/{key}"] == 1
        }
        if not targets:
            break

        def inline(item, targets=targets):
            if isinstance(item, dict):
                if set(item) == {"$ref"} and item["$ref"] in targets:
                    return inline(deepcopy(targets[item["$ref"]]))
                return {key: inline(child) for key, child in item.items()}
            if isinstance(item, list):
                return [inline(child) for child in item]
            return item

        value = inline(value)
        for reference in targets:
            value["$defs"].pop(reference.rsplit("/", 1)[-1])
    Draft202012Validator.check_schema(value)
    return value


def output_schema(name: str) -> dict:
    return deepcopy(_output_schema(name))


@cache
def _validator(name: str):
    return Draft202012Validator(_output_schema(name))


def validate_output(name: str, value: dict) -> None:
    # Avoid logging jsonschema's exception: it embeds complete result data.
    if not _validator(name).is_valid(value):
        raise ResearchError("invalid_output", "The operation returned an invalid public result contract.")


def failed(value: dict) -> bool:
    return value.get("outcome") in {"error", "unavailable"}


def batch_outcome(results: list[dict]) -> str:
    if all(failed(item) for item in results):
        return "error"
    if any(failed(item) or item.get("outcome") == "partial" for item in results):
        return "partial"
    return "data"
