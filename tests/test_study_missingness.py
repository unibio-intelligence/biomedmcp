import json
import os
from pathlib import Path

import pytest
from test_native_studies import request

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.study import StudyAnalytics


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("cna", "data_cna.txt"),
        ("expression", "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"),
    ],
)
@pytest.mark.parametrize("missing", ["table", "gene", "all_na"])
def test_missing_matrix_measurements_are_unavailable(study, kind, filename, missing):
    directory, install = study
    path = directory / filename
    if missing == "table":
        path.unlink()
    elif missing == "gene":
        path.write_text(path.read_text().replace("ERBB2", "OTHER"))
    else:
        lines = path.read_text().splitlines()
        lines = [line if not line.startswith("ERBB2\t") else "ERBB2\t2064\tNA\tNA\tNA\tNA" for line in lines]
        path.write_text("\n".join(lines) + "\n")
    analytics = install()
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="ERBB2", type=kind))
    assert (
        caught.value.code
        == {
            "table": "study_assay_unavailable",
            "gene": "study_gene_unavailable",
            "all_na": "study_measurements_unavailable",
        }[missing]
    )
    filters = {"amplified": ["ERBB2"]} if kind == "cna" else {"expression_above": {"ERBB2": 1}}
    with pytest.raises(ResearchError):
        analytics.run("filter", request(**filters))
    if kind == "expression":
        with pytest.raises(ResearchError) as comparison:
            analytics.run("compare", request(gene="TP53", target="ERBB2", type="expression"))
        assert comparison.value.code == caught.value.code


def test_partial_measurements_use_evaluable_denominator_and_exclusions(study):
    directory, install = study
    path = directory / "data_cna.txt"
    path.write_text("Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\t2\t0\tNA\tNA\n")
    result = install().run("filter", request(amplified=["ERBB2"]))
    assert result["sample_count"] == 1
    assert result["evaluable_samples"] == 2
    assert result["excluded_missing_samples"] == 2
    assert result["excluded_missing_sample_ids"] == ["S3", "S4"]
    assert result["measurement_coverage"]["cna:ERBB2"]["units"] == "discrete_copy_number_call"
    assert result["warnings"]


def test_expression_comparison_reports_partial_measurements_and_units(study):
    directory, install = study
    (directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt").write_text(
        "Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\tNA\t2\t3\tNA\n"
    )
    analytics = install()
    result = analytics.run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["evaluable_samples"] == 2
    assert result["excluded_missing_samples"] == 2
    assert result["mutant"]["n"] == result["wild_type"]["n"] == 1
    assert result["measurement_coverage"]["expression:ERBB2"]["units"] == "z_score"
    assert result["warnings"]


def test_measured_zero_matches_are_distinct_from_unavailable(study):
    directory, install = study
    (directory / "data_cna.txt").write_text(
        "Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\t0\t0\t0\t0\n"
    )
    result = install().run("filter", request(amplified=["ERBB2"]))
    assert result["sample_count"] == 0
    assert result["evaluable_samples"] == 4
    assert result["excluded_missing_samples"] == 0
    assert result["warnings"] == []


def test_expression_target_does_not_require_mutation_panel_membership(study):
    _, install = study
    install()
    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    manifest = json.loads(path.read_text())
    manifest["studies"][0]["mutation_coverage"]["genes"] = ["TP53"]
    path.write_text(json.dumps(manifest))

    result = StudyAnalytics().run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert result["mutant"]["n"] == 2
    assert result["wild_type"]["n"] == 2


def test_mutation_event_numerators_exclude_out_of_assay_samples(study):
    _, install = study
    install()
    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    value = json.loads(path.read_text())
    value["studies"][0]["mutation_coverage"]["samples"] = ["S1", "S3", "S4"]
    path.write_text(json.dumps(value))
    result = StudyAnalytics().run("query", request(gene="TP53"))
    assert result["total_samples"] == 3
    assert result["unique_samples"] == 1
    assert result["mutation_count"] == 1
    assert sum(count for _, count in result["top_variant_classes"]) == 1
    assert result["excluded_out_of_assay_mutation_events"] == 1


def test_clinical_exclusions_are_not_labeled_missing_measurements(study):
    _, install = study
    result = install().run("filter", request(amplified=["ERBB2"], cancer_type=["No matching cancer"]))
    assert result["sample_count"] == 0
    assert result["excluded_clinical_samples"] == 4
    assert result["excluded_missing_samples"] == 0
    assert result["warnings"] == []


def test_disjoint_measurements_do_not_make_a_healthy_zero_cohort(study):
    directory, install = study
    (directory / "data_cna.txt").write_text(
        "Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\t2\tNA\tNA\tNA\n"
    )
    (directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt").write_text(
        "Hugo_Symbol\tEntrez_Gene_Id\tS1\tS2\tS3\tS4\nERBB2\t2064\tNA\t3\tNA\tNA\n"
    )
    with pytest.raises(ResearchError) as caught:
        install().run("filter", request(amplified=["ERBB2"], expression_above={"ERBB2": 1}))
    assert caught.value.code == "study_measurements_unavailable"


@pytest.mark.asyncio
async def test_public_study_filter_reports_unavailable_not_healthy_zero(study):
    directory, install = study
    (directory / "data_cna.txt").unlink()
    install()
    result = await execute(
        ResearchService(),
        "study_analysis",
        {
            "analysis": "filter_cohort",
            "study": "ubi_synthetic",
            "amplified": ["ERBB2"],
        },
        scope="public",
    )
    assert result.outcome == "unavailable"
    assert result.sections["study"].error["code"] == "study_assay_unavailable"
    assert result.provenance == []
