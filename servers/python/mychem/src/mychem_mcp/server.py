"""MyChem.info MCP server: chemical search, annotation sections, ADMET reports and ID mapping."""

from typing import Annotated
from urllib.parse import quote

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp.errors import provider_tool_boundary
from biomedmcp.native.biothings import field_values, mapping_inputs, mappings, partial_outcome

from .client import MyChemClient

try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(title="Query MyChem", read_only_hint=True, open_world_hint=True)
except ImportError:  # pragma: no cover - annotations are optional metadata
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("mychem", version="0.1.0")
client = MyChemClient(cache_enabled=False)

ChemicalId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        description="InChIKey, ChEMBL ID, DrugBank ID, UNII, PubChem CID or name.",
    ),
]
SEARCH_FIELDS = "chembl.pref_name,chembl.molecule_chembl_id,chebi.name,drugbank.name,pubchem.cid,unii.unii"
ID_FIELDS = {
    "chembl": "chembl.molecule_chembl_id",
    "inchikey": "chembl.inchikey,pubchem.inchikey,drugbank.inchikey,unii.inchikey",
    "pubchem": "pubchem.cid",
    "drugbank": "drugbank.id",
    "unii": "unii.unii",
    "chebi": "chebi.id",
}
# Reported annotation paths per ADMET modality; physicochemical values are not predictions.
ADMET_PATHS = {
    "absorption": {
        "drugbank": ["drugbank.absorption"],
        "drugcentral": ["drugcentral.pharmacology.absorption"],
    },
    "distribution": {"drugbank": ["drugbank.volume_of_distribution", "drugbank.protein_binding"]},
    "metabolism": {"drugbank": ["drugbank.metabolism"]},
    "excretion": {"drugbank": ["drugbank.half_life", "drugbank.clearance", "drugbank.route_of_elimination"]},
    "toxicity": {"chembl": ["chembl.toxicity"], "drugbank": ["drugbank.toxicity"]},
    "physicochemical": {
        "logp": ["pubchem.logp", "pubchem.xlogp", "chembl.molecule_properties.alogp"],
        "molecular_weight": ["pubchem.molecular_weight", "chembl.molecule_properties.full_mwt"],
        "hbd": ["pubchem.hydrogen_bond_donor_count", "chembl.molecule_properties.hbd"],
        "hba": ["pubchem.hydrogen_bond_acceptor_count", "chembl.molecule_properties.hba"],
        "tpsa": ["pubchem.topological_polar_surface_area", "chembl.molecule_properties.psa"],
    },
}
SECTIONS = {
    "targets": ["drugcentral.bioactivity", "drugbank.targets"],
    "indications": ["drugcentral.drug_use", "chembl.drug_indications"],
    "interactions": ["drugbank.drug_interactions"],
}


def _path(chemical_id):
    return "chem/" + quote(chemical_id, safe="")


def _section(name, chemical_id, row):
    reported = {path: field_values(row, path) for path in SECTIONS[name]}
    return {
        "chemical_id": chemical_id,
        "record_id": row["_id"],
        "status": "complete" if any(reported.values()) else "partial",
        name: {path: values for path, values in reported.items() if values},
        "annotation_status": {
            path: "reported" if values else "unavailable" for path, values in reported.items()
        },
        "limitations": [
            "Values are source annotations as reported by MyChem; absence is not a negative finding."
        ],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
async def search_chemical(
    q: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description="MyChem query string (name, identifier or fielded query).",
        ),
    ],
    fields: Annotated[
        str, Field(min_length=1, max_length=512, description="Comma-separated MyChem fields to return.")
    ] = SEARCH_FIELDS,
    size: Annotated[int, Field(ge=1, le=100, description="Hits per page.")] = 10,
    from_: Annotated[int, Field(ge=0, le=10000, description="Zero-based offset of the first hit.")] = 0,
) -> dict:
    """Search MyChem.info (GET /v1/query) and return its hits/total envelope unchanged."""
    return await client.get("query", {"q": q, "fields": fields, "size": size, "from": from_})


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
async def get_chemical_by_id(
    chemical_id: ChemicalId,
    fields: Annotated[
        str | None, Field(max_length=512, description="Comma-separated fields; all when omitted.")
    ] = None,
    dotfield: Annotated[bool, Field(description="Flatten nested fields into dotted keys.")] = False,
) -> dict:
    """Fetch one MyChem.info annotation record (GET /v1/chem/{id}) with upstream field names intact."""
    params = {**({"fields": fields} if fields else {}), **({"dotfield": "true"} if dotfield else {})}
    return await client.get(_path(chemical_id), params or None)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
