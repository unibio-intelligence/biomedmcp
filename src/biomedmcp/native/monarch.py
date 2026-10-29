"""Bounded direct Monarch associations, retaining source predicates and taxa."""

import re

from .shapes import collection, invalid_shape

URL = "https://api.monarchinitiative.org/v3/api/association"
CACHE_PROJECTION = "monarch-direct-associations-v1"
CATEGORIES = {
    "genes": ["biolink:CausalGeneToDiseaseAssociation", "biolink:CorrelatedGeneToDiseaseAssociation"],
    "phenotypes": ["biolink:DiseaseToPhenotypicFeatureAssociation"],
    "models": ["biolink:GenotypeToDiseaseAssociation"],
}


async def associations(http, disease, section):
    phenotype = section == "phenotypes"
    params = {
        "subject" if phenotype else "object": disease,
        "category": CATEGORIES[section],
        "direct": True,
        "limit": 25,
        "offset": 0,
    }
    if section == "models":
        params.update(predicate="biolink:model_of", subject_category="biolink:Genotype")
    payload = await http.get(URL, params=params)
    rows = collection(payload, ("items",))
    total = payload.get("total")
    if (
        type(total) is not int
        or total < len(rows)
        or len(rows) > 25
        or type(payload.get("limit")) is not int
        or payload["limit"] != 25
        or type(payload.get("offset")) is not int
        or payload["offset"] != 0
        or (total > 0 and not rows)
    ):
        invalid_shape()
    for row in rows:
        if (
            not isinstance(row.get("id"), str)
            or not row["id"].strip()
            or row.get("category") not in CATEGORIES[section]
            or not isinstance(row.get("predicate"), str)
            or not row["predicate"].startswith("biolink:")
            or row.get("subject" if phenotype else "object") != disease
            or row.get("subject_category" if phenotype else "object_category") != "biolink:Disease"
        ):
            invalid_shape()
        other = row.get("object" if phenotype else "subject")
        other_category = row.get("object_category" if phenotype else "subject_category")
        if (
            not isinstance(other, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*:[^\s]+", other)
            or other_category
            != {
                "genes": "biolink:Gene",
                "phenotypes": "biolink:PhenotypicFeature",
                "models": "biolink:Genotype",
            }[section]
            or (section == "models" and row["predicate"] != "biolink:model_of")
        ):
            invalid_shape()
    return {
        "records": rows,
        "requested_disease": disease,
        "total": total,
        "limit": 25,
        "offset": 0,
        "complete": len(rows) == total,
        "relation_basis": "provider_direct_association",
        "section_outcomes": {"coverage": {"outcome": "partial"}} if len(rows) < total else {},
        "warnings": [
            (
                "Direct source associations retain their predicates, evidence and taxa; association does not establish causality. "
                "Model records retain the provider's model_of assertion and do not establish human efficacy. "
                "This is a bounded window of at most 25 associations."
            )
        ],
    }
