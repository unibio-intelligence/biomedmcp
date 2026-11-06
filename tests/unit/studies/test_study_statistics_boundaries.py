"""Invalid measurements and arithmetic limits cannot become negative evidence."""

import json

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.native.study_statistics import expression_comparison, kaplan_meier, logrank, summary


@pytest.mark.parametrize(
    "observation", [(float("nan"), True), (float("inf"), True), (-1, True), (1, 1), (True, True)]
)
@pytest.mark.parametrize("method", [kaplan_meier, lambda rows: logrank(rows, [(2, True)])])
def test_survival_helpers_reject_invalid_observations(method, observation):
    with pytest.raises(ResearchError) as caught:
        method([observation])
    assert caught.value.code == "invalid_study"


def test_extreme_finite_patient_summary_is_not_missing_or_nonfinite():
    result = summary([1.7e308, 1.7e308])
    assert result["mean"] == result["median"] == 1.7e308
    json.dumps(result, allow_nan=False)


def test_rank_inference_survives_unrepresentable_mean_effect_with_explicit_status():
    result = expression_comparison([1.7e308, 1.7e308], [-1.7e308, -1.7e308], units="release_units")
    assert result["p_value"] is not None
    effect = result["effect_size"]
    assert effect["rank_biserial"] == 1
    assert effect["mean_difference"] is None
    assert effect["mean_difference_status"] == "numerical_range_exceeded" and effect["mean_difference_reason"]
    assert effect["mean_difference_confidence_interval"]["status"] == "unavailable"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("scale", [1e200, 1e-200])
def test_unrepresentable_mean_uncertainty_is_explicit_without_fabricated_zero_width(scale):
    result = expression_comparison([scale, 2 * scale], [3 * scale, 4 * scale], units="release_units")
    assert result["p_value"] is not None
    interval = result["effect_size"]["mean_difference_confidence_interval"]
    assert interval["status"] == "unavailable" and interval["lower"] is None and interval["reason"]
    json.dumps(result, allow_nan=False)


def test_rank_direction_is_explicit_and_reverses_with_group_order():
    left, right = [1, 2, 2], [3, 4, 5]
    forward = expression_comparison(left, right, units="z_score")
    reverse = expression_comparison(right, left, units="z_score")
    assert forward["p_value"] == reverse["p_value"]
    assert forward["effect_size"]["rank_biserial"] == -1
    assert reverse["effect_size"]["rank_biserial"] == 1
    assert forward["effect_size"]["mean_difference"] == -reverse["effect_size"]["mean_difference"]


@pytest.mark.parametrize(
    "value,count",
    [(float.fromhex("0x1.fffffffffffffp+1023"), 3), (float.fromhex("0x0.0000000000001p-1022"), 2)],
)
def test_finite_mean_boundaries_do_not_overflow_or_underflow_into_a_false_zero(value, count):
    result = summary([value] * count)
    assert result["n"] == count and result["mean"] == value
    json.dumps(result, allow_nan=False)
