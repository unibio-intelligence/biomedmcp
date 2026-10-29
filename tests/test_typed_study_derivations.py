"""Derived study records preserve patient/sample units and consumed inputs."""

import hashlib
import json
from copy import deepcopy

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.extensions import StudyRequest

CASES = [
    ("cohort", {"gene": "TP53"}, "study_mutation_cohort"),
    ("top_mutated", {"limit": 1}, "study_mutation_ranking"),
    ("filter", {"amplified": ["ERBB2"]}, "study_filtered_cohort"),
    ("survival", {"gene": "TP53"}, "study_survival"),
    ("compare", {"gene": "TP53", "target": "KRAS"}, "study_mutation_association"),
    ("compare", {"gene": "TP53", "target": "ERBB2", "type": "expression"}, "study_expression_comparison"),
    ("co_occurrence", {"genes": ["TP53", "KRAS", "ABSENT"]}, "study_co_occurrence"),
    ("query", {"gene": "ALK", "type": "sv"}, "study_structural_variants"),
]


def run_case(study, operation, parameters):
    directory, install = study
    if parameters.get("type") == "sv":
        (directory / "data_sv.txt").write_text(
            "Site1_Hugo_Symbol\tSite2_Hugo_Symbol\tSample_Id\nALK\tEML4\tS1\nALK\tEML4\tS1\n"
        )
    return directory, install().run(operation, StudyRequest(study="ubi_synthetic", **parameters))


@pytest.mark.parametrize("operation,parameters,record_type", CASES)
def test_every_remaining_analysis_retains_typed_method_and_actual_inputs(
    study, operation, parameters, record_type
):
    directory, result = run_case(study, operation, parameters)
    assert result["record_type"] == record_type
    assert (
        result["identity_scope"]
        == "Gene symbols and sample/patient identifiers within this verified study release"
    )
    assert "species" not in result and "assembly" not in result
    assert result["derivation"]["operation"] == operation
    assert result["derivation"]["method"]
    for locator in result["input_locators"]:
        assert locator["sha256"] == hashlib.sha256((directory / locator["file"]).read_bytes()).hexdigest()
    roles = {item["role"] for item in result["input_locators"]}
    assert "clinical_sample_population" in roles
    if operation == "survival":
        assert "clinical_patient_outcomes" in roles
    else:
        assert "clinical_patient_outcomes" not in roles
    if operation == "filter" or parameters.get("type") == "expression":
        assert "gene_measurements" in roles
    if parameters.get("type") == "sv":
        assert result["event_count"] == 2 and result["unique_samples"] == 1
        assert result["coverage_status"] == "not_declared"
        assert "frequency" not in result
    json.dumps(result, allow_nan=False)


def test_empty_installed_structural_variant_table_is_a_reported_zero_window(study):
    directory, install = study
    (directory / "data_sv.txt").write_text("Site1_Hugo_Symbol\tSite2_Hugo_Symbol\tSample_Id\n")
    result = install().run("query", StudyRequest(study="ubi_synthetic", gene="ALK", type="sv"))
    assert result["event_count"] == result["unique_samples"] == 0
    assert result["records"] == [] and result["coverage_status"] == "not_declared"
    assert result["input_locators"][-1]["role"] == "structural_variant_events"


def test_structural_variant_cannot_join_an_unknown_clinical_sample(study):
    directory, install = study
    (directory / "data_sv.txt").write_text(
        "Site1_Hugo_Symbol\tSite2_Hugo_Symbol\tSample_Id\nALK\tEML4\tUNKNOWN\n"
    )
    with pytest.raises(ResearchError) as caught:
        install().run("query", StudyRequest(study="ubi_synthetic", gene="ALK", type="sv"))
    assert caught.value.code == "invalid_study"


def test_absent_patient_outcome_file_is_not_a_zero_event_survival_analysis(study):
    directory, install = study
    (directory / "data_clinical_patient.txt").unlink()
    with pytest.raises(ResearchError) as caught:
        install().run("survival", StudyRequest(study="ubi_synthetic", gene="TP53"))
    assert caught.value.code == "study_data_unavailable"


@pytest.mark.parametrize(
    "case_index,path,value",
    [
        (0, ["mutant_count"], 3),
        (0, ["wild_type_samples"], ["S1", "S2"]),
        (1, ["genes", 0, "frequency"], 0.9),
        (1, ["total_mutated_genes"], 0),
        (2, ["sample_count"], True),
        (2, ["evaluable_samples"], 3),
        (2, ["excluded_missing_samples"], 1),
        (3, ["groups", 0, "curve", 0, "at_risk"], 8),
        (3, ["groups", 0, "curve", 0, "survival"], 0.99),
        (3, ["excluded_patients"], 2),
        (3, ["log_rank", "p_value"], float("nan")),
        (4, ["both"], 1),
        (4, ["p_value"], 1.1),
        (4, ["analysis_unit"], "sample"),
        (5, ["evaluable_patients"], 1),
        (5, ["mutant", "mean"], float("inf")),
        (5, ["test", "effect_size", "units"], "invented_unit"),
        (6, ["multiple_testing", "hypotheses"], 1),
        (6, ["pairs", 1, "fdr_bh"], 0.0),
        (6, ["requested_genes"], ["TP53", "TP53", "ABSENT"]),
        (7, ["unique_samples"], 2),
        (7, ["records", 0, "Site1_Hugo_Symbol"], "FORGED"),
        (7, ["truncated"], True),
    ],
)
def test_inconsistent_derived_science_cannot_validate_as_a_typed_success(study, case_index, path, value):
    from pydantic import ValidationError

    from biomedmcp.study_derivations import DERIVED_RECORDS

    operation, parameters, _ = CASES[case_index]
    _, result = run_case(study, operation, parameters)
    changed = deepcopy(result)
    parent = changed
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ValidationError):
        DERIVED_RECORDS.validate_python(changed)


