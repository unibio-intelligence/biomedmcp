"""Selected Reactome controller/model contracts, observed 2026-10-11.

Source: reactome/content-service 8d5b39f; search-core c3c9936; graph-core 62aef35.
The source response remains data. This does not prove causal membership or live health.
"""

import math
import re

from biomedmcp.errors import invalid_parameters
from biomedmcp.native.shapes import collection, invalid_shape

STABLE = r"R-[A-Z]{3}-[1-9][0-9]*"
SPECIES = {
    "9606": ("Homo sapiens", "HSA"),
    "10090": ("Mus musculus", "MMU"),
    "10116": ("Rattus norvegicus", "RNO"),
}
REACTIONS = {
    "Reaction",
    "ReactionLikeEvent",
    "BlackBoxEvent",
    "Polymerisation",
    "Depolymerisation",
    "FailedReaction",
}


def text(value):
    if not isinstance(value, str) or not value.strip():
        invalid_shape()
    return value


def count(value):
    if type(value) is not int or value < 0:
        invalid_shape()
    return value


def obj(value):
    if not isinstance(value, dict) or not value or value.get("error") or value.get("errors"):
        invalid_shape()
    return value


def stable(value):
    if not isinstance(value, str) or not re.fullmatch(STABLE, value):
        invalid_shape()
    return value


def species_scope(value):
    if value in SPECIES:
        return SPECIES[value]
    return next((v for v in SPECIES.values() if value == v[0]), (value, None))


