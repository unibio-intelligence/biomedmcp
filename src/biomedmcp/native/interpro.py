"""Selected InterPro entry/protein contracts and scoped, bounded continuation.

Entry matches are predictions, not experimental residue/function measurements.
The integration qualifies the public projection observed on 2026-10-11; the
retired public serializer/OpenAPI URLs are not treated as available contracts.
"""

import math
import re
from urllib.parse import parse_qs, urlsplit

from ..errors import ResearchError
from ..pagination import page_payload
from .shapes import invalid_shape

BASE = "https://www.ebi.ac.uk/interpro/api"
ACCESSION = r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})"
TYPES = {
    "domain",
    "family",
    "repeat",
    "homologous_superfamily",
    "active_site",
    "binding_site",
    "conserved_site",
    "ptm",
}


def parameters(params, *, public=True):
    key = "cursor" if public else "after"
    if not isinstance(params, dict) or set(params) - {"limit", key}:
        raise ResearchError("invalid_parameters", "InterPro uses a page limit and a returned cursor.")
    limit, cursor = params.get("limit", 25), params.get(key)
    if (
        type(limit) is not int
        or not 1 <= limit <= 25
        or cursor is not None
        and (not isinstance(cursor, str) or not 1 <= len(cursor) <= (2048 if public else 8192))
    ):
        raise ResearchError("invalid_parameters", "InterPro requires a 1–25 page limit and a bounded cursor.")
    return limit, cursor


def accession(value):
    if not isinstance(value, str) or not re.fullmatch(ACCESSION, value):
        raise ResearchError(
            "invalid_identifier",
            "InterPro requires a canonical UniProt accession; isoform mapping is not inferred.",
        )
    return value


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


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        invalid_shape()
    return value


def protein_identity(payload, expected, species):
    """Anchor 204 absence to an independently verified, source-owned identity."""
    _object(payload)
    rows = [payload] if "primaryAccession" in payload else payload.get("results")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ResearchError(
            "unresolved_identity", "InterPro requires one exact UniProt protein before interpreting matches."
        )
    row = _object(rows[0])
    sequence = _object(row.get("sequence"))
    value = _text(sequence.get("value"))
    taxon = _integer(_object(row.get("organism")).get("taxonId"), 1)
    if row.get("primaryAccession") != expected or taxon != species:
        raise ResearchError(
            "identity_mismatch", "UniProt accession/species does not match the requested InterPro identity."
        )
    length = _integer(sequence.get("length"), 1)
    if len(value) != length:
        invalid_shape()
    return {"accession": expected, "length": length, "species": species}


def _link(value, identity, limit):
    if value is None:
        return None
    _text(value)
    if len(value) > 8192:
        invalid_shape()
    url = urlsplit(value)
    expected = f"/interpro/api/entry/interpro/protein/uniprot/{identity}/"
    if url.scheme != "https" or url.netloc != "www.ebi.ac.uk" or url.path != expected or url.fragment:
        invalid_shape()
    query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
    if (
        set(query) != {"page_size", "cursor"}
        or query["page_size"] != [str(limit)]
        or len(query["cursor"]) != 1
    ):
        invalid_shape()
    token = query["cursor"][0]
    if not 1 <= len(token) <= 8192 or any(ord(c) < 32 for c in token):
        invalid_shape()
    return token