def test_missing_expression_patients_remain_unavailable_inference_with_explicit_inputs(study):
    directory, install = study
    path = directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"
    path.write_text("Hugo_Symbol\tS1\tS2\tS3\tS4\nERBB2\tNA\tNA\t3\t4\n")
    result = install().run(
        "compare", StudyRequest(study="ubi_synthetic", gene="TP53", target="ERBB2", type="expression")
    )
    assert result["excluded_missing_samples"] == result["excluded_missing_patients"] == 2
    assert result["mutant"]["n"] == 0 and result["mutant"]["mean"] is None
    assert result["test"]["p_value"] is None and result["test"]["inference_status"] == "insufficient_data"
    assert {item["role"] for item in result["input_locators"]} == {
        "clinical_sample_population",
        "mutation_events",
        "gene_measurements",
    }


async def test_actual_mcp_exposes_derived_schema_and_preserves_patient_receipt(study, monkeypatch):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    _, install = study
    install()
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        discovery = await client.call_tool("capabilities", {"source": "study"})
        assert "study_derived" in discovery.structured_content["record_schemas"]
        response = await client.call_tool(
            "study_analysis",
            {
                "analysis": "compare",
                "study": "ubi_synthetic",
                "gene": "TP53",
                "target": "KRAS",
                "type": "mutations",
            },
        )
    result = response.structured_content
    data = result["sections"]["study"]["data"]
    assert data["record_type"] == "study_mutation_association" and data["analysis_unit"] == "patient"
    assert result["provenance"][0]["content_hash"] and result["receipt"]["result_sha256"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("predicate", ["expression_above", "expression_below"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_expression_predicate_is_rejected_before_analysis(predicate, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StudyRequest(study="ubi_synthetic", **{predicate: {"ERBB2": value}})


@pytest.mark.parametrize("case_index", range(len(CASES)))
def test_input_selector_drift_cannot_relabel_acquired_study_evidence(study, case_index):
    from pydantic import ValidationError

    from biomedmcp.study_derivations import DERIVED_RECORDS

    operation, parameters, _ = CASES[case_index]
    _, result = run_case(study, operation, parameters)
    changed = deepcopy(result)
    changed["input_locators"][-1]["selection"] = ["FORGED"]
    with pytest.raises(ValidationError):
        DERIVED_RECORDS.validate_python(changed)


def test_filter_cannot_lose_measurement_coverage_and_turn_missingness_into_negative(study):
    from pydantic import ValidationError

    from biomedmcp.study_derivations import DERIVED_RECORDS

    _, result = run_case(study, "filter", {"amplified": ["ERBB2"]})
    result["measurement_coverage"] = {}
    result["input_locators"] = [x for x in result["input_locators"] if x["role"] != "gene_measurements"]
    with pytest.raises(ValidationError):
        DERIVED_RECORDS.validate_python(result)


@pytest.mark.parametrize("bound,selected", [(1.7e308, 0), (-1.7e308, 4)])
def test_large_finite_expression_threshold_keeps_a_measured_population(study, bound, selected):
    _, install = study
    result = install().run("filter", StudyRequest(study="ubi_synthetic", expression_above={"ERBB2": bound}))
    assert result["sample_count"] == selected
    assert result["evaluable_samples"] == 4 and result["excluded_missing_samples"] == 0


async def test_large_typed_cohort_recovers_original_sample_identities_and_counts(study, monkeypatch):
    import os
    from pathlib import Path

    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    directory, install = study
    path = directory / "data_clinical_sample.txt"
    path.write_text(path.read_text() + "".join(f"P{i}\tS{i}\tLung\n" for i in range(5, 605)))
    install()
    manifest = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    declared = json.loads(manifest.read_text())
    declared["studies"][0]["mutation_coverage"]["samples"] = [f"S{i}" for i in range(1, 605)]
    manifest.write_text(json.dumps(declared))
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        response = await client.call_tool(
            "study_analysis", {"analysis": "mutation_cohort", "study": "ubi_synthetic", "gene": "TP53"}
        )
        section = response.structured_content["sections"]["study"]
        data = section["data"]
        assert data["record_type"] == "study_mutation_cohort"
        assert data["total_samples"] == 604 and data["wild_type_count"] == 602
        assert len(data["wild_type_samples"]) < data["wild_type_count"] and section["truncated"]
        root = json.loads((await client.read_resource(section["recovery"]["uri"]))[0].text)
        uri = next(item["uri"] for item in root["children"] if item["field"] == "wild_type_samples")
        recovered = []
        while uri is not None:
            chunk = json.loads((await client.read_resource(uri))[0].text)
            assert chunk["range"]["total"] == 602 and chunk["evidence_ids"] == section["evidence_ids"]
            recovered.extend(chunk["value"])
            uri = chunk["next_uri"]
    assert len(recovered) == len(set(recovered)) == 602
    assert set(recovered) == {f"S{i}" for i in range(3, 605)}


@pytest.mark.parametrize("value", [True, False, "1.5"])
def test_expression_predicate_cannot_coerce_booleans_or_strings_into_measurements(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StudyRequest(study="ubi_synthetic", expression_above={"ERBB2": value})
