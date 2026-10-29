"""Reactome source contracts behind the owned public pathway tasks."""

import hashlib
import json
import re
from typing import Literal
from xml.parsers import expat

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.native.shapes import collection, invalid_shape

from .contracts import (
    REACTIONS,
    count,
    diagram,
    event,
    events,
    interactions,
    participants,
    preflight,
    species_scope,
    stable,
    text,
)

mcp = FastMCP("reactome")
BASE_URL = "https://reactome.org/ContentService"
SEARCH_URL = "https://www.ebi.ac.uk/ebisearch/ws/rest/reactome"
ANNOTATIONS = ToolAnnotations(title="Query Reactome", readOnlyHint=True, openWorldHint=True)


async def read(url, params=None, *, media="application/json", asset=False):
    # Apply the endpoint budget while streaming, before JSON/XML construction.
    async with (
        httpx.AsyncClient(timeout=30.0) as client,
        client.stream("GET", url, params=params or {}, headers={"Accept": media}) as response,
    ):
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > 4_000_000:
                raise ResearchError(
                    "source_response_budget", "Reactome response exceeds the acquired payload budget."
                )
            body.extend(chunk)
        if asset:
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type != media:
                invalid_shape()
            return bytes(body)
        return json.loads(body)


async def search_window(query, species, limit, offset):
    # The independent EMBL-EBI Reactome index supports pathway text discovery
    # while Reactome's ContentService Solr endpoint is unavailable. Use this
    # engine consistently across pages, rather than mixing ranked result sets.
    name, prefix = species_scope(species)
    if name.isdigit():
        raise ResearchError("invalid_parameters", "Use a scientific species name or a supported taxonomy ID.")
    literal = query.replace("\\", "\\\\").replace('"', '\\"')
    index = await read(SEARCH_URL, {"format": "json"})
    domains = collection(index, ("domains",))
    if len(domains) != 1 or domains[0].get("id") != "reactome":
        invalid_shape()
    infos = collection(domains[0], ("indexInfos",))
    values = {text(i.get("name")): text(i.get("value")) for i in infos}
    release = text(values.get("Release version"))
    modified = text(values.get("Last modification date"))
    search_index = {
        "provider": "EMBL-EBI Search",
        "domain": "reactome",
        "release_version": release,
        "last_modified": modified,
        "url": SEARCH_URL,
    }
    payload = await read(
        SEARCH_URL,
        {
            "query": f'("{literal}") AND type:Pathway AND species:"{name}"',
            "format": "json",
            "fields": "name,description,species,stid,type",
            "start": offset,
            "size": limit,
        },
    )
    entries = collection(payload, ("entries",))
    total = count(payload.get("hitCount"))
    rows = []
    for entry in entries:
        fields = entry.get("fields")
        stids = collection(fields, ("stid",), element=str)
        names = collection(fields, ("name",), element=str)
        kinds = collection(fields, ("type",), element=str)
        species_names = collection(fields, ("species",), element=str)
        if len(stids) != 1 or not names or kinds != ["Pathway"] or name not in species_names:
            invalid_shape()
        stid = stable(stids[0])
        if (
            entry.get("source") != "reactome"
            or not re.fullmatch(r"[1-9][0-9]*", str(entry.get("id", "")))
            or stid.rsplit("-", 1)[1] != entry["id"]
            or (prefix and not stid.startswith(f"R-{prefix}-"))
        ):
            invalid_shape()
        rows.append(
            {
                "id": stid,
                "stId": stid,
                "name": text(names[0]),
                "exactType": "Pathway",
                "type": "Pathway",
                "species": species_names,
                "description": collection(fields, ("description",), element=str)
                if "description" in fields
                else [],
                "index_id": entry["id"],
                "search_index": search_index,
            }
        )
    if (
        len(rows) > limit
        or total < offset + len(rows)
        or (not rows and total > offset)
        or len({r["id"] for r in rows}) != len(rows)
    ):
        invalid_shape()
    return {
        "records": rows,
        "provider_response": payload,
        "total": total,
        "raw_count": len(rows),
        "offset": offset,
        "limit": limit,
        "exhausted": offset + len(rows) >= total,
        "search_endpoint": SEARCH_URL,
        "search_index": search_index,
        "warnings": [
            "Pathway discovery uses the independently updated EMBL-EBI Reactome text index; its release and ranking can differ from ContentService."
        ],
        "source_response_sha256": hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest(),
    }


