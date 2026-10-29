"""CIViC's selected GraphQL evidence fields and exact scientific scope."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import ResearchError
from .shapes import invalid_shape

CONTRACT = json.loads(Path(__file__).with_name("civic_contract.json").read_text())
TYPES = CONTRACT["types"]
COLLECTIONS = {"evidenceItems": "EvidenceItemConnection", "assertions": "AssertionConnection"}
PROFILE_FIELDS = """id name deprecated isComplex isMultiVariant variants{
 __typename id name feature{id name featureType featureInstance{
 __typename ...on Gene{name entrezId} ...on Fusion{knownPartnerGenes{name entrezId}}
 }}}"""
COMMON = f"id name link status molecularProfile{{{PROFILE_FIELDS}}} disease{{id name displayName}} therapies{{id name}}"
FIELDS = {
    "evidenceItems": COMMON
    + " description evidenceType evidenceLevel evidenceDirection significance source{id citation sourceType publicationYear sourceUrl retracted link}",
    "assertions": COMMON + " assertionType assertionDirection ampLevel significance summary",
}


def parameters(params, *, public=False):
    allowed = {"limit", "collection", "cursor" if public else "after"}
    if not isinstance(params, dict) or set(params) - allowed:
        raise ResearchError("invalid_parameters", "Unsupported CIViC section parameters.")
    limit = params.get("limit", 10)
    selected = params.get("collection")
    cursor = params.get("cursor" if public else "after")
    if (
        type(limit) is not int
        or not 1 <= limit <= 25
        or selected is not None
        and (not isinstance(selected, str) or selected not in COLLECTIONS)
    ):
        raise ResearchError(
            "invalid_parameters", "CIViC uses a 1–25 page limit and a declared evidence collection."
        )
    if cursor is not None and (
        not isinstance(cursor, str)
        or not cursor
        or len(cursor) > (2048 if public else 8192)
        or selected is None
    ):
        raise ResearchError(
            "invalid_parameters", "CIViC continuation requires one collection and a bounded cursor."
        )
    return limit, selected, cursor


def validate(value, ref, *, field=""):
    if ref.endswith("!"):
        if value is None:
            invalid_shape()
        return validate(value, ref[:-1], field=field)
    if value is None:
        return
    if ref.startswith("["):
        if not isinstance(value, list):
            invalid_shape()
        for item in value:
            validate(item, ref[1:-1], field=field)
        return
    if ref == "Int":
        if (
            type(value) is not int
            or not -(2**31) <= value < 2**31
            or field in {"id", "entrezId", "publicationYear"}
            and value < 1
        ):
            invalid_shape()
        return
    if ref == "Boolean":
        if type(value) is not bool:
            invalid_shape()
        return
    if ref == "String":
        if not isinstance(value, str) or field in {"name", "displayName", "link"} and not value.strip():
            invalid_shape()
        if field in {"link", "sourceUrl"}:
            try:
                url = urlsplit(value)
                valid = url.scheme in {"http", "https"} and bool(url.netloc) and not url.username
            except ValueError:
                valid = False
            if not valid:
                invalid_shape()
        return
    definition = TYPES[ref]
    if definition["kind"] == "ENUM":
        if not isinstance(value, str) or value not in definition["values"]:
            invalid_shape()
        return
    if not isinstance(value, dict) or value.get("error") or value.get("errors"):
        invalid_shape()
    if definition["kind"] in {"UNION", "INTERFACE"}:
        concrete = value.get("__typename")
        if concrete not in definition["members"]:
            invalid_shape()
        if definition["kind"] == "UNION":
            return validate(value, concrete)
    for name, child_ref in definition["fields"].items():
        if name not in value:
            invalid_shape()
        validate(value[name], child_ref, field=name)


def genes(profile):
    for variant in profile["variants"]:
        feature = variant["feature"]
        instance = feature["featureInstance"]
        if instance["__typename"] == "Gene":
            yield instance
        elif instance["__typename"] == "Fusion":
            yield from instance["knownPartnerGenes"]


def named_identity(record, requested, entity):
    """Convert a source-owned ID to an attributed name, never a name-shaped ID."""
    if (
        not isinstance(record, dict)
        or not isinstance(record.get("_id"), str)
        or not record["_id"].strip()
        or record.get("error")
        or record.get("errors")
    ):
        invalid_shape()
    identifiers = [record["_id"]]
    paths = {
        "drug": (("chembl", "molecule_chembl_id"), ("chebi", "id"), ("pubchem", "cid"), ("unii", "unii")),
        "disease": (),
    }
    for source, field in paths[entity]:
        branch = record.get(source)
        if isinstance(branch, dict):
            value = branch.get(field)
            identifiers.extend(value if isinstance(value, list) else [value])
    if requested.casefold() not in {
        str(value).casefold() for value in identifiers if isinstance(value, str) or type(value) is int
    }:
        raise ResearchError(
            "identity_mismatch",
            "CIViC's naming dependency did not confirm the requested source-owned identity.",
        )
    name_paths = {"drug": (("chembl", "pref_name"), ("chebi", "name")), "disease": (("mondo", "label"),)}
    for source, field in name_paths[entity]:
        branch = record.get(source)
        if branch is None:
            continue
        if not isinstance(branch, dict):
            invalid_shape()
        if field not in branch:
            continue
        name = branch[field]
        if not isinstance(name, str) or not name.strip() or len(name) > 512:
            invalid_shape()
        return {
            "requested_id": requested,
            "source_id": record["_id"],
            "name": name,
            "source": "mychem" if entity == "drug" else "mydisease",
            "name_field": source + "." + field,
        }
    raise ResearchError(
        "unresolved_identity",
        "CIViC requires an available attributed drug/disease name; absence of a name is not negative evidence.",
    )


def matches(row, entity, focus, entrez_id):
    profile = row["molecularProfile"]
    if profile["deprecated"]:
        return False
    if entity == "variant":
        from .variants import protein_change

        gene, change = focus.split(" ")
        return (
            profile["name"] == focus
            and not profile["isComplex"]
            and not profile["isMultiVariant"]
            and len(profile["variants"]) == 1
            and protein_change(profile["variants"][0]["name"]) == change
            and any(g["name"] == gene for g in genes(profile))
        )
    if entity == "gene":
        exact = [g for g in genes(profile) if g["name"] == focus]
        if entrez_id is not None and any(str(g["entrezId"]) != str(entrez_id) for g in exact):
            raise ResearchError(
                "identity_mismatch", "CIViC gene namespace does not match the qualified identity."
            )
        return bool(exact)
    if entity == "drug":
        return any(therapy["name"].casefold() == focus.casefold() for therapy in row["therapies"])
    return row["disease"] is not None and focus.casefold() in {
        row["disease"]["name"].casefold(),
        row["disease"]["displayName"].casefold(),
    }


async def evidence(http, focus, entity, *, limit=10, collection=None, after=None, entrez_id=None):
    parameters({"limit": limit, "collection": collection, "after": after})
    if (
        entity not in {"variant", "gene", "drug", "disease"}
        or not isinstance(focus, str)
        or not focus.strip()
        or len(focus) > 512
    ):
        raise ResearchError("unresolved_identity", "CIViC requires one qualified supported scientific focus.")
    selected = [collection] if collection else list(COLLECTIONS)
    field = {"drug": "therapyName", "disease": "diseaseName"}.get(entity, "molecularProfileName")
    query = (
        "query($name:String!,$first:Int!,$after:String){"
        + " ".join(
            name
            + "("
            + field
            + ":$name,status:ACCEPTED,first:$first,after:$after){totalCount pageInfo{hasNextPage endCursor} nodes{"
            + FIELDS[name]
            + "}}"
            for name in selected
        )
        + "}"
    )
    response = await http.post(
        "https://civicdb.org/api/graphql",
        {"query": query, "variables": {"name": focus, "first": limit, "after": after}},
    )
    if (
        not isinstance(response, dict)
        or response.get("error")
        or response.get("errors")
        or not isinstance(response.get("data"), dict)
    ):
        invalid_shape()
    data = response["data"]
    result = {
        "focus": focus,
        "entity": entity,
        "coverage": {},
        "section_outcomes": {},
        "_provider_pages": {},
        "match_policy": "Exact locally verified identities within accepted substring-query candidates; provider totals describe candidates, not exact matches.",
        "identity_scope": "Gene/protein molecular-profile evidence; no assembly/transcript/allele equivalence or clinical classification is inferred.",
        "warnings": [
            "CIViC name-filter candidate windows do not establish exhaustive evidence for the focus."
        ],
    }
    for name in selected:
        if name not in data:
            invalid_shape()
        page = data[name]
        if not isinstance(page, dict):
            invalid_shape()
        # Official links are origin-relative. Accept only declared CIViC record
        # paths; protocol-relative and arbitrary source URLs are never promoted.
        for row in page.get("nodes", []) if isinstance(page.get("nodes"), list) else []:
            if not isinstance(row, dict):
                continue
            for record in (row, row.get("source")):
                if isinstance(record, dict) and isinstance(record.get("link"), str):
                    link = record["link"]
                    if re.fullmatch(r"/(?:links/)?(?:evidence|assertions|sources)/[1-9][0-9]*", link):
                        record["link"] = "https://civicdb.org" + link
        validate(page, COLLECTIONS[name])
        rows, total, info = page["nodes"], page["totalCount"], page["pageInfo"]
        if total < len(rows) or len(rows) > limit or len({r["id"] for r in rows}) != len(rows):
            invalid_shape()
        if any(
            row["status"] != "ACCEPTED"
            or not row["molecularProfile"]["variants"]
            and not row["molecularProfile"]["deprecated"]
            for row in rows
        ):
            invalid_shape()
        more, token = info["hasNextPage"], info["endCursor"]
        if more and (not rows or not token or len(token) > 8192 or token == after or total <= len(rows)):
            invalid_shape()
        if after is None and not more and total != len(rows):
            invalid_shape()
        matched = [row for row in rows if matches(row, entity, focus, entrez_id)]
        result[name] = {
            **page,
            "nodes": matched,
            "pageInfo": {"hasNextPage": more},
            "candidate_count": len(rows),
        }
        result["coverage"][name] = {
            "candidates": len(rows),
            "matched": len(matched),
            "filtered": len(rows) - len(matched),
            "provider_candidate_total": total,
            "has_more": more,
            "page_limit": limit,
            "complete_from_start": after is None and not more,
        }
        result["section_outcomes"][name] = "partial" if more else "data" if matched else "empty"
        if more:
            result["_provider_pages"][name] = {"next_token": token, "raw_count": len(rows), "limit": limit}
    if not any(result[name]["nodes"] for name in selected):
        result["records"] = []
    return result


class CivicContinuation:
    """Scope opaque provider tokens to an expiring, signed scientific request."""

    def __init__(self, runtime):
        self.runtime = runtime

    @staticmethod
    def binding(request, collection, limit):
        from . import REVISION

        return {
            "operation": "get:civic",
            "entity": request.entity.value,
            "id": request.id,
            "species": request.species,
            "assembly": request.assembly,
            "implementation": REVISION,
            "collection": collection,
            "limit": limit,
        }

    async def resume(self, request, *, scope):
        from ..runtime import digest

        params = request.section_parameters.get("civic", {})
        limit, selected, cursor = parameters(params, public=True)
        internal = {"limit": limit, "collection": selected}
        if cursor is None:
            return internal, 0
        count = self.runtime.cursors.decode(cursor, query=self.binding(request, selected, limit), scope=scope)
        state = await self.runtime.cache.get("civic-page:" + digest(cursor))
        if state is None:
            raise ResearchError("expired_cursor", "CIViC continuation expired; restart the evidence request.")
        if (
            not isinstance(state, dict)
            or type(state.get("scanned")) is not int
            or state["scanned"] != count
            or not isinstance(state.get("after"), str)
            or not 1 <= len(state["after"]) <= 8192
        ):
            raise ResearchError(
                "cache_invalid_data", "Stored CIViC continuation is invalid; restart the request."
            )
        internal["after"] = state["after"]
        return internal, count

    async def issue(self, payload, request, *, scope, scanned):
        from ..runtime import digest

        actions = []
        for name, page in payload.get("_provider_pages", {}).items():
            count = scanned + page["raw_count"]
            if count >= 1000:
                payload["coverage"][name]["continuation_status"] = "scan_limit"
                payload["warnings"].append(
                    "CIViC continuation reached the 1000-candidate bound; evidence remains partial."
                )
                continue
            cursor = self.runtime.cursors.encode(
                query=self.binding(request, name, page["limit"]), scope=scope, offset=count
            )
            stored = await self.runtime.cache.put(
                "civic-page:" + digest(cursor), {"after": page["next_token"], "scanned": count}, 3600
            )
            if not stored:
                payload["coverage"][name]["continuation_status"] = "storage_limit"
                payload["warnings"].append(
                    "CIViC continuation storage is full; restart with a narrower focus."
                )
                continue
            actions.append(
                {
                    **request.model_dump(mode="json", exclude_none=True),
                    "sections": ["civic"],
                    "section_parameters": {
                        "civic": {"limit": page["limit"], "collection": name, "cursor": cursor}
                    },
                    "source_versions": {},
                    "sources": [],
                }
            )
        return actions
