"""Registry assertions preserve their source coding and enrollment meaning."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ResearchError


class TrialIdentity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"namespace": {"const": "nct"}}},
                    "then": {
                        "properties": {"value": {"pattern": r"^NCT\d{8}$", "not": {"const": "NCT00000000"}}}
                    },
                    "else": {"properties": {"value": {"pattern": r"^NCI-\d{4}-\d{5,}$"}}},
                }
            ]
        },
    )
    namespace: Literal["nct", "nci"]
    value: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def identity(self):
        import re

        pattern = r"NCT\d{8}" if self.namespace == "nct" else r"NCI-\d{4}-\d{5,}"
        if not re.fullmatch(pattern, self.value) or self.value == "NCT00000000":
            raise ValueError("Invalid trial registry identity")
        return self


class TrialEnrollment(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"count": {"type": "null"}}},
                    "then": {"properties": {"missingness": {"const": "not_supplied"}}},
                    "else": {"properties": {"missingness": {"const": "reported"}}},
                }
            ]
        },
    )
    count: int | None = Field(ge=0)
    basis: Literal["actual", "estimated", "minimum_target", "not_supplied"]
    unit: Literal["participants"] = "participants"
    missingness: Literal["reported", "not_supplied"]
    role: Literal["registry_enrollment", "minimum_target_accrual"]

    @model_validator(mode="after")
    def supplied(self):
        if (self.count is None) != (self.missingness == "not_supplied"):
            raise ValueError("Enrollment missingness must match its supplied count")
        return self


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    record_type: Literal["trial"] = "trial"
    assertion_type: Literal["registry_record"] = "registry_record"
    source: Literal["clinical-trials", "nci"]
    identities: list[TrialIdentity] = Field(min_length=1, max_length=64)
    species: Literal[9606] = 9606
    title: str | None
    status: str | None
    phases: list[str] | None
    study_type: str | None
    enrollment: TrialEnrollment
    has_results: bool | None
    results_missingness: Literal["reported", "not_supplied", "not_normalized"]
    source_release: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


def invalid_trial():
    raise ResearchError(
        "invalid_source_response", "Provider trial metadata violates its scientific record contract."
    )


def module(row, key):
    value = row.get(key, {})
    if not isinstance(value, dict):
        invalid_trial()
    return value


def trial_record(row, source):
    if not isinstance(row, dict):
        invalid_trial()
    if source == "clinical-trials":
        from clinical_trials_mcp.contracts import CONTRACT, PHASES, STATUSES

        protocol = module(row, "protocolSection")
        identity = module(protocol, "identificationModule")
        design = module(protocol, "designModule")
        enrollment = module(design, "enrollmentInfo")
        count = enrollment.get("count")
        basis = enrollment.get("type")
        if basis is not None and (not isinstance(basis, str) or basis not in {"ACTUAL", "ESTIMATED"}):
            invalid_trial()
        status = module(protocol, "statusModule").get("overallStatus")
        phases = design.get("phases")
        study_type = design.get("studyType")
        if study_type is not None and (
            not isinstance(study_type, str)
            or study_type not in CONTRACT["components"]["schemas"]["StudyType"]["enum"]
        ):
            invalid_trial()
        if status is not None and (not isinstance(status, str) or status not in STATUSES):
            invalid_trial()
        if phases is not None and (
            not isinstance(phases, list) or any(not isinstance(p, str) or p not in PHASES for p in phases)
        ):
            invalid_trial()
        aliases = identity.get("nctIdAliases", [])
        if not isinstance(aliases, list):
            invalid_trial()
        ids = [{"namespace": "nct", "value": value} for value in [identity.get("nctId"), *aliases]]
        values = {
            "title": identity.get("briefTitle"),
            "status": status,
            "phases": phases,
            "study_type": study_type,
            "enrollment": {
                "count": count,
                "basis": {"ACTUAL": "actual", "ESTIMATED": "estimated", None: "not_supplied"}[basis],
                "role": "registry_enrollment",
                "missingness": "not_supplied" if count is None else "reported",
            },
            "has_results": row.get("hasResults"),
            "results_missingness": "not_supplied" if row.get("hasResults") is None else "reported",
        }
    elif source == "nci":
        phase = row.get("phase")
        if phase is not None and not isinstance(phase, dict):
            invalid_trial()
        label = phase.get("phase") if phase is not None else None
        ids = [{"namespace": "nci", "value": row.get("nci_id")}]
        if row.get("nct_id") is not None:
            ids.append({"namespace": "nct", "value": row["nct_id"]})
        count = row.get("minimum_target_accrual_number")
        values = {
            "title": row.get("brief_title"),
            "status": row.get("current_trial_status"),
            "phases": [label] if label is not None else None,
            "study_type": row.get("study_protocol_type"),
            "enrollment": {
                "count": count,
                "basis": "minimum_target" if count is not None else "not_supplied",
                "role": "minimum_target_accrual",
                "missingness": "not_supplied" if count is None else "reported",
            },
            # The selected NCI fixture does not establish results_posted's full
            # contract or its equivalence to ClinicalTrials.gov's HasResults.
            "has_results": None,
            "results_missingness": "not_normalized",
        }
    else:
        invalid_trial()
    try:
        return TrialRecord.model_validate(
            {
                **row,
                **values,
                "record_type": "trial",
                "assertion_type": "registry_record",
                "source": source,
                "identities": ids,
                "species": 9606,
                "source_release": None,
                "evidence_ids": [],
            }
        ).model_dump(mode="json")
    except ValidationError:
        invalid_trial()


def rank_trials(rows, query):
    """Prioritize direct title/condition mentions within acquired source windows."""
    import re

    tokens = set(re.findall(r"\w+", query.casefold()))
    ranked = []
    for index, record in enumerate(rows):
        row = dict(record)
        conditions = row.get("conditions") or row.get("protocolSection", {}).get("conditionsModule", {}).get(
            "conditions", []
        )
        conditions = [c for c in conditions if isinstance(c, str)] if isinstance(conditions, list) else []
        title = str(row.get("title") or "").casefold()
        condition_words = set(re.findall(r"\w+", " ".join(conditions).casefold()))
        title_words = set(re.findall(r"\w+", title))
        # Registry titles commonly use regular plural disease names. Match
        # those whole words without making substrings into disease identities.
        title_matches = {t for t in tokens if t in title_words or t + "s" in title_words}
        condition_matches = {t for t in tokens if t in condition_words or t + "s" in condition_words}
        exact_condition = any(set(re.findall(r"\w+", c.casefold())) == tokens for c in conditions)
        score = 2 * len(title_matches) + len(condition_matches) + 2 * exact_condition
        row["conditions"] = conditions
        row["ranking"] = {
            "method": "title_condition_overlap",
            "score": score,
            "title_matches": len(title_matches),
            "condition_matches": len(condition_matches),
            "exact_condition": exact_condition,
            "scope": "Fetched provider windows; subtype matches remain eligible.",
        }
        ranked.append((score, index, row))
    return [row for _, _, row in sorted(ranked, key=lambda item: (-item[0], item[1]))]
