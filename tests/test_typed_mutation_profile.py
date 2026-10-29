"""Mutation events, unique samples and assay denominators remain independent."""

import hashlib
from types import SimpleNamespace

import pytest


def request():
    return SimpleNamespace(study="ubi_synthetic", gene="TP53", genes=[], mutated=[], type="mutations")


def test_profile_has_explicit_typed_sample_denominator_and_inputs(study):
    directory, install = study
    result = install().run("query", request())
    assert result["record_type"] == "study_mutation_profile"
    assert result["assertion_type"] == "verified_release_mutation_frequency"
    assert result["clinical_samples"] == result["assayed_samples"] == 4
    assert result["total_samples"] == result["assayed_samples"]
    assert result["unique_samples"] == 2 and result["mutation_count"] == 2
    assert result["frequency"] == 0.5
    assert result["sample_unit"] == "samples"
    assert result["calculation"] == {
        "numerator": 2,
        "denominator": 4,
        "method": "Unique mutated assayed samples divided by declared mutation-assayed samples.",
    }
    assert "species" not in result and "assembly" not in result
    for item in result["input_locators"]:
        assert item["sha256"] == hashlib.sha256((directory / item["file"]).read_bytes()).hexdigest()
    assert {item["role"] for item in result["input_locators"]} == {
        "clinical_sample_population",
        "mutation_events",
    }
    assert result["coverage_locator"] == {
        "release_metadata_sha256": result["release"]["metadata_sha256"],
        "pointer": "/mutation_coverage",
    }


def test_clinical_population_is_not_mutation_assay_denominator(study):
    directory, install = study
    sample_file = directory / "data_clinical_sample.txt"
    sample_file.write_text(sample_file.read_text() + "P5\tS5\tLung\n")
    analytics = install()
    result = analytics.run("query", request())
    assert result["clinical_samples"] == 5
    assert result["assayed_samples"] == result["total_samples"] == 4
    assert (
        result["frequency"]
        == result["calculation"]["numerator"] / result["calculation"]["denominator"]
        == 0.5
    )


def test_mutation_record_contract_rejects_a_wrong_denominator(study):
    from pydantic import ValidationError

    from biomedmcp.study_records import StudyMutationProfileRecord

    _, install = study
    result = install().run("query", request())
    result["calculation"]["denominator"] = 3
    with pytest.raises(ValidationError):
        StudyMutationProfileRecord.model_validate(result)


def test_sample_count_cannot_be_replaced_by_mutation_event_count(study):
    from pydantic import ValidationError

    from biomedmcp.study_records import StudyMutationProfileRecord

    _, install = study
    result = install().run("query", request())
    result["unique_samples"] = 3
    result["frequency"] = 0.75
    result["calculation"]["numerator"] = 3
    with pytest.raises(ValidationError):
        StudyMutationProfileRecord.model_validate(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("frequency", float("nan")),
        ("frequency", 0.25),
        ("assayed_samples", True),
        ("clinical_samples", 3),
        ("top_variant_classes", [["Missense_Mutation", True]]),
        ("top_variant_classes", [["Missense_Mutation", 3]]),
        ("top_variant_classes", []),
    ],
)
def test_invalid_mutation_summary_cannot_be_a_typed_success(study, field, value):
    from pydantic import ValidationError

    from biomedmcp.study_records import StudyMutationProfileRecord

    _, install = study
    result = install().run("query", request())
    result[field] = value
    with pytest.raises(ValidationError):
        StudyMutationProfileRecord.model_validate(result)
