# src/mygene_mcp/tools/variant.py
"""Genetic variant tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class VariantApi:
    """Tools for genetic variant queries."""
    
    async def get_gene_variants(
        self,
        client: MyGeneClient,
        gene_id: str,
        variant_type: Optional[str] = None,
        clinical_significance: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get variants from ClinVar and other sources."""
        fields = "symbol,name,entrezgene,clinvar,snpeff,grasp"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        variants_data = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "variant_sources": {}
        }
        
        # Process ClinVar variants
        if "clinvar" in result:
            clinvar = result["clinvar"]
            clinvar_variants = []
            
            if "rcv" in clinvar:
                rcv_list = clinvar["rcv"]
                if not isinstance(rcv_list, list):
                    rcv_list = [rcv_list]
                
                for rcv in rcv_list:
                    # Filter by clinical significance if specified
                    if clinical_significance:
                        rcv_sig = rcv.get("clinical_significance", "").lower()
                        if clinical_significance.lower() not in rcv_sig:
                            continue
                    
                    variant_info = {
                        "accession": rcv.get("accession", {}).get("accession"),
                        "title": rcv.get("title"),
                        "clinical_significance": rcv.get("clinical_significance"),
                        "last_evaluated": rcv.get("last_evaluated"),
                        "review_status": rcv.get("review_status"),
                        "conditions": rcv.get("conditions", {})
                    }
                    
                    # Add variant details
                    if "measure_set" in rcv:
                        measure_set = rcv["measure_set"]
                        if "measure" in measure_set:
                            measures = measure_set["measure"]
                            if not isinstance(measures, list):
                                measures = [measures]
                            
                            for measure in measures:
                                if variant_type and measure.get("type") != variant_type:
                                    continue
                                
                                variant_info["variant_type"] = measure.get("type")
                                variant_info["name"] = measure.get("name")
                    
                    clinvar_variants.append(variant_info)
            
            variants_data["variant_sources"]["clinvar"] = {
                "total": len(clinvar_variants),
                "variants": clinvar_variants
            }
        
        # Process SNPeff data if available
        if "snpeff" in result:
            snpeff = result["snpeff"]
            snpeff_variants = []
            
            if "ann" in snpeff:
                annotations = snpeff["ann"]
                if not isinstance(annotations, list):
                    annotations = [annotations]
                
                for ann in annotations:
                    snpeff_variants.append({
                        "effect": ann.get("effect"),
                        "putative_impact": ann.get("putative_impact"),
                        "gene_name": ann.get("gene_name"),
                        "feature_type": ann.get("feature_type")
                    })
            
            variants_data["variant_sources"]["snpeff"] = {
                "total": len(snpeff_variants),
                "annotations": snpeff_variants
            }
        
        # Process GRASP data if available
        if "grasp" in result:
            grasp = result["grasp"]
            grasp_variants = []
            
            if "publication" in grasp:
                publications = grasp["publication"]
                if not isinstance(publications, list):
                    publications = [publications]
                
                for pub in publications:
                    grasp_variants.append({
                        "phenotype": pub.get("phenotype"),
                        "snp_id": pub.get("snp_id"),
                        "p_value": pub.get("p_value"),
                        "pmid": pub.get("pmid")
                    })
            
            variants_data["variant_sources"]["grasp"] = {
                "total": len(grasp_variants),
                "associations": grasp_variants
            }
        
        # Count total variants
        total_variants = sum(
            source_data.get("total", 0) 
            for source_data in variants_data["variant_sources"].values()
        )
        
        return {
            "success": True,
            "total_variants": total_variants,
            "variants": variants_data
        }


VARIANT_TOOLS = [
    types.Tool(
        name="get_gene_variants",
        description="Get genetic variants associated with a gene from ClinVar and other sources",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "variant_type": {
                    "type": "string",
                    "description": "Type of variant",
                    "enum": ["Deletion", "Duplication", "Insertion", "Indel", "single nucleotide variant"]
                },
                "clinical_significance": {
                    "type": "string",
                    "description": "Clinical significance filter",
                    "enum": ["Pathogenic", "Likely pathogenic", "Uncertain significance", "Likely benign", "Benign"]
                }
            },
            "required": ["gene_id"]
        }
    )
]