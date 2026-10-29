"""Clinical information tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class ClinicalApi:
    """Tools for clinical information."""
    
    async def get_clinical_significance(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get clinical significance and variant interpretations."""
        params = {
            "fields": "clinvar,clinical_significance,pathogenic_variants"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        clinical_data = {
            "disease_id": disease_id,
            "clinvar_summary": {},
            "pathogenic_variants": [],
            "clinical_interpretations": []
        }
        
        # Process ClinVar data
        if "clinvar" in result:
            clinvar = result["clinvar"]
            
            # Count clinical significance
            if "variant" in clinvar:
                variants = clinvar["variant"]
                variants = variants if isinstance(variants, list) else [variants]
                
                sig_counts = {}
                for var in variants:
                    sig = var.get("clinical_significance", "Unknown")
                    sig_counts[sig] = sig_counts.get(sig, 0) + 1
                
                clinical_data["clinvar_summary"] = sig_counts
                
                # Get pathogenic variants
                for var in variants:
                    if "pathogenic" in var.get("clinical_significance", "").lower():
                        clinical_data["pathogenic_variants"].append({
                            "rsid": var.get("rsid"),
                            "gene": var.get("gene"),
                            "hgvs": var.get("hgvs"),
                            "clinical_significance": var.get("clinical_significance"),
                            "review_status": var.get("review_status")
                        })
        
        return {
            "success": True,
            "clinical_data": clinical_data
        }
    
    async def get_diagnostic_criteria(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get diagnostic criteria and guidelines."""
        params = {
            "fields": "diagnostic_criteria,clinical_features,phenotype_related_to_disease"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        diagnostic_info = {
            "disease_id": disease_id,
            "diagnostic_criteria": result.get("diagnostic_criteria"),
            "major_features": [],
            "minor_features": []
        }
        
        # Extract clinical features
        if "clinical_features" in result:
            features = result["clinical_features"]
            features = features if isinstance(features, list) else [features]
            
            for feature in features:
                if feature.get("importance") == "major":
                    diagnostic_info["major_features"].append(feature)
                else:
                    diagnostic_info["minor_features"].append(feature)
        
        # Extract frequent phenotypes as diagnostic clues
        if "phenotype_related_to_disease" in result:
            phenotypes = result["phenotype_related_to_disease"]
            phenotypes = phenotypes if isinstance(phenotypes, list) else [phenotypes]
            
            # Get high-frequency phenotypes
            diagnostic_info["common_phenotypes"] = [
                p for p in phenotypes 
                if p.get("frequency") and (
                    "frequent" in p["frequency"].lower() or
                    "very frequent" in p["frequency"].lower() or
                    "obligate" in p["frequency"].lower()
                )
            ]
        
        return {
            "success": True,
            "diagnostic_info": diagnostic_info
        }
    
    async def get_disease_prognosis(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get prognosis and outcome information."""
        params = {
            "fields": "prognosis,life_expectancy,disease_course,severity"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        prognosis_data = {
            "disease_id": disease_id,
            "prognosis": result.get("prognosis"),
            "life_expectancy": result.get("life_expectancy"),
            "disease_course": result.get("disease_course"),
            "severity": result.get("severity")
        }
        
        return {
            "success": True,
            "prognosis_data": prognosis_data
        }
    
    async def get_treatment_options(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        include_experimental: bool = False
    ) -> Dict[str, Any]:
        """Get treatment options and therapeutic approaches."""
        params = {
            "fields": "treatment,drug_treatment,gene_therapy,management"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        treatment_data = {
            "disease_id": disease_id,
            "standard_treatments": [],
            "drug_treatments": [],
            "gene_therapies": [],
            "management_approaches": []
        }
        
        # Extract treatment information
        if "treatment" in result:
            treatment_data["standard_treatments"] = result["treatment"]
        
        if "drug_treatment" in result:
            drugs = result["drug_treatment"]
            drugs = drugs if isinstance(drugs, list) else [drugs]
            
            for drug in drugs:
                if not include_experimental or drug.get("status") != "experimental":
                    treatment_data["drug_treatments"].append(drug)
        
        if "gene_therapy" in result:
            treatment_data["gene_therapies"] = result["gene_therapy"]
        
        if "management" in result:
            treatment_data["management_approaches"] = result["management"]
        
        return {
            "success": True,
            "treatment_options": treatment_data
        }
    
    async def get_clinical_trials(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        status: Optional[str] = "recruiting"
    ) -> Dict[str, Any]:
        """Get clinical trials for a disease."""
        params = {
            "fields": "clinical_trials,ctd.clinical_trials"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        trials_data = {
            "disease_id": disease_id,
            "active_trials": [],
            "all_trials": []
        }
        
        # Extract clinical trials
        if "clinical_trials" in result:
            trials = result["clinical_trials"]
            trials = trials if isinstance(trials, list) else [trials]
            
            for trial in trials:
                trials_data["all_trials"].append(trial)
                if status is None or trial.get("status", "").lower() == status.lower():
                    trials_data["active_trials"].append(trial)
        
        # Extract CTD trials
        if "ctd" in result and "clinical_trials" in result["ctd"]:
            ctd_trials = result["ctd"]["clinical_trials"]
            ctd_trials = ctd_trials if isinstance(ctd_trials, list) else [ctd_trials]
            trials_data["all_trials"].extend(ctd_trials)
        
        return {
            "success": True,
            "trials": trials_data,
            "filter_status": status
        }


CLINICAL_TOOLS = [
    types.Tool(
        name="get_clinical_significance",
        description="Get clinical significance and variant interpretations",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_diagnostic_criteria",
        description="Get diagnostic criteria and guidelines",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_disease_prognosis",
        description="Get prognosis and outcome information",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_treatment_options",
        description="Get treatment options and therapeutic approaches",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "include_experimental": {
                    "type": "boolean",
                    "description": "Include experimental treatments",
                    "default": False
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_clinical_trials",
        description="Get clinical trials for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "status": {
                    "type": "string",
                    "description": "Trial status filter",
                    "enum": ["recruiting", "active", "completed", "terminated", None]
                }
            },
            "required": ["disease_id"]
        }
    )
]