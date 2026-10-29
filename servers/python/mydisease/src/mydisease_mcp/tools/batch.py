"""Batch operation tools."""

from typing import Any, Dict, List, Optional
import mcp.types as types
from ..client import MyDiseaseClient, MyDiseaseError

MAX_BATCH_SIZE = 1000


class BatchApi:
    """Tools for batch operations on diseases."""
    
    async def batch_query_diseases(
        self,
        client: MyDiseaseClient,
        disease_ids: List[str],
        scopes: Optional[str] = "_id,mondo.mondo,orphanet.id,omim,umls.cui",
        fields: Optional[str] = "_id,name,mondo,orphanet,omim,inheritance",
        dotfield: Optional[bool] = True,
        returnall: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Query multiple diseases in a single request."""
        if len(disease_ids) > MAX_BATCH_SIZE:
            raise MyDiseaseError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {
            "q": disease_ids,
            "scopes": scopes,
            "fields": fields
        }
        if not dotfield:
            post_data["dotfield"] = False
        if returnall is not None:
            post_data["returnall"] = returnall
        
        results = await client.post("query", post_data)
        
        # Process results
        found = []
        missing = []
        for result in results:
            if result.get("notfound") is not True:
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
    
    async def batch_get_diseases(
        self,
        client: MyDiseaseClient,
        disease_ids: List[str],
        fields: Optional[str] = None,
        dotfield: Optional[bool] = True,
        email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get annotations for multiple diseases in a single request."""
        if len(disease_ids) > MAX_BATCH_SIZE:
            raise MyDiseaseError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {"ids": disease_ids}
        if fields:
            post_data["fields"] = fields
        if not dotfield:
            post_data["dotfield"] = False
        if email:
            post_data["email"] = email
        
        results = await client.post("disease", post_data)
        
        return {
            "success": True,
            "total": len(results),
            "diseases": results
        }


BATCH_TOOLS = [
    types.Tool(
        name="batch_query_diseases",
        description="Query multiple diseases in a single request (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "disease_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of disease IDs to query"
                },
                "scopes": {
                    "type": "string",
                    "description": "Comma-separated fields to search",
                    "default": "_id,mondo.mondo,orphanet.id,omim,umls.cui"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "_id,name,mondo,orphanet,omim,inheritance"
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
            "required": ["disease_ids"]
        }
    ),
    types.Tool(
        name="batch_get_diseases",
        description="Get full annotations for multiple diseases (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "disease_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of disease IDs"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return"
                },
                "dotfield": {
                    "type": "boolean",
                    "description": "Control dotfield notation",
                    "default": True
                },
                "email": {
                    "type": "string",
                    "description": "Email for large requests"
                }
            },
            "required": ["disease_ids"]
        }
    )
]