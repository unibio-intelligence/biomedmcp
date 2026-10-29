# src/mychem_mcp/tools/biological_context.py
"""Biological context and pathway tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyChemClient


class BiologicalContextApi:
    """Tools for biological context, pathways, and disease associations."""
    
    async def get_pathway_associations(
        self,
        client: MyChemClient,
        chemical_id: str
    ) -> Dict[str, Any]:
        """Get metabolic and signaling pathway associations for a chemical."""
        fields = [
            "pharmgkb.pathways",
            "drugbank.pathways",
            "chembl.metabolism",
            "drugbank.enzymes",
            "drugbank.transporters",
            "drugbank.carriers"
        ]
        
        params = {"fields": ",".join(fields)}
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        pathway_data = {
            "chemical_id": chemical_id,
            "pathways": [],
            "enzymes": [],
            "transporters": [],
            "carriers": []
        }
        
        # Extract PharmGKB pathways
        if "pharmgkb" in result and "pathways" in result["pharmgkb"]:
            pathways = result["pharmgkb"]["pathways"]
            if not isinstance(pathways, list):
                pathways = [pathways]
            
            for pathway in pathways:
                pathway_data["pathways"].append({
                    "source": "pharmgkb",
                    "name": pathway.get("name"),
                    "id": pathway.get("id")
                })
        
        # Extract DrugBank pathways and proteins
        if "drugbank" in result:
            db = result["drugbank"]
            
            if "pathways" in db:
                pathways = db["pathways"]
                if not isinstance(pathways, list):
                    pathways = [pathways]
                
                for pathway in pathways:
                    pathway_data["pathways"].append({
                        "source": "drugbank",
                        "name": pathway.get("name"),
                        "category": pathway.get("category")
                    })
            
            # Enzymes
            if "enzymes" in db:
                enzymes = db["enzymes"]
                if not isinstance(enzymes, list):
                    enzymes = [enzymes]
                pathway_data["enzymes"] = enzymes
            
            # Transporters
            if "transporters" in db:
                transporters = db["transporters"]
                if not isinstance(transporters, list):
                    transporters = [transporters]
                pathway_data["transporters"] = transporters
            
            # Carriers
            if "carriers" in db:
                carriers = db["carriers"]
                if not isinstance(carriers, list):
                    carriers = [carriers]
                pathway_data["carriers"] = carriers
        
        # Extract ChEMBL metabolism data
        if "chembl" in result and "metabolism" in result["chembl"]:
            metabolism = result["chembl"]["metabolism"]
            if isinstance(metabolism, dict):
                pathway_data["metabolism"] = metabolism
        
        return {
            "success": True,
            "pathway_associations": pathway_data
        }
    
    async def get_disease_associations(
        self,
        client: MyChemClient,
        chemical_id: str,
        include_offlabel: bool = False
    ) -> Dict[str, Any]:
        """Get disease associations and therapeutic indications."""
        fields = [
            "drugbank.indication",
            "drugbank.pharmacodynamics",
            "chembl.indication_class",
            "pharmgkb.diseases",
            "drugbank.categories"
        ]
        
        params = {"fields": ",".join(fields)}
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        disease_data = {
            "chemical_id": chemical_id,
            "approved_indications": [],
            "disease_associations": [],
            "therapeutic_categories": [],
            "pharmacodynamics": None
        }
        
        # Extract DrugBank data
        if "drugbank" in result:
            db = result["drugbank"]
            
            if "indication" in db:
                disease_data["approved_indications"].append({
                    "source": "drugbank",
                    "description": db["indication"]
                })
            
            if "pharmacodynamics" in db:
                disease_data["pharmacodynamics"] = db["pharmacodynamics"]
            
            if "categories" in db:
                categories = db["categories"]
                if not isinstance(categories, list):
                    categories = [categories]
                disease_data["therapeutic_categories"] = categories
        
        # Extract ChEMBL indication class
        if "chembl" in result and "indication_class" in result["chembl"]:
            indication_classes = result["chembl"]["indication_class"]
            if not isinstance(indication_classes, list):
                indication_classes = [indication_classes]
            
            for ind_class in indication_classes:
                disease_data["disease_associations"].append({
                    "source": "chembl",
                    "indication": ind_class
                })
        
        # Extract PharmGKB diseases
        if "pharmgkb" in result and "diseases" in result["pharmgkb"]:
            diseases = result["pharmgkb"]["diseases"]
            if not isinstance(diseases, list):
                diseases = [diseases]
            
            for disease in diseases:
                disease_data["disease_associations"].append({
                    "source": "pharmgkb",
                    "disease": disease.get("name"),
                    "id": disease.get("id")
                })
        
        return {
            "success": True,
            "disease_associations": disease_data
        }
    
    async def search_by_indication(
        self,
        client: MyChemClient,
        indication: str,
        drug_status: Optional[str] = "approved",
        size: int = 20
    ) -> Dict[str, Any]:
        """Search for drugs by therapeutic indication."""
        query_parts = [f'drugbank.indication:"{indication}"']
        
        if drug_status:
            query_parts.append(f'drugbank.groups:"{drug_status}"')
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "inchikey,drugbank.name,drugbank.indication,drugbank.groups,chembl.max_phase",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Process results
        drugs = []
        for hit in result.get("hits", []):
            drug_info = {
                "inchikey": hit.get("_id"),
                "name": hit.get("drugbank", {}).get("name"),
                "indication": hit.get("drugbank", {}).get("indication"),
                "status": hit.get("drugbank", {}).get("groups", []),
                "max_phase": hit.get("chembl", {}).get("max_phase")
            }
            drugs.append(drug_info)
        
        return {
            "success": True,
            "query_indication": indication,
            "drug_status_filter": drug_status,
            "total_found": len(drugs),
            "drugs": drugs
        }
    
    async def get_mechanism_of_action(
        self,
        client: MyChemClient,
        chemical_id: str
    ) -> Dict[str, Any]:
        """Get detailed mechanism of action information."""
        fields = [
            "drugbank.mechanism_of_action",
            "chembl.drug_mechanisms",
            "drugbank.pharmacodynamics",
            "drugbank.targets"
        ]
        
        params = {"fields": ",".join(fields)}
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        moa_data = {
            "chemical_id": chemical_id,
            "mechanisms": [],
            "primary_targets": []
        }
        
        # Extract DrugBank mechanism
        if "drugbank" in result:
            db = result["drugbank"]
            
            if "mechanism_of_action" in db:
                moa_data["mechanisms"].append({
                    "source": "drugbank",
                    "description": db["mechanism_of_action"],
                    "type": "detailed"
                })
            
            if "targets" in db:
                targets = db["targets"]
                if not isinstance(targets, list):
                    targets = [targets]
                
                for target in targets:
                    if target.get("actions"):
                        moa_data["primary_targets"].append({
                            "name": target.get("name"),
                            "gene_name": target.get("gene_name"),
                            "actions": target.get("actions"),
                            "organism": target.get("organism")
                        })
        
        # Extract ChEMBL mechanisms
        if "chembl" in result and "drug_mechanisms" in result["chembl"]:
            mechanisms = result["chembl"]["drug_mechanisms"]
            if not isinstance(mechanisms, list):
                mechanisms = [mechanisms]
            
            for mech in mechanisms:
                moa_data["mechanisms"].append({
                    "source": "chembl",
                    "action_type": mech.get("action_type"),
                    "mechanism": mech.get("mechanism_of_action"),
                    "target": mech.get("target_name")
                })
        
        return {
            "success": True,
            "mechanism_of_action": moa_data
        }
    
    async def find_drugs_by_target_class(
        self,
        client: MyChemClient,
        target_class: str,
        include_investigational: bool = False,
        size: int = 20
    ) -> Dict[str, Any]:
        """Find drugs that act on a specific target class."""
        query_parts = [f'chembl.target_class:"{target_class}"']
        
        if not include_investigational:
            query_parts.append('chembl.max_phase:4')
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "inchikey,chembl.pref_name,chembl.target_class,chembl.max_phase,chembl.drug_mechanisms",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        drugs = []
        for hit in result.get("hits", []):
            drug_info = {
                "inchikey": hit.get("_id"),
                "name": hit.get("chembl", {}).get("pref_name"),
                "target_classes": hit.get("chembl", {}).get("target_class", []),
                "development_phase": hit.get("chembl", {}).get("max_phase"),
                "mechanisms": []
            }
            
            # Extract mechanisms if available
            if "drug_mechanisms" in hit.get("chembl", {}):
                mechanisms = hit["chembl"]["drug_mechanisms"]
                if not isinstance(mechanisms, list):
                    mechanisms = [mechanisms]
                
                for mech in mechanisms:
                    drug_info["mechanisms"].append({
                        "action": mech.get("action_type"),
                        "target": mech.get("target_name")
                    })
            
            drugs.append(drug_info)
        
        return {
            "success": True,
            "target_class_query": target_class,
            "include_investigational": include_investigational,
            "total_found": len(drugs),
            "drugs": drugs
        }


BIOLOGICAL_CONTEXT_TOOLS = [
    types.Tool(
        name="get_pathway_associations",
        description="Get metabolic and signaling pathway associations for a chemical",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical identifier"
                }
            },
            "required": ["chemical_id"]
        }
    ),
    types.Tool(
        name="get_disease_associations",
        description="Get disease associations and therapeutic indications",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical identifier"
                },
                "include_offlabel": {
                    "type": "boolean",
                    "description": "Include off-label uses",
                    "default": False
                }
            },
            "required": ["chemical_id"]
        }
    ),
    types.Tool(
        name="search_by_indication",
        description="Search for drugs by therapeutic indication",
        input_schema={
            "type": "object",
            "properties": {
                "indication": {
                    "type": "string",
                    "description": "Disease or condition to treat"
                },
                "drug_status": {
                    "type": "string",
                    "description": "Drug approval status filter",
                    "default": "approved",
                    "enum": ["approved", "investigational", "experimental", None]
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["indication"]
        }
    ),
    types.Tool(
        name="get_mechanism_of_action",
        description="Get detailed mechanism of action information",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical identifier"
                }
            },
            "required": ["chemical_id"]
        }
    ),
    types.Tool(
        name="find_drugs_by_target_class",
        description="Find drugs that act on a specific target class (e.g., 'Kinase', 'GPCR')",
        input_schema={
            "type": "object",
            "properties": {
                "target_class": {
                    "type": "string",
                    "description": "Target protein class"
                },
                "include_investigational": {
                    "type": "boolean",
                    "description": "Include investigational drugs",
                    "default": False
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["target_class"]
        }
    )
]