# src/mychem_mcp/tools/annotation.py
"""Chemical annotation tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyChemClient


class AnnotationApi:
    """Tools for retrieving chemical annotations."""
    
    async def get_chemical_by_id(
        self,
        client: MyChemClient,
        chemical_id: str,
        fields: Optional[str] = None,
        dotfield: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Get detailed information about a chemical by ID."""
        params = {}
        if fields:
            params["fields"] = fields
        if not dotfield:
            params["dotfield"] = "false"
        
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        return {
            "success": True,
            "chemical": result
        }


ANNOTATION_TOOLS = [
    types.Tool(
        name="get_chemical_by_id",
        description="Get detailed information about a chemical by ID (InChIKey, ChEMBL ID, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical ID (InChIKey like 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N' or ChEMBL like 'CHEMBL25')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return (default: all)"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation in response",
                    "default": True
                }
            },
            "required": ["chemical_id"]
        }
    )
]