"""Disease identifier mapping tools."""

from typing import Any, Dict, List, Optional
import mcp.types as types
from ..client import MyDiseaseClient, MyDiseaseError


from biomedmcp.native.biothings import partial_outcome


class MappingApi:
    """Qualified per-query annotation candidates; no implicit first-match joins."""

    @partial_outcome
    async def map_disease_ids(
        self, client, input_ids: List[str], from_type: str, to_types: List[str], missing_ok: bool = True
    ) -> Dict[str, Any]:
        """Map literal identifiers; preserve all source matches and explicit missingness."""
        field_map = {
            "mondo": "mondo.mondo,mondo.id",
            "omim": "omim",
            "orphanet": "orphanet.id,orphanet.orphanet",
            "doid": "disease_ontology.doid",
            "umls": "umls.cui",
            "mesh": "mesh",
            "icd10": "icd10",
            "icd11": "icd11",
            "hp": "hpo.hpo_id",
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
        name="map_disease_ids",
        description="Map disease identifiers from one type to others (MONDO, OMIM, Orphanet, etc.)",
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
                    "enum": ["mondo", "omim", "orphanet", "doid", "umls", "mesh", "icd10", "icd11", "hp"],
                    "description": "Type of input identifiers",
                },
                "to_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["mondo", "omim", "orphanet", "doid", "umls", "mesh", "icd10", "icd11", "hp"],
                    },
                    "description": "Types to map to",
                },
                "missing_ok": {
                    "type": "boolean",
                    "description": "Include unmapped IDs in response",
                    "default": True,
                },
            },
            "required": ["input_ids", "from_type", "to_types"],
        },
    )
]
