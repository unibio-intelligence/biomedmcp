"""Variant-disease association tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class VariantApi:
    """Tools for variant-disease associations."""
    
    async def get_diseases_by_variant(
        self,
        client: MyDiseaseClient,
        variant_id: str,
        include_pathogenicity: bool = True,
        size: int = 20
    ) -> Dict[str, Any]:
        """Get diseases associated with a genetic variant."""
        # Build query for variant
        # Variant ID could be rsID, HGVS notation, etc.
        query_parts = []
        
        if variant_id.startswith("rs"):
            # dbSNP rsID
            query_parts.append(f'clinvar.variant.rsid:"{variant_id}"')
            query_parts.append(f'gwas_catalog.rsid:"{variant_id}"')
        else:
            # HGVS or other notation
            query_parts.append(f'clinvar.variant.hgvs:"{variant_id}"')
            query_parts.append(f'pathogenic_variants.hgvs:"{variant_id}"')
        
        q = " OR ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "_id,name,clinvar.variant,pathogenic_variants,gwas_catalog",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Process results
        diseases = []
        for hit in result.get("hits", []):
            disease_info = {
                "disease_id": hit.get("_id"),
                "disease_name": hit.get("name"),
                "variant_associations": []
            }
            
            # Extract ClinVar variants
            if "clinvar" in hit and "variant" in hit["clinvar"]:
                variants = hit["clinvar"]["variant"]
                variants = variants if isinstance(variants, list) else [variants]
                for var in variants:
                    if (var.get("rsid") == variant_id or 
                        var.get("hgvs") == variant_id):
                        disease_info["variant_associations"].append({
                            "source": "clinvar",
                            "variant_id": var.get("rsid") or var.get("hgvs"),
                            "clinical_significance": var.get("clinical_significance"),
                            "review_status": var.get("review_status")
                        })
            
            # Extract pathogenic variants
            if "pathogenic_variants" in hit:
                variants = hit["pathogenic_variants"]
                variants = variants if isinstance(variants, list) else [variants]
                for var in variants:
                    if var.get("hgvs") == variant_id:
                        disease_info["variant_associations"].append({
                            "source": "pathogenic_db",
                            "variant_id": var.get("hgvs"),
                            "pathogenicity": "pathogenic"
                        })
            
            # Extract GWAS catalog
            if "gwas_catalog" in hit and hit["gwas_catalog"].get("rsid") == variant_id:
                disease_info["variant_associations"].append({
                    "source": "gwas",
                    "variant_id": variant_id,
                    "p_value": hit["gwas_catalog"].get("p_value"),
                    "trait": hit["gwas_catalog"].get("trait")
                })
            
            if disease_info["variant_associations"]:
                diseases.append(disease_info)
        
        return {
            "success": True,
            "variant_id": variant_id,
            "total_diseases": len(diseases),
            "diseases": diseases
        }
    
    async def get_disease_variants(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        pathogenicity_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get all variants associated with a disease."""
        params = {
            "fields": "clinvar.variant,pathogenic_variants,gwas_catalog"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        variants = {
            "disease_id": disease_id,
            "clinvar_variants": [],
            "pathogenic_variants": [],
            "gwas_variants": []
        }
        
        # Extract ClinVar variants
        if "clinvar" in result and "variant" in result["clinvar"]:
            clinvar = result["clinvar"]["variant"]
            clinvar = clinvar if isinstance(clinvar, list) else [clinvar]
            
            for var in clinvar:
                if pathogenicity_filter is None or \
                   var.get("clinical_significance", "").lower() == pathogenicity_filter.lower():
                    variants["clinvar_variants"].append({
                        "rsid": var.get("rsid"),
                        "hgvs": var.get("hgvs"),
                        "gene": var.get("gene"),
                        "clinical_significance": var.get("clinical_significance"),
                        "review_status": var.get("review_status"),
                        "last_evaluated": var.get("last_evaluated")
                    })
        
        # Extract pathogenic variants
        if "pathogenic_variants" in result:
            path_vars = result["pathogenic_variants"]
            path_vars = path_vars if isinstance(path_vars, list) else [path_vars]
            variants["pathogenic_variants"] = path_vars
        
        # Extract GWAS variants
        if "gwas_catalog" in result:
            gwas = result["gwas_catalog"]
            gwas = gwas if isinstance(gwas, list) else [gwas]
            variants["gwas_variants"] = gwas
        
        return {
            "success": True,
            "variants": variants
        }
    
    async def get_variant_pathogenicity(
        self,
        client: MyDiseaseClient,
        variant_id: str
    ) -> Dict[str, Any]:
        """Get pathogenicity information for a variant across diseases."""
        # Search for the variant
        if variant_id.startswith("rs"):
            q = f'clinvar.variant.rsid:"{variant_id}"'
        else:
            q = f'clinvar.variant.hgvs:"{variant_id}" OR pathogenic_variants.hgvs:"{variant_id}"'
        
        params = {
            "q": q,
            "fields": "_id,name,clinvar.variant",
            "size": 100
        }
        
        result = await client.get("query", params=params)
        
        pathogenicity_data = {
            "variant_id": variant_id,
            "pathogenicity_summary": {},
            "disease_associations": []
        }
        
        # Collect pathogenicity across diseases
        pathogenicity_counts = {}
        
        for hit in result.get("hits", []):
            if "clinvar" in hit and "variant" in hit["clinvar"]:
                variants = hit["clinvar"]["variant"]
                variants = variants if isinstance(variants, list) else [variants]
                
                for var in variants:
                    if var.get("rsid") == variant_id or var.get("hgvs") == variant_id:
                        sig = var.get("clinical_significance", "Unknown")
                        pathogenicity_counts[sig] = pathogenicity_counts.get(sig, 0) + 1
                        
                        pathogenicity_data["disease_associations"].append({
                            "disease_id": hit.get("_id"),
                            "disease_name": hit.get("name"),
                            "clinical_significance": sig,
                            "review_status": var.get("review_status")
                        })
        
        pathogenicity_data["pathogenicity_summary"] = pathogenicity_counts
        
        return {
            "success": True,
            "pathogenicity": pathogenicity_data
        }
    
    async def search_by_variant_type(
        self,
        client: MyDiseaseClient,
        variant_type: str,
        gene_symbol: Optional[str] = None,
        size: int = 20
    ) -> Dict[str, Any]:
        """Search diseases by variant type (e.g., 'missense', 'deletion')."""
        query_parts = [f'clinvar.variant.variant_type:"{variant_type}"']
        
        if gene_symbol:
            query_parts.append(f'clinvar.variant.gene:"{gene_symbol}"')
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "_id,name,clinvar.variant",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Process results
        diseases = []
        for hit in result.get("hits", []):
            variant_count = 0
            example_variants = []
            
            if "clinvar" in hit and "variant" in hit["clinvar"]:
                variants = hit["clinvar"]["variant"]
                variants = variants if isinstance(variants, list) else [variants]
                
                for var in variants:
                    if var.get("variant_type") == variant_type:
                        if not gene_symbol or var.get("gene") == gene_symbol:
                            variant_count += 1
                            if len(example_variants) < 3:
                                example_variants.append({
                                    "rsid": var.get("rsid"),
                                    "gene": var.get("gene"),
                                    "hgvs": var.get("hgvs")
                                })
            
            if variant_count > 0:
                diseases.append({
                    "disease_id": hit.get("_id"),
                    "disease_name": hit.get("name"),
                    "variant_count": variant_count,
                    "example_variants": example_variants
                })
        
        return {
            "success": True,
            "variant_type": variant_type,
            "gene_filter": gene_symbol,
            "total_diseases": len(diseases),
            "diseases": diseases
        }


VARIANT_TOOLS = [
    types.Tool(
        name="get_diseases_by_variant",
        description="Find diseases associated with a genetic variant (rsID or HGVS)",
        input_schema={
            "type": "object",
            "properties": {
                "variant_id": {
                    "type": "string",
                    "description": "Variant ID (e.g., 'rs104894090', 'NM_000352.4:c.1187G>A')"
                },
                "include_pathogenicity": {
                    "type": "boolean",
                    "description": "Include pathogenicity information",
                    "default": True
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["variant_id"]
        }
    ),
    types.Tool(
        name="get_disease_variants",
        description="Get all variants associated with a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "pathogenicity_filter": {
                    "type": "string",
                    "description": "Filter by pathogenicity",
                    "enum": ["pathogenic", "likely_pathogenic", "benign", "likely_benign", "uncertain_significance"]
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_variant_pathogenicity",
        description="Get pathogenicity information for a variant across diseases",
        input_schema={
            "type": "object",
            "properties": {
                "variant_id": {
                    "type": "string",
                    "description": "Variant ID (rsID or HGVS)"
                }
            },
            "required": ["variant_id"]
        }
    ),
    types.Tool(
        name="search_by_variant_type",
        description="Search diseases by variant type",
        input_schema={
            "type": "object",
            "properties": {
                "variant_type": {
                    "type": "string",
                    "description": "Type of variant",
                    "enum": ["missense", "nonsense", "deletion", "insertion", "duplication", "frameshift"]
                },
                "gene_symbol": {
                    "type": "string",
                    "description": "Filter by gene symbol"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["variant_type"]
        }
    )
]