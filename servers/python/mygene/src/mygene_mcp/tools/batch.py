# src/mygene_mcp/tools/batch.py
"""Batch operation tools."""

from typing import Any, Dict, List, Optional
import mcp.types as types
from ..client import MyGeneClient, MyGeneError

MAX_BATCH_SIZE = 1000


class BatchApi:
    """Tools for batch operations on genes."""
    
    async def query_genes_batch(
        self,
        client: MyGeneClient,
        gene_ids: List[str],
        scopes: Optional[str] = "entrezgene,ensemblgene,symbol",
        fields: Optional[str] = "symbol,name,taxid,entrezgene",
        species: Optional[str] = None,
        dotfield: Optional[bool] = True,
        returnall: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Query multiple genes in a single request."""
        if len(gene_ids) > MAX_BATCH_SIZE:
            raise MyGeneError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {
            "ids": gene_ids,
            "scopes": scopes,
            "fields": fields
        }
        if species:
            post_data["species"] = species
        if not dotfield:
            post_data["dotfield"] = False
        # Fix: Always include returnall when it's explicitly set
        if returnall is not None:
            post_data["returnall"] = returnall
        
        results = await client.post("query", post_data)
        
        # Process results
        found = []
        missing = []
        for result in results:
            if result.get("found", False):
                found.append(result)
            else:
                missing.append(result.get("query", "Unknown"))
        
        return {
            "success": True,
            "total": len(results),
            "found": len(found),
            "missing": len(missing),
            "results": results,
            "missing_ids": missing
        }
    
    async def get_genes_batch(
        self,
        client: MyGeneClient,
        gene_ids: List[str],
        fields: Optional[str] = None,
        species: Optional[str] = None,
        dotfield: Optional[bool] = True,
        filter_: Optional[str] = None,
        email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get annotations for multiple genes in a single request."""
        if len(gene_ids) > MAX_BATCH_SIZE:
            raise MyGeneError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {"ids": gene_ids}
        if fields:
            post_data["fields"] = fields
        if species:
            post_data["species"] = species
        if not dotfield:
            post_data["dotfield"] = False
        if filter_:
            post_data["filter"] = filter_
        if email:
            post_data["email"] = email
        
        results = await client.post("gene", post_data)
        
        return {
            "success": True,
            "total": len(results),
            "genes": results
        }


BATCH_TOOLS = [
    types.Tool(
        name="query_genes_batch",
        description="Query multiple genes in a single request (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "gene_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene IDs or symbols to query"
                },
                "scopes": {
                    "type": "string",
                    "description": "Comma-separated fields to search",
                    "default": "entrezgene,ensemblgene,symbol"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "symbol,name,taxid,entrezgene"
                },
                "species": {
                    "type": "string",
                    "description": "Species filter"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation",
                    "default": True
                },
                "returnall": {
                    "type": "boolean",
                    "description": "Return all results including no matches",
                    "default": True
                }
            },
            "required": ["gene_ids"]
        }
    ),
    types.Tool(
        name="get_genes_batch",
        description="Get full annotations for multiple genes (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "gene_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene IDs"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return"
                },
                "species": {
                    "type": "string",
                    "description": "Species filter"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation",
                    "default": True
                },
                "filter_": {
                    "type": "string",
                    "description": "Filter expression"
                },
                "email": {
                    "type": "string",
                    "description": "Email for large requests"
                }
            },
            "required": ["gene_ids"]
        }
    )
]