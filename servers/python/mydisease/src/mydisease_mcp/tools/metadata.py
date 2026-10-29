"""Metadata and utility tools."""

from typing import Any, Dict
import mcp.types as types
from ..client import MyDiseaseClient


class MetadataApi:
    """Tools for retrieving MyDisease.info metadata."""
    
    async def get_mydisease_metadata(self, client: MyDiseaseClient) -> Dict[str, Any]:
        """Get metadata about the MyDisease.info API service."""
        result = await client.get("metadata")
        
        return {
            "success": True,
            "metadata": result
        }
    
    async def get_available_fields(self, client: MyDiseaseClient) -> Dict[str, Any]:
        """Get a list of all available fields in MyDisease.info."""
        result = await client.get("metadata/fields")
        
        # Organize fields by category
        field_categories = {
            "identifiers": [],
            "basic_info": [],
            "genetic": [],
            "clinical": [],
            "epidemiology": [],
            "ontology": [],
            "sources": []
        }
        
        for field, info in result.items():
            if any(id_type in field for id_type in ["mondo", "omim", "orphanet", "doid", "umls", "mesh", "icd"]):
                field_categories["identifiers"].append(field)
            elif any(term in field for term in ["gene", "variant", "causal"]):
                field_categories["genetic"].append(field)
            elif any(term in field for term in ["phenotype", "clinical", "treatment", "drug"]):
                field_categories["clinical"].append(field)
            elif any(term in field for term in ["prevalence", "incidence", "epidemiology"]):
                field_categories["epidemiology"].append(field)
            elif any(term in field for term in ["ontology", "parents", "children", "ancestors"]):
                field_categories["ontology"].append(field)
            elif any(source in field for source in ["disgenet", "ctd", "kegg", "pharmgkb"]):
                field_categories["sources"].append(field)
            else:
                field_categories["basic_info"].append(field)
        
        return {
            "success": True,
            "total_fields": len(result),
            "fields": result,
            "field_categories": field_categories
        }
    
    async def get_database_statistics(self, client: MyDiseaseClient) -> Dict[str, Any]:
        """Get statistics about the database."""
        metadata = await client.get("metadata")
        
        stats = {
            "total_diseases": metadata.get("stats", {}).get("total", 0),
            "last_updated": metadata.get("build_date"),
            "version": metadata.get("build_version"),
            "sources": {}
        }
        
        # Extract source statistics
        if "src" in metadata:
            for source, info in metadata["src"].items():
                stats["sources"][source] = {
                    "version": info.get("version"),
                    "total": info.get("stats", {}).get("total", 0),
                    "last_updated": info.get("update_date")
                }
        
        # Calculate coverage statistics
        if stats["sources"]:
            coverage = {
                "omim": stats["sources"].get("omim", {}).get("total", 0),
                "orphanet": stats["sources"].get("orphanet", {}).get("total", 0),
                "disgenet": stats["sources"].get("disgenet", {}).get("total", 0),
                "clinvar": stats["sources"].get("clinvar", {}).get("total", 0)
            }
            
            stats["coverage_summary"] = {
                "genetic_diseases": coverage["omim"],
                "rare_diseases": coverage["orphanet"],
                "gene_associations": coverage["disgenet"],
                "variant_annotations": coverage["clinvar"]
            }
        
        return {
            "success": True,
            "statistics": stats
        }


METADATA_TOOLS = [
    types.Tool(
        name="get_mydisease_metadata",
        description="Get metadata about MyDisease.info API including data sources and statistics",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    types.Tool(
        name="get_available_fields",
        description="Get all available fields in MyDisease.info organized by category",
        input_schema={
            "type": "object",
            "properties": {}
        }
    ),
    types.Tool(
        name="get_database_statistics",
        description="Get statistics about the disease database and coverage",
        input_schema={
            "type": "object",
            "properties": {}
        }
    )
]