"""Declarative charts over returned study values; no extra scientific inference."""

from __future__ import annotations

from .errors import ResearchError


def study_chart(payload: dict) -> dict:
    data = payload.get("result", payload)
    if isinstance(data, dict) and "result" in data and "query_type" in data:
        data = data["result"]
    title = (
        f"{data.get('study_id', 'Public study')} · {data.get('gene', data.get('target_gene', 'analysis'))}"
    )
    if data.get("measurement") == "cna" and "counts" in data:
        rows = [{"category": key, "value": value} for key, value in data["counts"].items()]
        unit = "Measured samples"
        metadata = {k: data[k] for k in ["total_samples", "measured_samples", "missing_samples"]}
    elif "deep_deletion" in data:
        rows = [
            {"category": key.replace("_", " "), "value": data[key]}
            for key in ("deep_deletion", "shallow_deletion", "diploid", "gain", "amplification")
        ]
        unit = "Samples"
        metadata = {"total_samples": data["total_samples"]}
    elif "top_variant_classes" in data:
        rows = [{"category": key, "value": value} for key, value in data["top_variant_classes"]]
        unit = "Mutation events"
        metadata = {
            k: data[k]
            for k in ("total_samples", "unique_samples", "mutation_count", "frequency")
            if k in data
        }
    elif data.get("genes") and "mutated_samples" in data["genes"][0]:
        rows = [{"category": r["gene"], "value": r["mutated_samples"]} for r in data["genes"][:25]]
        unit = "Mutated samples"
        metadata = {"total_samples": data["total_samples"]}
    elif data.get("groups") and "survival_1yr" in data["groups"][0]:
        # Fixed reported estimates are points. Do not interpolate them into a
        # Kaplan–Meier curve: upstream's JSON omits the full step coordinates.
        rows = [
            {"group": g["group_name"], "months": months, "survival": g[field]}
            for g in data["groups"]
            for months, field in ((12, "survival_1yr"), (36, "survival_3yr"), (60, "survival_5yr"))
            if g.get(field) is not None
        ]
        return {
            "format": "vega-lite",
            "spec": {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "title": title,
                "data": {"values": rows},
                "mark": {"type": "point", "filled": True},
                "encoding": {
                    "x": {"field": "months", "type": "quantitative", "title": "Months"},
                    "y": {
                        "field": "survival",
                        "type": "quantitative",
                        "scale": {"domain": [0, 1]},
                        "title": "Reported survival probability",
                    },
                    "color": {"field": "group", "type": "nominal"},
                },
            },
            "metadata": {
                "endpoint": data.get("endpoint"),
                "groups": data["groups"],
                "log_rank_p": data.get("log_rank_p"),
            },
            "limitations": ["Reported fixed-time estimates; this is not a full Kaplan–Meier curve."],
        }
    else:
        raise ResearchError(
            "chart_unavailable", "This result has no supported chart shape; use the returned JSON."
        )
    return {
        "format": "vega-lite",
        "spec": {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "data": {"values": rows},
            "mark": "bar",
            "encoding": {
                "x": {"field": "category", "type": "nominal", "title": None},
                "y": {"field": "value", "type": "quantitative", "title": unit, "scale": {"zero": True}},
            },
        },
        "metadata": metadata,
        "limitations": [],
    }
