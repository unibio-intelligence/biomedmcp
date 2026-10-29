"""Release-scoped derived science; sample, patient and assay units stay distinct."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .errors import ResearchError
from .extensions import StudyRequest
from .study_records import Count, Digest, MutationCoverageLocator, StudyCoverage, StudyRecordRelease

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
METHODS = {
    "study_mutation_cohort": "Partition declared mutation-assayed samples by any reported mutation in the requested gene.",
    "study_mutation_ranking": "Rank observed mutated genes by distinct assayed sample count, then gene symbol; divide by the declared assay sample population.",
    "study_filtered_cohort": "Intersect requested mutation, discrete CNA, expression and clinical predicates; exclude missing measurements without imputation.",
    "study_survival": "Assign each eligible patient once by any mutated assayed sample; retain finite nonnegative endpoint durations and binary status; Kaplan-Meier and two-sided log-rank.",
    "study_mutation_association": "Assign each eligible patient once by any mutated assayed sample for each gene; apply two-sided Fisher exact to unmodified patient counts.",
    "study_expression_comparison": "Assign each eligible patient once by mutation; summarize finite eligible biopsy measurements by patient median without imputation; compare patient groups by two-sided Mann-Whitney U.",
    "study_co_occurrence": "Assign each eligible patient once for each requested gene; Fisher exact for all unordered gene pairs; BH over the entire requested family including unavailable tests.",
    "study_structural_variants": "Retain source table rows matching either source gene symbol; count rows and distinct reported clinical sample identifiers; no assay coverage or build inference.",
}
OPERATIONS = {
    "study_mutation_cohort": "cohort",
    "study_mutation_ranking": "top_mutated",
    "study_filtered_cohort": "filter",
    "study_survival": "survival",
    "study_mutation_association": "compare",
    "study_expression_comparison": "compare",
    "study_co_occurrence": "co_occurrence",
    "study_structural_variants": "query",
}


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DerivedInput(StrictRecord):
    role: Literal[
        "clinical_sample_population",
        "mutation_events",
        "gene_measurements",
        "clinical_patient_outcomes",
        "structural_variant_events",
    ]
    file: Identity
    sha256: Digest
    selection: list[Identity] | None = Field(max_length=40)


class Derivation(StrictRecord):
    operation: Literal["cohort", "top_mutated", "filter", "survival", "compare", "co_occurrence", "query"]
    method: str = Field(min_length=1)


class DerivedStudyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    study_id: Identity
    release: StudyRecordRelease
    gene: Identity | None
    identity_scope: Literal["Gene symbols and sample/patient identifiers within this verified study release"]
    identity_namespace: Literal["verified_study_gene_symbol"]
    sample_identity_namespace: Literal["verified_study_sample_id"]
    assertion_type: Literal["verified_release_derivation"]
    total_samples: Count
    clinical_samples: Count
    denominator: str = Field(min_length=1)
    measurement_coverage: dict[str, StudyCoverage]
    warnings: list[str]
    excluded_out_of_assay_mutation_events: Count | None = None
    mutation_event_policy: (
        Literal["Exclude events outside the declared mutation-assayed sample population from all numerators."]
        | None
    ) = None
    derivation: Derivation
    input_locators: list[DerivedInput] = Field(min_length=1, max_length=5)
    coverage_locator: MutationCoverageLocator | None = None

    @model_validator(mode="after")
    def identity_and_inputs(self):
        if self.release.id != self.study_id or self.total_samples > self.clinical_samples:
            raise ValueError("Derived records must retain their clinical population and verified release")
        if (self.derivation.operation, self.derivation.method) != (
            OPERATIONS[self.record_type],
            METHODS[self.record_type],
        ):
            raise ValueError("Derived record method must identify the calculation actually performed")
        roles = [item.role for item in self.input_locators]
        files = [item.file for item in self.input_locators]
        if len(set(files)) != len(files) or roles.count("clinical_sample_population") != 1:
            raise ValueError("Every consumed file is located once with one clinical population input")
        for item in self.input_locators:
            if item.selection is not None and len(set(item.selection)) != len(item.selection):
                raise ValueError("Input row/column selectors must be distinct")
            if item.role == "clinical_sample_population" and (
                item.file != "data_clinical_sample.txt" or item.selection is not None
            ):
                raise ValueError("Clinical population must identify the complete consumed sample table")
            if item.role == "mutation_events" and item.file != "data_mutations.txt":
                raise ValueError("Mutation input must identify the consumed mutation table")
            if item.role == "structural_variant_events" and item.file != "data_sv.txt":
                raise ValueError("Structural variants must identify their consumed source table")
            if item.role == "clinical_patient_outcomes" and item.file != "data_clinical_patient.txt":
                raise ValueError("Survival must identify its consumed patient outcomes")
            if item.role == "gene_measurements":
                matches = [
                    a
                    for a in self.release.assays.values()
                    if isinstance(a, dict) and (a.get("file"), a.get("sha256")) == (item.file, item.sha256)
                ]
                if not matches or not item.selection:
                    raise ValueError(
                        "Measurement locators must retain the verified matrix and requested genes"
                    )
        if self.coverage_locator is not None:
            if self.excluded_out_of_assay_mutation_events is None or self.mutation_event_policy is None:
                raise ValueError(
                    "Mutation derivations must retain event exclusions and their population policy"
                )
            if (
                roles.count("mutation_events") != 1
                or self.coverage_locator.release_metadata_sha256 != self.release.metadata_sha256
            ):
                raise ValueError("Mutation assay coverage must retain its verified release metadata")
            coverage = (self.release.model_extra or {}).get("mutation_coverage", {})
            samples = coverage.get("samples") if isinstance(coverage, dict) else None
            genes = coverage.get("genes") if isinstance(coverage, dict) else None
            if (
                not isinstance(samples, list)
                or not samples
                or any(not isinstance(s, str) or not s for s in samples)
                or len(set(samples)) != len(samples)
            ):
                raise ValueError("Mutation derivations require declared distinct assayed samples")
            mutation = next(i for i in self.input_locators if i.role == "mutation_events")
            if genes != "all" and (
                mutation.selection is None
                or not isinstance(genes, list)
                or not set(mutation.selection) <= set(genes)
            ):
                raise ValueError("Mutation calculations must stay within the declared gene panel")
            assay = self.release.assays.get("mutations", {})
            if (
                not isinstance(assay, dict)
                or assay.get("available") is not True
                or (assay.get("file"), assay.get("sha256")) != (mutation.file, mutation.sha256)
            ):
                raise ValueError("Mutation input must agree with the available verified assay")
        elif "mutation_events" in roles:
            raise ValueError("Mutation inputs require explicit assay coverage")
        for key, coverage in self.measurement_coverage.items():
            assay = self.release.assays.get(coverage.assay, {})
            if (
                key != f"{coverage.assay}:{coverage.gene}"
                or assay.get("units") != coverage.units
                or not any(
                    i.role == "gene_measurements"
                    and i.file == assay.get("file")
                    and coverage.gene in (i.selection or [])
                    for i in self.input_locators
                )
            ):
                raise ValueError("Measurement coverage must retain its assay, gene, units and matrix input")
        return self

    def mutation_population(self):
        if self.coverage_locator is None:
            raise ValueError("This derived analysis requires declared mutation assay coverage")
        samples = self.release.model_extra["mutation_coverage"]["samples"]
        if len(samples) > self.clinical_samples:
            raise ValueError("Assayed population cannot exceed the clinical population")
        return len(samples)

    def require_roles(self, expected):
        if {i.role for i in self.input_locators} != set(expected):
            raise ValueError("Derived analysis inputs must include exactly its participating evidence types")

    def mutation_selection(self, genes):
        item = next(i for i in self.input_locators if i.role == "mutation_events")
        if item.selection != (None if genes is None else sorted(set(genes))):
            raise ValueError(
                "Mutation input selectors must identify the genes actually used by this calculation"
            )


class MutationCohortRecord(DerivedStudyRecord):
    record_type: Literal["study_mutation_cohort"]
    analysis_unit: Literal["sample"]
    denominator: Literal["declared mutation-assayed samples"]
    mutant_samples: list[Identity]
    wild_type_samples: list[Identity]
    mutant_count: Count
    wild_type_count: Count

    @model_validator(mode="after")
    def partition(self):
        self.require_roles({"clinical_sample_population", "mutation_events"})
        self.mutation_selection([self.gene])
        assayed = set(self.release.model_extra["mutation_coverage"]["samples"])
        if (
            self.total_samples != self.mutation_population()
            or self.gene is None
            or self.mutant_count != len(self.mutant_samples)
            or self.wild_type_count != len(self.wild_type_samples)
            or len(set(self.mutant_samples)) != self.mutant_count
            or len(set(self.wild_type_samples)) != self.wild_type_count
            or set(self.mutant_samples) & set(self.wild_type_samples)
            or set(self.mutant_samples) | set(self.wild_type_samples) != assayed
        ):
            raise ValueError("Mutant and wild-type cohorts must partition distinct declared assayed samples")
        return self


class RankedMutation(StrictRecord):
    gene: Identity
    mutated_samples: Annotated[int, Field(strict=True, ge=1)]
    frequency: Probability


class MutationRankingRecord(DerivedStudyRecord):
    record_type: Literal["study_mutation_ranking"]
    analysis_unit: Literal["sample"]
    denominator: Literal["declared mutation-assayed samples"]
    genes: list[RankedMutation] = Field(max_length=25)
    total_mutated_genes: Count
    ranking_truncated: bool
    ranking_scope: Literal["Observed mutated genes only; unlisted genes are not an assay-negative inventory"]

    @model_validator(mode="after")
    def ranking(self):
        self.require_roles({"clinical_sample_population", "mutation_events"})
        self.mutation_selection(None)
        if (
            self.total_samples != self.mutation_population()
            or len(self.genes) > self.total_mutated_genes
            or self.ranking_truncated != (len(self.genes) < self.total_mutated_genes)
            or len({r.gene for r in self.genes}) != len(self.genes)
        ):
            raise ValueError("Ranking coverage and gene identities must describe the retained window")
        if [(r.mutated_samples, r.gene) for r in self.genes] != sorted(
            [(r.mutated_samples, r.gene) for r in self.genes], key=lambda x: (-x[0], x[1])
        ) or any(
            r.mutated_samples > self.total_samples or r.frequency != r.mutated_samples / self.total_samples
            for r in self.genes
        ):
            raise ValueError("Mutation ranking requires distinct sample counts and exact assay frequencies")
        return self


class FilteredCohortRecord(DerivedStudyRecord):
    record_type: Literal["study_filtered_cohort"]
    analysis_unit: Literal["sample"]
    denominator: Literal["Eligible samples evaluable for every requested measurement"]
    population_samples: Count
    population_basis: Literal["clinical samples", "declared mutation-assayed samples"]
    eligible_samples: Count
    evaluable_samples: Count
    excluded_missing_samples: Count
    excluded_clinical_samples: Count
    excluded_missing_sample_ids: list[Identity] = Field(max_length=100)
    excluded_missing_sample_ids_truncated: bool
    sample_count: Count
    sample_ids: list[Identity] = Field(max_length=100)
    truncated: bool
    filters: StudyRequest

    @model_validator(mode="after")
    def selection(self):
        expected_coverage = {
            *(f"cna:{g}" for g in self.filters.amplified + self.filters.deleted),
            *(f"expression:{g}" for g in [*self.filters.expression_above, *self.filters.expression_below]),
        }
        if set(self.measurement_coverage) != expected_coverage:
            raise ValueError("Each requested measurement predicate requires its own acquired coverage")
        roles = {"clinical_sample_population"}
        if self.filters.mutated:
            roles.add("mutation_events")
            self.mutation_selection(self.filters.mutated)
        if expected_coverage:
            roles.add("gene_measurements")
        self.require_roles(roles)
        population = self.mutation_population() if self.filters.mutated else self.clinical_samples
        basis = "declared mutation-assayed samples" if self.filters.mutated else "clinical samples"
        if (
            self.population_samples != population
            or self.population_basis != basis
            or self.eligible_samples + self.excluded_clinical_samples != population
            or self.total_samples != self.evaluable_samples
            or self.evaluable_samples + self.excluded_missing_samples != self.eligible_samples
            or self.sample_count > self.evaluable_samples
        ):
            raise ValueError("Clinical and measurement exclusions must retain their separate populations")
        if (
            self.filters.study != self.study_id
            or self.filters.gene != self.gene
            or any(
                not math.isfinite(v)
                for v in [*self.filters.expression_above.values(), *self.filters.expression_below.values()]
            )
        ):
            raise ValueError("Filtering must retain the requested identity and finite thresholds")
        if not self.filters.cancer_type and self.excluded_clinical_samples:
            raise ValueError("Clinical exclusions require the declared clinical predicate")
        for ids, count, truncated in [
            (self.sample_ids, self.sample_count, self.truncated),
            (
                self.excluded_missing_sample_ids,
                self.excluded_missing_samples,
                self.excluded_missing_sample_ids_truncated,
            ),
        ]:
            if len(ids) != min(count, 100) or len(set(ids)) != len(ids) or truncated != (count > 100):
                raise ValueError("Displayed sample identifiers must have exact recoverable bounded counts")
        if set(self.sample_ids) & set(self.excluded_missing_sample_ids) or any(
            c.eligible_samples != self.eligible_samples or c.measured_samples < self.evaluable_samples
            for c in self.measurement_coverage.values()
        ):
            raise ValueError("Missing measurements cannot become selected negative or positive samples")
        return self


class StructuralVariantRecord(DerivedStudyRecord):
    record_type: Literal["study_structural_variants"]
    analysis_unit: Literal["source_table_row"]
    denominator: Literal["Source-reported structural-variant rows; assay coverage is not declared"]
    coverage_status: Literal["not_declared"]
    records: list[dict[str, str]] = Field(max_length=25)
    event_count: Count
    unique_samples: Count
    truncated: bool

    @model_validator(mode="after")
    def source_rows(self):
        self.require_roles({"clinical_sample_population", "structural_variant_events"})
        source = next(i for i in self.input_locators if i.role == "structural_variant_events")
        if source.selection != [self.gene]:
            raise ValueError("Structural-variant input must retain the actual requested gene")
        if (
            self.coverage_locator is not None
            or self.gene is None
            or self.total_samples != self.clinical_samples
            or len(self.records) != min(self.event_count, 25)
            or self.truncated != (self.event_count > 25)
            or self.unique_samples > min(self.event_count, self.clinical_samples)
        ):
            raise ValueError("Structural-variant rows cannot imply assay coverage or an invented population")
        if any(
            self.gene not in {r.get("Site1_Hugo_Symbol"), r.get("Site2_Hugo_Symbol")}
            or not r.get("Sample_Id")
            for r in self.records
        ):
            raise ValueError(
                "Structural-variant records must retain their source genes and sample identifiers"
            )
        n = len({r["Sample_Id"] for r in self.records})
        if n > self.unique_samples or (not self.truncated and n != self.unique_samples):
            raise ValueError("Source row counts and distinct reported samples are different units")
        return self


class StatisticalContext(StrictRecord):
    analysis_unit: Literal["patient"]
    selected_samples: Count
    eligible_patients: Count
    patients_with_multiple_samples: Count
    mutation_assignment: Literal["Any mutation in eligible assayed samples; each patient assigned once."]
    independence_assumption: Literal[
        "Patients treated as independent; family, site and treatment clustering are unmodeled."
    ]
    interpretation: Literal[
        "Exploratory unadjusted observational association; no causal or clinical recommendation."
    ]
    temporal_limit: Literal["Any-sample mutation assignment does not establish baseline exposure timing."]
    multiple_testing: Literal[
        "Single requested comparison; no correction across separate requests.",
        "BH over all requested pairs in this call; no correction across calls.",
    ]


class PatientStudyRecord(DerivedStudyRecord):
    patient_identity_namespace: Literal["verified_study_patient_id"]
    total_patients: Count
    analysis_unit: Literal["patient"]
    denominator: Literal["Patients with at least one declared mutation-assayed sample"]
    sample_denominator: Literal["declared mutation-assayed samples"]
    statistical_context: StatisticalContext

    @model_validator(mode="after")
    def patients(self):
        c = self.statistical_context
        if (
            self.total_samples != self.mutation_population()
            or c.selected_samples != self.total_samples
            or c.eligible_patients != self.total_patients
            or self.total_patients > self.total_samples
            or c.patients_with_multiple_samples > self.total_patients
            or self.total_patients + c.patients_with_multiple_samples > self.total_samples
        ):
            raise ValueError(
                "Patient inference must count independent patients separately from repeated biopsies"
            )
        return self


class OddsInterval(StrictRecord):
    confidence_level: Literal[0.95]
    method: Literal["Exact conditional odds-ratio interval"]
    lower: Nonnegative | None
    upper: Nonnegative | None
    upper_unbounded: bool
    status: Literal["estimated", "unavailable"]

    @model_validator(mode="after")
    def bounds(self):
        if self.status == "unavailable":
            if self.lower is not None or self.upper is not None or self.upper_unbounded:
                raise ValueError("Unavailable odds uncertainty must retain null bounds")
        elif (
            self.lower is None
            or self.upper_unbounded != (self.upper is None)
            or (self.upper is not None and self.lower > self.upper)
        ):
            raise ValueError("Finite and unbounded odds limits must remain distinct")
        return self


class ContingencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    both: Count
    a_only: Count
    b_only: Count
    neither: Count
    total_patients: Count
    analysis_unit: Literal["patient"]
    test: Literal["Two-sided Fisher exact (unmodified patient counts)"]
    odds_ratio_definition: Literal[
        "Observed cross-product ratio; distinct from the conditional maximum-likelihood estimate."
    ]
    log_odds_ratio_definition: Literal[
        "Log cross-product ratio; 0.5 added to all four effect-size cells only when any cell is zero."
    ]
    p_value: Probability | None
    odds_ratio: Nonnegative | None
    odds_ratio_status: Literal["finite", "infinite", "undefined"]
    conditional_odds_ratio: Nonnegative | None
    conditional_odds_ratio_status: Literal["finite", "infinite", "undefined"]
    log_odds_ratio: Number | None
    effect_pseudocount: Number | None
    conditional_odds_ratio_confidence_interval: OddsInterval
    inference_status: Literal["estimated", "insufficient_data", "insufficient_variation"]
    reason: str | None = None

    @model_validator(mode="after")
    def contingency_meaning(self):
        cells = [self.both, self.a_only, self.b_only, self.neither]
        if sum(cells) != self.total_patients:
            raise ValueError("Fisher cells must partition the stated patient denominator")
        marginal = [self.both + self.a_only, self.both + self.b_only]
        estimable = self.total_patients > 0 and all(0 < n < self.total_patients for n in marginal)
        if self.inference_status == "estimated":
            if (
                not estimable
                or self.p_value is None
                or self.log_odds_ratio is None
                or self.conditional_odds_ratio_confidence_interval.status != "estimated"
            ):
                raise ValueError(
                    "Estimated inference requires variable indicators, probability and uncertainty"
                )
            correction = 0.5 if 0 in cells else 0.0
            if self.effect_pseudocount != correction:
                raise ValueError("Pseudocounts apply only to effect size, never Fisher cell counts")
            expected = math.log(
                (self.both + correction)
                * (self.neither + correction)
                / ((self.a_only + correction) * (self.b_only + correction))
            )
            if not math.isclose(self.log_odds_ratio, expected, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError("Log odds must retain its declared effect-only correction")
            product = self.a_only * self.b_only
            if product:
                if (
                    self.odds_ratio_status != "finite"
                    or self.odds_ratio != self.both * self.neither / product
                ):
                    raise ValueError("Observed odds ratio must agree with the unmodified patient counts")
            elif self.odds_ratio_status != "infinite" or self.odds_ratio is not None:
                raise ValueError("Infinite effect must retain a null finite-value slot and explicit status")
            for value, status in [
                (self.odds_ratio, self.odds_ratio_status),
                (self.conditional_odds_ratio, self.conditional_odds_ratio_status),
            ]:
                if status == "undefined" or (status == "finite") != (value is not None):
                    raise ValueError("Finite, infinite and undefined odds estimates cannot be interchanged")
        elif (
            estimable
            or self.p_value is not None
            or any(
                v is not None
                for v in [
                    self.odds_ratio,
                    self.conditional_odds_ratio,
                    self.log_odds_ratio,
                    self.effect_pseudocount,
                ]
            )
            or not self.reason
            or self.conditional_odds_ratio_confidence_interval.status != "unavailable"
            or self.odds_ratio_status != "undefined"
            or self.conditional_odds_ratio_status != "undefined"
        ):
            raise ValueError("Unavailable inference must retain explicit reasons and null estimates")
        return self


class MutationAssociationRecord(PatientStudyRecord, ContingencyRecord):
    record_type: Literal["study_mutation_association"]
    target: Identity

    @model_validator(mode="after")
    def inputs(self):
        self.require_roles({"clinical_sample_population", "mutation_events"})
        if self.gene is None:
            raise ValueError("Mutation comparison requires its requested gene identity")
        self.mutation_selection([self.gene, self.target])
        return self


class PatientSummary(StrictRecord):
    n: Count
    mean: Number | None
    median: Number | None
    analysis_unit: Literal["patient"]

    @model_validator(mode="after")
    def values(self):
        if (self.n == 0) != (self.mean is None and self.median is None) or (
            self.n > 0 and (self.mean is None or self.median is None)
        ):
            raise ValueError("Unavailable patient measurements must stay null rather than zero")
        return self


class MeanInterval(StrictRecord):
    lower: Number | None
    upper: Number | None
    degrees_of_freedom: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] | None
    status: Literal["estimated", "unavailable"]
    confidence_level: Literal[0.95]
    method: Literal["Welch t interval for the difference in patient-level means"]
    reason: str | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.status == "estimated":
            if (
                self.lower is None
                or self.upper is None
                or self.degrees_of_freedom is None
                or self.lower > self.upper
            ):
                raise ValueError(
                    "Estimated mean uncertainty requires ordered finite limits and degrees of freedom"
                )
        elif (
            self.lower is not None
            or self.upper is not None
            or self.degrees_of_freedom is not None
            or not self.reason
        ):
            raise ValueError("Unavailable mean uncertainty requires null limits and a reason")
        return self


class ExpressionEffect(StrictRecord):
    mean_difference: Number | None
    mean_difference_status: Literal["estimated", "unavailable", "numerical_range_exceeded"]
    mean_difference_reason: str | None = None
    rank_biserial: Annotated[float, Field(strict=True, ge=-1, le=1, allow_inf_nan=False)] | None
    units: str = Field(min_length=1)
    direction: Literal["Mutant minus wild-type; positive rank-biserial means larger mutant values."]
    mean_difference_confidence_interval: MeanInterval


class ExpressionTest(StrictRecord):
    method: Literal["Two-sided Mann–Whitney U, asymptotic tie and continuity correction"]
    analysis_unit: Literal["patient"]
    statistic: Nonnegative | None
    p_value: Probability | None
    effect_size: ExpressionEffect
    inference_status: Literal[
        "estimated", "insufficient_data", "insufficient_variation", "numerical_range_exceeded"
    ]
    reason: str | None = None


class ExpressionComparisonRecord(PatientStudyRecord):
    record_type: Literal["study_expression_comparison"]
    target: Identity
    evaluable_samples: Count
    excluded_missing_samples: Count
    evaluable_patients: Count
    excluded_missing_patients: Count
    test: ExpressionTest
    mutant: PatientSummary
    wild_type: PatientSummary
    measurement: Literal["Release-provided expression values; no implicit normalization"]
    patient_expression_policy: Literal[
        "Median of finite measurements in eligible assayed samples; no imputation."
    ]

    @model_validator(mode="after")
    def expression(self):
        self.require_roles({"clinical_sample_population", "mutation_events", "gene_measurements"})
        if self.gene is None:
            raise ValueError("Patient expression comparison requires its requested mutation identity")
        self.mutation_selection([self.gene])
        if (
            self.evaluable_samples + self.excluded_missing_samples != self.total_samples
            or self.evaluable_patients + self.excluded_missing_patients != self.total_patients
            or self.mutant.n + self.wild_type.n != self.evaluable_patients
            or self.evaluable_patients > self.evaluable_samples
        ):
            raise ValueError("Sample and patient measurement missingness must remain independent")
        key = f"expression:{self.target}"
        coverage = self.measurement_coverage.get(key)
        effect = self.test.effect_size
        if (
            set(self.measurement_coverage) != {key}
            or coverage.measured_samples != self.evaluable_samples
            or coverage.eligible_samples != self.total_samples
            or effect.units != coverage.units
        ):
            raise ValueError(
                "Patient expression comparisons must retain release-provided assay units and coverage"
            )
        if self.test.inference_status == "estimated":
            if (
                not self.mutant.n
                or not self.wild_type.n
                or self.test.p_value is None
                or self.test.statistic is None
            ):
                raise ValueError("An estimated rank comparison requires measured patients in both groups")
        elif self.test.p_value is not None or not self.test.reason:
            raise ValueError("Unavailable rank inference must retain a null probability and explicit reason")
        if self.test.statistic is not None:
            product = self.mutant.n * self.wild_type.n
            if (
                not product
                or self.test.statistic > product
                or effect.rank_biserial != 2 * self.test.statistic / product - 1
            ):
                raise ValueError("Rank effect must retain the stated patient groups and direction")
        elif effect.rank_biserial is not None:
            raise ValueError("Missing rank statistic cannot acquire an effect size")
        if (effect.mean_difference_status == "estimated") != (effect.mean_difference is not None):
            raise ValueError("Mean effect status must preserve unavailable/numerical-range states")
        interval = effect.mean_difference_confidence_interval
        if interval.status == "estimated" and (
            min(self.mutant.n, self.wild_type.n) < 2
            or effect.mean_difference is None
            or not interval.lower <= effect.mean_difference <= interval.upper
        ):
            raise ValueError("Mean uncertainty needs two measured patients per group and its own effect")
        return self


class MutationPair(ContingencyRecord):
    gene_a: Identity
    gene_b: Identity
    fdr_bh: Probability | None

    @model_validator(mode="after")
    def pair(self):
        if (
            self.gene_a == self.gene_b
            or (self.fdr_bh is None) != (self.p_value is None)
            or (self.fdr_bh is not None and self.fdr_bh < self.p_value)
        ):
            raise ValueError("Distinct gene hypotheses retain unavailable probabilities and corrected bounds")
        return self


class MultipleTesting(StrictRecord):
    method: Literal["Benjamini–Hochberg"]
    family: Literal["All requested unordered distinct gene pairs in this one call"]
    hypotheses: Count
    estimable_tests: Count
    unavailable_policy: Literal[
        "Unavailable pairs retain null results and count in the requested family size."
    ]
    dependence_limit: Literal[
        "Shared genes and patients create dependence; arbitrary-dependence FDR control is not established."
    ]
    cross_request_correction: bool


class CoOccurrenceRecord(PatientStudyRecord):
    record_type: Literal["study_co_occurrence"]
    requested_genes: list[Identity] = Field(min_length=2, max_length=10)
    pairs: list[MutationPair] = Field(max_length=45)
    multiple_testing: MultipleTesting
    co_occurrence_definition: Literal[
        "Mutations may occur in different eligible samples of the same patient; this is not cell-level co-occurrence."
    ]

    @model_validator(mode="after")
    def family(self):
        self.require_roles({"clinical_sample_population", "mutation_events"})
        self.mutation_selection(self.requested_genes)
        expected = [
            (a, b) for index, a in enumerate(self.requested_genes) for b in self.requested_genes[index + 1 :]
        ]
        if (
            len(set(self.requested_genes)) != len(self.requested_genes)
            or [(p.gene_a, p.gene_b) for p in self.pairs] != expected
            or any(p.total_patients != self.total_patients for p in self.pairs)
            or self.multiple_testing.hypotheses != len(expected)
            or self.multiple_testing.estimable_tests != sum(p.p_value is not None for p in self.pairs)
            or self.multiple_testing.cross_request_correction
            or self.statistical_context.multiple_testing
            != "BH over all requested pairs in this call; no correction across calls."
        ):
            raise ValueError(
                "Multiple-testing correction must retain the complete requested patient hypothesis family"
            )
        return self


class SurvivalInterval(StrictRecord):
    lower: Probability | None
    upper: Probability | None
    status: Literal["undefined_at_zero", "boundary_no_events", "estimated"]


class SurvivalPoint(StrictRecord):
    time_months: Nonnegative
    at_risk: Annotated[int, Field(strict=True, ge=1)]
    events: Count
    censored: Count
    survival: Probability
    standard_error: Nonnegative | None
    confidence_interval: SurvivalInterval

    @model_validator(mode="after")
    def uncertainty(self):
        interval = self.confidence_interval
        if self.events + self.censored == 0 or self.events + self.censored > self.at_risk:
            raise ValueError("Each risk-set time consumes observed events or censoring only")
        if self.survival == 0:
            if (
                self.standard_error is not None
                or interval.lower is not None
                or interval.upper is not None
                or interval.status != "undefined_at_zero"
            ):
                raise ValueError("Observed extinction cannot establish zero uncertainty")
        elif self.survival == 1:
            if (self.standard_error, interval.lower, interval.upper, interval.status) != (
                0.0,
                1.0,
                1.0,
                "boundary_no_events",
            ):
                raise ValueError("No-event boundary retains its explicit asymptotic policy")
        elif (
            self.standard_error is None
            or interval.lower is None
            or interval.upper is None
            or interval.status != "estimated"
            or not interval.lower <= self.survival <= interval.upper
        ):
            raise ValueError("Pointwise survival uncertainty must retain ordered finite probability bounds")
        return self


class SurvivalUncertainty(StrictRecord):
    method: Literal["Greenwood standard error and pointwise log-log interval"]
    confidence_level: Literal[0.95]
    simultaneous_band: bool
    boundary_policy: Literal[
        "Undefined at survival zero; no-event asymptotic bounds do not prove absence of risk."
    ]


class SurvivalGroup(StrictRecord):
    group_name: Literal["mutant", "wild_type"]
    n_patients: Count
    n_events: Count
    n_censored: Count
    median_survival_months: Nonnegative | None
    median_definition: Literal["Earliest observed time with Kaplan–Meier survival at or below 0.5."]
    survival_1yr: Probability | None
    survival_3yr: Probability | None
    survival_5yr: Probability | None
    curve: list[SurvivalPoint]
    inference_status: Literal["estimated", "insufficient_data"]
    uncertainty: SurvivalUncertainty

    @model_validator(mode="after")
    def risk_sets(self):
        if (
            self.n_events + self.n_censored != self.n_patients
            or self.uncertainty.simultaneous_band
            or (self.inference_status == "estimated") != (self.n_patients > 0)
        ):
            raise ValueError("Survival observations and pointwise uncertainty must retain their patient unit")
        risk, value, crossing, previous = self.n_patients, 1.0, None, -1.0
        for point in self.curve:
            if point.time_months <= previous or point.at_risk != risk:
                raise ValueError("Survival times and risk-set denominators must agree")
            value *= 1 - point.events / risk
            if point.survival != value:
                raise ValueError("Survival must use event-before-censoring risk-set products")
            if crossing is None and value <= 0.5:
                crossing = point.time_months
            risk -= point.events + point.censored
            previous = point.time_months
        if (
            risk
            or sum(p.events for p in self.curve) != self.n_events
            or sum(p.censored for p in self.curve) != self.n_censored
            or self.median_survival_months != crossing
        ):
            raise ValueError(
                "Survival curve must consume all stated observations and retain its median definition"
            )
        for months, supplied in [(12, self.survival_1yr), (36, self.survival_3yr), (60, self.survival_5yr)]:
            value = None if not self.curve or months > self.curve[-1].time_months else 1.0
            if value is not None:
                for point in self.curve:
                    if point.time_months <= months:
                        value = point.survival
            if supplied != value:
                raise ValueError("Time-point survival cannot extrapolate beyond observed follow-up")
        return self


class LogRank(StrictRecord):
    statistic: Nonnegative | None
    p_value: Probability | None
    inference_status: Literal["estimated", "insufficient_data"]
    reason: str | None = None
    method: Literal["Two-sided log-rank, tied events hypergeometric variance"] | None = None
    degrees_of_freedom: Annotated[int, Field(strict=True, ge=1, le=1)] | None = None

    @model_validator(mode="after")
    def inference(self):
        if self.inference_status == "estimated":
            if (
                self.statistic is None
                or self.p_value is None
                or self.method is None
                or self.degrees_of_freedom != 1
            ):
                raise ValueError("Estimated log-rank inference requires finite statistic and probability")
        elif self.statistic is not None or self.p_value is not None or not self.reason:
            raise ValueError("Unavailable log-rank inference cannot become a null association")
        return self


class SurvivalRecord(PatientStudyRecord):
    record_type: Literal["study_survival"]
    endpoint: Literal["os", "dfs", "pfs", "dss"]
    groups: list[SurvivalGroup] = Field(min_length=2, max_length=2)
    excluded_patients: Count
    excluded_patients_by_reason: dict[
        Literal[
            "missing_patient_record",
            "missing_or_nonfinite_duration",
            "negative_duration",
            "missing_or_invalid_status",
        ],
        Count,
    ]
    patient_assignment: Literal["Any mutated eligible assayed sample; each patient counted once."]
    tie_policy: Literal["Events before censoring at the same time."]
    units: Literal["months"]
    log_rank: LogRank

    @model_validator(mode="after")
    def survival(self):
        if self.gene is None:
            raise ValueError("Survival groups require their requested mutation identity")
        self.mutation_selection([self.gene])
        self.require_roles({"clinical_sample_population", "mutation_events", "clinical_patient_outcomes"})
        if (
            {g.group_name for g in self.groups} != {"mutant", "wild_type"}
            or self.excluded_patients != sum(self.excluded_patients_by_reason.values())
            or sum(g.n_patients for g in self.groups) + self.excluded_patients != self.total_patients
        ):
            raise ValueError(
                "Excluded outcome records and measured patient groups must partition eligible patients"
            )
        patient = next(i for i in self.input_locators if i.role == "clinical_patient_outcomes")
        if patient.selection != [self.endpoint.upper() + "_MONTHS", self.endpoint.upper() + "_STATUS"]:
            raise ValueError("Survival inputs must locate the actual requested endpoint columns")
        if self.log_rank.inference_status == "estimated" and any(g.n_patients == 0 for g in self.groups):
            raise ValueError("A missing survival group cannot become an estimated comparison")
        return self


DERIVED_RECORDS = TypeAdapter(
    Annotated[
        MutationCohortRecord
        | MutationRankingRecord
        | FilteredCohortRecord
        | StructuralVariantRecord
        | MutationAssociationRecord
        | ExpressionComparisonRecord
        | CoOccurrenceRecord
        | SurvivalRecord,
        Field(discriminator="record_type"),
    ]
)


def derived_study_record(row, *, operation, request, files):
    """Validate only the newly derived families; existing profile contracts stay intact."""
    kind = {
        "cohort": "study_mutation_cohort",
        "top_mutated": "study_mutation_ranking",
        "filter": "study_filtered_cohort",
        "survival": "study_survival",
        "co_occurrence": "study_co_occurrence",
    }.get(operation)
    if operation == "compare":
        kind = "study_mutation_association" if request.type == "mutations" else "study_expression_comparison"
    if operation == "query" and request.type == "sv":
        kind = "study_structural_variants"
    if kind is None:
        return row
    try:
        mutation = operation in {"cohort", "top_mutated", "survival", "compare", "co_occurrence"} or (
            operation == "filter" and bool(request.mutated)
        )
        genes = (
            request.genes
            if operation == "co_occurrence"
            else request.mutated
            if operation == "filter"
            else [request.gene]
        )
        if operation == "compare" and request.type == "mutations":
            genes = [*genes, request.target]
        genes = sorted(set(filter(None, genes)))
        inputs = [
            {
                "role": "clinical_sample_population",
                "file": "data_clinical_sample.txt",
                "sha256": files["data_clinical_sample.txt"],
                "selection": None,
            }
        ]
        if mutation:
            inputs.append(
                {
                    "role": "mutation_events",
                    "file": "data_mutations.txt",
                    "sha256": files["data_mutations.txt"],
                    "selection": None if operation == "top_mutated" else genes,
                }
            )
        for assay in sorted({c["assay"] for c in row["measurement_coverage"].values()}):
            info = row["release"]["assays"][assay]
            inputs.append(
                {
                    "role": "gene_measurements",
                    "file": info["file"],
                    "sha256": files[info["file"]],
                    "selection": sorted(
                        {c["gene"] for c in row["measurement_coverage"].values() if c["assay"] == assay}
                    ),
                }
            )
        if operation == "survival":
            inputs.append(
                {
                    "role": "clinical_patient_outcomes",
                    "file": "data_clinical_patient.txt",
                    "sha256": files["data_clinical_patient.txt"],
                    "selection": [request.endpoint.upper() + "_MONTHS", request.endpoint.upper() + "_STATUS"],
                }
            )
        if kind == "study_structural_variants":
            inputs.append(
                {
                    "role": "structural_variant_events",
                    "file": "data_sv.txt",
                    "sha256": files["data_sv.txt"],
                    "selection": [request.gene],
                }
            )
        extra = {}
        if kind == "study_filtered_cohort":
            extra = {
                "population_samples": len(row["release"]["mutation_coverage"]["samples"])
                if mutation
                else row["clinical_samples"],
                "population_basis": "declared mutation-assayed samples" if mutation else "clinical samples",
            }
        if operation == "co_occurrence":
            extra["requested_genes"] = request.genes
        if kind == "study_structural_variants":
            extra.update(
                coverage_status="not_declared",
                denominator="Source-reported structural-variant rows; assay coverage is not declared",
            )
        if operation in {"survival", "compare", "co_occurrence"}:
            extra["patient_identity_namespace"] = "verified_study_patient_id"
        return DERIVED_RECORDS.validate_python(
            {
                **row,
                **extra,
                "record_type": kind,
                "identity_scope": "Gene symbols and sample/patient identifiers within this verified study release",
                "identity_namespace": "verified_study_gene_symbol",
                "sample_identity_namespace": "verified_study_sample_id",
                "assertion_type": "verified_release_derivation",
                "analysis_unit": "patient"
                if operation in {"survival", "compare", "co_occurrence"}
                else "source_table_row"
                if kind == "study_structural_variants"
                else "sample",
                "derivation": {"operation": operation, "method": METHODS[kind]},
                "input_locators": inputs,
                "coverage_locator": {
                    "release_metadata_sha256": row["release"]["metadata_sha256"],
                    "pointer": "/mutation_coverage",
                }
                if mutation
                else None,
            }
        ).model_dump(mode="json", exclude_unset=True)
    except (KeyError, ValidationError):
        raise ResearchError(
            "invalid_study", "Derived study result violates its scientific record contract."
        ) from None
