"""Data export tools."""

from typing import Any, Dict, List, Optional
import json
import csv
import io
import mcp.types as types
from ..client import MyDiseaseClient


class ExportApi:
    """Tools for exporting disease data."""
    
    async def export_disease_list(
        self,
        client: MyDiseaseClient,
        disease_ids: List[str],
        format: str = "tsv",
        fields: Optional[List[str]] = None
    ) -> str:
        """Export disease data in various formats."""
        # Default fields if not specified
        if not fields:
            fields = ["_id", "name", "mondo.mondo", "omim", "orphanet.id", 
                     "inheritance.inheritance_type", "prevalence"]
        
        # Fetch disease data
        fields_str = ",".join(fields)
        post_data = {
            "ids": disease_ids,
            "fields": fields_str
        }
        
        results = await client.post("disease", post_data)
        
        # Format based on requested type
        if format == "json":
            return json.dumps(results, indent=2)
        
        elif format in ["tsv", "csv"]:
            # Flatten nested fields
            flattened_results = []
            for disease in results:
                flat_disease = {}
                for field in fields:
                    if "." in field:
                        # Handle nested fields
                        parts = field.split(".")
                        value = disease
                        for part in parts:
                            if isinstance(value, dict) and part in value:
                                value = value[part]
                            else:
                                value = None
                                break
                        flat_disease[field] = value
                    else:
                        flat_disease[field] = disease.get(field)
                
                flattened_results.append(flat_disease)
            
            # Create CSV/TSV
            output = io.StringIO()
            delimiter = "\t" if format == "tsv" else ","
            writer = csv.DictWriter(output, fieldnames=fields, delimiter=delimiter)
            
            writer.writeheader()
            writer.writerows(flattened_results)
            
            return output.getvalue()
        
        elif format == "markdown":
            # Create markdown table
            lines = []
            
            # Header
            lines.append(f"# Disease List Export")
            lines.append("")
            lines.append("| " + " | ".join(fields) + " |")
            lines.append("|" + "|".join(["-" * 10 for _ in fields]) + "|")
            
            # Data rows
            for disease in results:
                values = []
                for field in fields:
                    if "." in field:
                        parts = field.split(".")
                        value = disease
                        for part in parts:
                            if isinstance(value, dict) and part in value:
                                value = value[part]
                            else:
                                value = ""
                                break
                    else:
                        value = disease.get(field, "")
                    
                    values.append(str(value) if value is not None else "")
                
                lines.append("| " + " | ".join(values) + " |")
            
            return "\n".join(lines)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    async def export_disease_comparison(
        self,
        client: MyDiseaseClient,
        disease_ids: List[str],
        comparison_fields: Optional[List[str]] = None,
        format: str = "markdown"
    ) -> str:
        """Export a comparison table of multiple diseases."""
        # Default comparison fields
        if not comparison_fields:
            comparison_fields = [
                "name",
                "inheritance",
                "genes",
                "prevalence",
                "age_of_onset",
                "main_phenotypes"
            ]
        
        # Build fields list
        field_map = {
            "inheritance": "inheritance.inheritance_type",
            "genes": "gene,causal_gene",
            "prevalence": "prevalence,orphanet.prevalence",
            "age_of_onset": "age_of_onset,orphanet.age_of_onset",
            "main_phenotypes": "phenotype_related_to_disease"
        }
        
        fields_to_fetch = set(["_id", "name", "mondo"])
        for field in comparison_fields:
            if field in field_map:
                fields_to_fetch.update(field_map[field].split(","))
            else:
                fields_to_fetch.add(field)
        
        # Fetch data
        post_data = {
            "ids": disease_ids,
            "fields": ",".join(fields_to_fetch)
        }
        
        results = await client.post("disease", post_data)
        
        # Process comparison data
        comparison_data = []
        
        for disease in results:
            row = {
                "disease_id": disease.get("_id", disease.get("query", "Unknown")),
                "name": disease.get("name", "Unknown")
            }
            
            # Extract comparison fields
            for field in comparison_fields:
                if field == "name":
                    continue  # Already added
                elif field == "inheritance":
                    inh = disease.get("inheritance", {})
                    if isinstance(inh, list):
                        row[field] = ", ".join([i.get("inheritance_type", "") for i in inh])
                    else:
                        row[field] = inh.get("inheritance_type", "")
                elif field == "genes":
                    genes = []
                    if "gene" in disease:
                        g = disease["gene"]
                        g = g if isinstance(g, list) else [g]
                        genes.extend([gene.get("symbol", "") for gene in g])
                    if "causal_gene" in disease:
                        g = disease["causal_gene"]
                        g = g if isinstance(g, list) else [g]
                        genes.extend([gene.get("symbol", "") for gene in g])
                    row[field] = ", ".join(set(filter(None, genes)))
                elif field == "prevalence":
                    if "orphanet" in disease and "prevalence" in disease["orphanet"]:
                        prev = disease["orphanet"]["prevalence"]
                        row[field] = prev.get("prevalence_class", "")
                    elif "prevalence" in disease:
                        row[field] = str(disease["prevalence"])
                    else:
                        row[field] = ""
                elif field == "age_of_onset":
                    if "orphanet" in disease and "age_of_onset" in disease["orphanet"]:
                        onset = disease["orphanet"]["age_of_onset"]
                        onset = onset if isinstance(onset, list) else [onset]
                        row[field] = ", ".join([o.get("label", "") for o in onset])
                    else:
                        row[field] = disease.get("age_of_onset", "")
                elif field == "main_phenotypes":
                    if "phenotype_related_to_disease" in disease:
                        phenos = disease["phenotype_related_to_disease"]
                        phenos = phenos if isinstance(phenos, list) else [phenos]
                        # Get top 5 phenotypes
                        top_phenos = [p.get("hpo_phenotype", "") for p in phenos[:5]]
                        row[field] = "; ".join(filter(None, top_phenos))
                    else:
                        row[field] = ""
                else:
                    row[field] = disease.get(field, "")
            
            comparison_data.append(row)
        
        # Format output
        if format == "json":
            return json.dumps(comparison_data, indent=2)
        
        elif format == "markdown":
            lines = []
            
            # Title
            lines.append("# Disease Comparison")
            lines.append("")
            
            # Create table
            headers = ["Disease ID", "Disease Name"] + [f.replace("_", " ").title() for f in comparison_fields if f != "name"]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join(["-" * 15 for _ in headers]) + "|")
            
            # Data rows
            for row in comparison_data:
                values = [row["disease_id"], row["name"]]
                for field in comparison_fields:
                    if field != "name":
                        val = row.get(field, "")
                        # Truncate long values
                        if len(str(val)) > 50:
                            val = str(val)[:47] + "..."
                        values.append(str(val))
                
                lines.append("| " + " | ".join(values) + " |")
            
            return "\n".join(lines)
        
        elif format in ["csv", "tsv"]:
            output = io.StringIO()
            delimiter = "\t" if format == "tsv" else ","
            
            fieldnames = ["disease_id", "name"] + comparison_fields
            writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=delimiter)
            
            writer.writeheader()
            writer.writerows(comparison_data)
            
            return output.getvalue()
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    async def export_gene_disease_matrix(
        self,
        client: MyDiseaseClient,
        gene_list: List[str],
        disease_list: Optional[List[str]] = None,
        format: str = "csv"
    ) -> str:
        """Export a gene-disease association matrix."""
        # If no disease list provided, find diseases for all genes
        if disease_list is None:
            disease_set = set()
            
            for gene in gene_list:
                q = f'gene.symbol:"{gene}" OR causal_gene.symbol:"{gene}"'
                params = {
                    "q": q,
                    "fields": "_id",
                    "size": 100
                }
                
                result = await client.get("query", params=params)
                for hit in result.get("hits", []):
                    disease_set.add(hit.get("_id"))
            
            disease_list = list(disease_set)
        
        # Create matrix
        matrix = {}
        
        # Fetch disease data
        post_data = {
            "ids": disease_list,
            "fields": "_id,name,gene,causal_gene"
        }
        
        results = await client.post("disease", post_data)
        
        # Build matrix
        for disease in results:
            disease_id = disease.get("_id")
            matrix[disease_id] = {
                "name": disease.get("name", ""),
                "genes": {}
            }
            
            # Initialize all genes to 0
            for gene in gene_list:
                matrix[disease_id]["genes"][gene] = 0
            
            # Mark associated genes
            if "gene" in disease:
                genes = disease["gene"]
                genes = genes if isinstance(genes, list) else [genes]
                for g in genes:
                    if g.get("symbol") in gene_list:
                        matrix[disease_id]["genes"][g["symbol"]] = 1
            
            if "causal_gene" in disease:
                genes = disease["causal_gene"]
                genes = genes if isinstance(genes, list) else [genes]
                for g in genes:
                    if g.get("symbol") in gene_list:
                        matrix[disease_id]["genes"][g["symbol"]] = 2  # 2 for causal
        
        # Format output
        if format == "json":
            return json.dumps(matrix, indent=2)
        
        elif format in ["csv", "tsv"]:
            output = io.StringIO()
            delimiter = "\t" if format == "tsv" else ","
            
            # Headers
            headers = ["Disease ID", "Disease Name"] + gene_list
            writer = csv.writer(output, delimiter=delimiter)
            writer.writerow(headers)
            
            # Data rows
            for disease_id, data in matrix.items():
                row = [disease_id, data["name"]]
                for gene in gene_list:
                    row.append(data["genes"][gene])
                writer.writerow(row)
            
            return output.getvalue()
        
        elif format == "markdown":
            lines = []
            
            lines.append("# Gene-Disease Association Matrix")
            lines.append("")
            lines.append("Legend: 0 = No association, 1 = Associated, 2 = Causal")
            lines.append("")
            
            # Create table
            headers = ["Disease"] + gene_list
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join(["-" * 20] + ["-" * 10 for _ in gene_list]) + "|")
            
            for disease_id, data in matrix.items():
                name = data["name"][:30] + "..." if len(data["name"]) > 30 else data["name"]
                row = [name]
                for gene in gene_list:
                    row.append(str(data["genes"][gene]))
                lines.append("| " + " | ".join(row) + " |")
            
            return "\n".join(lines)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    async def export_phenotype_profile(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        format: str = "json"
    ) -> str:
        """Export comprehensive phenotype profile for a disease."""
        # Fetch comprehensive data
        fields = [
            "_id",
            "name",
            "hpo",
            "phenotype_related_to_disease",
            "clinical_features",
            "inheritance",
            "age_of_onset",
            "prevalence"
        ]
        
        params = {"fields": ",".join(fields)}
        result = await client.get(f"disease/{disease_id}", params=params)
        
        # Build phenotype profile
        profile = {
            "disease_id": disease_id,
            "disease_name": result.get("name"),
            "inheritance": [],
            "age_of_onset": result.get("age_of_onset"),
            "prevalence": result.get("prevalence"),
            "phenotypes": [],
            "phenotype_categories": {}
        }
        
        # Process inheritance
        if "inheritance" in result:
            inh = result["inheritance"]
            inh = inh if isinstance(inh, list) else [inh]
            profile["inheritance"] = [i.get("inheritance_type") for i in inh]
        
        # Process phenotypes
        if "phenotype_related_to_disease" in result:
            phenos = result["phenotype_related_to_disease"]
            phenos = phenos if isinstance(phenos, list) else [phenos]
            
            for pheno in phenos:
                phenotype_info = {
                    "hpo_id": pheno.get("hpo_id"),
                    "phenotype": pheno.get("hpo_phenotype"),
                    "frequency": pheno.get("frequency"),
                    "onset": pheno.get("onset")
                }
                profile["phenotypes"].append(phenotype_info)
                
                # Categorize by frequency
                freq = pheno.get("frequency", "Unknown")
                if freq not in profile["phenotype_categories"]:
                    profile["phenotype_categories"][freq] = []
                profile["phenotype_categories"][freq].append(phenotype_info)
        
        # Format output
        if format == "json":
            return json.dumps(profile, indent=2)
        
        elif format == "markdown":
            lines = []
            
            # Header
            lines.append(f"# Phenotype Profile: {profile['disease_name'] or disease_id}")
            lines.append("")
            
            # Basic info
            lines.append("## Basic Information")
            lines.append(f"- **Inheritance**: {', '.join(profile['inheritance']) if profile['inheritance'] else 'Unknown'}")
            lines.append(f"- **Age of Onset**: {profile['age_of_onset'] or 'Unknown'}")
            lines.append(f"- **Prevalence**: {profile['prevalence'] or 'Unknown'}")
            lines.append("")
            
            # Phenotypes by frequency
            lines.append("## Clinical Features by Frequency")
            
            for frequency, phenotypes in profile["phenotype_categories"].items():
                lines.append(f"\n### {frequency}")
                for pheno in phenotypes:
                    lines.append(f"- {pheno['phenotype']} ({pheno['hpo_id']})")
            
            return "\n".join(lines)
        
        else:
            raise ValueError(f"Unsupported format: {format}")


