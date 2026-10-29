# src/mygene_mcp/tools/expression.py
"""Gene expression tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class ExpressionApi:
    """Tools for gene expression data queries."""
    
    async def query_genes_by_expression(
        self,
        client: MyGeneClient,
        tissue: Optional[str] = None,
        cell_type: Optional[str] = None,
        expression_level: Optional[str] = None,
        dataset: Optional[str] = None,
        species: Optional[str] = "human",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Query genes by expression patterns."""
        # Build expression query
        query_parts = []
        
        if tissue:
            # Check multiple expression sources
            tissue_query = f'(hpa.tissue."{tissue}" OR gtex.tissue."{tissue}" OR biogps.tissue."{tissue}")'
            query_parts.append(tissue_query)
        
        if cell_type:
            query_parts.append(f'hpa.subcellular_location:"{cell_type}"')
        
        if expression_level:
            # Expression level queries (high, medium, low)
            if dataset:
                query_parts.append(f'{dataset}.expression_level:"{expression_level}"')
            else:
                query_parts.append(f'expression_level:"{expression_level}"')
        
        if dataset and not expression_level and not tissue:
            # Query for genes with any data from this dataset
            query_parts.append(f'_exists_:{dataset}')
        
        if not query_parts:
            query_parts.append("_exists_:hpa OR _exists_:gtex OR _exists_:biogps")
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,hpa,gtex,biogps",
            "species": species,
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "query": q,
            "total": result.get("total", 0),
            "hits": result.get("hits", [])
        }
    
    async def get_gene_expression_profile(
        self,
        client: MyGeneClient,
        gene_id: str,
        datasets: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get expression profile across tissues/cell types."""
        if datasets:
            fields = ",".join(datasets)
        else:
            fields = "hpa,gtex,biogps,exac"
        
        fields += ",symbol,name,entrezgene"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        # Process expression data
        expression_profile = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "expression_data": {}
        }
        
        # Extract HPA data
        if "hpa" in result:
            hpa_data = result["hpa"]
            expression_profile["expression_data"]["hpa"] = {
                "tissues": hpa_data.get("tissue", []),
                "subcellular_location": hpa_data.get("subcellular_location", []),
                "rna_tissue_specificity": hpa_data.get("rna_tissue_specificity", {})
            }
        
        # Extract GTEx data
        if "gtex" in result:
            expression_profile["expression_data"]["gtex"] = result["gtex"]
        
        # Extract BioGPS data
        if "biogps" in result:
            expression_profile["expression_data"]["biogps"] = result["biogps"]
        
        # Extract ExAC expression data
        if "exac" in result and "expression" in result["exac"]:
            expression_profile["expression_data"]["exac"] = result["exac"]["expression"]
        
        return {
            "success": True,
            "expression_profile": expression_profile
        }


EXPRESSION_TOOLS = [
    types.Tool(
        name="query_genes_by_expression",
        description="Find genes based on expression patterns in tissues or cell types",
        input_schema={
            "type": "object",
            "properties": {
                "tissue": {
                    "type": "string",
                    "description": "Tissue type (e.g., 'brain', 'liver', 'heart')"
                },
                "cell_type": {
                    "type": "string",
                    "description": "Cell type or subcellular location"
                },
                "expression_level": {
                    "type": "string",
                    "description": "Expression level: 'high', 'medium', 'low', 'not detected'",
                    "enum": ["high", "medium", "low", "not detected"]
                },
                "dataset": {
                    "type": "string",
                    "description": "Dataset source: 'hpa', 'gtex', 'biogps'",
                    "enum": ["hpa", "gtex", "biogps"]
                },
                "species": {
                    "type": "string",
                    "description": "Species filter",
                    "default": "human"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            }
        }
    ),
    types.Tool(
        name="get_gene_expression_profile",
        description="Get comprehensive expression profile for a gene across tissues and datasets",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "datasets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific datasets to include (default: all)"
                }
            },
            "required": ["gene_id"]
        }
    )
]