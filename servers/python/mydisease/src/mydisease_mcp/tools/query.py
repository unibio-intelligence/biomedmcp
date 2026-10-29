"""Disease query tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class QueryApi:
    """Tools for querying diseases."""
    
    async def search_disease(
        self,
        client: MyDiseaseClient,
        q: str,
        fields: Optional[str] = "_id,name,mondo,orphanet,omim,umls.cui,disgenet",
        size: Optional[int] = 10,
        from_: Optional[int] = None,
        sort: Optional[str] = None,
        facets: Optional[str] = None,
        facet_size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search for diseases using various query types."""
        params = {"q": q}
        if fields:
            params["fields"] = fields
        if size is not None:
            params["size"] = size
        if from_ is not None:
            params["from"] = from_
        if sort:
            params["sort"] = sort
        if facets:
            params["facets"] = facets
            params["facet_size"] = facet_size
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "total": result.get("total", 0),
            "took": result.get("took", 0),
            "hits": result.get("hits", []),
            "facets": result.get("facets", {})
        }
    
    async def search_by_field(
        self,
        client: MyDiseaseClient,
        field_queries: Dict[str, str],
        operator: str = "AND",
        fields: Optional[str] = "_id,name,mondo,orphanet,omim",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search by specific fields with boolean operators."""
        query_parts = []
        for field, value in field_queries.items():
            if " " in value and not (value.startswith('"') and value.endswith('"')):
                value = f'"{value}"'
            query_parts.append(f"{field}:{value}")
        
        q = f" {operator} ".join(query_parts)
        
        return await self.search_disease(
            client=client,
            q=q,
            fields=fields,
            size=size
        )
    
    async def get_field_statistics(
        self,
        client: MyDiseaseClient,
        field: str,
        size: int = 100
    ) -> Dict[str, Any]:
        """Get statistics for a specific field."""
        params = {
            "q": "*",
            "facets": field,
            "facet_size": size,
            "size": 0
        }
        
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
            "total_diseases": result.get("total", 0)
        }
    
    async def search_by_phenotype(
        self,
        client: MyDiseaseClient,
        phenotypes: List[str],
        match_all: bool = False,
        fields: Optional[str] = "_id,name,hpo,phenotype_related_to_disease",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search diseases by phenotype/symptom terms."""
        # Build query for phenotypes
        phenotype_queries = []
        for phenotype in phenotypes:
            phenotype_queries.append(f'hpo.phenotype_name:"{phenotype}" OR phenotype_related_to_disease.hpo_phenotype:"{phenotype}"')
        
        operator = " AND " if match_all else " OR "
        q = operator.join([f"({pq})" for pq in phenotype_queries])
        
        return await self.search_disease(
            client=client,
            q=q,
            fields=fields,
            size=size
        )
    
    async def build_complex_query(
        self,
        client: MyDiseaseClient,
        criteria: List[Dict[str, Any]],
        logic: str = "AND",
        fields: Optional[str] = "_id,name,mondo,orphanet,omim,disgenet",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Build complex queries with multiple criteria."""
        query_parts = []
        
        for criterion in criteria:
            criterion_type = criterion.get("type")
            
            if criterion_type == "field":
                field = criterion["field"]
                value = criterion["value"]
                if " " in str(value) and not (str(value).startswith('"') and str(value).endswith('"')):
                    value = f'"{value}"'
                query_parts.append(f"{field}:{value}")
            
            elif criterion_type == "range":
                field = criterion["field"]
                min_val = criterion.get("min", "*")
                max_val = criterion.get("max", "*")
                query_parts.append(f"{field}:[{min_val} TO {max_val}]")
            
            elif criterion_type == "exists":
                field = criterion["field"]
                query_parts.append(f"_exists_:{field}")
            
            elif criterion_type == "text":
                value = criterion["value"]
                query_parts.append(value)
            
            else:
                raise ValueError(f"Unknown criterion type: {criterion_type}")
        
        q = f" {logic} ".join(query_parts)
        
        return await self.search_disease(
            client=client,
            q=q,
            fields=fields,
            size=size
        )


QUERY_TOOLS = [
    types.Tool(
        name="search_disease",
        description="Search for diseases by name, ID, symptom, or any text",
        input_schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Query string (e.g., 'Alzheimer', 'OMIM:104300', 'memory loss')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "_id,name,mondo,orphanet,omim,umls.cui,disgenet"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results (max 1000)",
                    "default": 10
                },
                "from_": {
                    "type": "integer",
                    "description": "Starting offset for pagination"
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
                }
            },
            "required": ["q"]
        }
    ),
    types.Tool(
        name="search_by_field",
        description="Search diseases by specific field values",
        input_schema={
            "type": "object",
            "properties": {
                "field_queries": {
                    "type": "object",
                    "description": "Field-value pairs (e.g., {'mondo.id': 'MONDO:0007739'})"
                },
                "operator": {
                    "type": "string",
                    "description": "Boolean operator",
                    "default": "AND",
                    "enum": ["AND", "OR"]
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "_id,name,mondo,orphanet,omim"
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
        description="Get statistics and top values for a field",
        input_schema={
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "Field to analyze (e.g., 'inheritance.inheritance_type', 'prevalence.source')"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of top values",
                    "default": 100
                }
            },
            "required": ["field"]
        }
    ),
    types.Tool(
        name="search_by_phenotype",
        description="Search diseases by phenotype/symptom terms",
        input_schema={
            "type": "object",
            "properties": {
                "phenotypes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of phenotype/symptom terms"
                },
                "match_all": {
                    "type": "boolean",
                    "description": "Require all phenotypes to match",
                    "default": False
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "_id,name,hpo,phenotype_related_to_disease"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            },
            "required": ["phenotypes"]
        }
    ),
    types.Tool(
        name="build_complex_query",
        description="Build complex queries with multiple criteria",
        input_schema={
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "array",
                    "description": "List of query criteria",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["field", "range", "exists", "text"],
                                "description": "Criterion type"
                            },
                            "field": {
                                "type": "string",
                                "description": "Field name"
                            },
                            "value": {
                                "type": "string",
                                "description": "Value"
                            },
                            "min": {
                                "type": "number",
                                "description": "Minimum value"
                            },
                            "max": {
                                "type": "number",
                                "description": "Maximum value"
                            }
                        }
                    }
                },
                "logic": {
                    "type": "string",
                    "description": "Logic operator",
                    "default": "AND",
                    "enum": ["AND", "OR"]
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "_id,name,mondo,orphanet,omim,disgenet"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            },
            "required": ["criteria"]
        }
    )
]