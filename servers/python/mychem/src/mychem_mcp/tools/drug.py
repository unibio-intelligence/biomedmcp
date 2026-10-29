# src/mychem_mcp/tools/drug.py
"""Drug-specific tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyChemClient


class DrugApi:
    """Tools for drug-specific queries."""
    
    async def search_drug(
        self,
        client: MyChemClient,
        query: str,
        fields: Optional[str] = "drugbank,chembl,pubchem,name,pharmgkb",
        include_withdrawn: Optional[bool] = False,
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search for drugs with comprehensive information."""
        params = {
            "q": query,
            "fields": fields,
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Filter withdrawn drugs if requested
        if not include_withdrawn:
            hits = []
            for hit in result.get("hits", []):
                if "drugbank" in hit and isinstance(hit["drugbank"], dict):
                    groups = hit["drugbank"].get("groups", [])
                    if "withdrawn" not in groups:
                        hits.append(hit)
                else:
                    hits.append(hit)
            result["hits"] = hits
        
        return {
            "success": True,
            "total": len(result.get("hits", [])),
            "hits": result.get("hits", [])
        }
    
    async def get_drug_interactions(
        self,
        client: MyChemClient,
        drug_id: str
    ) -> Dict[str, Any]:
        """Get drug-drug interactions."""
        params = {"fields": "drugbank.drug_interactions,chembl.drug_mechanisms"}
        
        result = await client.get(f"chem/{drug_id}", params=params)
        
        interactions = []
        
        # Extract DrugBank interactions
        if "drugbank" in result and "drug_interactions" in result["drugbank"]:
            db_interactions = result["drugbank"]["drug_interactions"]
            if not isinstance(db_interactions, list):
                db_interactions = [db_interactions]
            
            for interaction in db_interactions:
                interactions.append({
                    "drug": interaction.get("name"),
                    "drug_id": interaction.get("drugbank-id"),
                    "description": interaction.get("description"),
                    "source": "drugbank"
                })
        
        return {
            "success": True,
            "drug_id": drug_id,
            "total_interactions": len(interactions),
            "interactions": interactions
        }
    
    async def get_drug_targets(
        self,
        client: MyChemClient,
        drug_id: str
    ) -> Dict[str, Any]:
        """Get drug targets and mechanisms."""
        params = {"fields": "drugbank.targets,chembl.target_component,pharmgkb.gene"}
        
        result = await client.get(f"chem/{drug_id}", params=params)
        
        targets = {
            "drugbank_targets": [],
            "chembl_targets": [],
            "pharmgkb_genes": []
        }
        
        # DrugBank targets
        if "drugbank" in result and "targets" in result["drugbank"]:
            db_targets = result["drugbank"]["targets"]
            if not isinstance(db_targets, list):
                db_targets = [db_targets]
            targets["drugbank_targets"] = db_targets
        
        # ChEMBL targets
        if "chembl" in result and "target_component" in result["chembl"]:
            chembl_targets = result["chembl"]["target_component"]
            if not isinstance(chembl_targets, list):
                chembl_targets = [chembl_targets]
            targets["chembl_targets"] = chembl_targets
        
        # PharmGKB genes
        if "pharmgkb" in result and "gene" in result["pharmgkb"]:
            pharmgkb_genes = result["pharmgkb"]["gene"]
            if not isinstance(pharmgkb_genes, list):
                pharmgkb_genes = [pharmgkb_genes]
            targets["pharmgkb_genes"] = pharmgkb_genes
        
        return {
            "success": True,
            "drug_id": drug_id,
            "targets": targets
        }


DRUG_TOOLS = [
    types.Tool(
        name="search_drug",
        description="Search for drugs with information from DrugBank, ChEMBL, and other sources",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Drug name or identifier"
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "drugbank,chembl,pubchem,name,pharmgkb"
                },
                "include_withdrawn": {
                    "type": "boolean",
                    "description": "Include withdrawn drugs in results",
                    "default": False
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    ),
    types.Tool(
        name="get_drug_interactions",
        description="Get drug-drug interaction information",
        input_schema={
            "type": "object",
            "properties": {
                "drug_id": {
                    "type": "string",
                    "description": "Drug identifier (InChIKey, ChEMBL ID, etc.)"
                }
            },
            "required": ["drug_id"]
        }
    ),
    types.Tool(
        name="get_drug_targets",
        description="Get drug target proteins and mechanisms",
        input_schema={
            "type": "object",
            "properties": {
                "drug_id": {
                    "type": "string",
                    "description": "Drug identifier"
                }
            },
            "required": ["drug_id"]
        }
    )
]