def entry(row, identity):
    """Check every match used for identity or residue interpretation."""
    _object(row)
    meta = _object(row.get("metadata"))
    if (
        not re.fullmatch(r"IPR\d{6}", _text(meta.get("accession")))
        or meta.get("source_database") != "interpro"
    ):
        invalid_shape()
    _text(meta.get("name"))
    if meta.get("type") not in TYPES:
        invalid_shape()
    members = meta.get("member_databases")
    if members is not None:
        _object(members)
        for database, annotations in members.items():
            _text(database)
            _object(annotations)
            for key, text in annotations.items():
                _text(key)
                _text(text)
    terms = meta.get("go_terms")
    if terms is not None:
        if not isinstance(terms, list):
            invalid_shape()
        for term in terms:
            _object(term)
            if not re.fullmatch(r"GO:\d{7}", _text(term.get("identifier"))):
                invalid_shape()
            _text(term.get("name"))
            category = _object(term.get("category"))
            if category.get("code") not in {"F", "C", "P"}:
                invalid_shape()
            _text(category.get("name"))
    proteins = row.get("proteins")
    if not isinstance(proteins, list) or len(proteins) != 1:
        invalid_shape()
    protein = _object(proteins[0])
    if (
        _text(protein.get("accession")).upper() != identity["accession"]
        or _integer(protein.get("protein_length"), 1) != identity["length"]
        or protein.get("organism") != str(identity["species"])
        or protein.get("source_database") not in {"reviewed", "unreviewed"}
    ):
        invalid_shape()
    if "in_alphafold" in protein and type(protein["in_alphafold"]) is not bool:
        invalid_shape()
    locations = protein.get("entry_protein_locations")
    if not isinstance(locations, list) or not locations:
        invalid_shape()
    for location in locations:
        _object(location)
        if "representative" in location and type(location["representative"]) is not bool:
            invalid_shape()
        if location.get("model") is not None:
            _text(location["model"])
        if location.get("score") is not None and (
            type(location["score"]) not in {int, float} or not math.isfinite(location["score"])
        ):
            invalid_shape()
        fragments = location.get("fragments")
        if not isinstance(fragments, list) or not fragments:
            invalid_shape()
        previous = 0
        for fragment in fragments:
            _object(fragment)
            start, end = _integer(fragment.get("start"), 1), _integer(fragment.get("end"), 1)
            if not previous < start <= end <= identity["length"]:
                invalid_shape()
            previous = end
            if fragment.get("dc-status") not in {
                "CONTINUOUS",
                "N_TERMINAL_DISC",
                "C_TERMINAL_DISC",
                "NC_TERMINAL_DISC",
            }:
                invalid_shape()
    # InterPro's integrated entry and match projection is distinct from the
    # annotations of member databases and imported GO/AlphaFold content.
    return {
        "metadata": {key: meta[key] for key in ("accession", "name", "type", "source_database")},
        "proteins": [
            {
                **{
                    key: protein[key]
                    for key in ("accession", "protein_length", "organism", "source_database")
                },
                "entry_protein_locations": [
                    {
                        "fragments": [
                            {key: fragment[key] for key in ("start", "end", "dc-status")}
                            for fragment in location["fragments"]
                        ],
                        **(
                            {"representative": location["representative"]}
                            if "representative" in location
                            else {}
                        ),
                    }
                    for location in locations
                ],
            }
        ],
    }


async def acquire(http, identity, *, limit=25, after=None, scanned=0, total=None, release=None, seen=()):
    """One provider window; next links are parsed but never followed verbatim."""
    accession(identity["accession"])
    params = {"page_size": limit, **({"cursor": after} if after else {})}
    response = await http.get(
        f"{BASE}/entry/interpro/protein/uniprot/{identity['accession']}/", params=params, response_meta=True
    )
    _object(response)
    headers = _object(response.get("headers"))
    current_release = headers.get("interpro-version")
    if current_release is not None and not re.fullmatch(r"\d+\.\d+", _text(current_release)):
        invalid_shape()
    if scanned and current_release != release:
        raise ResearchError(
            "source_contract_changed",
            "InterPro release changed during continuation; restart without mixing snapshots.",
        )
    status, body = response.get("status"), response.get("body")
    if status == 204:
        if body is not None or after is not None or scanned or total not in {None, 0}:
            invalid_shape()
        rows, count, following = [], 0, None
    elif status == 200:
        _object(body)
        count = _integer(body.get("count"))
        rows = body.get("results")
        if not isinstance(rows, list) or len(rows) > limit or count < scanned + len(rows):
            invalid_shape()
        if not {"next", "previous"} <= body.keys():
            invalid_shape()
        try:
            following = _link(body["next"], identity["accession"], limit)
            _link(body["previous"], identity["accession"], limit)
        except (ValueError, TypeError):
            invalid_shape()
        if (
            (following is None) != (scanned + len(rows) == count)
            or following is not None
            and (not rows or following == after)
        ):
            invalid_shape()
        ids = [_text(_object(_object(row).get("metadata")).get("accession")) for row in rows]
        if len(set(ids)) != len(ids) or set(ids) & set(seen):
            invalid_shape()
        rows = [entry(row, identity) for row in rows]
    else:
        invalid_shape()
    if total is not None and count != total:
        raise ResearchError(
            "source_contract_changed",
            "InterPro result count changed during continuation; restart the request.",
        )
    value = page_payload(
        rows,
        raw_count=len(rows),
        total=count,
        exhausted=following is None,
        continuation=following,
        next_offset=None if following is None else scanned + len(rows),
    )
    value.update(
        {
            "protein_identity": identity,
            "source_release": current_release,
            "url": f"{BASE}/entry/interpro/protein/uniprot/{identity['accession']}/",
            "coverage": {
                "total_entries": count,
                "scanned_before": scanned,
                "acquired_entries": len(rows),
                "complete": following is None,
                "interpretation": "InterPro entry matches for this protein; families, sites and domains remain distinct. Absence is confined to this source query, not biological function.",
            },
            "coordinate_system": "1-based inclusive UniProt sequence fragments; discontinuous gaps do not overlap a residue. Accession, species and length agreement does not establish identical sequence releases.",
        }
    )
    if following is not None:
        value["section_outcomes"] = {"interpro": {"outcome": "partial", "sources": ["interpro"]}}
    return value


