# src/mychem_mcp/tools/patent.py
"""Patent-related tools."""

from typing import Any, Dict, Optional
import mcp.types as types
from ..client import MyChemClient


class PatentApi:
    """Tools for patent data."""
    
    async def get_patent_data(
        self,
        client: MyChemClient,
        chemical_id: str
    ) -> Dict[str, Any]:
        """Get patent information for a chemical."""
        params = {"fields": "pharmgkb.patent,drugbank.patents,chembl.patent"}
        
        result = await client.get(f"chem/{chemical_id}", params=params)
        
        patents = {
            "chemical_id": chemical_id,
            "patents": []
        }
        
        # Extract patents from different sources
        if "pharmgkb" in result and "patent" in result["pharmgkb"]:
            pharmgkb_patents = result["pharmgkb"]["patent"]
            if not isinstance(pharmgkb_patents, list):
                pharmgkb_patents = [pharmgkb_patents]
            for patent in pharmgkb_patents:
                patents["patents"].append({
                    "patent_number": patent,
                    "source": "pharmgkb"
                })
        
        if "drugbank" in result and "patents" in result["drugbank"]:
            drugbank_patents = result["drugbank"]["patents"]
            if not isinstance(drugbank_patents, list):
                drugbank_patents = [drugbank_patents]
            for patent in drugbank_patents:
                patents["patents"].append({
                    "patent_number": patent.get("number"),
                    "country": patent.get("country"),
                    "approved": patent.get("approved"),
                    "expires": patent.get("expires"),
                    "source": "drugbank"
                })
        
        return {
            "success": True,
            "total_patents": len(patents["patents"]),
            "patent_data": patents
        }
    
    async def search_patents_by_chemical(
        self,
        client: MyChemClient,
        chemical_name: str,
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search for chemicals mentioned in patents."""
        params = {
            "q": f'_exists_:pharmgkb.patent OR _exists_:drugbank.patents OR _exists_:chembl.patent AND name:"{chemical_name}"',
            "fields": "inchikey,name,pharmgkb.patent,drugbank.patents,chembl.patent",
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "query": chemical_name,
            "total": result.get("total", 0),
            "hits": result.get("hits", [])
        }


PATENT_TOOLS = [
    types.Tool(
        name="get_patent_data",
        description="Get patent information for a chemical",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical identifier"
                }
            },
            "required": ["chemical_id"]
        }
    ),
    types.Tool(
        name="search_patents_by_chemical",
        description="Search for chemicals mentioned in patents",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_name": {
                    "type": "string",
                    "description": "Chemical name to search for"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            },
            "required": ["chemical_name"]
        }
    )
]