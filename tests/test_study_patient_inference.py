"""Inference must use qualified independent patients, not repeated biopsies."""

import json
import os
from pathlib import Path

import pytest
from test_native_studies import request

from biomedmcp.errors import ResearchError
from biomedmcp.native.study import StudyAnalytics, kaplan_meier


def repeat_patient(directory):
    path = directory / "data_clinical_sample.txt"
    path.write_text(path.read_text().replace("P2\tS2", "P1\tS2"))


@pytest.mark.parametrize("operation", ["compare", "co_occurrence"])
def test_mutation_tables_count_patients_once_and_retain_sample_denominator(study, operation):
    directory, install = study
    repeat_patient(directory)
    args = (
        request(gene="TP53", target="KRAS", type="mutations")
        if operation == "compare"
        else request(genes=["TP53", "KRAS"])
    )
    result = install().run(operation, args)
    table = result if operation == "compare" else result["pairs"][0]
    assert [table[k] for k in ["both", "a_only", "b_only", "neither"]] == [0, 1, 1, 1]
    assert result["total_samples"] == 4
    assert table["total_patients"] == 3 and table["analysis_unit"] == "patient"
    assert result["statistical_context"]["patients_with_multiple_samples"] == 1


def test_expression_uses_one_finite_patient_median_and_exclusive_mutation_groups(study):
    directory, install = study
    repeat_patient(directory)
    result = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["evaluable_samples"] == 4
    assert result["evaluable_patients"] == 3
    assert result["mutant"]["n"] == 1 and result["mutant"]["mean"] == 1.5
    assert result["wild_type"]["n"] == 2 and result["wild_type"]["mean"] == 3.0
    assert result["test"]["effect_size"]["mean_difference_confidence_interval"]["status"] == "unavailable"


def test_patient_expression_missingness_is_distinct_from_sample_missingness(study):
    directory, install = study
    repeat_patient(directory)
    path = directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"
    path.write_text("Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\tNA\tNA\t3\t4\n")
    result = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["excluded_missing_samples"] == 2
    assert result["excluded_missing_patients"] == 1
    assert result["evaluable_patients"] == 2 and result["mutant"]["n"] == 0
    assert result["test"]["p_value"] is None and result["test"]["reason"]


def test_out_of_panel_biopsy_cannot_assign_a_patient_to_mutant(study):
    directory, install = study
    repeat_patient(directory)
    path = directory / "data_mutations.txt"
    path.write_text("Hugo_Symbol\tTumor_Sample_Barcode\nTP53\tS2\nKRAS\tS3\n")
    install()
    manifest = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    data = json.loads(manifest.read_text())
    data["studies"][0]["mutation_coverage"]["samples"] = ["S1", "S3", "S4"]
    manifest.write_text(json.dumps(data))
    result = StudyAnalytics().run("compare", request(gene="TP53", target="KRAS", type="mutations"))
    assert result["total_patients"] == 3 and result["total_samples"] == 3
    assert result["both"] == result["a_only"] == 0
    assert result["p_value"] is None and result["inference_status"] == "insufficient_variation"


@pytest.mark.parametrize("operation", ["survival", "compare", "co_occurrence"])
def test_inference_rejects_missing_patient_identity(study, operation):
    directory, install = study
    path = directory / "data_clinical_sample.txt"
    path.write_text(path.read_text().replace("P1\tS1", "\tS1"))
    args = request(gene="TP53", target="ERBB2", type="expression", genes=["TP53", "KRAS"])
    with pytest.raises(ResearchError) as caught:
        install().run(operation, args)
    assert caught.value.code == "invalid_study"


def test_duplicate_requested_gene_pairs_are_not_independent_hypotheses(study):
    _, install = study
    with pytest.raises(ResearchError) as caught:
        install().run("co_occurrence", request(genes=["TP53", "TP53"]))
    assert caught.value.code == "invalid_request"


@pytest.mark.parametrize("observations", [[(1, True), (2, True)], [(1, True), (1, True)]])
def test_complete_observed_extinction_does_not_report_zero_uncertainty(observations):
    point = kaplan_meier(observations)["curve"][-1]
    assert point["survival"] == 0
    assert point["standard_error"] is None


