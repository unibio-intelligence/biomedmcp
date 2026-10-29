"""Focused typed-record schemas; discovery stays within the compact tool budget."""

from copy import deepcopy
from functools import cache
from typing import Annotated

from pydantic import Field, TypeAdapter

from .errors import ResearchError

FAMILIES = ("literature", "trial", "variant", "expression", "study")


@cache
def _record_schema(family):
    if family == "literature":
        from .scientific_records import LiteratureRecord

        adapter = TypeAdapter(LiteratureRecord)
    elif family == "trial":
        from .trial_records import TrialRecord

        adapter = TypeAdapter(TrialRecord)
    elif family == "variant":
        from .native.gnomad import VariantPopulationRecord
        from .variant_assertion_records import ExpertVariantAssertionRecord

        adapter = TypeAdapter(
            Annotated[
                VariantPopulationRecord | ExpertVariantAssertionRecord, Field(discriminator="record_type")
            ]
        )
    elif family == "expression":
        from .expression_records import EXPRESSION_RECORDS

        adapter = EXPRESSION_RECORDS
    elif family == "study":
        from .study_metadata import StudyMetadataRecord
        from .study_records import StudyMeasurementRecord, StudyMutationProfileRecord

        adapter = TypeAdapter(
            Annotated[
                StudyMeasurementRecord | StudyMutationProfileRecord | StudyMetadataRecord,
                Field(discriminator="record_type"),
            ]
        )
    else:
        raise ResearchError("invalid_parameters", "Unknown scientific record family.")
    schema = adapter.json_schema()
    for definition in [schema, *schema.get("$defs", {}).values()]:
        if "record_type" in definition.get("properties", {}) and "record_type" not in definition.get(
            "required", []
        ):
            definition.setdefault("required", []).append("record_type")
    schema["$id"] = f"biomedmcp://schemas/records/{family}"
    schema["x-ubi-qualification"] = (
        "Selected source record families only. Schema availability does not qualify a source, grant data permissions or establish current provider health."
    )
    return schema


def record_schema(family):
    return deepcopy(_record_schema(family))
