"""MyDisease.info MCP server: disease search, annotation sections, HPO evidence and ID mapping."""

import re
from typing import Annotated, Literal
from urllib.parse import quote

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp.errors import provider_tool_boundary
from biomedmcp.native.biothings import field_values, mapping_inputs, mappings, objects, partial_outcome

from .client import MyDiseaseClient

try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query MyDisease", read_only_hint=True, open_world_hint=True
    )
except ImportError:  # pragma: no cover - annotations are optional metadata
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("mydisease", version="0.1.0")
client = MyDiseaseClient(cache_enabled=False)

DiseaseId = Annotated[
    str, Field(min_length=1, max_length=256, description="MONDO, DOID, OMIM, Orphanet identifier or name.")
]
HPO = r"^HP:[0-9]{7}$"
PhenotypeId = Annotated[str, Field(pattern=HPO, description="HPO term, e.g. HP:0001250.")]
SEARCH_FIELDS = "mondo.label,mondo.mondo,disease_ontology.name,disease_ontology.doid,orphanet.preferred_label"
ID_FIELDS = {
    "mondo": "mondo.mondo",
    "doid": "disease_ontology.doid",
    "orphanet": "orphanet.id",
    "omim": "mondo.xrefs.omim",
    "mesh": "mondo.xrefs.mesh",
}
SECTIONS = {
    "variants": ["disgenet.variants_related_to_disease"],
    "prevalence": ["orphanet.prevalence"],
    "prognosis": ["orphanet.age_of_death", "orphanet.age_of_onset", "orphanet.type_of_inheritance"],
    "clinical_features": ["hpo.phenotype_related_to_disease", "orphanet.phenotypes"],
}
LIMITATION = "Values are source annotations as reported by MyDisease; absence is not a negative finding."


def _path(disease_id):
    return "disease/" + quote(disease_id, safe="")


def _section(name, disease_id, row):
    reported = {path: field_values(row, path) for path in SECTIONS[name]}
    return {
        "disease_id": disease_id,
        "record_id": row["_id"],
        "status": "complete" if any(reported.values()) else "partial",
        name: {path: values for path, values in reported.items() if values},
        "annotation_status": {
            path: "reported" if values else "unavailable" for path, values in reported.items()
        },
        "limitations": [LIMITATION],
    }


def _phenotype_rows(row):
    """Every HPO annotation row, whether nested under `hpo` or exposed at the top level."""
    rows = list(objects(row.get("phenotype_related_to_disease")))
    for node in objects(row.get("hpo")):
        rows.extend(objects(node.get("phenotype_related_to_disease")))
    return rows


