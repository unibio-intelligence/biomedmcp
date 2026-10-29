"""Verified study matrix measurements, without inferred normalization or species."""

from collections import Counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ResearchError

Count = Annotated[int, Field(strict=True, ge=0)]
Measurement = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StudyInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["clinical_sample_population", "gene_measurements"]
    file: str = Field(min_length=1)
    sha256: Digest
    gene: str | None


class StudyCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    assay: Literal["cna", "expression"]
    gene: str = Field(min_length=1)
    units: str = Field(min_length=1)
    eligible_samples: Count
    measured_samples: Count
    missing_samples: Count
    missing_sample_ids: list[str] = Field(max_length=100)
    missing_sample_ids_truncated: bool
    coverage_basis: Literal["Finite values in the checksummed gene row; no imputation."]

    @model_validator(mode="after")
    def population(self):
        if self.measured_samples + self.missing_samples != self.eligible_samples:
            raise ValueError("Measured and missing samples must partition the eligible population")
        if len(set(self.missing_sample_ids)) != len(self.missing_sample_ids):
            raise ValueError("Missing sample identifiers must be distinct")
        if len(self.missing_sample_ids) != min(self.missing_samples, 100):
            raise ValueError("Missing sample identifiers must describe the bounded missing population")
        if self.missing_sample_ids_truncated != (self.missing_samples > 100):
            raise ValueError("Missing sample truncation must agree with the missing population")
        return self


