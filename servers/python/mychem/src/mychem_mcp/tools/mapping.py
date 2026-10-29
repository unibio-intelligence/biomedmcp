# src/mychem_mcp/tools/mapping.py
"""Chemical identifier mapping tools."""

from typing import Any, Dict, List, Optional
import mcp.types as types
from ..client import MyChemClient, MyChemError


from biomedmcp.native.biothings import partial_outcome


class MappingApi:
    """Qualified per-query annotation candidates; no implicit first-match joins."""

    @partial_outcome
    async def map_identifiers(
        self, client, input_ids: List[str], from_type: str, to_types: List[str], missing_ok: bool = True
    ) -> Dict[str, Any]:
        """Map literal identifiers; preserve all source matches and explicit missingness."""
        field_map = {
            "inchikey": "pubchem.inchikey,chembl.inchikey,drugbank.inchikey",
            "pubchem": "pubchem.cid",
            "chembl": "chembl.molecule_chembl_id",
            "drugbank": "drugbank.id",
            "unii": "unii.unii",
            "cas": "drugbank.cas_number,pubchem.cas",
            "smiles": "pubchem.smiles.canonical,chembl.smiles",
            "inchi": "pubchem.inchi,chembl.inchi",
            "name": "chembl.pref_name,drugbank.name,pubchem.synonyms",
        }
        from biomedmcp.native.biothings import mapping_inputs, mappings

        input_fields = {key: value for key, value in field_map.items() if key != "name"}
        mapping_inputs(input_ids, from_type, to_types, field_map)
        if from_type not in input_fields:
            from biomedmcp.errors import ResearchError

            raise ResearchError(
                "invalid_parameters",
                "Use ordinary search for chemical names; mapping requires literal identifiers.",
            )
        fields = ["_id"] + [field_map[target] for target in to_types]
        rows = await client.post(
            "query",
            {"q": list(dict.fromkeys(input_ids)), "scopes": field_map[from_type], "fields": ",".join(fields)},
        )
        return mappings(rows, input_ids, from_type, to_types, field_map, missing_ok)


MAPPING_TOOLS = [
    types.Tool(
        name="map_identifiers",
        description="Map chemical identifiers from one type to others (InChIKey, PubChem CID, ChEMBL ID, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "input_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of input identifiers",
                },
                "from_type": {
                    "type": "string",
                    "enum": [
                        "inchikey",
                        "pubchem",
                        "chembl",
                        "drugbank",
                        "unii",
                        "cas",
                        "smiles",
                        "inchi",
                        "name",
                    ],
                    "description": "Type of input identifiers",
                },
                "to_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "inchikey",
                            "pubchem",
                            "chembl",
                            "drugbank",
                            "unii",
                            "cas",
                            "smiles",
                            "inchi",
                            "name",
                        ],
                    },
                    "description": "Types to map to",
                },
                "missing_ok": {
                    "type": "boolean",
                    "description": "Whether to include unmapped IDs in response",
                    "default": True,
                },
            },
            "required": ["input_ids", "from_type", "to_types"],
        },
    )
]
