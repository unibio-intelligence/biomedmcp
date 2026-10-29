"""Minimum projected UniProt JSON contracts, based on the official domain model.

Annotations may be absent in projections or unannotated records. Present fields
must have their documented shapes; accession and requested sequence are required.
"""

import math
import re

from biomedmcp.errors import ResearchError
from biomedmcp.native.shapes import collection, invalid_shape

ACCESSION = re.compile(r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})")


def text(value):
    if not isinstance(value, str) or not value.strip():
        invalid_shape()
    return value


def object_(value):
    if not isinstance(value, dict) or not value or any(k in value for k in ("error", "errors", "messages")):
        invalid_shape()
    return value


def positive_integer(value):
    if type(value) is not int or value < 1:
        invalid_shape()
    return value


def accession(value):
    if not isinstance(value, str) or not ACCESSION.fullmatch(value):
        invalid_shape()
    return value


def valued(value):
    text(object_(value).get("value"))


def optional_list(record, key, validate):
    if key in record:
        for item in collection(record, (key,)):
            validate(item)


def cross_reference(value):
    object_(value)
    text(value.get("database"))
    text(value.get("id"))
    for prop in collection(value, ("properties",)) if "properties" in value else []:
        text(prop.get("key"))
        text(prop.get("value"))


def comment(value):
    object_(value)
    text(value.get("commentType"))
    if value["commentType"] not in {"FUNCTION", "SIMILARITY"}:
        return
    texts = collection(value, ("texts",))
    if not texts:
        invalid_shape()
    for item in texts:
        valued(item)
        for evidence in collection(item, ("evidences",)) if "evidences" in item else []:
            object_(evidence)
            code = evidence.get("evidenceCode")
            if not isinstance(code, str) or not re.fullmatch(r"ECO:[0-9]{7}", code):
                invalid_shape()
            if "source" in evidence or "id" in evidence:
                text(evidence.get("source"))
                text(evidence.get("id"))


def feature(value):
    object_(value)
    text(value.get("type"))
    location = object_(value.get("location"))
    points = []
    for key in ("start", "end"):
        point = object_(location.get(key))
        if point.get("modifier") == "UNKNOWN" and point.get("value") is None:
            # The REST serializer emits an explicit null for an unknown endpoint.
            # Preserve uncertainty; it is not zero or a sequence-terminal bound.
            continue
        if "value" in point:
            points.append(positive_integer(point["value"]))
        elif point.get("modifier") != "UNKNOWN":
            invalid_shape()
    if len(points) == 2 and points[0] > points[1]:
        invalid_shape()


def gene(value):
    object_(value)
    if not any(k in value for k in ("geneName", "synonyms", "orderedLocusNames", "orfNames")):
        invalid_shape()
    if "geneName" in value:
        valued(value["geneName"])
    for key in ("synonyms", "orderedLocusNames", "orfNames"):
        optional_list(value, key, valued)


def protein_name(value):
    object_(value)
    valued(value.get("fullName"))
    for key in ("shortNames", "ecNumbers"):
        optional_list(value, key, valued)


def protein_description(value):
    object_(value)
    if not any(
        k in value
        for k in (
            "recommendedName",
            "alternativeNames",
            "submissionNames",
            "includes",
            "contains",
            "allergenName",
            "biotechName",
            "cdAntigenNames",
            "innNames",
        )
    ):
        invalid_shape()
    if "recommendedName" in value:
        protein_name(value["recommendedName"])
    for key in ("alternativeNames", "submissionNames"):
        optional_list(value, key, protein_name)
    for key in ("includes", "contains"):
        optional_list(value, key, protein_description)
    for key in ("allergenName", "biotechName"):
        if key in value:
            valued(value[key])
    for key in ("cdAntigenNames", "innNames"):
        optional_list(value, key, valued)


def sequence(value, *, required=False):
    object_(value)
    if not any(k in value for k in ("value", "length", "molWeight", "crc64", "md5")):
        invalid_shape()
    if "value" in value:
        raw = text(value["value"])
        if not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWYBXZJUO]+", raw):
            invalid_shape()
    elif required:
        invalid_shape()
    if "length" in value:
        length = positive_integer(value["length"])
        if "value" in value and length != len(value["value"]):
            invalid_shape()
    if "molWeight" in value:
        mass = value["molWeight"]
        if type(mass) not in (int, float) or not math.isfinite(mass) or mass <= 0:
            invalid_shape()
    for key, pattern in (("crc64", r"[0-9A-Fa-f]{16}"), ("md5", r"[0-9A-Fa-f]{32}")):
        if key in value and (not isinstance(value[key], str) or not re.fullmatch(pattern, value[key])):
            invalid_shape()


def protein(value, *, expected=None, require_sequence=False):
    object_(value)
    primary = accession(value.get("primaryAccession"))
    if "secondaryAccessions" in value:
        if not isinstance(value["secondaryAccessions"], list):
            invalid_shape()
        for other in value["secondaryAccessions"]:
            accession(other)
    if expected and expected not in [primary, *value.get("secondaryAccessions", [])]:
        raise ResearchError("identity_mismatch", "UniProt returned a different protein identity.")
    if "inactiveReason" in value or value.get("entryType") == "Inactive":
        raise ResearchError(
            "source_not_found", "UniProt entry is inactive; resolve a current protein identity."
        )
    if "entryType" in value and value["entryType"] not in {
        "UniProtKB reviewed (Swiss-Prot)",
        "UniProtKB unreviewed (TrEMBL)",
    }:
        invalid_shape()
    if "uniProtkbId" in value:
        text(value["uniProtkbId"])
    if "organism" in value:
        organism = object_(value["organism"])
        if not any(k in organism for k in ("taxonId", "scientificName", "commonName", "synonyms", "lineage")):
            invalid_shape()
        if "taxonId" in organism:
            positive_integer(organism["taxonId"])
        if "scientificName" in organism:
            text(organism["scientificName"])
    if "proteinDescription" in value:
        protein_description(value["proteinDescription"])
    if "sequence" in value:
        sequence(value["sequence"], required=require_sequence)
    elif require_sequence:
        invalid_shape()
    optional_list(value, "genes", gene)
    optional_list(value, "features", feature)
    optional_list(value, "uniProtKBCrossReferences", cross_reference)
    optional_list(value, "comments", comment)
    for key in ("references", "keywords", "geneLocations", "organismHosts"):
        optional_list(value, key, object_)
    if "annotationScore" in value:
        score = value["annotationScore"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 5:
            invalid_shape()
    return value


def proteins(value, *, require_sequence=False):
    object_(value)
    rows = collection(value, ("results",))
    for row in rows:
        protein(row, require_sequence=require_sequence)
    return rows