async def test_actual_mcp_repeated_patient_comparison_has_one_inferential_unit(study, monkeypatch):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    directory, install = study
    repeat_patient(directory)
    install()
    async with Client(create_server(service=ResearchService())) as client:
        response = await client.call_tool(
            "study_analysis",
            {
                "analysis": "compare",
                "study": "ubi_synthetic",
                "gene": "TP53",
                "target": "ERBB2",
                "type": "expression",
            },
        )
    data = response.structured_content["sections"]["study"]["data"]
    assert data["mutant"]["n"] == 1
    assert data["statistical_context"]["analysis_unit"] == "patient"
    json.dumps(response.structured_content, allow_nan=False)


def test_unavailable_pairs_stay_in_the_requested_multiple_testing_family(study):
    _, install = study
    result = install().run("co_occurrence", request(genes=["TP53", "KRAS", "ABSENT"]))
    assert [(p["gene_a"], p["gene_b"]) for p in result["pairs"]] == [
        ("TP53", "KRAS"),
        ("TP53", "ABSENT"),
        ("KRAS", "ABSENT"),
    ]
    assert result["multiple_testing"]["hypotheses"] == 3
    assert result["multiple_testing"]["estimable_tests"] == 1
    assert result["multiple_testing"]["cross_request_correction"] is False
    assert all(p["p_value"] is None and p["fdr_bh"] is None and p["reason"] for p in result["pairs"][1:])


@pytest.mark.parametrize(
    "replacement,reason",
    [
        ("P1\t1:DECEASED\tNA", "missing_or_nonfinite_duration"),
        ("P1\t1:DECEASED\tinf", "missing_or_nonfinite_duration"),
        ("P1\t1:DECEASED\t-1", "negative_duration"),
        ("P1\tUNKNOWN\t12", "missing_or_invalid_status"),
        (None, "missing_patient_record"),
    ],
)
def test_survival_reports_actual_excluded_patient_reason(study, replacement, reason):
    directory, install = study
    path = directory / "data_clinical_patient.txt"
    path.write_text(
        path.read_text().replace("P1\t1:DECEASED\t12\n", "" if replacement is None else replacement + "\n")
    )
    result = install().run("survival", request(gene="TP53"))
    assert result["excluded_patients_by_reason"] == {reason: 1}
    assert result["excluded_patients"] == 1
    assert sum(group["n_patients"] for group in result["groups"]) == 3
    json.dumps(result, allow_nan=False)


def test_absent_survival_endpoint_cannot_establish_a_null_association(study):
    _, install = study
    result = install().run("survival", request(gene="TP53", endpoint="pfs"))
    assert result["excluded_patients"] == 4
    assert all(group["inference_status"] == "insufficient_data" for group in result["groups"])
    assert result["log_rank"]["p_value"] is None and result["log_rank"]["reason"]


def test_patient_aggregation_is_invariant_to_sample_order_and_uses_partial_finite_measurements(study):
    directory, install = study
    repeat_patient(directory)
    matrix = directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"
    matrix.write_text("Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\tNA\t1\t4\t2\n")
    before = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    path = directory / "data_clinical_sample.txt"
    header, *rows = path.read_text().splitlines()
    path.write_text("\n".join([header, *reversed(rows)]) + "\n")
    after = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert before["mutant"] == after["mutant"] == {"n": 1, "mean": 1, "median": 1, "analysis_unit": "patient"}
    assert before["test"] == after["test"]
    assert after["excluded_missing_samples"] == 1 and after["excluded_missing_patients"] == 0
    assert after["evaluable_patients"] == 3 and after["evaluable_samples"] == 3


def test_extreme_finite_biopsies_remain_measured_patient_values(study):
    directory, install = study
    repeat_patient(directory)
    path = directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"
    path.write_text("Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\t1.7e308\t1.7e308\t1\t2\n")
    result = install().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["mutant"]["median"] == 1.7e308
    assert result["evaluable_patients"] == 3 and result["excluded_missing_patients"] == 0
    assert result["test"]["p_value"] is not None
    json.dumps(result, allow_nan=False)
