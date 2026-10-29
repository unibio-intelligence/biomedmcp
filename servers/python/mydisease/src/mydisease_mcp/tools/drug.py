"""Drug and treatment tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class DrugApi:
    """Tools for drug and treatment information."""
    
    async def get_disease_drugs(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        approved_only: bool = True
    ) -> Dict[str, Any]:
        """Get drugs used to treat a disease."""
        params = {
            "fields": "drug,drug_treatment,ctd.drug_therapy"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        drugs = {
            "disease_id": disease_id,
            "approved_drugs": [],
            "experimental_drugs": [],
            "drug_classes": set()
        }
        
        # Extract drug information
        if "drug" in result:
            drug_data = result["drug"]
            drug_data = drug_data if isinstance(drug_data, list) else [drug_data]
            
            for drug in drug_data:
                drug_info = {
                    "name": drug.get("name"),
                    "drugbank_id": drug.get("drugbank_id"),
                    "status": drug.get("status", "unknown"),
                    "mechanism": drug.get("mechanism"),
                    "drug_class": drug.get("drug_class")
                }
                
                if drug.get("drug_class"):
                    drugs["drug_classes"].add(drug["drug_class"])
                
                if approved_only and drug.get("status") == "approved":
                    drugs["approved_drugs"].append(drug_info)
                elif not approved_only:
                    if drug.get("status") == "approved":
                        drugs["approved_drugs"].append(drug_info)
                    else:
                        drugs["experimental_drugs"].append(drug_info)
        
        # Extract drug treatment data
        if "drug_treatment" in result:
            treatments = result["drug_treatment"]
            treatments = treatments if isinstance(treatments, list) else [treatments]
            
            for treatment in treatments:
                if approved_only and treatment.get("approved"):
                    drugs["approved_drugs"].append(treatment)
                elif not approved_only:
                    if treatment.get("approved"):
                        drugs["approved_drugs"].append(treatment)
                    else:
                        drugs["experimental_drugs"].append(treatment)
        
        # Extract CTD drug therapy
        if "ctd" in result and "drug_therapy" in result["ctd"]:
            ctd_drugs = result["ctd"]["drug_therapy"]
            ctd_drugs = ctd_drugs if isinstance(ctd_drugs, list) else [ctd_drugs]
            
            for drug in ctd_drugs:
                drug_info = {
                    "name": drug.get("drug_name"),
                    "cas_number": drug.get("cas_number"),
                    "therapy_type": drug.get("therapy_type"),
                    "evidence": drug.get("evidence")
                }
                drugs["experimental_drugs"].append(drug_info)
        
        drugs["drug_classes"] = list(drugs["drug_classes"])
        
        return {
            "success": True,
            "drugs": drugs,
            "approved_only": approved_only
        }
    
    async def search_drugs_by_indication(
        self,
        client: MyDiseaseClient,
        indication: str,
        drug_status: Optional[str] = "approved",
        size: int = 20
    ) -> Dict[str, Any]:
        """Search for drugs by disease indication."""
        query_parts = [f'drug.indication:"{indication}" OR drug_treatment.indication:"{indication}"']
        
        if drug_status:
            query_parts.append(f'drug.status:"{drug_status}"')
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "_id,name,drug,drug_treatment",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Process results
        drugs_by_disease = []
        
        for hit in result.get("hits", []):
            disease_drugs = {
                "disease_id": hit.get("_id"),
                "disease_name": hit.get("name"),
                "drugs": []
            }
            
            # Extract matching drugs
            if "drug" in hit:
                drugs = hit["drug"]
                drugs = drugs if isinstance(drugs, list) else [drugs]
                
                for drug in drugs:
                    if indication.lower() in drug.get("indication", "").lower():
                        if drug_status is None or drug.get("status") == drug_status:
                            disease_drugs["drugs"].append({
                                "name": drug.get("name"),
                                "status": drug.get("status"),
                                "indication": drug.get("indication")
                            })
            
            if disease_drugs["drugs"]:
                drugs_by_disease.append(disease_drugs)
        
        return {
            "success": True,
            "indication_query": indication,
            "drug_status_filter": drug_status,
            "total_diseases": len(drugs_by_disease),
            "results": drugs_by_disease
        }
    
    async def get_drug_targets(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get drug targets for a disease."""
        params = {
            "fields": "drug.targets,drug_treatment.targets,gene,causal_gene"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        targets = {
            "disease_id": disease_id,
            "drug_targets": [],
            "disease_genes": [],
            "potential_targets": []
        }
        
        # Extract drug targets
        if "drug" in result:
            drugs = result["drug"]
            drugs = drugs if isinstance(drugs, list) else [drugs]
            
            for drug in drugs:
                if "targets" in drug:
                    drug_targets = drug["targets"]
                    drug_targets = drug_targets if isinstance(drug_targets, list) else [drug_targets]
                    
                    for target in drug_targets:
                        targets["drug_targets"].append({
                            "drug_name": drug.get("name"),
                            "target_name": target.get("name"),
                            "target_gene": target.get("gene_symbol"),
                            "action": target.get("action")
                        })
        
        # Extract disease genes as potential targets
        if "gene" in result:
            genes = result["gene"]
            genes = genes if isinstance(genes, list) else [genes]
            targets["disease_genes"] = [g.get("symbol") for g in genes if g.get("symbol")]
        
        if "causal_gene" in result:
            causal = result["causal_gene"]
            causal = causal if isinstance(causal, list) else [causal]
            
            for gene in causal:
                if gene.get("symbol") not in targets["disease_genes"]:
                    targets["potential_targets"].append({
                        "gene_symbol": gene.get("symbol"),
                        "gene_name": gene.get("name"),
                        "target_type": "causal_gene"
                    })
        
        return {
            "success": True,
            "targets": targets
        }
    
    async def get_pharmacogenomics(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get pharmacogenomics information for disease treatments."""
        params = {
            "fields": "pharmgkb,drug.pharmacogenomics,clinvar.variant"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        pgx_data = {
            "disease_id": disease_id,
            "pgx_variants": [],
            "drug_gene_interactions": [],
            "dosing_guidelines": []
        }
        
        # Extract PharmGKB data
        if "pharmgkb" in result:
            pgkb = result["pharmgkb"]
            
            if "variants" in pgkb:
                variants = pgkb["variants"]
                variants = variants if isinstance(variants, list) else [variants]
                pgx_data["pgx_variants"] = variants
            
            if "drug_labels" in pgkb:
                labels = pgkb["drug_labels"]
                labels = labels if isinstance(labels, list) else [labels]
                pgx_data["dosing_guidelines"] = labels
        
        # Extract drug pharmacogenomics
        if "drug" in result:
            drugs = result["drug"]
            drugs = drugs if isinstance(drugs, list) else [drugs]
            
            for drug in drugs:
                if "pharmacogenomics" in drug:
                    pgx = drug["pharmacogenomics"]
                    pgx_data["drug_gene_interactions"].append({
                        "drug": drug.get("name"),
                        "gene": pgx.get("gene"),
                        "variant": pgx.get("variant"),
                        "effect": pgx.get("effect"),
                        "recommendation": pgx.get("recommendation")
                    })
        
        # Extract relevant ClinVar variants
        if "clinvar" in result and "variant" in result["clinvar"]:
            variants = result["clinvar"]["variant"]
            variants = variants if isinstance(variants, list) else [variants]
            
            for var in variants:
                if "pharmacogenomic" in var.get("clinical_significance", "").lower():
                    pgx_data["pgx_variants"].append({
                        "rsid": var.get("rsid"),
                        "gene": var.get("gene"),
                        "significance": var.get("clinical_significance")
                    })
        
        return {
            "success": True,
            "pharmacogenomics": pgx_data
        }


DRUG_TOOLS = [
    types.Tool(
        name="get_disease_drugs",
        description="Get drugs used to treat a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "approved_only": {
                    "type": "boolean",
                    "description": "Only show approved drugs",
                    "default": True
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="search_drugs_by_indication",
        description="Search for drugs by disease indication",
        input_schema={
            "type": "object",
            "properties": {
                "indication": {
                    "type": "string",
                    "description": "Disease indication"
                },
                "drug_status": {
                    "type": "string",
                    "description": "Drug approval status",
                    "enum": ["approved", "experimental", "investigational", None]
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
        name="get_drug_targets",
        description="Get drug targets for a disease",
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
        name="get_pharmacogenomics",
        description="Get pharmacogenomics information for disease treatments",
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
    )
]