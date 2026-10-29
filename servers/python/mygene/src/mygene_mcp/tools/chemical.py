# src/mygene_mcp/tools/chemical.py
"""Chemical and drug interaction tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class ChemicalApi:
    """Tools for chemical/drug interaction queries."""
    
    async def query_genes_by_chemical(
        self,
        client: MyGeneClient,
        chemical_name: Optional[str] = None,
        chemical_id: Optional[str] = None,
        interaction_type: Optional[str] = None,
        species: Optional[str] = "human",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Find genes that interact with chemicals/drugs."""
        query_parts = []
        
        if chemical_name:
            # Search across multiple chemical databases
            query_parts.append(
                f'(pharmgkb.chemical.name:"{chemical_name}" OR '
                f'chebi.name:"{chemical_name}" OR '
                f'chembl.molecule_chembl_id:"{chemical_name}" OR '
                f'drugbank.name:"{chemical_name}")'
            )
        
        if chemical_id:
            # Handle different chemical ID formats
            if chemical_id.startswith("CHEMBL"):
                query_parts.append(f'chembl.molecule_chembl_id:"{chemical_id}"')
            elif chemical_id.startswith("DB"):
                query_parts.append(f'drugbank.id:"{chemical_id}"')
            elif chemical_id.startswith("CHEBI:"):
                query_parts.append(f'chebi.id:"{chemical_id}"')
            else:
                query_parts.append(f'chemical_id:"{chemical_id}"')
        
        if interaction_type:
            query_parts.append(f'pharmgkb.type:"{interaction_type}"')
        
        if not query_parts:
            # Get all genes with chemical interactions
            query_parts.append(
                "_exists_:pharmgkb OR _exists_:chebi OR _exists_:chembl OR _exists_:drugbank"
            )
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,entrezgene,pharmgkb,chebi,chembl,drugbank",
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
    
    async def get_gene_chemical_interactions(
        self,
        client: MyGeneClient,
        gene_id: str,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get chemical/drug interactions for a gene."""
        fields = "symbol,name,entrezgene,pharmgkb,chebi,chembl,drugbank"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        chemical_data = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "chemical_sources": {}
        }
        
        # Process PharmGKB data
        if "pharmgkb" in result and (not sources or "pharmgkb" in sources):
            pharmgkb = result["pharmgkb"]
            chemicals = []
            
            if "chemical" in pharmgkb:
                chemical_list = pharmgkb["chemical"]
                if not isinstance(chemical_list, list):
                    chemical_list = [chemical_list]
                
                for chemical in chemical_list:
                    chemicals.append({
                        "name": chemical.get("name"),
                        "id": chemical.get("id"),
                        "type": chemical.get("type")
                    })
            
            chemical_data["chemical_sources"]["pharmgkb"] = {
                "total": len(chemicals),
                "chemicals": chemicals
            }
        
        # Process ChEBI data
        if "chebi" in result and (not sources or "chebi" in sources):
            chebi = result["chebi"]
            chebi_compounds = []
            
            if isinstance(chebi, dict):
                chebi_compounds.append({
                    "id": chebi.get("id"),
                    "name": chebi.get("name"),
                    "definition": chebi.get("definition")
                })
            elif isinstance(chebi, list):
                for compound in chebi:
                    chebi_compounds.append({
                        "id": compound.get("id"),
                        "name": compound.get("name"),
                        "definition": compound.get("definition")
                    })
            
            chemical_data["chemical_sources"]["chebi"] = {
                "total": len(chebi_compounds),
                "compounds": chebi_compounds
            }
        
        # Process ChEMBL data
        if "chembl" in result and (not sources or "chembl" in sources):
            chembl = result["chembl"]
            
            if "target_component" in chembl:
                targets = chembl["target_component"]
                if not isinstance(targets, list):
                    targets = [targets]
                
                chemical_data["chemical_sources"]["chembl"] = {
                    "total": len(targets),
                    "targets": targets
                }
        
        # Process DrugBank data
        if "drugbank" in result and (not sources or "drugbank" in sources):
            drugbank = result["drugbank"]
            drugs = []
            
            if isinstance(drugbank, list):
                for drug in drugbank:
                    drugs.append({
                        "id": drug.get("id"),
                        "name": drug.get("name"),
                        "groups": drug.get("groups", [])
                    })
            elif isinstance(drugbank, dict):
                drugs.append({
                    "id": drugbank.get("id"),
                    "name": drugbank.get("name"),
                    "groups": drugbank.get("groups", [])
                })
            
            chemical_data["chemical_sources"]["drugbank"] = {
                "total": len(drugs),
                "drugs": drugs
            }
        
        # Count total interactions
        total_interactions = sum(
            source_data.get("total", 0) 
            for source_data in chemical_data["chemical_sources"].values()
        )
        
        return {
            "success": True,
            "total_interactions": total_interactions,
            "chemical_interactions": chemical_data
        }


CHEMICAL_TOOLS = [
    types.Tool(
        name="query_genes_by_chemical",
        description="Find genes that interact with specific chemicals or drugs",
        input_schema={
            "type": "object",
            "properties": {
                "chemical_name": {
                    "type": "string",
                    "description": "Chemical or drug name (e.g., 'aspirin', 'imatinib')"
                },
                "chemical_id": {
                    "type": "string",
                    "description": "Chemical ID (e.g., 'CHEMBL25', 'DB00619', 'CHEBI:15365')"
                },
                "interaction_type": {
                    "type": "string",
                    "description": "Type of interaction (for PharmGKB)"
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
        name="get_gene_chemical_interactions",
        description="Get all chemical/drug interactions for a specific gene",
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
                    "description": "Filter by specific sources",
                    "enum": ["pharmgkb", "chebi", "chembl", "drugbank"]
                }
            },
            "required": ["gene_id"]
        }
    )
]