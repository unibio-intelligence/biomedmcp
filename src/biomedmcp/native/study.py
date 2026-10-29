"""Native read-only study analytics with explicit sample/patient denominators."""

import threading
from collections import Counter, defaultdict
from contextlib import ExitStack
from typing import ClassVar

from ..errors import ResearchError
from ..studies import study_paths, study_registry, verify_study_member
from ..study_derivations import derived_study_record
from ..study_metadata import study_metadata_record
from ..study_records import study_measurement_record, study_mutation_profile_record
from .study_statistics import (
    adjust_bh,
    contingency,
    expression_comparison,
    finite,
    kaplan_meier,
    logrank,
    median,
    summary,
)
from .study_storage import (
    ANALYSIS_RESERVATION,
    MAX_RESULT_BYTES,
    budget_error,
    matrix_index,
    matrix_row,
    payload_bytes,
    read_table,
    study_cache,
    verified_members,
)


class StudyAnalytics:
    def __init__(self, registry=None, cache=None):
        self.registry = study_registry() if registry is None else registry
        self.cache = study_cache if cache is None else cache
        self._context = threading.local()

    def table(self, directory, name, *, expected, ticket, kind, sample_ids=None):
        path = directory / name
        return read_table(path, expected, ticket, kind, sample_ids)

    def load(self, study):
        registry = self._context.registry
        if study not in registry:
            raise ResearchError("study_unavailable", "Study is not an installed verified public release.")
        view = StudyView(self, study, registry[study], self._context.stack)
        self._context.view = view
        return view

    def mutated(self, data, gene):
        if not data["mutation_available"]:
            raise ResearchError(
                "study_data_unavailable", "No mutation assay is available; missing data is not wild-type."
            )
        return {r["Tumor_Sample_Barcode"] for r in data["mutation_index"].get(gene, ())}

    def matrix(self, data, kind, gene, samples=None):
        if not data["assays"][kind]["available"]:
            raise ResearchError(
                "study_assay_unavailable",
                f"No {kind} assay is installed; missing measurements are not negative results.",
            )
        row = data.row(kind, gene)
        all_values = {s: v for s in data["samples"] if (v := finite(row.get(s))) is not None}
        values = {s: v for s, v in all_values.items() if samples is None or s in samples}
        if not all_values or (samples and not values):
            raise ResearchError(
                "study_measurements_unavailable",
                f"The {kind} gene row has no finite measurements in the eligible population.",
            )
        if (
            kind == "cna"
            and data["assays"][kind]["units"] == "discrete_copy_number_call"
            and any(v not in {-2, -1, 0, 1, 2} for v in values.values())
        ):
            raise ResearchError("invalid_study", "Discrete CNA calls must be -2, -1, 0, 1 or 2.")
        return values

    def run(self, operation, request, *, registry=None):
        current = study_registry()
        if registry is not None and registry != current:
            raise ResearchError("study_version_changed", "Study release changed before analysis.")
        registry = current
        self.registry = registry  # Diagnostic view only; analyses use their own snapshot.
        self._context.registry = registry
        self._context.view = None
        try:
            with self.cache.reserve(ANALYSIS_RESERVATION), ExitStack() as stack:
                self._context.stack = stack
                try:
                    result = self._run(operation, request)
                    # Refuse an oversized source calculation before creating
                    # typed model/JSON copies of its nested patient evidence.
                    if payload_bytes(result) > MAX_RESULT_BYTES:
                        raise budget_error()
                    if self._context.view is not None:
                        result = derived_study_record(
                            result,
                            operation=operation,
                            request=request,
                            files=self._context.view.consumed,
                        )
                    if payload_bytes(result) > MAX_RESULT_BYTES:
                        raise budget_error()
                    if self._context.view is not None:
                        self._context.view.verify_consumed()
                    if study_registry() != registry:
                        raise ResearchError("study_version_changed", "Study release changed during analysis.")
                    return result
                finally:
                    if self._context.view is not None:
                        self._context.view.clear()
        finally:
            self._context.__dict__.clear()

    def _run(self, operation, request):
        if operation == "list":
            return {"studies": [study_metadata_record(row) for row in self._context.registry.values()]}
        if operation == "co_occurrence" and (
            len(request.genes) < 2 or len(set(request.genes)) != len(request.genes)
        ):
            raise ResearchError("invalid_request", "Co-occurrence requires distinct gene hypotheses.")
        data = self.load(request.study)
        samples = set(data["samples"])
        gene = request.gene
        mutation_operation = (
            operation in {"cohort", "survival", "compare", "co_occurrence", "top_mutated"}
            or (operation == "query" and request.type == "mutations")
            or (operation == "filter" and request.mutated)
        )
        if mutation_operation:
            coverage = data["release"].get("mutation_coverage", {})
            declared = coverage.get("samples")
            genes = coverage.get("genes")
            if not declared or not genes:
                raise ResearchError(
                    "study_data_unavailable",
                    "Mutation denominators require declared assayed samples and gene coverage in the release manifest.",
                )
            if not set(declared) <= samples:
                raise ResearchError("invalid_study", "Mutation coverage references unknown samples.")
            requested = set(filter(None, [gene, *request.genes, *request.mutated]))
            if operation == "compare" and request.type == "mutations":
                requested.add(request.target)
            if genes != "all" and (operation == "top_mutated" or not requested <= set(genes)):
                raise ResearchError(
                    "study_data_unavailable",
                    "Requested genes are not covered by this declared mutation assay.",
                )
            samples = set(declared)
        assayed_samples = samples.copy()
        excluded_clinical = 0
        if operation == "filter" and request.cancer_type:
            clinical = {s for s, r in data["samples"].items() if r.get("CANCER_TYPE") in request.cancer_type}
            excluded_clinical = len(samples - clinical)
            samples &= clinical
        mutated = self.mutated(data, gene) & samples if mutation_operation else set()
        common = {
            "study_id": request.study,
            "release": data["release"],
            "gene": gene,
            "total_samples": len(samples),
            "clinical_samples": len(data["samples"]),
            "denominator": "declared mutation-assayed samples" if mutation_operation else "clinical samples",
            "measurement_coverage": {},
            "warnings": ["Synthetic demonstration with invented measurements; not a real biological cohort."]
            if data["release"].get("synthetic")
            else [],
        }
        if mutation_operation:
            excluded = sum(n for s, n in data["mutation_sample_counts"].items() if s not in assayed_samples)
            common["excluded_out_of_assay_mutation_events"] = excluded
            common["mutation_event_policy"] = (
                "Exclude events outside the declared mutation-assayed sample population from all numerators."
            )
            if excluded:
                common["warnings"].append(
                    f"Excluded {excluded} mutation events outside the declared assay population."
                )

        def measurements(kind, target):
            values = self.matrix(data, kind, target, samples)
            missing = samples - values.keys()
            common["measurement_coverage"][f"{kind}:{target}"] = {
                "assay": kind,
                "gene": target,
                "units": data["assays"][kind]["units"],
                "eligible_samples": len(samples),
                "measured_samples": len(values),
                "missing_samples": len(missing),
                "missing_sample_ids": sorted(missing)[:100],
                "missing_sample_ids_truncated": len(missing) > 100,
                "coverage_basis": "Finite values in the checksummed gene row; no imputation.",
            }
            if missing:
                common["warnings"].append(
                    f"{kind} measurements for {target} exclude {len(missing)} eligible samples with missing values."
                )
            return values

        if operation in {"survival", "compare", "co_occurrence"}:
            patient_samples = defaultdict(set)
            for sample in samples:
                patient = data["samples"][sample].get("PATIENT_ID")
                if not isinstance(patient, str) or not patient.strip():
                    raise ResearchError(
                        "invalid_study", "Inferential samples require a nonempty patient identity."
                    )
                patient_samples[patient].add(sample)
            patients = set(patient_samples)
            mutant_patients = {patient for patient, members in patient_samples.items() if members & mutated}
            common.update(
                total_patients=len(patients),
                analysis_unit="patient",
                sample_denominator=common["denominator"],
                denominator="Patients with at least one declared mutation-assayed sample",
                statistical_context={
                    "analysis_unit": "patient",
                    "selected_samples": len(samples),
                    "eligible_patients": len(patients),
                    "patients_with_multiple_samples": sum(
                        len(members) > 1 for members in patient_samples.values()
                    ),
                    "mutation_assignment": "Any mutation in eligible assayed samples; each patient assigned once.",
                    "independence_assumption": "Patients treated as independent; family, site and treatment clustering are unmodeled.",
                    "interpretation": "Exploratory unadjusted observational association; no causal or clinical recommendation.",
                    "temporal_limit": "Any-sample mutation assignment does not establish baseline exposure timing.",
                    "multiple_testing": "Single requested comparison; no correction across separate requests.",
                },
            )

        if operation == "query":
            if request.type == "mutations":
                events = [
                    r for r in data["mutation_index"].get(gene, ()) if r["Tumor_Sample_Barcode"] in samples
                ]
                result = {
                    **common,
                    "unique_samples": len(mutated),
                    "mutation_count": len(events),
                    "frequency": len(mutated) / len(samples) if samples else None,
                    "top_variant_classes": [
                        [classification, count]
                        for classification, count in Counter(
                            r.get("Variant_Classification", "unknown") for r in events
                        ).most_common(25)
                    ],
                }
                result = study_mutation_profile_record(result, files=data.files)
            else:
                if request.type == "sv":
                    if "data_sv.txt" not in data.files:
                        raise ResearchError(
                            "study_data_unavailable", "No structural-variant assay is installed."
                        )
                    rows = [
                        r
                        for r in data["sv"]
                        if gene in {r.get("Site1_Hugo_Symbol"), r.get("Site2_Hugo_Symbol")}
                    ]
                    if sum(payload_bytes(row) for row in rows[:25]) > MAX_RESULT_BYTES:
                        raise budget_error()
                    return {
                        **common,
                        "records": [dict(row) for row in rows[:25]],
                        "event_count": len(rows),
                        "unique_samples": len({r.get("Sample_Id") for r in rows}),
                        "truncated": len(rows) > 25,
                    }
                values = measurements("cna" if request.type == "cna" else "expression", gene)
                result = {
                    **common,
                    "total_samples": len(values),
                    "eligible_samples": len(samples),
                    "evaluable_samples": len(values),
                    "denominator": "Samples with finite gene-level assay measurements",
                    "measurement": request.type,
                    "measured_samples": len(values),
                    "missing_samples": len(samples) - len(values),
                    "values": values,
                    "counts": dict(Counter(str(v) for v in values.values())),
                }
                result = study_measurement_record(
                    result, files=data.files, assay=data["assays"][request.type]
                )
        elif operation == "cohort":
            result = {
                **common,
                "mutant_samples": sorted(mutated),
                "wild_type_samples": sorted(samples - mutated),
                "mutant_count": len(mutated),
                "wild_type_count": len(samples - mutated),
            }
        elif operation == "survival":
            if "data_clinical_patient.txt" not in data.files:
                raise ResearchError(
                    "study_data_unavailable",
                    "No patient outcome table is installed; unavailable follow-up is not zero events.",
                )
            groups = {"mutant": [], "wild_type": []}
            exclusions = Counter()
            prefix = request.endpoint.upper()
            for patient in sorted(patients):
                row = data["patients"].get(patient)
                if row is None:
                    exclusions["missing_patient_record"] += 1
                    continue
                duration = finite(row.get(prefix + "_MONTHS"))
                status = str(row.get(prefix + "_STATUS", "")).split(":")[0]
                if duration is None:
                    exclusions["missing_or_nonfinite_duration"] += 1
                elif duration < 0:
                    exclusions["negative_duration"] += 1
                elif status not in {"0", "1"}:
                    exclusions["missing_or_invalid_status"] += 1
                else:
                    groups["mutant" if patient in mutant_patients else "wild_type"].append(
                        (duration, status == "1")
                    )
            result = {
                **common,
                "endpoint": request.endpoint,
                "groups": [{"group_name": name, **kaplan_meier(obs)} for name, obs in groups.items()],
                "excluded_patients": sum(exclusions.values()),
                "excluded_patients_by_reason": dict(exclusions),
                "patient_assignment": "Any mutated eligible assayed sample; each patient counted once.",
                "tie_policy": "Events before censoring at the same time.",
                "units": "months",
                "log_rank": logrank(groups["mutant"], groups["wild_type"]),
            }
        elif operation == "compare":
            target = request.target
            if request.type == "mutations":
                other = self.mutated(data, target) & samples
                other_patients = {patient for patient, members in patient_samples.items() if members & other}
                result = {
                    **common,
                    "target": target,
                    **contingency(mutant_patients, other_patients, patients),
                }
            else:
                values = measurements("expression", target)
                patient_values = {
                    patient: median(measured)
                    for patient, members in patient_samples.items()
                    if (measured := [values[sample] for sample in sorted(members) if sample in values])
                }
                left = [
                    value for patient, value in sorted(patient_values.items()) if patient in mutant_patients
                ]
                right = [
                    value
                    for patient, value in sorted(patient_values.items())
                    if patient not in mutant_patients
                ]
                result = {
                    **common,
                    "evaluable_samples": len(values),
                    "excluded_missing_samples": len(samples - values.keys()),
                    "evaluable_patients": len(patient_values),
                    "excluded_missing_patients": len(patients - patient_values.keys()),
                    "test": expression_comparison(left, right, units=data["assays"]["expression"]["units"]),
                    "target": target,
                    "measurement": "Release-provided expression values; no implicit normalization",
                    "patient_expression_policy": "Median of finite measurements in eligible assayed samples; no imputation.",
                    "mutant": summary(left),
                    "wild_type": summary(right),
                }
        elif operation == "co_occurrence":
            result = {**common, "pairs": []}
            mutation_sets = {gene: self.mutated(data, gene) & samples for gene in request.genes}
            mutated_by_patient = {
                gene: {
                    patient for patient, members in patient_samples.items() if members & mutation_sets[gene]
                }
                for gene in request.genes
            }
            for index, left in enumerate(request.genes):
                for right in request.genes[index + 1 :]:
                    result["pairs"].append(
                        {
                            "gene_a": left,
                            "gene_b": right,
                            **contingency(mutated_by_patient[left], mutated_by_patient[right], patients),
                        }
                    )
            adjusted = adjust_bh([pair["p_value"] for pair in result["pairs"]])
            for pair, value in zip(result["pairs"], adjusted, strict=True):
                pair["fdr_bh"] = value
            result["multiple_testing"] = {
                "method": "Benjamini–Hochberg",
                "family": "All requested unordered distinct gene pairs in this one call",
                "hypotheses": len(result["pairs"]),
                "estimable_tests": sum(value is not None for value in adjusted),
                "unavailable_policy": "Unavailable pairs retain null results and count in the requested family size.",
                "dependence_limit": "Shared genes and patients create dependence; arbitrary-dependence FDR control is not established.",
                "cross_request_correction": False,
            }
            common["statistical_context"]["multiple_testing"] = (
                "BH over all requested pairs in this call; no correction across calls."
            )
            result["co_occurrence_definition"] = (
                "Mutations may occur in different eligible samples of the same patient; this is not cell-level co-occurrence."
            )
        elif operation == "top_mutated":
            mutated_by_gene = defaultdict(set)
            for g, rows in data["mutation_index"].items():
                mutated_by_gene[g].update(
                    r["Tumor_Sample_Barcode"] for r in rows if r["Tumor_Sample_Barcode"] in samples
                )
            result = {
                **common,
                "total_mutated_genes": sum(bool(ids) for ids in mutated_by_gene.values()),
                "ranking_truncated": sum(bool(ids) for ids in mutated_by_gene.values()) > request.limit,
                "ranking_scope": "Observed mutated genes only; unlisted genes are not an assay-negative inventory",
                "genes": [
                    {"gene": g, "mutated_samples": n, "frequency": n / len(samples) if samples else None}
                    for g, n in sorted(
                        ((g, len(ids)) for g, ids in mutated_by_gene.items() if ids),
                        key=lambda p: (-p[1], p[0]),
                    )[: request.limit]
                ],
            }
        elif operation == "filter":
            evaluable = samples.copy()
            positive = samples.copy()
            for g in request.mutated:
                positive &= self.mutated(data, g)
            for field, threshold in [("amplified", 2), ("deleted", -2)]:
                for g in getattr(request, field):
                    if data["assays"]["cna"]["units"] != "discrete_copy_number_call":
                        raise ResearchError(
                            "unsupported_measurement_units",
                            "Amplification/deletion filters require discrete CNA calls.",
                        )
                    values = measurements("cna", g)
                    evaluable &= values.keys()
                    positive &= {
                        s for s, v in values.items() if (v >= threshold if threshold > 0 else v <= threshold)
                    }
            for field, above in [("expression_above", True), ("expression_below", False)]:
                for g, bound in getattr(request, field).items():
                    values = measurements("expression", g)
                    evaluable &= values.keys()
                    positive &= {s for s, v in values.items() if (v > bound if above else v < bound)}
            if samples and not evaluable:
                raise ResearchError(
                    "study_measurements_unavailable",
                    "No eligible sample has measurements for every requested assay filter.",
                )
            selected = positive & evaluable
            missing = samples - evaluable
            result = {
                **common,
                "total_samples": len(evaluable),
                "eligible_samples": len(samples),
                "evaluable_samples": len(evaluable),
                "excluded_missing_samples": len(missing),
                "excluded_clinical_samples": excluded_clinical,
                "excluded_missing_sample_ids": sorted(missing)[:100],
                "excluded_missing_sample_ids_truncated": len(missing) > 100,
                "denominator": "Eligible samples evaluable for every requested measurement",
                "sample_count": len(selected),
                "sample_ids": sorted(selected)[:100],
                "truncated": len(selected) > 100,
                "filters": request.model_dump(exclude={"chart"}),
            }
        else:
            raise ResearchError("unknown_operation", "Unsupported study analysis.")
        return result