class StudyRecordRelease(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: str = Field(min_length=1)
    release: str = Field(min_length=1)
    sha256: Digest
    metadata_sha256: Digest
    source_url: str = Field(min_length=1)
    assays: dict


class MutationCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    numerator: Count
    denominator: Annotated[int, Field(strict=True, ge=1)]
    method: Literal["Unique mutated assayed samples divided by declared mutation-assayed samples."]


class MutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["clinical_sample_population", "mutation_events"]
    file: str = Field(min_length=1)
    sha256: Digest
    gene: str | None


class MutationCoverageLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    release_metadata_sha256: Digest
    pointer: Literal["/mutation_coverage"]


class StudyMutationProfileRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    record_type: Literal["study_mutation_profile"]
    assertion_type: Literal["verified_release_mutation_frequency"]
    study_id: str = Field(min_length=1)
    release: StudyRecordRelease
    gene: str = Field(min_length=1)
    identity_scope: Literal["gene within this verified study release"]
    sample_unit: Literal["samples"]
    clinical_samples: Count
    assayed_samples: Annotated[int, Field(strict=True, ge=1)]
    total_samples: Annotated[int, Field(strict=True, ge=1)]
    denominator: Literal["declared mutation-assayed samples"]
    unique_samples: Count
    mutation_count: Count
    top_variant_classes: list[list[str | int]] = Field(max_length=25)
    frequency: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    excluded_out_of_assay_mutation_events: Count
    calculation: MutationCalculation
    input_locators: list[MutationInput] = Field(min_length=2, max_length=2)
    coverage_locator: MutationCoverageLocator
    exclusion_scope: Literal["All study mutation events outside declared assay samples"]

    @model_validator(mode="after")
    def scientific_meaning(self):
        coverage = (self.release.model_extra or {}).get("mutation_coverage", {})
        samples = coverage.get("samples") if isinstance(coverage, dict) else None
        genes = coverage.get("genes") if isinstance(coverage, dict) else None
        if (
            not isinstance(samples, list)
            or not samples
            or any(not isinstance(s, str) or not s for s in samples)
            or len(set(samples)) != len(samples)
            or (genes != "all" and (not isinstance(genes, list) or self.gene not in genes))
        ):
            raise ValueError("Mutation frequency requires declared sample and gene assay coverage")
        if (
            self.release.id != self.study_id
            or self.total_samples != self.assayed_samples
            or self.assayed_samples != len(samples)
            or self.assayed_samples > self.clinical_samples
            or self.unique_samples > self.assayed_samples
            or self.unique_samples > self.mutation_count
            or self.calculation.numerator != self.unique_samples
            or self.calculation.denominator != self.assayed_samples
            or self.frequency != self.unique_samples / self.assayed_samples
        ):
            raise ValueError(
                "Unique mutant samples, events and clinical/assay populations must remain distinct"
            )
        if any(
            len(pair) != 2
            or not isinstance(pair[0], str)
            or not pair[0]
            or type(pair[1]) is not int
            or pair[1] < 1
            for pair in self.top_variant_classes
        ):
            raise ValueError("Mutation class counts must be positive event counts")
        if (
            len({pair[0] for pair in self.top_variant_classes}) != len(self.top_variant_classes)
            or sum(pair[1] for pair in self.top_variant_classes) > self.mutation_count
            or (
                len(self.top_variant_classes) < 25
                and sum(pair[1] for pair in self.top_variant_classes) != self.mutation_count
            )
        ):
            raise ValueError("Reported mutation classes must agree with bounded event coverage")
        inputs = {item.role: item for item in self.input_locators}
        if set(inputs) != {"clinical_sample_population", "mutation_events"}:
            raise ValueError("Clinical population and mutation inputs are both required")
        clinical, mutation = inputs["clinical_sample_population"], inputs["mutation_events"]
        assay = self.release.assays.get("mutations", {})
        if (
            clinical.file != "data_clinical_sample.txt"
            or clinical.gene is not None
            or mutation.gene != self.gene
            or not isinstance(assay, dict)
            or not assay.get("available")
            or (mutation.file, mutation.sha256) != (assay.get("file"), assay.get("sha256"))
            or self.coverage_locator.release_metadata_sha256 != self.release.metadata_sha256
        ):
            raise ValueError("Mutation calculation inputs must retain their verified release identity")
        return self


def study_mutation_profile_record(row: dict, *, files: dict) -> dict:
    try:
        assay = row["release"]["assays"]["mutations"]
        return StudyMutationProfileRecord.model_validate(
            {
                **row,
                "record_type": "study_mutation_profile",
                "assertion_type": "verified_release_mutation_frequency",
                "identity_scope": "gene within this verified study release",
                "sample_unit": "samples",
                "exclusion_scope": "All study mutation events outside declared assay samples",
                "assayed_samples": row["total_samples"],
                "calculation": {
                    "numerator": row["unique_samples"],
                    "denominator": row["total_samples"],
                    "method": "Unique mutated assayed samples divided by declared mutation-assayed samples.",
                },
                "coverage_locator": {
                    "release_metadata_sha256": row["release"]["metadata_sha256"],
                    "pointer": "/mutation_coverage",
                },
                "input_locators": [
                    {
                        "role": "clinical_sample_population",
                        "file": "data_clinical_sample.txt",
                        "sha256": files["data_clinical_sample.txt"],
                        "gene": None,
                    },
                    {
                        "role": "mutation_events",
                        "file": assay["file"],
                        "sha256": files[assay["file"]],
                        "gene": row["gene"],
                    },
                ],
            }
        ).model_dump(mode="json")
    except (ValidationError, KeyError):
        raise ResearchError(
            "invalid_study", "Study mutation profile violates its scientific record contract."
        ) from None


class StudyMeasurementRecord(BaseModel):
    # Retain release metadata and existing descriptive fields. Only this family
    # is qualified here; other study analyses do not receive this discriminator.
    model_config = ConfigDict(extra="allow", strict=True)
    record_type: Literal["study_measurements"]
    assertion_type: Literal["verified_release_measurements"]
    study_id: str = Field(min_length=1)
    release: StudyRecordRelease
    gene: str = Field(min_length=1)
    identity_scope: Literal["gene row within this verified study release"]
    measurement: Literal["cna", "expression"]
    total_samples: Count
    clinical_samples: Count
    eligible_samples: Count
    evaluable_samples: Count
    measured_samples: Count
    missing_samples: Count
    denominator: Literal["Samples with finite gene-level assay measurements"]
    sample_unit: Literal["samples"]
    values: dict[str, Measurement] = Field(min_length=1)
    counts: dict[str, Count]
    measurement_coverage: dict[str, StudyCoverage]
    input_locators: list[StudyInput] = Field(min_length=2, max_length=2)
    units_basis: Literal["manifest declaration", "managed cBioPortal file format"]
    method: Literal[
        "Retain finite release values; count samples by exact value; no imputation or normalization."
    ]

    @model_validator(mode="after")
    def scientific_meaning(self):
        n = len(self.values)
        if not n or {self.total_samples, self.evaluable_samples, self.measured_samples} != {n}:
            raise ValueError("Measured sample counts must match the retained finite measurements")
        if self.eligible_samples > self.clinical_samples:
            raise ValueError("Eligible samples must be drawn from the clinical population")
        if self.measured_samples + self.missing_samples != self.eligible_samples:
            raise ValueError("Missing measurements cannot become measured negative samples")
        if self.counts != dict(Counter(str(value) for value in self.values.values())):
            raise ValueError("Value counts must agree with the retained measurements")
        key = f"{self.measurement}:{self.gene}"
        if set(self.measurement_coverage) != {key}:
            raise ValueError("Coverage must describe the requested assay and gene")
        coverage = self.measurement_coverage[key]
        if (
            coverage.assay,
            coverage.gene,
            coverage.eligible_samples,
            coverage.measured_samples,
            coverage.missing_samples,
        ) != (self.measurement, self.gene, self.eligible_samples, n, self.missing_samples):
            raise ValueError("Coverage counts and identity must agree with the measurement record")
        if set(self.values) & set(coverage.missing_sample_ids):
            raise ValueError("A sample cannot be both measured and missing")
        inputs = {item.role: item for item in self.input_locators}
        if set(inputs) != {"clinical_sample_population", "gene_measurements"}:
            raise ValueError("Both clinical population and gene matrix inputs are required")
        if (
            inputs["gene_measurements"].gene != self.gene
            or inputs["clinical_sample_population"].gene is not None
        ):
            raise ValueError("Input locators must retain the requested gene row")
        if inputs["clinical_sample_population"].file != "data_clinical_sample.txt":
            raise ValueError("Clinical population locator must identify the consumed sample table")
        assay = self.release.assays.get(self.measurement, {})
        if not isinstance(assay, dict) or self.release.id != self.study_id:
            raise ValueError("Measurements must retain their release identity")
        matrix = inputs["gene_measurements"]
        if (matrix.file, matrix.sha256, coverage.units, self.units_basis) != (
            assay.get("file"),
            assay.get("sha256"),
            assay.get("units"),
            assay.get("units_basis"),
        ):
            raise ValueError("Matrix identity and units must agree with the verified release")
        return self


def study_measurement_record(row: dict, *, files: dict, assay: dict) -> dict:
    try:
        return StudyMeasurementRecord.model_validate(
            {
                **row,
                "record_type": "study_measurements",
                "assertion_type": "verified_release_measurements",
                "identity_scope": "gene row within this verified study release",
                "sample_unit": "samples",
                "units_basis": assay["units_basis"],
                "method": "Retain finite release values; count samples by exact value; no imputation or normalization.",
                "input_locators": [
                    {
                        "role": "clinical_sample_population",
                        "file": "data_clinical_sample.txt",
                        "sha256": files["data_clinical_sample.txt"],
                        "gene": None,
                    },
                    {
                        "role": "gene_measurements",
                        "file": assay["file"],
                        "sha256": assay["sha256"],
                        "gene": row["gene"],
                    },
                ],
            }
        ).model_dump(mode="json")
    except (ValidationError, KeyError):
        raise ResearchError(
            "invalid_study", "Study measurements violate their scientific record contract."
        ) from None
