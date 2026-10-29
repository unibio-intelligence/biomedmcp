"""Fixed FDA enforcement facts; submitted narratives and documents excluded."""

import re

from biomedmcp.native.shapes import collection, invalid_shape


def recall_projection(payload):
    records = []
    for raw in collection(payload, ("results",)):
        number = raw.get("recall_number")
        if not isinstance(number, str) or not re.fullmatch(r"[A-Z]-\d+-\d+", number):
            invalid_shape()
        if raw.get("classification") not in {"Class I", "Class II", "Class III", "Not Yet Classified"}:
            invalid_shape()
        row = {"recall_number": number, "classification": raw["classification"]}
        for key in ("event_id", "status", "product_type", "recalling_firm", "voluntary_mandated"):
            if key in raw:
                if not isinstance(raw[key], str) or not raw[key]:
                    invalid_shape()
                row[key] = raw[key]
        for key in (
            "report_date",
            "recall_initiation_date",
            "center_classification_date",
            "termination_date",
        ):
            if key in raw:
                if not isinstance(raw[key], str) or not re.fullmatch(r"\d{8}", raw[key]):
                    invalid_shape()
                row[key] = raw[key]
        records.append(row)
    result = {"results": records}
    meta = payload.get("meta")
    if meta is not None:
        if not isinstance(meta, dict):
            invalid_shape()
        result["meta"] = {}
        if "last_updated" in meta:
            if not isinstance(meta["last_updated"], str):
                invalid_shape()
            result["meta"]["last_updated"] = meta["last_updated"]
        if "results" in meta:
            counts = meta["results"]
            if not isinstance(counts, dict) or any(
                type(counts.get(k)) is not int or counts[k] < 0 for k in ("skip", "limit", "total")
            ):
                invalid_shape()
            result["meta"]["results"] = {k: counts[k] for k in ("skip", "limit", "total")}
    return result
