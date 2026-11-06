import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.extensions import ExtendedSources, StudyRequest
from biomedmcp.native.study import contingency, kaplan_meier, logrank


def request(**kwargs):
    return StudyRequest(study="ubi_synthetic", **kwargs)


def test_mutation_counts_denominator_and_top_genes_are_native(study):
    _, install = study
    analytics = install()
    result = analytics.run("query", request(gene="TP53"))
    assert result["total_samples"] == 4 and result["unique_samples"] == 2
    assert result["mutation_count"] == 2 and result["frequency"] == 0.5
    assert result["denominator"] == "declared mutation-assayed samples"
    top = analytics.run("top_mutated", request())
    assert top["genes"][0] == {"gene": "TP53", "mutated_samples": 2, "frequency": 0.5}


def test_missing_assay_coverage_is_unavailable_not_wildtype(study):
    _, install = study
    with pytest.raises(ResearchError, match="assayed samples"):
        install(False).run("cohort", request(gene="TP53"))


def test_missing_mutation_table_does_not_mean_no_mutations(study):
    directory, install = study
    (directory / "data_mutations.txt").unlink()
    with pytest.raises(ResearchError, match="No mutation assay"):
        install().run("cohort", request(gene="TP53"))


def test_cna_missing_values_and_filter_intersection(study):
    _, install = study
    analytics = install()
    cna = analytics.run("query", request(gene="ERBB2", type="cna"))
    assert cna["values"] == {"S1": 2.0, "S2": 0.0, "S3": 1.0, "S4": -2.0}
    filtered = analytics.run("filter", request(mutated=["TP53"], amplified=["ERBB2"]))
    assert filtered["sample_ids"] == ["S1"] and filtered["sample_count"] == 1
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="ABSENT", type="expression"))
    assert caught.value.code == "study_gene_unavailable"


def test_survival_exact_values_patient_denominators(study):
    _, install = study
    result = install().run("survival", request(gene="TP53"))
    groups = {g["group_name"]: g for g in result["groups"]}
    assert groups["mutant"]["n_patients"] == 2 and groups["mutant"]["n_events"] == 1
    assert groups["mutant"]["median_survival_months"] == 12
    assert groups["mutant"]["survival_1yr"] == 0.5
    assert groups["wild_type"]["median_survival_months"] == 18
    assert groups["wild_type"]["survival_1yr"] == 1.0
    assert result["log_rank"]["statistic"] == pytest.approx(1 / 17)
    assert result["log_rank"]["p_value"] == pytest.approx(0.8083651559)


def test_tied_events_before_censoring_and_no_extrapolation():
    result = kaplan_meier([(2, True), (2, False), (5, True), (8, False)])
    assert [(p["at_risk"], p["events"], p["censored"]) for p in result["curve"]] == [
        (4, 1, 1),
        (2, 1, 0),
        (1, 0, 1),
    ]
    assert result["curve"][0]["survival"] == 0.75
    assert result["curve"][1]["survival"] == 0.375
    assert result["median_survival_months"] == 5
    assert result["survival_1yr"] is None
    assert logrank([(2, False)], [(3, False)])["p_value"] is None


def test_multiple_samples_per_patient_count_once(study):
    directory, install = study
    p = directory / "data_clinical_sample.txt"
    p.write_text(p.read_text().replace("P2\tS2", "P1\tS2"))
    result = install().run("survival", request(gene="TP53"))
    assert sum(g["n_patients"] for g in result["groups"]) == 3


def test_fisher_exact_counts_and_declared_effect_correction(study):
    _, install = study
    data = install().run("co_occurrence", request(genes=["TP53", "KRAS"]))["pairs"][0]
    assert [data[k] for k in ["both", "a_only", "b_only", "neither"]] == [0, 2, 1, 1]
    assert data["p_value"] == 1.0 and data["fdr_bh"] == 1.0
    assert data["effect_pseudocount"] == 0.5
    assert contingency({1, 2, 3}, {1, 2, 4}, set(range(1, 7)))["odds_ratio"] == 4.0


def test_expression_comparison_uses_measured_values(study):
    _, install = study
    result = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["mutant"]["n"] == 2 and result["mutant"]["mean"] == 1.5
    assert result["wild_type"]["mean"] == 3.0
    assert result["test"]["p_value"] is not None


async def test_python_extension_executes_study_and_chart_without_executable(study, monkeypatch):
    _, install = study
    install()
    import asyncio

    def forbidden(*args, **kwargs):
        raise AssertionError("No subprocess may implement public research")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    source = ExtendedSources()
    result = await source.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53", "chart": True})
    assert sum(r["value"] for r in result["chart"]["spec"]["data"]["values"]) == result["mutation_count"]
    assert result["chart"]["metadata"]["total_samples"] == 4


def test_duplicate_patient_ids_fail_release_loading(study):
    directory, install = study
    p = directory / "data_clinical_patient.txt"
    p.write_text(p.read_text().replace("P2\t", "P1\t"))
    with pytest.raises(ResearchError, match="Duplicate patient"):
        install().run("survival", request(gene="TP53"))