EXPORT_TOOLS = [
    types.Tool(
        name="export_disease_list",
        description="Export disease data in various formats (TSV, CSV, JSON, Markdown)",
        input_schema={
            "type": "object",
            "properties": {
                "disease_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of disease IDs to export"
                },
                "format": {
                    "type": "string",
                    "description": "Export format",
                    "default": "tsv",
                    "enum": ["tsv", "csv", "json", "markdown"]
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to include in export"
                }
            },
            "required": ["disease_ids"]
        }
    ),
    types.Tool(
        name="export_disease_comparison",
        description="Export a comparison table of multiple diseases",
        input_schema={
            "type": "object",
            "properties": {
                "disease_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of diseases to compare"
                },
                "comparison_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Fields to compare"
                },
                "format": {
                    "type": "string",
                    "description": "Export format",
                    "default": "markdown",
                    "enum": ["csv", "tsv", "json", "markdown"]
                }
            },
            "required": ["disease_ids"]
        }
    ),
    types.Tool(
        name="export_gene_disease_matrix",
        description="Export a gene-disease association matrix",
        input_schema={
            "type": "object",
            "properties": {
                "gene_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene symbols"
                },
                "disease_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of disease IDs (optional)"
                },
                "format": {
                    "type": "string",
                    "description": "Export format",
                    "default": "csv",
                    "enum": ["csv", "tsv", "json", "markdown"]
                }
            },
            "required": ["gene_list"]
        }
    ),
    types.Tool(
        name="export_phenotype_profile",
        description="Export comprehensive phenotype profile for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "format": {
                    "type": "string",
                    "description": "Export format",
                    "default": "json",
                    "enum": ["json", "markdown"]
                }
            },
            "required": ["disease_id"]
        }
    )
]