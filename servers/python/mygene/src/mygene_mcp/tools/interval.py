# src/mygene_mcp/tools/interval.py
"""Genomic interval query tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyGeneClient


class IntervalApi:
    """Tool for querying genes by genomic interval."""
    
    async def query_genes_by_interval(
        self,
        client: MyGeneClient,
        chr: str,
        start: int,
        end: int,
        species: Optional[str] = "human",
        fields: Optional[str] = "symbol,name,taxid,entrezgene",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Query genes by genomic interval (chromosome position)."""
        # Fix: Check if chr already has prefix
        if chr.startswith("chr"):
            q = f"{chr}:{start}-{end}"
        else:
            q = f"chr{chr}:{start}-{end}"
        
        params = {
            "q": q,
            "species": species,
            "fields": fields,
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "interval": {
                "chr": chr,
                "start": start,
                "end": end,
                "species": species
            },
            "total": result.get("total", 0),
            "hits": result.get("hits", [])
        }


INTERVAL_TOOLS = [
    types.Tool(
        name="query_genes_by_interval",
        description="Find genes in a genomic region by chromosome position",
        input_schema={
            "type": "object",
            "properties": {
                "chr": {
                    "type": "string",
                    "description": "Chromosome (e.g., '1', 'X', 'chr1')"
                },
                "start": {
                    "type": "integer",
                    "description": "Start position"
                },
                "end": {
                    "type": "integer",
                    "description": "End position"
                },
                "species": {
                    "type": "string",
                    "description": "Species for the query",
                    "default": "human"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "symbol,name,taxid,entrezgene"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results to return",
                    "default": 10
                }
            },
            "required": ["chr", "start", "end"]
        }
    )
]