@mcp.tool(annotations=ANNOTATIONS)
async def search_pathways(
    query: str, species: str = "Homo sapiens", limit: int = 20, offset: int = 0
) -> dict:
    """Search the EMBL-EBI Reactome index with literal text and forced species/type filters.

    Results are source text matches, not mechanistic or causal gene/disease associations.
    Index release, original search response and counts are retained. This independently
    updated index can lag Reactome ContentService; ranking follows EBI Search.
    """
    with provider_boundary("reactome"):
        preflight("search_pathways", locals())
        return {"query": query, "species": species, **await search_window(query, species, limit, offset)}


@mcp.tool(annotations=ANNOTATIONS)
async def get_pathway_info(
    pathway_id: str,
    detail_level: Literal["basic", "hierarchy", "participants", "reactions", "full"] = "basic",
) -> dict:
    """Retrieve an exact stable pathway and its provider-asserted events/physical participants.

    Participants retain reference entities; these are not a gene list or pairwise interactions.
    Hierarchy includes subpathways and reactions. Full preserves successful peer acquisitions
    with explicit section outcomes; missing peers do not establish absence.
    """
    with provider_boundary("reactome"):
        preflight("get_pathway_info", locals())
        choices = ["basic", "hierarchy", "participants"] if detail_level == "full" else [detail_level]
        result = {"pathway_id": pathway_id, "detail_level": detail_level}
        statuses = {}
        for choice in choices:
            try:
                if choice == "basic":
                    value = event(
                        await read(f"{BASE_URL}/data/query/{pathway_id}"), expected=pathway_id, pathway=True
                    )
                elif choice == "participants":
                    value = participants(await read(f"{BASE_URL}/data/participants/{pathway_id}"))
                else:
                    value = events(await read(f"{BASE_URL}/data/pathway/{pathway_id}/containedEvents"))
                    if choice == "reactions":
                        value = [row for row in value if row["schemaClass"] in REACTIONS]
                result[choice] = value
                statuses[choice] = {"outcome": "data" if value else "empty"}
            except (httpx.HTTPError, ValueError, ResearchError) as exc:
                if detail_level != "full":
                    raise
                if isinstance(exc, ResearchError):
                    error = exc
                elif isinstance(exc, ValueError):
                    error = ResearchError(
                        "invalid_source_response", "Reactome returned an invalid peer response."
                    )
                else:
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    error = ResearchError(
                        {
                            401: "source_authentication_failed",
                            403: "source_access_denied",
                            404: "source_not_found",
                            429: "source_rate_limited",
                        }.get(status, "source_unavailable"),
                        "Reactome peer acquisition failed.",
                        retryable=status is None or status == 429 or status >= 500,
                    )
                statuses[choice] = {"outcome": "error", "error": error.as_dict()}
        if not any("error" not in value for value in statuses.values()):
            raise ResearchError(
                "source_unavailable", "No requested Reactome acquisition succeeded.", retryable=True
            )
        if detail_level == "full" and "hierarchy" in result:
            result["reactions"] = [row for row in result["hierarchy"] if row["schemaClass"] in REACTIONS]
            statuses["reactions"] = {"outcome": "data" if result["reactions"] else "empty"}
        if all(value["outcome"] == "empty" for value in statuses.values()):
            result["resolution"] = "empty"
        result["section_outcomes"] = statuses
        return result


