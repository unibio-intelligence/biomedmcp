"""Qualified Complex Portal search-summary membership and bounded continuation.

Free-text discovery hits are not membership assertions. Only exact protein
participant and taxon matches enter the selected projection. Search does not
provide an experimental binding measurement or a pinned data release.
"""

import hashlib
import json
import re

from ..errors import ResearchError
from ..pagination import page_payload
from .http import segment
from .interpro import ACCESSION
from .shapes import invalid_shape

BASE = "https://www.ebi.ac.uk/intact/complex-ws"
MAX_SCAN = 1000
COMPLEX_ID = r"CPX-[1-9]\d*"


def _object(value):
    if (
        not isinstance(value, dict)
        or value.get("error")
        or value.get("errors")
        or value.get("success") is False
    ):
        invalid_shape()
    return value


def _text(value, maximum=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        invalid_shape()
    return value


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        invalid_shape()
    return value


def _hash(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError):
        invalid_shape()
    return hashlib.sha256(raw).hexdigest()


def accession(value):
    if not isinstance(value, str) or not re.fullmatch(ACCESSION, value):
        raise ResearchError(
            "invalid_identifier",
            "Complex membership requires a canonical UniProt accession; isoform membership is not inferred.",
        )
    return value


def parameters(value):
    if not isinstance(value, dict) or set(value) - {"limit", "cursor"}:
        raise ResearchError("invalid_parameters", "Complex membership uses limit and a returned cursor.")
    limit, cursor = value.get("limit", 25), value.get("cursor")
    if (
        type(limit) is not int
        or not 1 <= limit <= 25
        or cursor is not None
        and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 2048)
    ):
        raise ResearchError(
            "invalid_parameters", "Use a 1–25 complex page limit and a bounded service cursor."
        )
    return limit, cursor


