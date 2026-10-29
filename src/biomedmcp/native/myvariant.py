"""Minimum MyVariant shapes for fields used in identity and evidence extraction.

Contract: docs.myvariant.info variant_query_service / variant_annotation_service,
reviewed 2026-10-09. Optional source annotations remain optional, never fabricated.
"""

from .shapes import collection, invalid_shape


def text(value):
    if not isinstance(value, str) or not value.strip():
        invalid_shape()


def texts(value):
    values = value if isinstance(value, list) else [value]
    for item in values:
        text(item)


def objects(value):
    values = value if isinstance(value, list) else [value]
    if any(
        not isinstance(item, dict) or not item or item.get("error") or item.get("errors") for item in values
    ):
        invalid_shape()
    return values


def record(value):
    if not isinstance(value, dict) or value.get("error") or value.get("errors") or "notfound" in value:
        invalid_shape()
    text(value.get("_id"))
    for key in ("dbnsfp", "dbsnp", "snpeff", "cadd", "dbscsnv", "gnomad_exome", "gnomad_genome", "clinvar"):
        if key in value and (
            not isinstance(value[key], dict)
            or not value[key]
            or value[key].get("error")
            or value[key].get("errors")
        ):
            invalid_shape()
    for key in ("cosmic", "cgi"):
        if key in value:
            objects(value[key])
    db = value.get("dbnsfp", {})
    for key in ("genename", "hgvsp"):
        if key in db:
            texts(db[key])
    snpeff = value.get("snpeff", {})
    if "ann" in snpeff:
        for annotation in objects(snpeff["ann"]):
            for key in ("genename", "hgvs_p", "hgvs_c", "feature_id"):
                if key in annotation:
                    # Noncoding annotations can legitimately have no protein change.
                    if key == "hgvs_p" and annotation[key] is None:
                        continue
                    text(annotation[key])
    dbsnp = value.get("dbsnp", {})
    if "rsid" in dbsnp:
        texts(dbsnp["rsid"])
    for key in ("hg19", "hg38"):
        if key in value:
            for coordinates in objects(value[key]):
                start = coordinates.get("start")
                end = coordinates.get("end", start)
                if type(start) is not int or start < 1 or type(end) is not int or end < start:
                    invalid_shape()
    return value


def query_response(value, *, offset=0):
    hits = collection(value, ("hits",))
    total = value.get("total")
    if type(total) is not int or total < 0 or (hits and total < offset + len(hits)):
        invalid_shape()
    if not hits and offset < total:
        invalid_shape()
    for hit in hits:
        record(hit)
    if len({hit["_id"] for hit in hits}) != len(hits):
        invalid_shape()
    return hits, total


def direct_response(value):
    # Empty lists and POST-only notfound markers are not a qualified GET result.
    hits = value if isinstance(value, list) else [value]
    if not hits:
        invalid_shape()
    for hit in hits:
        record(hit)
    return hits
