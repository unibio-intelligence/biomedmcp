# src/mychem_mcp/tools/batch.py
"""Batch operation tools."""

from typing import Any, Dict, List, Optional
import mcp.types as types
from ..client import MyChemClient, MyChemError

MAX_BATCH_SIZE = 1000


class BatchApi:
    """Tools for batch operations on chemicals."""
    
    async def batch_query_chemicals(
        self,
        client: MyChemClient,
        chemical_ids: List[str],
        scopes: Optional[str] = "inchikey,chembl.molecule_chembl_id,drugbank.id,pubchem.cid",
        fields: Optional[str] = "inchikey,pubchem,chembl,drugbank,name",
        dotfield: Optional[bool] = True,
        returnall: Optional[bool] = True
    ) -> Dict[str, Any]:
        """Query multiple chemicals in a single request."""
        if len(chemical_ids) > MAX_BATCH_SIZE:
            raise MyChemError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {
            "q": chemical_ids,
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
    
    async def batch_get_chemicals(
        self,
        client: MyChemClient,
        chemical_ids: List[str],
        fields: Optional[str] = None,
        dotfield: Optional[bool] = True,
        email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get annotations for multiple chemicals in a single request."""
        if len(chemical_ids) > MAX_BATCH_SIZE:
            raise MyChemError(f"Batch size exceeds maximum of {MAX_BATCH_SIZE}")
        
        post_data = {"ids": chemical_ids}
        if fields:
            post_data["fields"] = fields
        if not dotfield:
            post_data["dotfield"] = False
        if email:
            post_data["email"] = email
        
        results = await client.post("chem", post_data)
        
        return {
            "success": True,
            "total": len(results),
            "chemicals": results
        }


BATCH_TOOLS = [
    types.Tool(
        name="batch_query_chemicals",
        description="Query multiple chemicals in a single request (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of chemical IDs to query"
                },
                "scopes": {
                    "type": "string",
                    "description": "Comma-separated fields to search",
                    "default": "inchikey,chembl.molecule_chembl_id,drugbank.id,pubchem.cid"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "inchikey,pubchem,chembl,drugbank,name"
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
            "required": ["chemical_ids"]
        }
    ),
    types.Tool(
        name="batch_get_chemicals",
        description="Get full annotations for multiple chemicals (up to 1000)",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of chemical IDs"
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
            "required": ["chemical_ids"]
        }
    )
]