@mcp.tool(annotations=ANNOTATIONS)
async def find_pathways_by_gene(gene: str, species: str = "Homo sapiens") -> dict:
    """Map a gene symbol through the documented UniProt mapping resource within one species.

    Returns lower-level provider pathway memberships, including disease pathways without
    an undeclared disease filter. Public gene tasks resolve gene identity before mapping.
    """
    with provider_boundary("reactome"):
        preflight("find_pathways_by_gene", locals())
        rows = events(
            await read(f"{BASE_URL}/data/mapping/UniProt/{gene}/pathways", {"species": species}),
            species=species,
            pathways=True,
        )
        return {"gene": gene, "species": species, "results": rows}


@mcp.tool(annotations=ANNOTATIONS)
async def find_pathways_by_disease(
    disease: str, species: str = "Homo sapiens", limit: int = 20, offset: int = 0
) -> dict:
    """Search Pathway annotations for the supplied disease text, with forced type/species.

    This is literal source text search, not a verified ontology-to-pathway association.
    """
    with provider_boundary("reactome"):
        preflight("find_pathways_by_disease", locals())
        return {
            "disease": disease,
            "species": species,
            "relation_basis": "provider_pathway_text_search",
            **await search_window(disease, species, limit, offset),
        }


@mcp.tool(annotations=ANNOTATIONS)
async def get_protein_interactions(protein_id: str, limit: int = 20, page: int = 0) -> dict:
    """Retrieve one bounded static interaction page for an accession.

    Provider counts describe the acquired page. Species, regulatory and catalytic
    classifications are not inferred; no total/exhaustion claim follows from this page.
    """
    with provider_boundary("reactome"):
        preflight("get_protein_interactions", locals())
        value = interactions(
            await read(
                f"{BASE_URL}/interactors/static/molecule/{protein_id}/details",
                {"page": page, "pageSize": limit},
            ),
            accession=protein_id,
            limit=limit,
        )
        return {
            "protein_id": protein_id,
            "page": page,
            "limit": limit,
            "interactions": value,
            "coverage": "acquired_page_only",
        }


@mcp.tool(annotations=ANNOTATIONS)
async def get_pathway_diagram(pathway_id: str, output_format: Literal["json", "svg", "png"] = "json") -> dict:
    """Retrieve diagram geometry or a checked external image locator with byte hash.

    JSON is the diagram layout, not the pathway identity record. Images remain external
    source assets; their media/signature and bytes are checked without executing SVG.
    Mutable current diagram URLs are time-dependent, not frozen release identities.
    """
    with provider_boundary("reactome"):
        preflight("get_pathway_diagram", locals())
        if output_format == "json":
            url = f"https://reactome.org/download/current/diagram/{pathway_id}.json"
            value = diagram(await read(url), pathway_id)
            return {"pathway_id": pathway_id, "format": output_format, "url": url, "diagram": value}
        media = "image/png" if output_format == "png" else "image/svg+xml"
        url = f"{BASE_URL}/exporter/diagram/{pathway_id}.{output_format}"
        body = await read(url, media=media, asset=True)
        if output_format == "png":
            if not body.startswith(b"\x89PNG\r\n\x1a\n"):
                invalid_shape()
        else:
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                invalid_shape()
            parser = expat.ParserCreate(namespace_separator="}")
            depth = nodes = 0

            def start(name, attributes):
                nonlocal depth, nodes
                if nodes == 0 and name != "http://www.w3.org/2000/svg}svg":
                    invalid_shape()
                depth += 1
                nodes += 1
                if depth > 64 or nodes > 100000:
                    invalid_shape()

            def end(name):
                nonlocal depth
                depth -= 1

            parser.StartElementHandler = start
            parser.EndElementHandler = end
            try:
                parser.Parse(body, True)
            except expat.ExpatError:
                invalid_shape()
        return {
            "pathway_id": pathway_id,
            "format": output_format,
            "asset": {
                "url": url,
                "media_type": media,
                "byte_count": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "content_location": "external_provider",
                "validation": "media_and_signature_only",
            },
            "warnings": [
                "External image URLs are time-dependent; SVG is untrusted source data and has not been executed."
            ],
        }
