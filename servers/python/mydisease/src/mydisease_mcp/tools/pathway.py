"""Pathway and biological process tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class PathwayApi:
    """Tools for pathway analysis."""
    
    async def get_disease_pathways(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get pathways associated with a disease."""
        params = {
            "fields": "pathway,kegg_pathway,reactome_pathway,wikipathways"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        pathways = {
            "disease_id": disease_id,
            "all_pathways": [],
            "pathways_by_source": {}
        }
        
        # Extract general pathway data
        if "pathway" in result:
            pathway_data = result["pathway"]
            pathway_data = pathway_data if isinstance(pathway_data, list) else [pathway_data]
            
            for pathway in pathway_data:
                if source is None or pathway.get("source") == source:
                    pathways["all_pathways"].append(pathway)
                    
                    src = pathway.get("source", "unknown")
                    if src not in pathways["pathways_by_source"]:
                        pathways["pathways_by_source"][src] = []
                    pathways["pathways_by_source"][src].append(pathway)
        
        # Extract KEGG pathways
        if "kegg_pathway" in result and (source is None or source == "kegg"):
            kegg = result["kegg_pathway"]
            kegg = kegg if isinstance(kegg, list) else [kegg]
            
            pathways["pathways_by_source"]["kegg"] = kegg
            pathways["all_pathways"].extend([
                {**p, "source": "kegg"} for p in kegg
            ])
        
        # Extract Reactome pathways
        if "reactome_pathway" in result and (source is None or source == "reactome"):
            reactome = result["reactome_pathway"]
            reactome = reactome if isinstance(reactome, list) else [reactome]
            
            pathways["pathways_by_source"]["reactome"] = reactome
            pathways["all_pathways"].extend([
                {**p, "source": "reactome"} for p in reactome
            ])
        
        # Extract WikiPathways
        if "wikipathways" in result and (source is None or source == "wikipathways"):
            wiki = result["wikipathways"]
            wiki = wiki if isinstance(wiki, list) else [wiki]
            
            pathways["pathways_by_source"]["wikipathways"] = wiki
            pathways["all_pathways"].extend([
                {**p, "source": "wikipathways"} for p in wiki
            ])
        
        return {
            "success": True,
            "pathways": pathways,
            "filter_source": source
        }
    
    async def search_diseases_by_pathway(
        self,
        client: MyDiseaseClient,
        pathway_id: str,
        pathway_name: Optional[str] = None,
        size: int = 20
    ) -> Dict[str, Any]:
        """Search diseases associated with a specific pathway."""
        query_parts = []
        
        # Build query based on pathway ID or name
        if pathway_id.startswith("hsa"):  # KEGG pathway
            query_parts.append(f'kegg_pathway.id:"{pathway_id}"')
        elif pathway_id.startswith("R-"):  # Reactome
            query_parts.append(f'reactome_pathway.id:"{pathway_id}"')
        elif pathway_id.startswith("WP"):  # WikiPathways
            query_parts.append(f'wikipathways.id:"{pathway_id}"')
        else:
            # Generic pathway search
            query_parts.append(f'pathway.id:"{pathway_id}"')
        
        if pathway_name:
            query_parts.append(f'pathway.name:"{pathway_name}"')
            query_parts.append(f'kegg_pathway.name:"{pathway_name}"')
            query_parts.append(f'reactome_pathway.name:"{pathway_name}"')
        
        q = " OR ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "_id,name,pathway,kegg_pathway,reactome_pathway",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        # Process results
        diseases = []
        for hit in result.get("hits", []):
            disease_info = {
                "disease_id": hit.get("_id"),
                "disease_name": hit.get("name"),
                "pathway_associations": []
            }
            
            # Check all pathway fields
            for field in ["pathway", "kegg_pathway", "reactome_pathway"]:
                if field in hit:
                    pathways = hit[field]
                    pathways = pathways if isinstance(pathways, list) else [pathways]
                    
                    for pathway in pathways:
                        if (pathway.get("id") == pathway_id or 
                            (pathway_name and pathway_name.lower() in pathway.get("name", "").lower())):
                            disease_info["pathway_associations"].append({
                                "source": field.replace("_pathway", ""),
                                "pathway_id": pathway.get("id"),
                                "pathway_name": pathway.get("name")
                            })
            
            if disease_info["pathway_associations"]:
                diseases.append(disease_info)
        
        return {
            "success": True,
            "pathway_query": {
                "id": pathway_id,
                "name": pathway_name
            },
            "total_diseases": len(diseases),
            "diseases": diseases
        }
    
    async def get_pathway_genes(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get genes involved in disease pathways."""
        params = {
            "fields": "gene,pathway,kegg_pathway.genes,reactome_pathway.genes"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        pathway_genes = {
            "disease_id": disease_id,
            "disease_genes": [],
            "pathway_specific_genes": {},
            "all_pathway_genes": set()
        }
        
        # Get disease genes
        if "gene" in result:
            genes = result["gene"]
            genes = genes if isinstance(genes, list) else [genes]
            pathway_genes["disease_genes"] = [g.get("symbol") for g in genes if g.get("symbol")]
        
        # Extract genes from pathways
        if "kegg_pathway" in result:
            kegg = result["kegg_pathway"]
            kegg = kegg if isinstance(kegg, list) else [kegg]
            
            for pathway in kegg:
                if "genes" in pathway:
                    pathway_id = pathway.get("id")
                    genes = pathway["genes"]
                    genes = genes if isinstance(genes, list) else [genes]
                    
                    pathway_genes["pathway_specific_genes"][pathway_id] = genes
                    pathway_genes["all_pathway_genes"].update(genes)
        
        if "reactome_pathway" in result:
            reactome = result["reactome_pathway"]
            reactome = reactome if isinstance(reactome, list) else [reactome]
            
            for pathway in reactome:
                if "genes" in pathway:
                    pathway_id = pathway.get("id")
                    genes = pathway["genes"]
                    genes = genes if isinstance(genes, list) else [genes]
                    
                    pathway_genes["pathway_specific_genes"][pathway_id] = genes
                    pathway_genes["all_pathway_genes"].update(genes)
        
        # Convert set to list
        pathway_genes["all_pathway_genes"] = list(pathway_genes["all_pathway_genes"])
        
        # Find overlap between disease genes and pathway genes
        disease_gene_set = set(pathway_genes["disease_genes"])
        pathway_gene_set = set(pathway_genes["all_pathway_genes"])
        pathway_genes["overlapping_genes"] = list(disease_gene_set & pathway_gene_set)
        
        return {
            "success": True,
            "pathway_genes": pathway_genes
        }
    
    async def get_pathway_enrichment(
        self,
        client: MyDiseaseClient,
        gene_list: List[str],
        p_value_cutoff: float = 0.05,
        size: int = 20
    ) -> Dict[str, Any]:
        """Find diseases with pathways enriched for given gene list."""
        # Search for diseases associated with these genes
        gene_queries = [f'gene.symbol:"{gene}"' for gene in gene_list]
        q = " OR ".join(gene_queries)
        
        params = {
            "q": q,
            "fields": "_id,name,gene,pathway,kegg_pathway",
            "size": 100
        }
        
        result = await client.get("query", params=params)
        
        # Analyze pathway enrichment
        pathway_counts = {}
        disease_pathways = {}
        
        for hit in result.get("hits", []):
            disease_id = hit.get("_id")
            
            # Count genes per disease
            if "gene" in hit:
                genes = hit["gene"]
                genes = genes if isinstance(genes, list) else [genes]
                gene_symbols = {g.get("symbol") for g in genes if g.get("symbol")}
                
                overlap = len(set(gene_list) & gene_symbols)
                
                if overlap > 0:
                    # Extract pathways
                    pathways = []
                    
                    if "pathway" in hit:
                        pw = hit["pathway"]
                        pw = pw if isinstance(pw, list) else [pw]
                        pathways.extend(pw)
                    
                    if "kegg_pathway" in hit:
                        kegg = hit["kegg_pathway"]
                        kegg = kegg if isinstance(kegg, list) else [kegg]
                        pathways.extend(kegg)
                    
                    for pathway in pathways:
                        pathway_id = pathway.get("id") or pathway.get("name")
                        if pathway_id:
                            if pathway_id not in pathway_counts:
                                pathway_counts[pathway_id] = {
                                    "count": 0,
                                    "diseases": [],
                                    "pathway_name": pathway.get("name")
                                }
                            
                            pathway_counts[pathway_id]["count"] += overlap
                            pathway_counts[pathway_id]["diseases"].append({
                                "disease_id": disease_id,
                                "disease_name": hit.get("name"),
                                "gene_overlap": overlap
                            })
        
        # Calculate enrichment scores (simplified)
        enriched_pathways = []
        total_genes = len(gene_list)
        
        for pathway_id, data in pathway_counts.items():
            # Simple enrichment score based on gene overlap
            enrichment_score = data["count"] / total_genes
            
            if enrichment_score >= p_value_cutoff:
                enriched_pathways.append({
                    "pathway_id": pathway_id,
                    "pathway_name": data["pathway_name"],
                    "enrichment_score": round(enrichment_score, 3),
                    "gene_count": data["count"],
                    "disease_count": len(data["diseases"]),
                    "diseases": data["diseases"][:5]  # Top 5 diseases
                })
        
        # Sort by enrichment score
        enriched_pathways.sort(key=lambda x: x["enrichment_score"], reverse=True)
        
        return {
            "success": True,
            "query_genes": gene_list,
            "total_genes": total_genes,
            "p_value_cutoff": p_value_cutoff,
            "enriched_pathways": enriched_pathways[:size]
        }


PATHWAY_TOOLS = [
    types.Tool(
        name="get_disease_pathways",
        description="Get biological pathways associated with a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "source": {
                    "type": "string",
                    "description": "Pathway database source",
                    "enum": ["kegg", "reactome", "wikipathways", None]
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="search_diseases_by_pathway",
        description="Find diseases associated with a specific pathway",
        input_schema={
            "type": "object",
            "properties": {
                "pathway_id": {
                    "type": "string",
                    "description": "Pathway ID (e.g., 'hsa04110', 'R-HSA-109582')"
                },
                "pathway_name": {
                    "type": "string",
                    "description": "Pathway name to search"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["pathway_id"]
        }
    ),
    types.Tool(
        name="get_pathway_genes",
        description="Get genes involved in disease pathways",
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
        name="get_pathway_enrichment",
        description="Find pathways enriched for a gene list",
        input_schema={
            "type": "object",
            "properties": {
                "gene_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene symbols"
                },
                "p_value_cutoff": {
                    "type": "number",
                    "description": "Significance cutoff",
                    "default": 0.05
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 20
                }
            },
            "required": ["gene_list"]
        }
    )
]