def preflight(operation, params):
    for key in ("pathway_id",):
        if key in params and (not isinstance(params[key], str) or not re.fullmatch(STABLE, params[key])):
            raise invalid_parameters()
    for key in ("gene", "protein_id"):
        if key in params and (
            not isinstance(params[key], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", params[key])
        ):
            raise invalid_parameters()
    if "species" in params:
        species = params["species"]
        if not isinstance(species, str) or not re.fullmatch(
            r"[1-9][0-9]{0,9}|[A-Z][A-Za-z]+(?: [a-z][a-z-]+){1,3}", species
        ):
            raise invalid_parameters()
    for key in ("query", "disease"):
        if key in params and (
            not isinstance(params[key], str) or not params[key].strip() or len(params[key]) > 1000
        ):
            raise invalid_parameters()
    for key in ("offset", "page"):
        if key in params and (type(params[key]) is not int or not 0 <= params[key] <= 2147483647):
            raise invalid_parameters()
    if "limit" in params and (type(params["limit"]) is not int or not 1 <= params["limit"] <= 100):
        raise invalid_parameters()


def event(value, *, expected=None, species=None, pathway=False):
    value = obj(value)
    stid = stable(value.get("stId"))
    text(value.get("displayName"))
    kind = text(value.get("schemaClass"))
    if pathway and kind not in {"Pathway", "TopLevelPathway"}:
        invalid_shape()
    if expected is not None and stid != expected:
        invalid_shape()
    if "dbId" in value and (count(value["dbId"]) == 0):
        invalid_shape()
    for key in ("isInDisease", "isInferred", "hasDiagram"):
        if key in value and value[key] is not None and type(value[key]) is not bool:
            invalid_shape()
    if "speciesName" in value and value["speciesName"] is not None:
        text(value["speciesName"])
    if species is not None:
        name, prefix = species_scope(species)
        if value.get("speciesName") is not None and value["speciesName"] != name:
            invalid_shape()
        if prefix is not None and not stid.startswith(f"R-{prefix}-"):
            invalid_shape()
        if prefix is None and value.get("speciesName") != name:
            # An unknown taxonomy number is not a scientific species name.
            # Require explicit provider species evidence rather than guessing.
            names = [r.get("taxId") for r in value.get("species", []) if isinstance(r, dict)]
            if species not in names:
                invalid_shape()
    return value


def events(value, *, species=None, pathways=False):
    if not isinstance(value, list):
        invalid_shape()
    # DatabaseObject uses Jackson @JsonIdentityInfo(property="dbId"). An
    # event already serialized inside a peer is a numeric reference here.
    # Resolve only definitions in this response, never fetch or invent one.
    definitions, pending, visited = {}, [value], 0
    while pending:
        node = pending.pop()
        visited += 1
        if visited > 100000:
            invalid_shape()
        if isinstance(node, dict):
            if "dbId" in node:
                identity = count(node["dbId"])
                if not identity or (identity in definitions and definitions[identity] != node):
                    invalid_shape()
                definitions[identity] = node
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    rows = []
    for row in value:
        if type(row) is int:
            if row <= 0 or row not in definitions:
                invalid_shape()
            row = definitions[row]
        if not isinstance(row, dict):
            invalid_shape()
        rows.append(row)
    for row in rows:
        event(row, species=species, pathway=pathways)
    ids = [r["stId"] for r in rows]
    if len(ids) != len(set(ids)):
        invalid_shape()
    return rows


def participants(value):
    rows = collection(value, ())
    for row in rows:
        if count(row.get("peDbId")) == 0:
            invalid_shape()
        text(row.get("displayName"))
        text(row.get("schemaClass"))
        for ref in collection(row, ("refEntities",)):
            if count(ref.get("dbId")) == 0:
                invalid_shape()
            for key in ("identifier", "schemaClass", "displayName"):
                text(ref.get(key))
            if ref.get("stId") is not None:
                identifier = text(ref["stId"])
                if identifier.startswith("R-"):
                    stable(identifier)
                elif (
                    not re.fullmatch(r"[a-z][a-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identifier)
                    or identifier.split(":", 1)[1] != ref["identifier"]
                ):
                    invalid_shape()
    return rows


def search(value, *, species, limit, offset):
    groups = collection(value, ("results",))
    total = count(value.get("numberOfMatches"))
    count(value.get("rowCount"))
    number_groups = count(value.get("numberOfGroups"))
    # A forced, unclustered Pathway query has exactly one type group when nonempty.
    if number_groups != len(groups) or len(groups) > 1:
        invalid_shape()
    rows = []
    for group in groups:
        if group.get("typeName") != "Results" or count(group.get("entriesCount")) != total:
            invalid_shape()
        count(group.get("rowCount"))
        entries = collection(group, ("entries",))
        for row in entries:
            stable(row.get("id"))
            if row.get("stId") != row["id"] or row.get("exactType") not in {"Pathway", "TopLevelPathway"}:
                invalid_shape()
            text(row.get("name"))
            reported_species = collection(row, ("species",), element=str)
            name, prefix = species_scope(species)
            if name not in reported_species or (prefix and not row["id"].startswith(f"R-{prefix}-")):
                invalid_shape()
            if "isDisease" in row and row["isDisease"] is not None and type(row["isDisease"]) is not bool:
                invalid_shape()
            rows.append(row)
    if value["rowCount"] != len(rows) or any(g["rowCount"] != len(g["entries"]) for g in groups):
        invalid_shape()
    if len(rows) > limit or total < offset + len(rows) or (not rows and total > offset):
        invalid_shape()
    if len({r["id"] for r in rows}) != len(rows):
        invalid_shape()
    return rows, total


def interactions(value, *, accession, limit):
    value = obj(value)
    text(value.get("resource"))
    entities = collection(value, ("entities",))
    if len(entities) != 1 or entities[0].get("acc") != accession:
        invalid_shape()
    entity = entities[0]
    rows = collection(entity, ("interactors",))
    # Controller's count is the acquired page's interactions.size(), not a global total.
    if count(entity.get("count")) != len(rows) or len(rows) > limit:
        invalid_shape()
    for row in rows:
        text(row.get("acc"))
        for key in ("id", "evidences"):
            if row.get(key) is not None:
                count(row[key])
        if row.get("score") is not None and (
            type(row["score"]) not in (float, int) or not math.isfinite(row["score"])
        ):
            invalid_shape()
    return value


def diagram(value, expected):
    value = obj(value)
    if value.get("stableId") != expected:
        invalid_shape()
    # NON_EMPTY serialization may omit an empty geometry list.
    if not any(key in value for key in ("nodes", "edges")):
        invalid_shape()
    for key in ("nodes", "edges"):
        if key in value:
            collection(value, (key,))
    return value
