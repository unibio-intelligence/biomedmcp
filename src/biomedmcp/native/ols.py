"""OLS v1 HPO contracts: search candidates and one exact ontology term.

Ontology definitions, obsolete/replacement assertions and synonym scopes remain
source data. Only the documented HPO class projection is accepted for search.
"""

import re

from ..pagination import page_payload
from .shapes import collection, invalid_shape

BASE = "https://www.ebi.ac.uk/ols4/api"


def _object(value):
    if (
        not isinstance(value, dict)
        or value.get("error")
        or value.get("errors")
        or value.get("success") is False
    ):
        invalid_shape()
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        invalid_shape()
    return value


def _count(value):
    if type(value) is not int or value < 0:
        invalid_shape()
    return value


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        invalid_shape()


def _xrefs(value):
    if not isinstance(value, list):
        invalid_shape()
    for row in value:
        _object(row)
        for key in ("database", "id", "description", "url"):
            if row.get(key) is not None and not isinstance(row[key], str):
                invalid_shape()


def term(row, *, requested_id=None, search=False):
    """Require consistent identity before normalizing an executable ID."""
    _object(row)
    identity = _text(row.get("obo_id"))
    if not re.fullmatch(r"HP:\d{7}", identity) or (requested_id is not None and identity != requested_id):
        invalid_shape()
    short_form = identity.replace(":", "_")
    if row.get("short_form") != short_form or row.get("iri") not in {
        "http://purl.obolibrary.org/obo/" + short_form,
        "https://purl.obolibrary.org/obo/" + short_form,
    }:
        invalid_shape()
    if row.get("ontology_name") != "hp" or row.get("ontology_prefix") != "HP":
        invalid_shape()
    _text(row.get("label"))
    if search and row.get("type") != "class":
        invalid_shape()
    for key in ("is_obsolete", "is_defining_ontology", "has_children", "is_root", "is_preferred_root"):
        if key in row and type(row[key]) is not bool:
            invalid_shape()
    if search and (row.get("is_obsolete") is True or row.get("is_defining_ontology") is False):
        invalid_shape()
    for key in (
        "description",
        "synonyms",
        "exact_synonyms",
        "related_synonyms",
        "narrow_synonyms",
        "broad_synonyms",
        "in_subset",
    ):
        if row.get(key) is not None:
            _strings(row[key])
    for key in ("term_replaced_by", "ontology_iri", "lang"):
        if row.get(key) is not None:
            _text(row[key])
    if row.get("annotation") is not None:
        _object(row["annotation"])
    if row.get("obo_xref") is not None:
        _xrefs(row["obo_xref"])
    if row.get("obo_definition_citation") is not None:
        citations = row["obo_definition_citation"]
        if not isinstance(citations, list):
            invalid_shape()
        for citation in citations:
            _object(citation)
            _text(citation.get("definition"))
            if citation.get("oboXrefs") is not None:
                _xrefs(citation["oboXrefs"])
    if row.get("obo_synonym") is not None:
        synonyms = row["obo_synonym"]
        if not isinstance(synonyms, list):
            invalid_shape()
        for synonym in synonyms:
            _object(synonym)
            _text(synonym.get("name"))
            for key in ("scope", "type"):
                if synonym.get(key) is not None:
                    _text(synonym[key])
            if synonym.get("xrefs") is not None:
                _xrefs(synonym["xrefs"])
    result = {**row, "id": identity}
    if row.get("id") is not None and row["id"] != identity:
        result["source_record_id"] = _text(row["id"])
    return result


async def search(http, query, limit, offset):
    payload = _object(
        await http.get(
            BASE + "/search",
            params={
                "q": query,
                "ontology": "hp",
                "rows": limit,
                "start": offset,
                "type": "class",
                "local": "true",
            },
        )
    )
    rows = collection(payload, ("response", "docs"))
    response = _object(payload["response"])
    total, start = _count(response.get("numFound")), _count(response.get("start"))
    if (
        start != offset
        or len(rows) > limit
        or (rows and offset + len(rows) > total)
        or (not rows and offset < total)
    ):
        invalid_shape()
    if "responseHeader" in payload:
        header = _object(payload["responseHeader"])
        if type(header.get("status")) is not int or header["status"] != 0:
            invalid_shape()
    normalized = [term(row, search=True) for row in rows]
    if len({row["id"] for row in normalized}) != len(normalized):
        invalid_shape()
    exhausted = offset + len(rows) >= total
    return page_payload(
        normalized,
        raw_count=len(rows),
        total=total,
        exhausted=exhausted,
        next_offset=None if exhausted else offset + len(rows),
        exhaustion_basis="total",
    )


async def record(http, identity):
    payload = _object(await http.get(BASE + "/ontologies/hp/terms", params={"obo_id": identity}))
    rows = collection(payload, ("_embedded", "terms"))
    page = _object(payload.get("page"))
    counts = {key: _count(page.get(key)) for key in ("size", "totalElements", "totalPages", "number")}
    # The exact-ID controller returns a single-item PageImpl or HTTP 404.
    # Empty/multiple/incomplete 200 responses are not exact identity results.
    if len(rows) != 1 or counts != {"size": 1, "totalElements": 1, "totalPages": 1, "number": 0}:
        invalid_shape()
    return term(rows[0], requested_id=identity)
