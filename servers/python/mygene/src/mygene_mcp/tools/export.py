# src/mygene_mcp/tools/export.py
"""Data export tools."""

from typing import Any, Dict, List, Optional
import json
import csv
import io
import mcp.types as types
from ..client import MyGeneClient


class ExportApi:
    """Tools for exporting gene data."""
    
    async def export_gene_list(
        self,
        client: MyGeneClient,
        gene_ids: List[str],
        format: str = "tsv",
        fields: Optional[List[str]] = None
    ) -> str:
        """Export gene data in various formats."""
        # Default fields if not specified
        if not fields:
            fields = ["symbol", "name", "taxid", "entrezgene", "ensembl.gene", "type_of_gene"]
        
        # Fetch gene data
        fields_str = ",".join(fields)
        post_data = {
            "ids": gene_ids,
            "fields": fields_str
        }
        
        results = await client.post("gene", post_data)
        
        # Format based on requested type
        if format == "json":
            return json.dumps(results, indent=2)
        
        elif format in ["tsv", "csv"]:
            # Flatten nested fields
            flattened_results = []
            for gene in results:
                flat_gene = {}
                for field in fields:
                    if "." in field:
                        # Handle nested fields
                        parts = field.split(".")
                        value = gene
                        for part in parts:
                            if isinstance(value, dict) and part in value:
                                value = value[part]
                            else:
                                value = None
                                break
                        flat_gene[field] = value
                    else:
                        flat_gene[field] = gene.get(field)
                
                flattened_results.append(flat_gene)
            
            # Create CSV/TSV
            output = io.StringIO()
            delimiter = "\t" if format == "tsv" else ","
            writer = csv.DictWriter(output, fieldnames=fields, delimiter=delimiter)
            
            writer.writeheader()
            writer.writerows(flattened_results)
            
            return output.getvalue()
        
        elif format == "xml":
            # Simple XML format
            xml_output = ['<?xml version="1.0" encoding="UTF-8"?>']
            xml_output.append("<genes>")
            
            for gene in results:
                xml_output.append("  <gene>")
                for field in fields:
                    value = gene.get(field, "")
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value)
                    xml_output.append(f"    <{field}>{value}</{field}>")
                xml_output.append("  </gene>")
            
            xml_output.append("</genes>")
            return "\n".join(xml_output)
        
        else:
            raise ValueError(f"Unsupported format: {format}")


EXPORT_TOOLS = [
    types.Tool(
        name="export_gene_list",
        description="Export gene data in various formats (TSV, CSV, JSON, XML)",
        input_schema={
            "type": "object",
            "properties": {
                "gene_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene IDs to export"
                },
                "format": {
                    "type": "string",
                    "description": "Export format",
                    "default": "tsv",
                    "enum": ["tsv", "csv", "json", "xml"]
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to include in export"
                }
            },
            "required": ["gene_ids"]
        }
    )
]