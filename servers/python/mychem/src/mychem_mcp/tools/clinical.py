# src/mychem_mcp/tools/clinical.py
"""Clinical trials and FDA approval tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyChemClient


class ClinicalApi:
    """Tools for clinical data."""
    
    async def get_clinical_trials(
        self,
        client: MyChemClient,
        chemical_id: str
    ) -> Dict[str, Any]:
        """Get clinical trials data for a drug."""
        params = {"fields": "drugbank.clinical_trials,chembl.clinical_trials,pharmgkb.clinical_annotations"}
        
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        trials_data = {
            "chemical_id": chemical_id,
            "clinical_trials": []
        }
        
        # Extract clinical trials from different sources
        if "drugbank" in result and "clinical_trials" in result["drugbank"]:
            db_trials = result["drugbank"]["clinical_trials"]
            if not isinstance(db_trials, list):
                db_trials = [db_trials]
            for trial in db_trials:
                trials_data["clinical_trials"].append({
                    **trial,
                    "source": "drugbank"
                })
        
        if "chembl" in result and "clinical_trials" in result["chembl"]:
            chembl_trials = result["chembl"]["clinical_trials"]
            if not isinstance(chembl_trials, list):
                chembl_trials = [chembl_trials]
            for trial in chembl_trials:
                trials_data["clinical_trials"].append({
                    **trial,
                    "source": "chembl"
                })
        
        return {
            "success": True,
            "total_trials": len(trials_data["clinical_trials"]),
            "trials": trials_data
        }
    
    async def get_fda_approval(
        self,
        client: MyChemClient,
        chemical_id: str
    ) -> Dict[str, Any]:
        """Get FDA approval status and information."""
        params = {"fields": "drugbank.fda_label,drugbank.fda_approval,pharmgkb.fda_approval,chembl.max_phase"}
        
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        fda_data = {
            "chemical_id": chemical_id,
            "approval_status": "Unknown",
            "approval_details": {}
        }
        
        # Check FDA approval from different sources
        if "drugbank" in result:
            drugbank = result["drugbank"]
            if "fda_approval" in drugbank:
                fda_data["approval_status"] = "Approved"
                fda_data["approval_details"]["drugbank"] = drugbank["fda_approval"]
            if "fda_label" in drugbank:
                fda_data["approval_details"]["fda_label"] = drugbank["fda_label"]
        
        if "pharmgkb" in result and "fda_approval" in result["pharmgkb"]:
            fda_data["approval_status"] = "Approved"
            fda_data["approval_details"]["pharmgkb"] = result["pharmgkb"]["fda_approval"]
        
        if "chembl" in result and "max_phase" in result["chembl"]:
            max_phase = result["chembl"]["max_phase"]
            fda_data["approval_details"]["max_phase"] = max_phase
            if max_phase == 4:
                fda_data["approval_status"] = "Approved"
            elif max_phase < 4:
                fda_data["approval_status"] = f"Phase {max_phase}"
        
        return {
            "success": True,
            "fda_data": fda_data
        }


CLINICAL_TOOLS = [
    types.Tool(
        name="get_clinical_trials",
        description="Get clinical trials data for a drug",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical/drug identifier"
                }
            },
            "required": ["chemical_id"]
        }
    ),
    types.Tool(
        name="get_fda_approval",
        description="Get FDA approval status and label information",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical/drug identifier"
                }
            },
            "required": ["chemical_id"]
        }
    )
]