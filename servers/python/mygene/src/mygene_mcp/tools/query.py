# src/mygene_mcp/tools/query.py
"""Gene query tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class QueryApi:
    """Tool for querying genes from MyGene.info API."""
    
    async def query_genes(
        self,
        client: MyGeneClient,
        q: str,
        fields: Optional[str] = "symbol,name,taxid,entrezgene",
        species: Optional[str] = None,
        size: Optional[int] = 10,
        from_: Optional[int] = None,
        sort: Optional[str] = None,
        facets: Optional[str] = None,
        facet_size: Optional[int] = 10,
        fetch_all: Optional[bool] = False,
        scroll_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for genes using the MyGene.info query API."""
        params = {"q": q}
        if fields:
            params["fields"] = fields
        if species:
            params["species"] = species
        if size is not None:
            params["size"] = size
        if from_ is not None:
            params["from"] = from_
        if sort:
            params["sort"] = sort
        if facets:
            params["facets"] = facets
            params["facet_size"] = facet_size
        if fetch_all:
            params["fetch_all"] = "true"
        if scroll_id:
            params["scroll_id"] = scroll_id
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "total": result.get("total", 0),
            "took": result.get("took", 0),
            "hits": result.get("hits", []),
            "scroll_id": result.get("_scroll_id"),
            "facets": result.get("facets", {})
        }
    
    async def search_by_field(
        self,
        client: MyGeneClient,
        field_queries: Dict[str, str],
        operator: str = "AND",
        fields: Optional[str] = "symbol,name,taxid,entrezgene",
        species: Optional[str] = None,
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search by specific fields with boolean operators."""
        # Build query string
        query_parts = []
        for field, value in field_queries.items():
            # Handle special characters in values
            if " " in value and not (value.startswith('"') and value.endswith('"')):
                value = f'"{value}"'
            query_parts.append(f"{field}:{value}")
        
        q = f" {operator} ".join(query_parts)
        
        return await self.query_genes(
            client=client,
            q=q,
            fields=fields,
            species=species,
            size=size
        )
    
    async def get_field_statistics(
        self,
        client: MyGeneClient,
        field: str,
        size: int = 100,
        species: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics for a specific field."""
        params = {
            "q": "*",
            "facets": field,
            "facet_size": size,
            "size": 0
        }
        if species:
            params["species"] = species
        
        result = await client.get("query", params=params)
        
        facet_data = result.get("facets", {}).get(field, {})
        terms = facet_data.get("terms", [])
        
        return {
            "success": True,
            "field": field,
            "total_unique_values": facet_data.get("total", 0),
            "top_values": [
                {
                    "value": term["term"],
                    "count": term["count"],
                    "percentage": round(term["count"] / result.get("total", 1) * 100, 2)
                }
                for term in terms
            ],
            "total_genes": result.get("total", 0)
        }


QUERY_TOOLS = [
    types.Tool(
        name="query_genes",
        description="Search for genes using various query types (symbol, name, wildcards, fielded queries, boolean operators)",
        input_schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Query string (e.g., 'CDK2', 'cyclin*', 'go.MF:kinase AND taxid:9606')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "symbol,name,taxid,entrezgene"
                },
                "species": {
                    "type": "string",
                    "description": "Species filter (e.g., 'human', 'mouse', or taxonomy ID)"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results to return (max 1000)",
                    "default": 10
                },
                "from_": {
                    "type": "integer",
                    "description": "Starting result offset for pagination"
                },
                "sort": {
                    "type": "string",
                    "description": "Sort order for results"
                },
                "facets": {
                    "type": "string",
                    "description": "Facet fields for aggregation"
                },
                "facet_size": {
                    "type": "integer",
                    "description": "Number of facet results",
                    "default": 10
                },
                "fetch_all": {
                    "type": "boolean",
                    "description": "Fetch all results (returns scroll_id)",
                    "default": False
                },
                "scroll_id": {
                    "type": "string",
                    "description": "Scroll ID for fetching next batch"
                }
            },
            "required": ["q"]
        }
    ),
    types.Tool(
        name="search_by_field",
        description="Search genes by specific field values with boolean logic",
        input_schema={
            "type": "object",
            "properties": {
                "field_queries": {
                    "type": "object",
                    "description": "Field-value pairs (e.g., {'interpro': 'IPR000001', 'pfam': 'PF00001'})"
                },
                "operator": {
                    "type": "string",
                    "description": "Boolean operator: AND or OR",
                    "default": "AND",
                    "enum": ["AND", "OR"]
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "symbol,name,taxid,entrezgene"
                },
                "species": {
                    "type": "string",
                    "description": "Species filter"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            },
            "required": ["field_queries"]
        }
    ),
    types.Tool(
        name="get_field_statistics",
        description="Get statistics and top values for a specific field",
        input_schema={
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "Field to analyze (e.g., 'type_of_gene', 'taxid', 'go.CC')"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of top values to return",
                    "default": 100
                },
                "species": {
                    "type": "string",
                    "description": "Species filter"
                }
            },
            "required": ["field"]
        }
    )
]