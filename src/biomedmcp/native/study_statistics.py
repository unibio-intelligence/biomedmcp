"""Patient-level exploratory inference, qualified against independent R fixtures."""

import math
from collections import defaultdict
from statistics import NormalDist
from statistics import median as ordinary_median

from ..errors import ResearchError

CONFIDENCE_LEVEL = 0.95
Z95 = NormalDist().inv_cdf((1 + CONFIDENCE_LEVEL) / 2)


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def observations(values):
    result = []
    for time, event in values:
        time = None if isinstance(time, bool) else finite(time)
        if time is None or time < 0 or not isinstance(event, bool):
            raise ResearchError(
                "invalid_study", "Survival observations require finite nonnegative times and boolean events."
            )
        result.append((time, event))
    return result


def kaplan_meier(values):
    values = observations(values)
    grouped = defaultdict(lambda: [0, 0])
    for time, event in values:
        grouped[time][0 if event else 1] += 1
    risk, survival, greenwood = len(values), 1.0, 0.0
    curve, crossing = [], None
    for time, (events, censored) in sorted(grouped.items()):
        before = risk
        if events:
            survival *= 1 - events / risk
            if risk > events:
                greenwood += events / (risk * (risk - events))
            if crossing is None and survival <= 0.5:
                crossing = time
        if survival == 0:
            standard_error = lower = upper = None
            uncertainty_status = "undefined_at_zero"
        elif survival == 1:
            standard_error, lower, upper = 0.0, 1.0, 1.0
            uncertainty_status = "boundary_no_events"
        else:
            standard_error = survival * math.sqrt(greenwood)
            log_hazard = math.log(-math.log(survival))
            displacement = Z95 * math.sqrt(greenwood) / abs(math.log(survival))
            # Large displacements have limiting bounds 0 and 1; avoid exp overflow.
            lower = math.exp(-math.exp(log_hazard + displacement)) if log_hazard + displacement < 700 else 0.0
            upper = math.exp(-math.exp(log_hazard - displacement))
            uncertainty_status = "estimated"
        curve.append(
            {
                "time_months": time,
                "at_risk": before,
                "events": events,
                "censored": censored,
                "survival": survival,
                "standard_error": standard_error,
                "confidence_interval": {"lower": lower, "upper": upper, "status": uncertainty_status},
            }
        )
        risk -= events + censored

    def at(months):
        if not curve or months > curve[-1]["time_months"]:
            return None
        value = 1.0
        for point in curve:
            if point["time_months"] <= months:
                value = point["survival"]
        return value

    return {
        "n_patients": len(values),
        "n_events": sum(event for _, event in values),
        "n_censored": sum(not event for _, event in values),
        "median_survival_months": crossing,
        "median_definition": "Earliest observed time with Kaplan–Meier survival at or below 0.5.",
        "survival_1yr": at(12),
        "survival_3yr": at(36),
        "survival_5yr": at(60),
        "curve": curve,
        "inference_status": "estimated" if values else "insufficient_data",
        "uncertainty": {
            "method": "Greenwood standard error and pointwise log-log interval",
            "confidence_level": CONFIDENCE_LEVEL,
            "simultaneous_band": False,
            "boundary_policy": "Undefined at survival zero; no-event asymptotic bounds do not prove absence of risk.",
        },
    }


def logrank(left, right):
    from scipy.stats import chi2

    left, right = observations(left), observations(right)
    grouped = defaultdict(lambda: [0, 0, 0, 0])
    for group, rows in enumerate([left, right]):
        for time, event in rows:
            grouped[time][group * 2 + (0 if event else 1)] += 1
    n1, n2, difference, variance = len(left), len(right), 0.0, 0.0
    for d1, c1, d2, c2 in (row for _, row in sorted(grouped.items())):
        n, d = n1 + n2, d1 + d2
        if d and n > 1:
            difference += d1 - d * n1 / n
            variance += n1 * n2 * d * (n - d) / (n * n * (n - 1))
        n1 -= d1 + c1
        n2 -= d2 + c2
    if not left or not right or variance <= 0:
        return {
            "statistic": None,
            "p_value": None,
            "inference_status": "insufficient_data",
            "reason": "Insufficient events or risk-set variation.",
        }
    statistic = difference**2 / variance
    return {
        "statistic": statistic,
        "p_value": float(chi2.sf(statistic, 1)),
        "inference_status": "estimated",
        "method": "Two-sided log-rank, tied events hypergeometric variance",
        "degrees_of_freedom": 1,
    }