def _phenotype_ids(row):
    found = {n.get("hpo_id") for n in objects(row.get("hpo"))} | {
        n.get("hpo_id") for n in _phenotype_rows(row)
    }
    return {term for term in found if isinstance(term, str) and re.fullmatch(HPO, term)}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def search_disease(
    q: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description="MyDisease query string (name, identifier or fielded query).",
        ),
    ],
    fields: Annotated[
        str, Field(min_length=1, max_length=512, description="Comma-separated MyDisease fields to return.")
    ] = SEARCH_FIELDS,
    size: Annotated[int, Field(ge=1, le=100, description="Hits per page.")] = 10,
    from_: Annotated[int, Field(ge=0, le=10000, description="Zero-based offset of the first hit.")] = 0,
) -> dict:
    """Search MyDisease.info (GET /v1/query) and return its hits/total envelope unchanged."""
    return await client.get("query", {"q": q, "fields": fields, "size": size, "from": from_})


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def get_disease_by_id(
    disease_id: DiseaseId,
    fields: Annotated[
        str | None, Field(max_length=512, description="Comma-separated fields; all when omitted.")
    ] = None,
    dotfield: Annotated[bool, Field(description="Flatten nested fields into dotted keys.")] = False,
) -> dict:
    """Fetch one MyDisease.info annotation record (GET /v1/disease/{id}) with upstream field names intact."""
    params = {**({"fields": fields} if fields else {}), **({"dotfield": "true"} if dotfield else {})}
    return await client.get(_path(disease_id), params or None)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def get_disease_variants(disease_id: DiseaseId) -> dict:
    """Report DisGeNET variant annotations attached to one MyDisease record."""
    row = await client.get(_path(disease_id), {"fields": ",".join(SECTIONS["variants"])})
    return _section("variants", disease_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def get_disease_prevalence(disease_id: DiseaseId) -> dict:
    """Report Orphanet prevalence annotations attached to one MyDisease record."""
    row = await client.get(_path(disease_id), {"fields": ",".join(SECTIONS["prevalence"])})
    return _section("prevalence", disease_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def get_disease_prognosis(disease_id: DiseaseId) -> dict:
    """Report Orphanet natural-history annotations (age of onset, age of death, inheritance) for one MyDisease record."""
    row = await client.get(_path(disease_id), {"fields": ",".join(SECTIONS["prognosis"])})
    return _section("prognosis", disease_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
async def get_diagnostic_criteria(disease_id: DiseaseId) -> dict:
    """Report HPO and Orphanet clinical-feature annotations for one MyDisease record."""
    row = await client.get(_path(disease_id), {"fields": "hpo,orphanet.phenotypes"})
    return _section("clinical_features", disease_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
@partial_outcome
async def get_gene_disease_evidence(
    gene_symbol: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")],
    disease_id: DiseaseId,
) -> dict:
    """Return DisGeNET gene-disease assertions for one gene symbol on one MyDisease record, as reported, with no derived association call or aggregate score."""
    row = await client.get(_path(disease_id), {"fields": "disgenet.genes_related_to_disease"})
    assertions = [
        {"source": "disgenet", "reported_assertion": item}
        for item in field_values(row, "disgenet.genes_related_to_disease")
        if isinstance(item, dict) and item.get("gene_name") == gene_symbol
    ]
    return {
        "gene_symbol": gene_symbol,
        "disease_id": disease_id,
        "record_id": row["_id"],
        "status": "complete" if assertions else "partial",
        "evidence_status": "reported" if assertions else "unavailable",
        "assertions": assertions,
        "is_associated": None,
        "aggregate_score": None,
        "limitations": [
            "Symbol matches do not qualify species or namespace; scores are the source's own fields.",
            LIMITATION,
        ],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
@partial_outcome
async def get_phenotype_frequency(disease_id: DiseaseId, phenotype_id: PhenotypeId) -> dict:
    """Return every HPO annotation row for one phenotype on one MyDisease record, keeping raw frequency values or HPO frequency terms exactly as reported."""
    row = await client.get(_path(disease_id), {"fields": "hpo"})
    annotations = []
    for item in _phenotype_rows(row):
        if phenotype_id not in {item.get("hpo_id"), item.get("hpo_phenotype")}:
            continue
        frequency, term = item.get("frequency"), item.get("frequency_hp")
        measured = (isinstance(frequency, (int, float)) and not isinstance(frequency, bool)) or (
            isinstance(term, str) and re.fullmatch(HPO, term)
        )
        annotations.append({**item, "measurement_status": "reported" if measured else "unavailable"})
    reported = [a for a in annotations if a["measurement_status"] == "reported"]
    return {
        "disease_id": disease_id,
        "phenotype_id": phenotype_id,
        "record_id": row["_id"],
        "status": "complete" if annotations and len(reported) == len(annotations) else "partial",
        "measurement_status": "reported" if reported else "unavailable",
        "annotations": annotations,
        "limitations": [
            "Frequencies are not converted to percentages; missing rows are not negative evidence."
        ],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
@partial_outcome
async def get_phenotype_similarity(
    phenotype_list: Annotated[list[PhenotypeId], Field(min_length=1, max_length=100)],
    algorithm: Literal["jaccard", "dice"] = "jaccard",
    min_similarity: Annotated[float, Field(ge=0, le=1)] = 0.5,
    size: Annotated[int, Field(ge=1, le=100, description="Source window size; one window only.")] = 20,
) -> dict:
    """Rank diseases annotated with any query HPO term by Jaccard or Dice overlap of exact HPO identifier sets within one MyDisease query window (GET /v1/query); not a clinical similarity."""
    query = sorted(set(phenotype_list))
    q = " OR ".join(f'hpo.phenotype_related_to_disease.hpo_id:"{term}"' for term in query)
    data = await client.get("query", {"q": q, "fields": "hpo", "size": size, "from": 0})
    diseases, unavailable = [], []
    for hit in data["hits"]:
        annotated = _phenotype_ids(hit)
        if not annotated:
            unavailable.append(hit["_id"])
            continue
        shared = annotated & set(query)
        numerator, denominator = (
            (len(shared), len(annotated | set(query)))
            if algorithm == "jaccard"
            else (2 * len(shared), len(annotated) + len(query))
        )
        score = numerator / denominator
        if score >= min_similarity:
            diseases.append(
                {
                    "disease_id": hit["_id"],
                    "similarity_score": score,
                    "numerator": numerator,
                    "denominator": denominator,
                    "shared_phenotypes": sorted(shared),
                    "annotation_count": len(annotated),
                }
            )
    diseases.sort(key=lambda d: (-d["similarity_score"], d["disease_id"]))
    total = data.get("total", len(data["hits"]))
    window = {
        "size": size,
        "returned": len(data["hits"]),
        "source_total": total,
        "has_more": total > len(data["hits"]),
    }
    return {
        "algorithm": algorithm,
        "query_phenotypes": query,
        "status": "partial" if window["has_more"] or unavailable or not diseases else "complete",
        "diseases": diseases,
        "source_window": window,
        "unavailable_annotation_ids": unavailable,
        "limitations": [
            "Annotation-set overlap of exact HPO identifiers; no ontology propagation or diagnosis."
        ],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mydisease")
@partial_outcome
async def map_disease_ids(
    input_ids: Annotated[
        list[str], Field(min_length=1, max_length=1000, description="Literal identifiers in from_type.")
    ],
    from_type: Annotated[str, Field(description="One of: " + ", ".join(ID_FIELDS))],
    to_types: Annotated[
        list[str], Field(min_length=1, max_length=len(ID_FIELDS), description="Target namespaces.")
    ],
    missing_ok: Annotated[bool, Field(description="Whether unmapped inputs are acceptable.")] = True,
) -> dict:
    """Map disease identifiers between MONDO, DOID, Orphanet, OMIM and MeSH namespaces in one POST /v1/query batch; every match stays a candidate."""
    mapping_inputs(input_ids, from_type, to_types, ID_FIELDS)
    unique = list(dict.fromkeys(input_ids))
    rows = await client.post(
        "query",
        {"q": unique, "scopes": ID_FIELDS[from_type], "fields": ",".join(ID_FIELDS[t] for t in to_types)},
    )
    return mappings(rows, input_ids, from_type, to_types, ID_FIELDS, missing_ok)
