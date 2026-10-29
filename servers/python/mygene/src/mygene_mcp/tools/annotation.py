# src/mygene_mcp/tools/annotation.py
"""Gene annotation tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyGeneClient


class AnnotationApi:
    """Tool for retrieving gene annotations from MyGene.info API."""
    
    async def get_gene_annotation(
        self,
        client: MyGeneClient,
        gene_id: str,
        fields: Optional[str] = None,
        species: Optional[str] = None,
        dotfield: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Get detailed annotation for a specific gene by ID."""
        params = {}
        if fields:
            params["fields"] = fields
        if species:
            params["species"] = species
        if not dotfield:
            params["dotfield"] = "false"
        
        result = await client.get(f"gene/{gene_id}", params=params)
        
        return {
            "success": True,
            "gene": result
        }


ANNOTATION_TOOLS = [
    types.Tool(
        name="get_gene_annotation",
        description="Get detailed annotation for a specific gene by ID (Entrez or Ensembl)",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez like '1017' or Ensembl like 'ENSG00000123374')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return (default: all)"
                },
                "species": {
                    "type": "string",
                    "description": "Species filter"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation in response",
                    "default": True
                }
            },
            "required": ["gene_id"]
        }
    )
]