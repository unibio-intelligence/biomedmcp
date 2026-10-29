"""Fixed independently generated R results; normal CI never executes R or networks."""

import hashlib
import json
from pathlib import Path

import pytest

from biomedmcp.native import study as methods

FIXTURES = Path(__file__).parent / "fixtures/statistics"
CASES = json.loads((FIXTURES / "r-cases.json").read_text())
REFERENCE = json.loads((FIXTURES / "r-reference.json").read_text())
REFERENCES = {
    key: {case["id"]: case for case in rows} for key, rows in REFERENCE.items() if isinstance(rows, list)
}


def same(actual, expected, *, relative=1e-10, absolute=1e-12):
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected, rel=relative, abs=absolute)


def test_independent_reference_inputs_and_generator_are_unchanged():
    for field, path in [
        ("inputs_md5", FIXTURES / "r-cases.json"),
        ("generator_md5", FIXTURES.parents[2] / "scripts/reference-statistics.R"),
    ]:
        assert (
            hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest() == REFERENCE["reference"][field]
        )
    assert REFERENCE["reference"]["survival_version"] == "3.8.6"
    assert REFERENCE["reference"]["stats_version"] == "4.6.1"


@pytest.mark.parametrize("case", CASES["kaplan_meier"], ids=lambda row: row["id"])
def test_kaplan_meier_and_pointwise_uncertainty_match_r_survival(case):
    expected = REFERENCES["kaplan_meier"][case["id"]]
    result = methods.kaplan_meier(case["observations"])
    assert len(result["curve"]) == len(expected["curve"])
    same(result["median_survival_months"], expected.get("median_survival_months"))
    for point, reference in zip(result["curve"], expected["curve"], strict=True):
        for field in ["time_months", "at_risk", "events", "censored", "survival", "standard_error"]:
            same(point[field], reference[field])
        same(point["confidence_interval"]["lower"], reference["lower"])
        same(point["confidence_interval"]["upper"], reference["upper"])
    if not case["observations"]:
        assert result["inference_status"] == "insufficient_data"


@pytest.mark.parametrize("case", CASES["logrank"], ids=lambda row: row["id"])
def test_logrank_matches_independent_r_survdiff(case):
    expected = REFERENCES["logrank"][case["id"]]
    result = methods.logrank(case["left"], case["right"])
    if case["id"] in {"no_events", "empty_group", "all_fail_same_time"}:
        assert result["statistic"] is None and result["p_value"] is None and result["reason"]
        return
    same(result["statistic"], expected["statistic"])
    same(result["p_value"], expected["p_value"])
    if expected["p_value"] is None:
        assert result["reason"]


def table_sets(table):
    both, a_only, b_only, neither = [count for row in table for count in row]
    a = set(range(both + a_only))
    b = set(range(both)) | set(range(both + a_only, both + a_only + b_only))
    return a, b, set(range(both + a_only + b_only + neither))


@pytest.mark.parametrize("case", CASES["fisher"], ids=lambda row: row["id"])
def test_fisher_conditional_effect_and_exact_interval_match_r(case):
    expected = REFERENCES["fisher"][case["id"]]
    result = methods.contingency(*table_sets(case["table"]))
    counts = [count for row in case["table"] for count in row]
    assert [result[field] for field in ["both", "a_only", "b_only", "neither"]] == counts
    if case["id"] in {"empty", "constant"}:
        assert result["p_value"] is None and result["reason"]
        assert result["log_odds_ratio"] is None
        return
    same(result["p_value"], expected["p_value"])
    # The reference keeps R's equations and tightens its root-solver tolerance.
    same(result["conditional_odds_ratio"], expected["conditional_odds_ratio"], relative=1e-8, absolute=1e-10)
    interval = result["conditional_odds_ratio_confidence_interval"]
    same(interval["lower"], expected["lower"], relative=1e-8, absolute=1e-10)
    same(interval["upper"], expected["upper"], relative=1e-8, absolute=1e-10)
    assert interval["upper_unbounded"] == expected["upper_unbounded"]
    if expected["conditional_odds_ratio_infinite"]:
        assert result["conditional_odds_ratio_status"] == "infinite"
    assert result["analysis_unit"] == "patient"


@pytest.mark.parametrize("case", CASES["expression"], ids=lambda row: row["id"])
def test_expression_rank_test_and_welch_mean_interval_match_r(case):
    expected = REFERENCES["expression"][case["id"]]
    result = methods.expression_comparison(case["left"], case["right"], units="z_score")
    same(result["statistic"], expected["statistic"])
    same(result["p_value"], expected["p_value"])
    same(result["effect_size"]["mean_difference"], expected["mean_difference"])
    interval = result["effect_size"]["mean_difference_confidence_interval"]
    same(interval["lower"], expected["mean_difference_lower"])
    same(interval["upper"], expected["mean_difference_upper"])
    same(interval["degrees_of_freedom"], expected["degrees_of_freedom"])
    if expected["p_value"] is None:
        assert result["reason"]


@pytest.mark.parametrize("case", CASES["bh"], ids=lambda row: row["id"])
def test_bh_matches_r_with_full_requested_family_and_missing_tests(case):
    expected = REFERENCES["bh"][case["id"]]["adjusted"]
    result = methods.adjust_bh(case["p_values"])
    assert len(result) == len(expected)
    for actual, reference in zip(result, expected, strict=True):
        same(actual, reference)
