"""Disease annotation tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyDiseaseClient


class AnnotationApi:
    """Tools for retrieving disease annotations."""
    
    async def get_disease_by_id(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        fields: Optional[str] = None,
        dotfield: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Get detailed information about a disease by ID."""
        params = {}
        if fields:
            params["fields"] = fields
        if not dotfield:
            params["dotfield"] = "false"
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        return {
            "success": True,
            "disease": result
        }


ANNOTATION_TOOLS = [
    types.Tool(
        name="get_disease_by_id",
        description="Get comprehensive disease information by ID (OMIM, Orphanet, MONDO, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID (e.g., 'OMIM:104300', 'ORPHANET:15', 'MONDO:0007739')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return (default: all)"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation",
                    "default": True
                }
            },
            "required": ["disease_id"]
        }
    )
]