def protein_identity(payload, expected, species):
    _object(payload)
    rows = [payload] if "primaryAccession" in payload else payload.get("results")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ResearchError("unresolved_identity", "Complex membership requires one exact UniProt identity.")
    row = _object(rows[0])
    sequence = _object(row.get("sequence"))
    text = _text(sequence.get("value"), 1000000)
    length = _integer(sequence.get("length"), 1)
    taxon = _integer(_object(row.get("organism")).get("taxonId"), 1)
    if row.get("primaryAccession") != expected or taxon != species:
        raise ResearchError(
            "identity_mismatch", "UniProt accession/species does not match the requested complex membership."
        )
    if len(text) != length:
        invalid_shape()
    return {
        "namespace": "uniprot",
        "accession": expected,
        "species": species,
        "length": length,
        "sequence_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _taxon(value):
    if value is None:
        return None
    text = _text(value, 512)
    match = re.fullmatch(r".+;\s*(-?\d+)", text)
    if match is None:
        invalid_shape()
    return int(match[1])


def summary(row, identity, index):
    _object(row)
    complex_id = _text(row.get("complexAC"), 64)
    if not re.fullmatch(COMPLEX_ID, complex_id) or type(row.get("predictedComplex")) is not bool:
        invalid_shape()
    name = _text(row.get("complexName"))
    taxon = _taxon(row.get("organismName"))
    if taxon is not None and taxon < 1:
        invalid_shape()
    description = row.get("description")
    if description is not None and (not isinstance(description, str) or len(description) > 100000):
        invalid_shape()
    interactors = row.get("interactors")
    if not isinstance(interactors, list) or not 1 <= len(interactors) <= 5000:
        invalid_shape()
    matching, unknown, wrong_participant = [], False, False
    isoforms = False
    for position, item in enumerate(interactors):
        _object(item)
        identifier = _text(item.get("identifier"), 256)
        kind = _text(item.get("interactorType"), 256)
        participant_taxon = _taxon(item.get("organismName"))
        if kind == "protein" and participant_taxon is not None and participant_taxon < 1:
            invalid_shape()
        stoichiometry = item.get("stochiometry")
        if stoichiometry is not None:
            _text(stoichiometry, 512)
        if kind != "protein":
            continue
        if identifier.startswith(identity["accession"] + "-"):
            isoforms = True
        if identifier != identity["accession"]:
            continue
        if participant_taxon is None or taxon is None:
            unknown = True
        elif taxon == identity["species"] and participant_taxon == identity["species"]:
            matching.append(
                {
                    "identifier": identifier,
                    "species": participant_taxon,
                    "stoichiometry_raw": stoichiometry,
                    "source_locator": f"/elements/{index}/interactors/{position}",
                }
            )
        elif participant_taxon != identity["species"]:
            wrong_participant = True
    reason = (
        "qualified"
        if matching
        else "unknown_species"
        if unknown
        else "wrong_complex_species"
        if taxon is not None and taxon != identity["species"]
        else "wrong_participant_species"
        if wrong_participant
        else "isoform_candidate"
        if isoforms
        else "no_exact_member"
    )
    value = {
        "record_type": "complex_membership",
        "complex_id": complex_id,
        "complex_namespace": "complexportal",
        "name": name,
        "species": taxon,
        "description": description,
        "predicted_by_source": row["predictedComplex"],
        "membership_assertion": "source_search_participant_annotation",
        "experimental_binding": "not_assessed_from_search_summary",
        "matching_participants": matching,
        "source_release": None,
        "source_locator": f"/elements/{index}",
        "source_record_sha256": _hash(row),
        "source_url": "https://www.ebi.ac.uk/complexportal/complex/" + complex_id,
    }
    return value, reason


async def acquire(http, identity, *, limit=25, state=None):
    state = state or {"offset": 0, "seen": [], "total": None, "sequence_sha256": identity["sequence_sha256"]}
    if state["sequence_sha256"] != identity["sequence_sha256"]:
        raise ResearchError(
            "identity_mismatch", "UniProt sequence changed during complex continuation; restart the request."
        )
    offset = state["offset"]
    width = min(limit, MAX_SCAN - offset)
    data = _object(
        await http.get(
            BASE + "/search/" + segment(identity["accession"]), params={"first": offset, "number": width}
        )
    )
    rows = data.get("elements")
    count = _integer(data.get("size"))
    total = _integer(data.get("totalNumberOfResults"))
    if (
        not isinstance(rows, list)
        or count != len(rows)
        or count > width
        or total < offset + count
        or count == 0
        and total > offset
    ):
        invalid_shape()
    if state["total"] is not None and total != state["total"]:
        raise ResearchError(
            "source_version_changed",
            "Complex Portal search total changed; restart this time-dependent query.",
            retryable=True,
        )
    seen, records, uncertain = set(state["seen"]), [], []
    filtering = dict.fromkeys(
        [
            "duplicates",
            "no_exact_member",
            "wrong_complex_species",
            "wrong_participant_species",
            "unknown_species",
            "isoform_candidate",
        ],
        0,
    )
    for index, row in enumerate(rows):
        record, reason = summary(row, identity, index)
        if record["complex_id"] in seen:
            filtering["duplicates"] += 1
            continue
        seen.add(record["complex_id"])
        if reason == "qualified":
            records.append(record)
        else:
            filtering[reason] += 1
            if reason in {"unknown_species", "isoform_candidate"}:
                uncertain.append(
                    {
                        "complex_id": record["complex_id"],
                        "reason": reason,
                        "source_locator": record["source_locator"],
                        "source_record_sha256": record["source_record_sha256"],
                    }
                )
    following = offset + count if offset + count < total else None
    payload = page_payload(
        records,
        raw_count=count,
        filtered_count=count - len(records),
        filtering=filtering,
        next_offset=following,
        exhausted=following is None,
        total=total,
        exhaustion_basis="total",
    )
    payload.update(
        {
            "protein_identity": identity,
            "unqualified_candidates": uncertain,
            "source_release": None,
            "coverage": {
                "source_offset": offset,
                "source_window_count": count,
                "source_query_total": total,
                "qualified_memberships_in_window": len(records),
                "filtering": filtering,
                "time_dependent": True,
                "negative_evidence_scope": "Exact participant/species matches in this acquired discovery window; search hits and total are not membership counts or experimental evidence.",
            },
            "_complexportal_state": {
                "offset": offset + count,
                "seen": sorted(seen),
                "total": total,
                "sequence_sha256": identity["sequence_sha256"],
            },
            "warnings": [
                "Search uses free-text discovery; description mentions do not establish membership. Curated/predicted flags do not establish experimental binding measurements."
            ],
        }
    )
    if following is not None or offset or uncertain or filtering["duplicates"]:
        payload["section_outcomes"] = {"complexportal": {"outcome": "partial"}}
    return payload


class Continuation:
    def __init__(self, runtime):
        self.runtime = runtime

    @staticmethod
    def binding(request, limit):
        from . import REVISION

        return {
            "operation": "get:complexes",
            "id": request.id,
            "species": request.species,
            "limit": limit,
            "freshness": request.freshness,
            "implementation": REVISION,
        }

    async def resume(self, request, *, scope):
        from ..runtime import digest

        limit, cursor = parameters(request.section_parameters.get("complexes", {}))
        if cursor is None:
            return {"limit": limit}
        offset = self.runtime.cursors.decode(cursor, query=self.binding(request, limit), scope=scope)
        state = await self.runtime.cache.get("complexportal-page:" + digest(cursor))
        if state is None:
            raise ResearchError(
                "expired_cursor", "Complex continuation expired; restart the same protein request."
            )
        if (
            not isinstance(state, dict)
            or set(state) != {"offset", "seen", "total", "sequence_sha256"}
            or type(offset) is not int
            or not 0 < offset < MAX_SCAN
            or type(state.get("offset")) is not int
            or state["offset"] != offset
            or type(state.get("total")) is not int
            or state["total"] <= offset
            or not isinstance(state.get("seen"), list)
            or not 1 <= len(state["seen"]) <= offset
            or any(not isinstance(i, str) or not re.fullmatch(COMPLEX_ID, i) for i in state["seen"])
            or len(set(state["seen"])) != len(state["seen"])
            or not isinstance(state.get("sequence_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", state["sequence_sha256"])
        ):
            raise ResearchError(
                "cache_invalid_data", "Stored complex continuation is invalid; restart the request."
            )
        return {"limit": limit, "state": state}

    async def issue(self, payload, request, *, scope):
        from ..runtime import digest

        if payload["_provider_page"]["exhausted"]:
            return []
        state = payload["_complexportal_state"]
        if state["offset"] >= MAX_SCAN:
            payload["coverage"]["continuation_status"] = "scan_limit"
            payload["warnings"].append(
                "Complex search reached 1000 acquired candidates; remaining evidence is unassessed."
            )
            return []
        limit, _ = parameters(request.section_parameters.get("complexes", {}))
        cursor = self.runtime.cursors.encode(
            query=self.binding(request, limit), scope=scope, offset=state["offset"]
        )
        try:
            stored = await self.runtime.cache.put("complexportal-page:" + digest(cursor), state, 3600)
        except ResearchError:
            stored = False
        if not stored:
            payload["coverage"]["continuation_status"] = "storage_unavailable"
            payload["warnings"].append(
                "Complex continuation storage is unavailable; acquired evidence is retained and remaining evidence is unassessed."
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
                    "freshness": request.freshness,
                    "sections": ["complexes"],
                    "sources": ["complexportal", "uniprot"],
                    "section_parameters": {"complexes": {"limit": limit, "cursor": cursor}},
                },
            }
        ]