def contingency(a, b, universe):
    from scipy.stats import fisher_exact
    from scipy.stats.contingency import odds_ratio

    a, b = a & universe, b & universe
    counts = len(a & b), len(a - b), len(b - a), len(universe - a - b)
    both, a_only, b_only, neither = counts
    result = {
        "both": both,
        "a_only": a_only,
        "b_only": b_only,
        "neither": neither,
        "total_patients": len(universe),
        "analysis_unit": "patient",
        "test": "Two-sided Fisher exact (unmodified patient counts)",
        "odds_ratio_definition": "Observed cross-product ratio; distinct from the conditional maximum-likelihood estimate.",
        "log_odds_ratio_definition": "Log cross-product ratio; 0.5 added to all four effect-size cells only when any cell is zero.",
    }
    interval = {
        "confidence_level": CONFIDENCE_LEVEL,
        "method": "Exact conditional odds-ratio interval",
        "lower": None,
        "upper": None,
        "upper_unbounded": False,
        "status": "unavailable",
    }
    result.update(
        p_value=None,
        odds_ratio=None,
        odds_ratio_status="undefined",
        conditional_odds_ratio=None,
        conditional_odds_ratio_status="undefined",
        log_odds_ratio=None,
        effect_pseudocount=None,
        conditional_odds_ratio_confidence_interval=interval,
    )
    if not universe or not a or a == universe or not b or b == universe:
        result.update(
            inference_status="insufficient_data" if not universe else "insufficient_variation",
            reason="No eligible patients."
            if not universe
            else "One or both mutation indicators are constant among eligible patients.",
        )
        return result
    table = [[both, a_only], [b_only, neither]]
    sample_odds, p_value = fisher_exact(table)
    conditional = odds_ratio(table, kind="conditional")
    limits = conditional.confidence_interval(confidence_level=CONFIDENCE_LEVEL)
    correction = 0.5 if 0 in counts else 0.0
    result.update(
        inference_status="estimated",
        p_value=float(p_value),
        odds_ratio=finite(sample_odds),
        odds_ratio_status="finite" if math.isfinite(sample_odds) else "infinite",
        conditional_odds_ratio=finite(conditional.statistic),
        conditional_odds_ratio_status="finite" if math.isfinite(conditional.statistic) else "infinite",
        log_odds_ratio=math.log(
            (both + correction) * (neither + correction) / ((a_only + correction) * (b_only + correction))
        ),
        effect_pseudocount=correction,
    )
    interval.update(
        lower=finite(limits.low),
        upper=finite(limits.high),
        upper_unbounded=math.isinf(limits.high),
        status="estimated",
    )
    return result


def mean(values):
    if not values:
        return None
    scale = max(abs(value) for value in values)
    if not scale:
        return 0.0
    # Scaling before summing preserves finite extremes and equal subnormal values.
    return (math.fsum(value / scale for value in values) / len(values)) * scale


def median(values):
    value = ordinary_median(values)
    if math.isfinite(value):
        return value
    ordered = sorted(values)
    middle = len(ordered) // 2
    return mean(ordered[middle - 1 : middle + 1])


def summary(values):
    return {
        "n": len(values),
        "mean": mean(values),
        "median": median(values) if values else None,
        "analysis_unit": "patient",
    }


