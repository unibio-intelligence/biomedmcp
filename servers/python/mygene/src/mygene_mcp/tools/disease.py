# src/mygene_mcp/tools/disease.py
"""Disease association tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class DiseaseApi:
    """Tools for disease-related gene queries."""
    
    async def query_genes_by_disease(
        self,
        client: MyGeneClient,
        disease_name: Optional[str] = None,
        disease_id: Optional[str] = None,
        source: Optional[str] = None,
        species: Optional[str] = "human",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Find genes associated with diseases."""
        query_parts = []
        
        if disease_name:
            if source:
                if source == "disgenet":
                    query_parts.append(f'disgenet.diseases.disease_name:"{disease_name}"')
                elif source == "clinvar":
                    query_parts.append(f'clinvar.rcv.conditions.name:"{disease_name}"')
                elif source == "omim":
                    query_parts.append(f'omim.name:"{disease_name}"')
            else:
                # Search across all disease sources
                query_parts.append(
                    f'(disgenet.diseases.disease_name:"{disease_name}" OR '
                    f'clinvar.rcv.conditions.name:"{disease_name}" OR '
                    f'omim.name:"{disease_name}")'
                )
        
        if disease_id:
            if source:
                query_parts.append(f'{source}.disease_id:"{disease_id}"')
            else:
                # Try to identify ID type and search appropriately
                if disease_id.startswith("OMIM:"):
                    query_parts.append(f'omim.omim_id:"{disease_id[5:]}"')
                elif disease_id.startswith("C"):
                    query_parts.append(f'disgenet.diseases.disease_id:"{disease_id}"')
                else:
                    query_parts.append(f'disease_id:"{disease_id}"')
        
        if not query_parts:
            # Get all genes with disease associations
            query_parts.append("_exists_:disgenet OR _exists_:clinvar OR _exists_:omim")
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,entrezgene,disgenet,clinvar,omim",
            "species": species,
            "size": size
        }
        
        result = await client.get("query", params=params)
        
        return {
            "success": True,
            "query": q,
            "total": result.get("total", 0),
            "hits": result.get("hits", [])
        }
    
    async def get_gene_disease_associations(
        self,
        client: MyGeneClient,
        gene_id: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get disease associations for a gene."""
        fields = "symbol,name,entrezgene,disgenet,clinvar,omim"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        disease_associations = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "disease_sources": {}
        }
        
        # Process DisGeNET data
        if "disgenet" in result and (not sources or "disgenet" in sources):
            disgenet = result["disgenet"]
            diseases = []
            
            if "diseases" in disgenet:
                disease_list = disgenet["diseases"]
                if not isinstance(disease_list, list):
                    disease_list = [disease_list]
                
                for disease in disease_list:
                    diseases.append({
                        "disease_id": disease.get("disease_id"),
                        "disease_name": disease.get("disease_name"),
                        "score": disease.get("score"),
                        "source": disease.get("source")
                    })
            
            disease_associations["disease_sources"]["disgenet"] = {
                "total": len(diseases),
                "diseases": diseases
            }
        
        # Process ClinVar data
        if "clinvar" in result and (not sources or "clinvar" in sources):
            clinvar = result["clinvar"]
            variants = []
            
            if "rcv" in clinvar:
                rcv_list = clinvar["rcv"]
                if not isinstance(rcv_list, list):
                    rcv_list = [rcv_list]
                
                for rcv in rcv_list:
                    conditions = rcv.get("conditions", {})
                    clinical_significance = rcv.get("clinical_significance")
                    
                    variants.append({
                        "rcv_accession": rcv.get("accession", {}).get("accession"),
                        "conditions": conditions,
                        "clinical_significance": clinical_significance,
                        "last_evaluated": rcv.get("last_evaluated")
                    })
            
            disease_associations["disease_sources"]["clinvar"] = {
                "total": len(variants),
                "variants": variants
            }
        
        # Process OMIM data
        if "omim" in result and (not sources or "omim" in sources):
            omim = result["omim"]
            
            omim_diseases = []
            if isinstance(omim, dict):
                omim_diseases.append({
                    "omim_id": omim.get("omim_id"),
                    "name": omim.get("name"),
                    "inheritance": omim.get("inheritance")
                })
            elif isinstance(omim, list):
                for entry in omim:
                    omim_diseases.append({
                        "omim_id": entry.get("omim_id"),
                        "name": entry.get("name"),
                        "inheritance": entry.get("inheritance")
                    })
            
            disease_associations["disease_sources"]["omim"] = {
                "total": len(omim_diseases),
                "diseases": omim_diseases
            }
        
        # Count total disease associations
        total_associations = sum(
            source_data.get("total", 0) 
            for source_data in disease_associations["disease_sources"].values()
        )
        
        return {
            "success": True,
            "total_associations": total_associations,
            "disease_associations": disease_associations
        }


DISEASE_TOOLS = [
    types.Tool(
        name="query_genes_by_disease",
        description="Find genes associated with specific diseases",
        input_schema={
            "type": "object",
            "properties": {
                "disease_name": {
                    "type": "string",
                    "description": "Disease name (e.g., 'breast cancer', 'alzheimer disease')"
                },
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID (e.g., 'OMIM:114480', 'C0006142')"
                },
                "source": {
                    "type": "string",
                    "description": "Disease database source",
                    "enum": ["disgenet", "clinvar", "omim"]
                },
                "species": {
                    "type": "string",
                    "description": "Species filter",
                    "default": "human"
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
        name="get_gene_disease_associations",
        description="Get all disease associations for a specific gene",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by specific disease sources",
                    "enum": ["disgenet", "clinvar", "omim"]
                }
            },
            "required": ["gene_id"]
        }
    )
]