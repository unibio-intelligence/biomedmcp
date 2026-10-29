# src/mychem_mcp/tools/query.py
"""Enhanced chemical query tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyChemClient


class QueryApi:
    """Enhanced tools for querying chemicals."""
    
    async def search_chemical(
        self,
        client: MyChemClient,
        q: str,
        fields: Optional[str] = "inchikey,pubchem,chembl,drugbank,name",
        size: Optional[int] = 10,
        from_: Optional[int] = None,
        sort: Optional[str] = None,
        facets: Optional[str] = None,
        facet_size: Optional[int] = 10,
        fetch_all: Optional[bool] = False,
        scroll_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search for chemicals using various query types."""
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
        client: MyChemClient,
        field_queries: Dict[str, str],
        operator: str = "AND",
        fields: Optional[str] = "inchikey,pubchem,chembl,drugbank,name",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search by specific fields with boolean operators."""
        query_parts = []
        for field, value in field_queries.items():
            if " " in value and not (value.startswith('"') and value.endswith('"')):
                value = f'"{value}"'
            query_parts.append(f"{field}:{value}")
        
        q = f" {operator} ".join(query_parts)
        
        return await self.search_chemical(
            client=client,
            q=q,
            fields=fields,
            size=size
        )
    
    async def get_field_statistics(
        self,
        client: MyChemClient,
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
            "total_chemicals": result.get("total", 0)
        }
    
    async def search_by_molecular_properties(
        self,
        client: MyChemClient,
        mw_min: Optional[float] = None,
        mw_max: Optional[float] = None,
        logp_min: Optional[float] = None,
        logp_max: Optional[float] = None,
        hbd_max: Optional[int] = None,
        hba_max: Optional[int] = None,
        tpsa_max: Optional[float] = None,
        rotatable_bonds_max: Optional[int] = None,
        fields: Optional[str] = "inchikey,pubchem,chembl,drugbank,name",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Search chemicals by molecular property ranges (Lipinski's Rule of Five, etc.)."""
        query_parts = []
        
        if mw_min is not None or mw_max is not None:
            mw_min_val = mw_min if mw_min is not None else "*"
            mw_max_val = mw_max if mw_max is not None else "*"
            query_parts.append(f"pubchem.molecular_weight:[{mw_min_val} TO {mw_max_val}]")
        
        if logp_min is not None or logp_max is not None:
            logp_min_val = logp_min if logp_min is not None else "*"
            logp_max_val = logp_max if logp_max is not None else "*"
            query_parts.append(f"pubchem.xlogp:[{logp_min_val} TO {logp_max_val}]")
        
        if hbd_max is not None:
            query_parts.append(f"pubchem.h_bond_donor_count:[* TO {hbd_max}]")
        
        if hba_max is not None:
            query_parts.append(f"pubchem.h_bond_acceptor_count:[* TO {hba_max}]")
        
        if tpsa_max is not None:
            query_parts.append(f"pubchem.tpsa:[* TO {tpsa_max}]")
        
        if rotatable_bonds_max is not None:
            query_parts.append(f"pubchem.rotatable_bond_count:[* TO {rotatable_bonds_max}]")
        
        if not query_parts:
            raise ValueError("At least one molecular property filter must be specified")
        
        q = " AND ".join(query_parts)
        
        return await self.search_chemical(
            client=client,
            q=q,
            fields=fields,
            size=size
        )
    
    async def build_complex_query(
        self,
        client: MyChemClient,
        criteria: List[Dict[str, Any]],
        logic: str = "AND",
        fields: Optional[str] = "inchikey,pubchem,chembl,drugbank,name",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Build complex queries with multiple criteria.
        
        Example criteria:
        [
            {"type": "field", "field": "drugbank.groups", "value": "approved"},
            {"type": "range", "field": "pubchem.molecular_weight", "min": 150, "max": 500},
            {"type": "exists", "field": "chembl.max_phase"},
            {"type": "text", "value": "inhibitor"}
        ]
        """
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
        
        return await self.search_chemical(
            client=client,
            q=q,
            fields=fields,
            size=size
        )


# Add new tools to QUERY_TOOLS
QUERY_TOOLS = [
    types.Tool(
        name="search_chemical",
        description="Search for chemicals using various query types (name, formula, InChI, SMILES, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Query string (e.g., 'aspirin', 'C9H8O4', 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N')"
                },
                "fields": {
                    "type": "string",
                    "description": "Comma-separated fields to return",
                    "default": "inchikey,pubchem,chembl,drugbank,name"
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
        description="Search chemicals by specific field values with boolean logic",
        input_schema={
            "type": "object",
            "properties": {
                "field_queries": {
                    "type": "object",
                    "description": "Field-value pairs (e.g., {'chembl.molecule_chembl_id': 'CHEMBL25'})"
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
                    "default": "inchikey,pubchem,chembl,drugbank,name"
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
                    "description": "Field to analyze (e.g., 'chembl.molecule_type', 'drugbank.groups')"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of top values to return",
                    "default": 100
                }
            },
            "required": ["field"]
        }
    ),
    types.Tool(
        name="search_by_molecular_properties",
        description="Search chemicals by molecular property ranges (MW, LogP, HBD, HBA, TPSA, etc.)",
        input_schema={
            "type": "object",
            "properties": {
                "mw_min": {
                    "type": "number",
                    "description": "Minimum molecular weight"
                },
                "mw_max": {
                    "type": "number",
                    "description": "Maximum molecular weight"
                },
                "logp_min": {
                    "type": "number",
                    "description": "Minimum LogP"
                },
                "logp_max": {
                    "type": "number",
                    "description": "Maximum LogP"
                },
                "hbd_max": {
                    "type": "integer",
                    "description": "Maximum hydrogen bond donors"
                },
                "hba_max": {
                    "type": "integer",
                    "description": "Maximum hydrogen bond acceptors"
                },
                "tpsa_max": {
                    "type": "number",
                    "description": "Maximum topological polar surface area"
                },
                "rotatable_bonds_max": {
                    "type": "integer",
                    "description": "Maximum rotatable bonds"
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "inchikey,pubchem,chembl,drugbank,name"
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results",
                    "default": 10
                }
            }
        }
    ),
    types.Tool(
        name="build_complex_query",
        description="Build complex queries with multiple criteria and logic",
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
                                "description": "Field name (for field, range, exists types)"
                            },
                            "value": {
                                "type": "string",
                                "description": "Value (for field and text types)"
                            },
                            "min": {
                                "type": "number",
                                "description": "Minimum value (for range type)"
                            },
                            "max": {
                                "type": "number",
                                "description": "Maximum value (for range type)"
                            }
                        }
                    }
                },
                "logic": {
                    "type": "string",
                    "description": "Logic operator between criteria",
                    "default": "AND",
                    "enum": ["AND", "OR"]
                },
                "fields": {
                    "type": "string",
                    "description": "Fields to return",
                    "default": "inchikey,pubchem,chembl,drugbank,name"
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