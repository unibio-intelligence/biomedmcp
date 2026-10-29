# src/mychem_mcp/tools/admet.py
"""ADMET (Absorption, Distribution, Metabolism, Excretion, Toxicity) tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyChemClient


from biomedmcp.native.biothings import partial_outcome


class ADMETApi:
    """Tools for ADMET properties."""

    @partial_outcome
    async def get_admet_properties(self, client: MyChemClient, chemical_id: str) -> Dict[str, Any]:
        """Retrieve reported annotations; missing modalities are unavailable, not negative."""
        from biomedmcp.native.biothings import attribution, field_values

        modalities = ("absorption", "distribution", "metabolism", "excretion", "toxicity")
        paths = [f"{source}.{name}" for source in ("chembl", "drugbank") for name in modalities]
        paths += ["pubchem.molecular_weight", "pubchem.logp", "pubchem.tpsa"]
        row = await client.get(f"chem/{chemical_id}", params={"fields": ",".join(paths)})
        values = {name: {} for name in modalities}
        for source in ("chembl", "drugbank"):
            for name in modalities:
                reported = field_values(row, f"{source}.{name}")
                if reported:
                    values[name][source] = reported
        values = {name: reported or None for name, reported in values.items()}
        values["physicochemical"] = {
            name: field_values(row, f"pubchem.{name}") or None
            for name in ("molecular_weight", "logp", "tpsa")
        }
        return {
            "success": True,
            "status": "partial" if any(values[name] is None for name in modalities) else "complete",
            "chemical_id": chemical_id,
            "record_id": row["_id"],
            "admet_properties": values,
            "measurement_status": {
                name: "reported_annotation" if values[name] is not None else "unavailable"
                for name in modalities
            },
            "provenance": attribution(row, f"/chem/{row['_id']}"),
            "limitations": [
                "Source annotations are not computed ADMET predictions or measured negative results.",
                "Physicochemical properties do not establish exposure, toxicity or clinical safety.",
            ],
        }

    async def predict_toxicity(self, client: MyChemClient, chemical_id: str) -> Dict[str, Any]:
        """Get toxicity predictions and data."""
        params = {
            "fields": "chembl.toxicity,drugbank.toxicity,pubchem.ld50,pharmgkb.toxicity,ghs.hazard_statements"
        }

        result = await client.get(f"chem/{chemical_id}", params=params)

        toxicity_data = {
            "chemical_id": chemical_id,
            "acute_toxicity": {},
            "chronic_toxicity": {},
            "hazard_classification": {},
        }

        # Extract toxicity data from various sources
        if "chembl" in result and "toxicity" in result["chembl"]:
            toxicity_data["chembl_toxicity"] = result["chembl"]["toxicity"]

        if "drugbank" in result and "toxicity" in result["drugbank"]:
            toxicity_data["drugbank_toxicity"] = result["drugbank"]["toxicity"]

        if "pubchem" in result and "ld50" in result["pubchem"]:
            toxicity_data["acute_toxicity"]["ld50"] = result["pubchem"]["ld50"]

        if "ghs" in result and "hazard_statements" in result["ghs"]:
            toxicity_data["hazard_classification"]["ghs"] = result["ghs"]["hazard_statements"]

        return {"success": True, "toxicity_data": toxicity_data}


ADMET_TOOLS = [
    types.Tool(
        name="get_admet_properties",
        description="Get ADMET (Absorption, Distribution, Metabolism, Excretion, Toxicity) properties",
        input_schema={
            "type": "object",
            "properties": {"chemical_id": {"type": "string", "description": "Chemical identifier"}},
            "required": ["chemical_id"],
        },
    ),
    types.Tool(
        name="predict_toxicity",
        description="Get toxicity predictions and hazard classifications",
        input_schema={
            "type": "object",
            "properties": {"chemical_id": {"type": "string", "description": "Chemical identifier"}},
            "required": ["chemical_id"],
        },
    ),
]