def expression_comparison(left, right, *, units):
    from scipy.stats import mannwhitneyu, t

    if any(finite(value) is None for value in left + right):
        raise ResearchError("invalid_study", "Expression comparisons require finite patient measurements.")
    interval = {
        "lower": None,
        "upper": None,
        "degrees_of_freedom": None,
        "status": "unavailable",
        "confidence_level": CONFIDENCE_LEVEL,
        "method": "Welch t interval for the difference in patient-level means",
    }
    effect = {
        "mean_difference": None,
        "mean_difference_status": "unavailable",
        "rank_biserial": None,
        "units": units,
        "direction": "Mutant minus wild-type; positive rank-biserial means larger mutant values.",
        "mean_difference_confidence_interval": interval,
    }
    result = {
        "method": "Two-sided Mann–Whitney U, asymptotic tie and continuity correction",
        "analysis_unit": "patient",
        "statistic": None,
        "p_value": None,
        "effect_size": effect,
    }
    if not left or not right:
        result.update(
            inference_status="insufficient_data", reason="Both mutation groups require measured patients."
        )
        interval["reason"] = "Both groups require at least two measured patients for mean uncertainty."
        return result
    test = mannwhitneyu(left, right, alternative="two-sided", method="asymptotic", use_continuity=True)
    averages = [mean(left), mean(right)]
    effect.update(
        mean_difference=finite(averages[0] - averages[1]),
        rank_biserial=2 * float(test.statistic) / (len(left) * len(right)) - 1,
    )
    effect["mean_difference_status"] = (
        "estimated" if effect["mean_difference"] is not None else "numerical_range_exceeded"
    )
    if effect["mean_difference"] is None:
        effect["mean_difference_reason"] = "Difference exceeds the supported finite numeric range."
    result["statistic"] = float(test.statistic)
    if len(set(left + right)) == 1:
        result.update(inference_status="insufficient_variation", reason="All patient measurements are tied.")
    elif finite(test.pvalue) is None:
        result.update(
            inference_status="numerical_range_exceeded", reason="Rank-test probability is not finite."
        )
    else:
        result.update(inference_status="estimated", p_value=float(test.pvalue))
    if min(len(left), len(right)) < 2:
        interval["reason"] = "Both groups require at least two measured patients for mean uncertainty."
    else:
        try:
            variances = [
                math.fsum((value - average) ** 2 for value in rows) / (len(rows) - 1) / len(rows)
                for rows, average in zip([left, right], averages, strict=True)
            ]
            variance = math.fsum(variances)
            if variance == 0:
                interval["reason"] = (
                    "No variance for mean uncertainty estimation."
                    if all(len(set(rows)) == 1 for rows in [left, right])
                    else "Numerical range exceeds supported mean uncertainty estimation."
                )
            else:
                df = variance**2 / math.fsum(
                    value**2 / (len(rows) - 1) for value, rows in zip(variances, [left, right], strict=True)
                )
                width = float(t.ppf((1 + CONFIDENCE_LEVEL) / 2, df)) * math.sqrt(variance)
                lower, upper = (
                    finite(effect["mean_difference"] - width),
                    finite(effect["mean_difference"] + width),
                )
                if lower is None or upper is None or not math.isfinite(df):
                    raise OverflowError
                interval.update(lower=lower, upper=upper, degrees_of_freedom=df, status="estimated")
        except (OverflowError, ZeroDivisionError, TypeError):
            interval["reason"] = "Numerical range exceeds supported mean uncertainty estimation."
    return result


def adjust_bh(values):
    if any(value is not None and (finite(value) is None or not 0 <= value <= 1) for value in values):
        raise ResearchError(
            "invalid_study", "Multiple-test correction requires finite probabilities or unavailable tests."
        )
    ranked = sorted((value, index) for index, value in enumerate(values) if value is not None)
    adjusted, current = [None] * len(values), 1.0
    for rank in range(len(ranked) - 1, -1, -1):
        value, index = ranked[rank]
        current = min(current, value * len(values) / (rank + 1))
        adjusted[index] = current
    return adjusted
