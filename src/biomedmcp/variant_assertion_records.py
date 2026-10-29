"""Source expert assertions are categorical observations, never computed diagnoses."""

from typing import Literal
from urllib.parse import urlencode

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import ResearchError
from .runtime import digest

ENDPOINT = "https://erepo.clinicalgenome.org/evrepo/api/summary/classifications"


class AssertionAlleleIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    namespace: Literal["clingen_allele_id"]
    value: str = Field(pattern=r"^CA[0-9]+$")
    species: None
    assembly: None
    transcript: None
    context_missingness: Literal["not_qualified_by_summary_contract"]
    binding_basis: Literal[
        "Exact source caId field and exact-filtered repository query; no cross-namespace allele equivalence is inferred."
    ]


class AssertionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: Literal["https://erepo.clinicalgenome.org/evrepo/api/summary/classifications"]
    source_page: Literal[1]
    row_index: int = Field(ge=0, le=24)
    provider_record_pointer: str
    delivered_record_pointer: str
    classification_pointer: str
    panel_pointer: str
    version_pointer: str
    source_url: str

    @field_validator("source_page", mode="before")
    @classmethod
    def integer_page(cls, value):
        if type(value) is not int:
            raise ValueError("Source page must be an integer")
        return value


class ExpertVariantAssertionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    record_type: Literal["variant_assertion"]
    assertion_type: Literal["provider_expert_classification"]
    source: Literal["clingen"]
    variant_identity: AssertionAlleleIdentity
    classification: str = Field(min_length=1, max_length=512)
    ep: str = Field(min_length=1, max_length=1024)
    uuid: str = Field(min_length=1, max_length=512)
    docVersion: str = Field(min_length=1, max_length=128)
    caId: str = Field(pattern=r"^CA[0-9]+$")
    unit: Literal["source_categorical_classification"]
    condition: None
    condition_missingness: Literal["not_qualified_by_summary_contract"]
    retracted: bool | None
    retraction_missingness: Literal["reported", "not_supplied"]
    source_release: None
    reproducibility: Literal["time_dependent_summary; document version is observed, not a replay pin"]
    method: Literal[
        "Retain this source expert-panel interpretation independently; no classification synthesis, ranking or clinical recommendation is performed."
    ]
    input_locator: AssertionInput
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_record: dict[str, JsonValue]

    @model_validator(mode="after")
    def meaning(self):
        raw = self.provider_record
        if any(not getattr(self, key).strip() for key in ("classification", "ep", "uuid", "docVersion")):
            raise ValueError("Source interpretation fields must not be blank")
        if "retracted" in raw and type(raw["retracted"]) is not bool:
            raise ValueError("Reported source retraction must be a boolean")
        if any(
            raw.get(key) != getattr(self, key)
            for key in ("caId", "classification", "ep", "uuid", "docVersion")
        ):
            raise ValueError("Expert interpretation must preserve its own source fields")
        if self.variant_identity.value != self.caId:
            raise ValueError("Assertion allele identity must match the source record")
        if self.retracted != raw.get("retracted") or self.retraction_missingness != (
            "reported" if "retracted" in raw else "not_supplied"
        ):
            raise ValueError("Missing source retraction status cannot become false")
        if self.source_record_sha256 != digest(raw):
            raise ValueError("Expert interpretation must bind the original provider row")
        position = self.input_locator.row_index
        pointer = f"/data/{position}"
        delivered = f"/records/{position}/provider_record"
        locator = self.input_locator
        expected_url = (
            ENDPOINT
            + "?"
            + urlencode(
                {"columns": "caId", "values": self.caId, "matchTypes": "exact", "pgSize": 25, "pg": 1}
            )
        )
        if (
            locator.provider_record_pointer,
            locator.delivered_record_pointer,
            locator.classification_pointer,
            locator.panel_pointer,
            locator.version_pointer,
            locator.source_url,
        ) != (
            pointer,
            delivered,
            delivered + "/classification",
            delivered + "/ep",
            delivered + "/docVersion",
            expected_url,
        ):
            raise ValueError("Source inputs must locate this interpretation, panel and version")
        return self


def expert_variant_assertion(row, caid, index):
    """Normalize only already-validated summary records, preserving each source row."""
    try:
        delivered = f"/records/{index}/provider_record"
        return ExpertVariantAssertionRecord.model_validate(
            {
                "record_type": "variant_assertion",
                "assertion_type": "provider_expert_classification",
                "source": "clingen",
                "variant_identity": {
                    "namespace": "clingen_allele_id",
                    "value": caid,
                    "species": None,
                    "assembly": None,
                    "transcript": None,
                    "context_missingness": "not_qualified_by_summary_contract",
                    "binding_basis": "Exact source caId field and exact-filtered repository query; no cross-namespace allele equivalence is inferred.",
                },
                **{key: row[key] for key in ("classification", "ep", "uuid", "docVersion", "caId")},
                "unit": "source_categorical_classification",
                "condition": None,
                "condition_missingness": "not_qualified_by_summary_contract",
                "retracted": row.get("retracted"),
                "retraction_missingness": "reported" if "retracted" in row else "not_supplied",
                "source_release": None,
                "reproducibility": "time_dependent_summary; document version is observed, not a replay pin",
                "method": "Retain this source expert-panel interpretation independently; no classification synthesis, ranking or clinical recommendation is performed.",
                "input_locator": {
                    "endpoint": ENDPOINT,
                    "source_page": 1,
                    "row_index": index,
                    "provider_record_pointer": f"/data/{index}",
                    "delivered_record_pointer": delivered,
                    "classification_pointer": delivered + "/classification",
                    "panel_pointer": delivered + "/ep",
                    "version_pointer": delivered + "/docVersion",
                    "source_url": ENDPOINT
                    + "?"
                    + urlencode(
                        {"columns": "caId", "values": caid, "matchTypes": "exact", "pgSize": 25, "pg": 1}
                    ),
                },
                "source_record_sha256": digest(row),
                "provider_record": row,
            }
        ).model_dump(mode="json")
    except (ValidationError, ValueError, TypeError, KeyError):
        raise ResearchError(
            "invalid_source_response",
            "Provider expert interpretation violates its scientific record contract.",
        ) from None