def overlaps(payload, position):
    matches = []
    for row in payload["records"]:
        for location in row["proteins"][0]["entry_protein_locations"]:
            for fragment in location["fragments"]:
                if fragment["start"] <= position <= fragment["end"]:
                    matches.append(
                        {
                            "accession": row["metadata"]["accession"],
                            "name": row["metadata"]["name"],
                            "entry_type": row["metadata"]["type"],
                            "start": fragment["start"],
                            "end": fragment["end"],
                            "fragment_status": fragment["dc-status"],
                            "representative": location.get("representative"),
                        }
                    )
    return matches


class Continuation:
    """Account-scoped provider tokens; clients receive signed service cursors."""

    def __init__(self, runtime):
        self.runtime = runtime

    @staticmethod
    def binding(request, limit):
        from . import REVISION

        return {
            "operation": "get:domains",
            "id": request.id,
            "species": request.species,
            "limit": limit,
            "implementation": REVISION,
        }

    async def resume(self, request, *, scope):
        from ..runtime import digest

        limit, cursor = parameters(request.section_parameters.get("domains", {}))
        if cursor is None:
            return {"limit": limit}, {"scanned": 0, "seen": []}
        scanned = self.runtime.cursors.decode(cursor, query=self.binding(request, limit), scope=scope)
        state = await self.runtime.cache.get("interpro-page:" + digest(cursor))
        if state is None:
            raise ResearchError(
                "expired_cursor", "InterPro continuation expired; restart the same protein request."
            )
        if (
            not isinstance(state, dict)
            or set(state) != {"after", "scanned", "seen", "total", "release", "length"}
            or type(state.get("scanned")) is not int
            or state.get("scanned") != scanned
            or type(scanned) is not int
            or not 0 < scanned < 1000
            or not isinstance(state.get("after"), str)
            or not 1 <= len(state["after"]) <= 8192
            or type(state.get("total")) is not int
            or state["total"] <= scanned
            or type(state.get("length")) is not int
            or state["length"] < 1
            or not isinstance(state.get("seen"), list)
            or len(state["seen"]) != scanned
            or any(not isinstance(i, str) or not re.fullmatch(r"IPR\d{6}", i) for i in state["seen"])
            or len(set(state["seen"])) != scanned
            or state.get("release") is not None
            and (not isinstance(state["release"], str) or not re.fullmatch(r"\d+\.\d+", state["release"]))
        ):
            raise ResearchError(
                "cache_invalid_data", "Stored InterPro continuation is invalid; restart the request."
            )
        return {"limit": limit, **state}, state

    async def issue(self, payload, request, *, scope, state):
        from ..runtime import digest

        page = payload.get("_provider_page")
        if not page or page["exhausted"]:
            return []
        limit, _ = parameters(request.section_parameters.get("domains", {}))
        scanned = state["scanned"] + page["raw_count"]
        seen = [*state["seen"], *[row["metadata"]["accession"] for row in payload["records"]]]
        payload["section_outcomes"] = {"interpro": {"outcome": "partial", "sources": ["interpro"]}}
        if scanned >= 1000:
            payload["coverage"]["continuation_status"] = "scan_limit"
            payload.setdefault("warnings", []).append(
                "InterPro continuation reached 1000 entries; remaining evidence is unassessed."
            )
            return []
        cursor = self.runtime.cursors.encode(query=self.binding(request, limit), scope=scope, offset=scanned)
        stored = await self.runtime.cache.put(
            "interpro-page:" + digest(cursor),
            {
                "after": page["continuation"],
                "scanned": scanned,
                "seen": seen,
                "total": page["total"],
                "release": payload["source_release"],
                "length": payload["protein_identity"]["length"],
            },
            3600,
        )
        if not stored:
            payload["coverage"]["continuation_status"] = "storage_limit"
            payload.setdefault("warnings", []).append(
                "InterPro continuation storage is full; remaining evidence is unassessed."
            )
            return []
        payload["coverage"]["continuation_status"] = "available"
        return [
            {
                "tool": "get",
                "arguments": {
                    "entity": "protein",
                    "id": request.id,
                    "species": request.species,
                    "sections": ["domains"],
                    "sources": ["interpro", "uniprot"],
                    "section_parameters": {"domains": {"limit": limit, "cursor": cursor}},
                },
            }
        ]