async def get_drug_targets(drug_id: ChemicalId) -> dict:
    """Report DrugCentral bioactivity and DrugBank target annotations for one MyChem record."""
    row = await client.get(_path(drug_id), {"fields": ",".join(SECTIONS["targets"])})
    return _section("targets", drug_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
async def get_disease_associations(chemical_id: ChemicalId) -> dict:
    """Report DrugCentral drug-use and ChEMBL indication annotations for one MyChem record."""
    row = await client.get(_path(chemical_id), {"fields": ",".join(SECTIONS["indications"])})
    return _section("indications", chemical_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
async def get_drug_interactions(drug_id: ChemicalId) -> dict:
    """Report DrugBank drug-interaction annotations for one MyChem record."""
    row = await client.get(_path(drug_id), {"fields": ",".join(SECTIONS["interactions"])})
    return _section("interactions", drug_id, row)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
@partial_outcome
async def get_admet_properties(chemical_id: ChemicalId) -> dict:
    """Collect reported absorption, distribution, metabolism, excretion, toxicity and physicochemical annotations from one MyChem record; unavailable modalities stay explicit."""
    fields = ",".join(path for group in ADMET_PATHS.values() for paths in group.values() for path in paths)
    row = await client.get(_path(chemical_id), {"fields": fields})
    properties, status = {}, {}
    for modality, group in ADMET_PATHS.items():
        values = {}
        for label, paths in group.items():
            found = [item for path in paths for item in field_values(row, path)]
            if found:
                values[label] = found
        properties[modality] = values or None
        status[modality] = "reported" if values else "unavailable"
    return {
        "chemical_id": chemical_id,
        "record_id": row["_id"],
        "status": "complete" if all(v == "reported" for v in status.values()) else "partial",
        "admet_properties": properties,
        "measurement_status": status,
        "limitations": [
            "Reported source annotations only; physicochemical descriptors are not ADMET predictions.",
            "An unavailable modality means no annotation was returned, not a negative measurement.",
        ],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mychem")
@partial_outcome
async def map_identifiers(
    input_ids: Annotated[
        list[str], Field(min_length=1, max_length=1000, description="Literal identifiers in from_type.")
    ],
    from_type: Annotated[str, Field(description="One of: " + ", ".join(ID_FIELDS))],
    to_types: Annotated[
        list[str], Field(min_length=1, max_length=len(ID_FIELDS), description="Target namespaces.")
    ],
    missing_ok: Annotated[bool, Field(description="Whether unmapped inputs are acceptable.")] = True,
) -> dict:
    """Map chemical identifiers between ChEMBL, InChIKey, PubChem, DrugBank, UNII and ChEBI namespaces in one POST /v1/query batch; every match stays a candidate."""
    mapping_inputs(input_ids, from_type, to_types, ID_FIELDS)
    unique = list(dict.fromkeys(input_ids))
    rows = await client.post(
        "query",
        {"q": unique, "scopes": ID_FIELDS[from_type], "fields": ",".join(ID_FIELDS[t] for t in to_types)},
    )
    return mappings(rows, input_ids, from_type, to_types, ID_FIELDS, missing_ok)
