# src/mygene_mcp/tools/homology.py
"""Homology and ortholog tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class HomologyApi:
    """Tools for homology and ortholog queries."""
    
    async def get_gene_orthologs(
        self,
        client: MyGeneClient,
        gene_id: str,
        target_species: Optional[List[str]] = None,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get orthologs across species."""
        fields = "symbol,name,entrezgene,homologene,ensembl.homologene,pantherdb.ortholog"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        orthologs = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "orthologs": {}
        }
        
        # Process HomoloGene data
        if "homologene" in result:
            homologene = result["homologene"]
            homologene_id = homologene.get("id")
            
            if homologene_id and "genes" in homologene:
                for gene_entry in homologene["genes"]:
                    taxid = gene_entry[0]
                    entrezgene = gene_entry[1]
                    
                    # Skip self
                    if str(entrezgene) == str(gene_id):
                        continue
                    
                    # Apply species filter
                    if target_species:
                        species_match = False
                        for species in target_species:
                            if species.isdigit() and int(species) == taxid:
                                species_match = True
                            elif species == "human" and taxid == 9606:
                                species_match = True
                            elif species == "mouse" and taxid == 10090:
                                species_match = True
                            elif species == "rat" and taxid == 10116:
                                species_match = True
                        
                        if not species_match:
                            continue
                    
                    if "homologene" not in orthologs["orthologs"]:
                        orthologs["orthologs"]["homologene"] = []
                    
                    orthologs["orthologs"]["homologene"].append({
                        "taxid": taxid,
                        "entrezgene": entrezgene,
                        "homologene_id": homologene_id
                    })
        
        # Process Ensembl homology data
        if "ensembl" in result and "homologene" in result["ensembl"]:
            if "ensembl" not in orthologs["orthologs"]:
                orthologs["orthologs"]["ensembl"] = []
            
            ensembl_homologs = result["ensembl"]["homologene"]
            if not isinstance(ensembl_homologs, list):
                ensembl_homologs = [ensembl_homologs]
            
            orthologs["orthologs"]["ensembl"] = ensembl_homologs
        
        # Process PANTHER data
        if "pantherdb" in result and "ortholog" in result["pantherdb"]:
            if "pantherdb" not in orthologs["orthologs"]:
                orthologs["orthologs"]["pantherdb"] = []
            
            panther_orthologs = result["pantherdb"]["ortholog"]
            if not isinstance(panther_orthologs, list):
                panther_orthologs = [panther_orthologs]
            
            orthologs["orthologs"]["pantherdb"] = panther_orthologs
        
        # Filter by sources if specified
        if sources:
            filtered_orthologs = {}
            for source in sources:
                if source in orthologs["orthologs"]:
                    filtered_orthologs[source] = orthologs["orthologs"][source]
            orthologs["orthologs"] = filtered_orthologs
        
        return {
            "success": True,
            "ortholog_data": orthologs
        }
    
    async def query_homologous_genes(
        self,
        client: MyGeneClient,
        gene_symbol: str,
        species_list: List[str],
        homology_type: Optional[str] = "ortholog",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Find homologous genes across species."""
        # First, find the gene in all specified species
        query_parts = []
        
        for species in species_list:
            query_parts.append(f'(symbol:"{gene_symbol}" AND species:{species})')
        
        q = " OR ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,entrezgene,taxid,homologene,pantherdb",
            "size": size * len(species_list)  # Get more results to cover all species
        }
        
        result = await client.get("query", params=params)
        
        # Group results by homology
        homology_groups = {}
        
        for hit in result.get("hits", []):
            if "homologene" in hit and "id" in hit["homologene"]:
                homologene_id = hit["homologene"]["id"]
                
                if homologene_id not in homology_groups:
                    homology_groups[homologene_id] = {
                        "homologene_id": homologene_id,
                        "genes": []
                    }
                
                homology_groups[homologene_id]["genes"].append({
                    "symbol": hit.get("symbol"),
                    "name": hit.get("name"),
                    "entrezgene": hit.get("entrezgene"),
                    "taxid": hit.get("taxid")
                })
        
        return {
            "success": True,
            "query": q,
            "total_genes": result.get("total", 0),
            "homology_groups": list(homology_groups.values()),
            "homology_type": homology_type
        }


HOMOLOGY_TOOLS = [
    types.Tool(
        name="get_gene_orthologs",
        description="Get orthologous genes across different species",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "target_species": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target species (e.g., ['human', 'mouse', 'rat'] or taxids)"
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Homology data sources to use",
                    "enum": ["homologene", "ensembl", "pantherdb"]
                }
            },
            "required": ["gene_id"]
        }
    ),
    types.Tool(
        name="query_homologous_genes",
        description="Find homologous genes with the same symbol across species",
        input_schema={
            "type": "object",
            "properties": {
                "gene_symbol": {
                    "type": "string",
                    "description": "Gene symbol to search for"
                },
                "species_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of species to search"
                },
                "homology_type": {
                    "type": "string",
                    "description": "Type of homology",
                    "default": "ortholog",
                    "enum": ["ortholog", "paralog"]
                },
                "size": {
                    "type": "integer",
                    "description": "Results per species",
                    "default": 10
                }
            },
            "required": ["gene_symbol", "species_list"]
        }
    )
]