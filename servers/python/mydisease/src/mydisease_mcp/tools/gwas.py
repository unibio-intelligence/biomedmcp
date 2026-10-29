"""GWAS (Genome-Wide Association Studies) tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class GWASApi:
    """Tools for GWAS data."""
    
    async def get_gwas_associations(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        p_value_threshold: Optional[float] = 5e-8
    ) -> Dict[str, Any]:
        """Get GWAS associations for a disease."""
        params = {
            "fields": "gwas_catalog,gwas"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        gwas_data = {
            "disease_id": disease_id,
            "associations": [],
            "top_variants": [],
            "associated_traits": []
        }
        
        # Extract GWAS catalog data
        if "gwas_catalog" in result:
            gwas = result["gwas_catalog"]
            gwas = gwas if isinstance(gwas, list) else [gwas]
            
            traits = set()
            
            for assoc in gwas:
                p_val = assoc.get("p_value")
                
                # Apply p-value filter if specified
                if p_value_threshold is None or (p_val and float(p_val) <= p_value_threshold):
                    association = {
                        "rsid": assoc.get("rsid"),
                        "p_value": p_val,
                        "risk_allele": assoc.get("risk_allele"),
                        "risk_allele_frequency": assoc.get("risk_allele_frequency"),
                        "odds_ratio": assoc.get("odds_ratio"),
                        "beta": assoc.get("beta"),
                        "trait": assoc.get("trait"),
                        "study": assoc.get("study"),
                        "pubmed_id": assoc.get("pubmed_id"),
                        "sample_size": assoc.get("sample_size"),
                        "ancestry": assoc.get("ancestry")
                    }
                    
                    gwas_data["associations"].append(association)
                    
                    if assoc.get("trait"):
                        traits.add(assoc.get("trait"))
            
            # Sort by p-value to get top variants
            gwas_data["associations"].sort(key=lambda x: float(x.get("p_value", 1)))
            gwas_data["top_variants"] = gwas_data["associations"][:10]
            gwas_data["associated_traits"] = list(traits)
        
        # Extract general GWAS data
        if "gwas" in result:
            general_gwas = result["gwas"]
            general_gwas = general_gwas if isinstance(general_gwas, list) else [general_gwas]
            gwas_data["associations"].extend(general_gwas)
        
        return {
            "success": True,
            "gwas_data": gwas_data,
            "p_value_threshold": p_value_threshold
        }
    
    async def search_gwas_by_trait(
        self,
        client: MyDiseaseClient,
        trait: str,
        min_sample_size: Optional[int] = None,
        ancestry: Optional[str] = None,
        size: int = 20
    ) -> Dict[str, Any]:
        """Search GWAS studies by trait."""
        query_parts = [f'gwas_catalog.trait:"{trait}"']
        
        if ancestry:
            query_parts.append(f'gwas_catalog.ancestry:"{ancestry}"')
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "_id,name,gwas_catalog",
            "size": 100  # Get more to filter by sample size
        }
        
        result = await client.get("query", params=params)
        
        # Process and filter results
        studies = []
        
        for hit in result.get("hits", []):
            if "gwas_catalog" in hit:
                gwas = hit["gwas_catalog"]
                gwas = gwas if isinstance(gwas, list) else [gwas]
                
                for study in gwas:
                    if study.get("trait") and trait.lower() in study["trait"].lower():
                        sample_size = study.get("sample_size")
                        
                        # Apply sample size filter
                        if min_sample_size is None or (sample_size and int(sample_size) >= min_sample_size):
                            studies.append({
                                "disease_id": hit.get("_id"),
                                "disease_name": hit.get("name"),
                                "trait": study.get("trait"),
                                "rsid": study.get("rsid"),
                                "p_value": study.get("p_value"),
                                "odds_ratio": study.get("odds_ratio"),
                                "sample_size": sample_size,
                                "ancestry": study.get("ancestry"),
                                "pubmed_id": study.get("pubmed_id")
                            })
        
        # Sort by p-value
        studies.sort(key=lambda x: float(x.get("p_value", 1)))
        
        return {
            "success": True,
            "trait_query": trait,
            "filters": {
                "min_sample_size": min_sample_size,
                "ancestry": ancestry
            },
            "total_studies": len(studies),
            "studies": studies[:size]
        }
    
    async def get_gwas_variants(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        gene_symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get GWAS variants for a disease, optionally filtered by gene."""
        params = {
            "fields": "gwas_catalog,gene"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        variants = {
            "disease_id": disease_id,
            "variants_by_gene": {},
            "all_variants": []
        }
        
        # Get gene list if needed for filtering
        gene_list = []
        if gene_symbol and "gene" in result:
            genes = result["gene"]
            genes = genes if isinstance(genes, list) else [genes]
            gene_list = [g.get("symbol") for g in genes if g.get("symbol")]
        
        # Extract GWAS variants
        if "gwas_catalog" in result:
            gwas = result["gwas_catalog"]
            gwas = gwas if isinstance(gwas, list) else [gwas]
            
            for var in gwas:
                variant_info = {
                    "rsid": var.get("rsid"),
                    "position": var.get("position"),
                    "chromosome": var.get("chromosome"),
                    "p_value": var.get("p_value"),
                    "mapped_gene": var.get("mapped_gene"),
                    "effect_size": var.get("odds_ratio") or var.get("beta")
                }
                
                # Filter by gene if specified
                if gene_symbol:
                    if var.get("mapped_gene") == gene_symbol:
                        variants["all_variants"].append(variant_info)
                else:
                    variants["all_variants"].append(variant_info)
                
                # Group by gene
                mapped_gene = var.get("mapped_gene", "intergenic")
                if mapped_gene not in variants["variants_by_gene"]:
                    variants["variants_by_gene"][mapped_gene] = []
                variants["variants_by_gene"][mapped_gene].append(variant_info)
        
        return {
            "success": True,
            "variants": variants,
            "gene_filter": gene_symbol
        }
    
    async def get_gwas_statistics(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get statistical summary of GWAS findings for a disease."""
        params = {
            "fields": "gwas_catalog"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        statistics = {
            "disease_id": disease_id,
            "total_associations": 0,
            "significant_associations": 0,
            "unique_variants": set(),
            "ancestry_distribution": {},
            "year_distribution": {},
            "top_genes": {},
            "median_odds_ratio": None,
            "strongest_association": None
        }
        
        if "gwas_catalog" in result:
            gwas = result["gwas_catalog"]
            gwas = gwas if isinstance(gwas, list) else [gwas]
            
            odds_ratios = []
            p_values = []
            
            for assoc in gwas:
                statistics["total_associations"] += 1
                
                # Count significant associations
                p_val = assoc.get("p_value")
                if p_val and float(p_val) < 5e-8:
                    statistics["significant_associations"] += 1
                
                # Track unique variants
                if assoc.get("rsid"):
                    statistics["unique_variants"].add(assoc["rsid"])
                
                # Ancestry distribution
                ancestry = assoc.get("ancestry", "Unknown")
                statistics["ancestry_distribution"][ancestry] = \
                    statistics["ancestry_distribution"].get(ancestry, 0) + 1
                
                # Year distribution (from study info)
                year = assoc.get("year")
                if year:
                    statistics["year_distribution"][year] = \
                        statistics["year_distribution"].get(year, 0) + 1
                
                # Gene distribution
                gene = assoc.get("mapped_gene")
                if gene:
                    statistics["top_genes"][gene] = \
                        statistics["top_genes"].get(gene, 0) + 1
                
                # Collect odds ratios
                if assoc.get("odds_ratio"):
                    odds_ratios.append(float(assoc["odds_ratio"]))
                
                # Track p-values for strongest association
                if p_val:
                    p_values.append((float(p_val), assoc))
            
            # Calculate statistics
            statistics["unique_variants"] = len(statistics["unique_variants"])
            
            if odds_ratios:
                odds_ratios.sort()
                statistics["median_odds_ratio"] = odds_ratios[len(odds_ratios)//2]
            
            if p_values:
                p_values.sort(key=lambda x: x[0])
                statistics["strongest_association"] = p_values[0][1]
            
            # Get top genes
            top_genes_list = sorted(
                statistics["top_genes"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            statistics["top_genes"] = dict(top_genes_list)
        
        return {
            "success": True,
            "statistics": statistics
        }


GWAS_TOOLS = [
    types.Tool(
        name="get_gwas_associations",
        description="Get GWAS associations for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "p_value_threshold": {
                    "type": "number",
                    "description": "P-value threshold for significance",
                    "default": 5e-8
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="search_gwas_by_trait",
        description="Search GWAS studies by trait name",
        input_schema={
            "type": "object",
            "properties": {
                "trait": {
                    "type": "string",
                    "description": "Trait name to search for"
                },
                "min_sample_size": {
                    "type": "integer",
                    "description": "Minimum sample size"
                },
                "ancestry": {
                    "type": "string",
                    "description": "Ancestry group (e.g., 'European', 'Asian')"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["trait"]
        }
    ),
    types.Tool(
        name="get_gwas_variants",
        description="Get GWAS variants for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "gene_symbol": {
                    "type": "string",
                    "description": "Filter by gene symbol"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_gwas_statistics",
        description="Get statistical summary of GWAS findings",
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