class StudyView:
    """Per-analysis references; release immutable payload leases before returning."""

    TABLES: ClassVar = {
        "samples": "data_clinical_sample.txt",
        "patients": "data_clinical_patient.txt",
        "mutations": "data_mutations.txt",
        "sv": "data_sv.txt",
    }

    def __init__(self, analytics, study, release, stack):
        self.analytics, self.release, self.stack = analytics, release, stack
        manifest, root = study_paths()
        root = root.resolve()
        self.directory = root / study
        self.files = verified_members(manifest, study, release["metadata_sha256"])
        self.key = (str(root), study, release["metadata_sha256"])
        self.values = {}
        self.consumed = {}

    def verify(self, filename):
        if filename not in self.consumed:
            verify_study_member(self.directory / filename, self.files[filename])
            self.consumed[filename] = self.files[filename]

    def verify_consumed(self):
        for filename, expected in self.consumed.items():
            verify_study_member(self.directory / filename, expected)

    def component(self, name, builder):
        if name not in self.values:
            self.values[name] = self.stack.enter_context(
                self.analytics.cache.lease((*self.key, name), builder)
            )
        return self.values[name]

    def __getitem__(self, kind):
        if kind == "release":
            return self.release
        if kind == "assays":
            return self.release["assays"]
        if kind == "mutation_available":
            return self.TABLES["mutations"] in self.files
        if kind == "sample_ids":
            self["samples"]
            return self.values["samples"]["sample_ids"]
        if kind in {"mutation_index", "mutation_sample_counts"}:
            self["mutations"]
            return self.values["mutations"]["genes" if kind == "mutation_index" else "sample_counts"]
        filename = self.TABLES[kind]
        if filename not in self.files:
            if kind == "samples":
                raise ResearchError("study_data_unavailable", "This release has no clinical sample table.")
            return {} if kind == "patients" else ()
        sample_ids = self["sample_ids"] if kind in {"mutations", "sv"} and kind not in self.values else None
        self.verify(filename)
        value = self.component(
            kind,
            lambda ticket: self.analytics.table(
                self.directory,
                filename,
                expected=self.files[filename],
                ticket=ticket,
                kind=kind,
                sample_ids=sample_ids,
            ),
        )
        return value["rows"] if kind in {"samples", "mutations"} else value

    def row(self, kind, gene):
        assay = self.release["assays"][kind]
        path = self.directory / assay["file"]
        self.verify(assay["file"])
        index = self.component(
            ("matrix-index", kind), lambda ticket: matrix_index(path, assay["sha256"], ticket)
        )
        return self.component(
            ("matrix-row", kind, gene), lambda ticket: matrix_row(path, index, gene, ticket)
        )

    def clear(self):
        self.values.clear()
