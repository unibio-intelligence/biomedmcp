# src/mychem_mcp/tools/metadata.py
"""Metadata and utility tools."""

from typing import Any, Dict
import mcp.types as types
from ..client import MyChemClient


class MetadataApi:
    """Tools for retrieving MyChemInfo metadata."""
    
    async def get_mychem_metadata(self, client: MyChemClient) -> Dict[str, Any]:
        """Get metadata about the MyChemInfo API service."""
        result = await client.get("metadata")
        
        return {
            "success": True,
            "metadata": result
        }
    
    async def get_available_fields(self, client: MyChemClient) -> Dict[str, Any]:
        """Get a list of all available fields in MyChemInfo."""
        result = await client.get("metadata/fields")
        
        return {
            "success": True,
            "fields": result
        }
    
    async def get_database_statistics(self, client: MyChemClient) -> Dict[str, Any]:
        """Get statistics about the database."""
        metadata = await client.get("metadata")
        
        stats = {
            "total_chemicals": metadata.get("stats", {}).get("total", 0),
            "last_updated": metadata.get("build_date"),
            "version": metadata.get("build_version"),
            "sources": {}
        }
        
        # Extract source statistics
        if "src" in metadata:
            for source, info in metadata["src"].items():
                stats["sources"][source] = {
                    "version": info.get("version"),
                    "total": info.get("stats", {}).get("total", 0)
                }
        
        return {
            "success": True,
            "statistics": stats
        }


METADATA_TOOLS = [
    types.Tool(
        name="get_mychem_metadata",
        description="Get metadata about MyChemInfo API including data sources and statistics",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    types.Tool(
        name="get_available_fields",
        description="Get a list of all available fields in MyChemInfo",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    types.Tool(
        name="get_database_statistics",
        description="Get statistics about the chemical database",
        input_schema={
            "type": "object",
            "properties": {}
        }
    )
]