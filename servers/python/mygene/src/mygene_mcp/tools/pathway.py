# src/mygene_mcp/tools/pathway.py
"""Pathway analysis tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class PathwayApi:
    """Tools for pathway-related queries."""
    
    async def query_genes_by_pathway(
        self,
        client: MyGeneClient,
        pathway_id: Optional[str] = None,
        pathway_name: Optional[str] = None,
        source: Optional[str] = None,
        species: Optional[str] = "human",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Find genes in specific pathways."""
        query_parts = []
        
        if pathway_id:
            if source:
                query_parts.append(f'pathway.{source}.id:"{pathway_id}"')
            else:
                # Search across all pathway sources
                query_parts.append(
                    f'(pathway.kegg.id:"{pathway_id}" OR '
                    f'pathway.reactome.id:"{pathway_id}" OR '
                    f'pathway.wikipathways.id:"{pathway_id}")'
                )
        
        if pathway_name:
            if source:
                query_parts.append(f'pathway.{source}.name:"{pathway_name}"')
            else:
                # Search across all pathway names
                query_parts.append(
                    f'(pathway.kegg.name:"{pathway_name}" OR '
                    f'pathway.reactome.name:"{pathway_name}" OR '
                    f'pathway.wikipathways.name:"{pathway_name}" OR '
                    f'pathway.netpath.name:"{pathway_name}" OR '
                    f'pathway.biocarta.name:"{pathway_name}")'
                )
        
        if not query_parts:
            # Get all genes with pathway data
            query_parts.append("_exists_:pathway")
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,entrezgene,pathway",
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
    
    async def get_gene_pathways(
        self,
        client: MyGeneClient,
        gene_id: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get all pathways for a gene."""
        fields = "symbol,name,entrezgene,pathway"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        pathways = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "pathways": {}
        }
        
        if "pathway" in result:
            pathway_data = result["pathway"]
            
            # Process each pathway source
            for source in ["kegg", "reactome", "wikipathways", "netpath", "biocarta", "pid"]:
                if source in pathway_data:
                    if sources and source not in sources:
                        continue
                    
                    source_pathways = pathway_data[source]
                    if isinstance(source_pathways, list):
                        pathways["pathways"][source] = source_pathways
                    else:
                        pathways["pathways"][source] = [source_pathways]
        
        # Count total pathways
        total_pathways = sum(len(p) for p in pathways["pathways"].values())
        
        return {
            "success": True,
            "total_pathways": total_pathways,
            "pathway_sources": list(pathways["pathways"].keys()),
            "pathways": pathways
        }


PATHWAY_TOOLS = [
    types.Tool(
        name="query_genes_by_pathway",
        description="Find genes involved in specific biological pathways",
        input_schema={
            "type": "object",
            "properties": {
                "pathway_id": {
                    "type": "string",
                    "description": "Pathway ID (e.g., 'hsa04110' for KEGG cell cycle)"
                },
                "pathway_name": {
                    "type": "string",
                    "description": "Pathway name (e.g., 'Cell cycle', 'Apoptosis')"
                },
                "source": {
                    "type": "string",
                    "description": "Pathway database source",
                    "enum": ["kegg", "reactome", "wikipathways", "netpath", "biocarta", "pid"]
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
        name="get_gene_pathways",
        description="Get all pathways associated with a specific gene",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by specific pathway sources"
                }
            },
            "required": ["gene_id"]
        }
    )
]