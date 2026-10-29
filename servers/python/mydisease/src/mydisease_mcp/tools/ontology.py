"""Disease ontology and classification tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


class OntologyApi:
    """Tools for disease ontology and relationships."""
    
    async def get_disease_ontology(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get ontology information for a disease."""
        params = {
            "fields": "mondo,disease_ontology,icd10,icd11,umls,mesh,medgen"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        ontology_data = {
            "disease_id": disease_id,
            "ontologies": {},
            "cross_references": []
        }
        
        # Extract MONDO
        if "mondo" in result:
            mondo = result["mondo"]
            ontology_data["ontologies"]["mondo"] = {
                "id": mondo.get("mondo") or mondo.get("id"),
                "label": mondo.get("label"),
                "definition": mondo.get("definition"),
                "synonyms": mondo.get("synonym", [])
            }
        
        # Extract Disease Ontology
        if "disease_ontology" in result:
            do = result["disease_ontology"]
            ontology_data["ontologies"]["disease_ontology"] = {
                "id": do.get("doid"),
                "name": do.get("name"),
                "definition": do.get("def")
            }
        
        # Extract ICD codes
        if "icd10" in result:
            icd10 = result["icd10"]
            icd10 = icd10 if isinstance(icd10, list) else [icd10]
            ontology_data["ontologies"]["icd10"] = icd10
        
        if "icd11" in result:
            ontology_data["ontologies"]["icd11"] = result["icd11"]
        
        # Extract UMLS
        if "umls" in result:
            umls = result["umls"]
            ontology_data["ontologies"]["umls"] = {
                "cui": umls.get("cui"),
                "name": umls.get("name"),
                "semantic_types": umls.get("semantic_types", [])
            }
        
        # Extract other identifiers
        if "mesh" in result:
            ontology_data["cross_references"].append({
                "source": "mesh",
                "id": result["mesh"]
            })
        
        if "medgen" in result:
            ontology_data["cross_references"].append({
                "source": "medgen",
                "id": result["medgen"]
            })
        
        return {
            "success": True,
            "ontology_data": ontology_data
        }
    
    async def get_disease_classification(
        self,
        client: MyDiseaseClient,
        disease_id: str
    ) -> Dict[str, Any]:
        """Get disease classification and hierarchy."""
        params = {
            "fields": "mondo.parents,mondo.children,mondo.ancestors,disease_ontology.parents,disease_ontology.children"
        }
        
        result = await client.get(f"disease/{disease_id}", params=params)
        
        classification = {
            "disease_id": disease_id,
            "hierarchy": {
                "parents": [],
                "children": [],
                "ancestors": []
            }
        }
        
        # Extract MONDO hierarchy
        if "mondo" in result:
            mondo = result["mondo"]
            if "parents" in mondo:
                parents = mondo["parents"]
                parents = parents if isinstance(parents, list) else [parents]
                classification["hierarchy"]["parents"].extend([
                    {"source": "mondo", "id": p.get("id"), "label": p.get("label")}
                    for p in parents
                ])
            
            if "children" in mondo:
                children = mondo["children"]
                children = children if isinstance(children, list) else [children]
                classification["hierarchy"]["children"].extend([
                    {"source": "mondo", "id": c.get("id"), "label": c.get("label")}
                    for c in children
                ])
            
            if "ancestors" in mondo:
                ancestors = mondo["ancestors"]
                ancestors = ancestors if isinstance(ancestors, list) else [ancestors]
                classification["hierarchy"]["ancestors"] = ancestors
        
        # Extract Disease Ontology hierarchy
        if "disease_ontology" in result:
            do = result["disease_ontology"]
            if "parents" in do:
                parents = do["parents"]
                parents = parents if isinstance(parents, list) else [parents]
                classification["hierarchy"]["parents"].extend([
                    {"source": "disease_ontology", "id": p}
                    for p in parents
                ])
        
        return {
            "success": True,
            "classification": classification
        }
    
    async def get_related_diseases(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        relationship_type: str = "all",
        size: int = 20
    ) -> Dict[str, Any]:
        """Get related diseases based on various relationships."""
        # First get the disease info
        params = {
            "fields": "mondo,name,gene,phenotype_related_to_disease"
        }
        
        disease_result = await client.get(f"disease/{disease_id}", params=params)
        
        related_diseases = {
            "disease_id": disease_id,
            "disease_name": disease_result.get("name"),
            "related_by_hierarchy": [],
            "related_by_genes": [],
            "related_by_phenotypes": []
        }
        
        # Get hierarchically related diseases
        if relationship_type in ["all", "hierarchy"] and "mondo" in disease_result:
            mondo = disease_result["mondo"]
            
            # Search for siblings (same parent)
            if "parents" in mondo:
                parents = mondo["parents"]
                parents = parents if isinstance(parents, list) else [parents]
                
                for parent in parents:
                    parent_id = parent.get("id")
                    if parent_id:
                        # Find diseases with same parent
                        q = f'mondo.parents.id:"{parent_id}"'
                        params = {
                            "q": q,
                            "fields": "_id,name,mondo",
                            "size": size
                        }
                        
                        siblings_result = await client.get("query", params=params)
                        
                        for hit in siblings_result.get("hits", []):
                            if hit.get("_id") != disease_id:
                                related_diseases["related_by_hierarchy"].append({
                                    "disease_id": hit.get("_id"),
                                    "disease_name": hit.get("name"),
                                    "relationship": "sibling",
                                    "via_parent": parent_id
                                })
        
        # Get diseases with shared genes
        if relationship_type in ["all", "genes"] and "gene" in disease_result:
            genes = disease_result["gene"]
            genes = genes if isinstance(genes, list) else [genes]
            
            gene_symbols = [g.get("symbol") for g in genes if g.get("symbol")][:5]  # Limit to 5 genes
            
            if gene_symbols:
                gene_queries = [f'gene.symbol:"{symbol}"' for symbol in gene_symbols]
                q = " OR ".join(gene_queries)
                
                params = {
                    "q": q,
                    "fields": "_id,name,gene",
                    "size": size
                }
                
                gene_result = await client.get("query", params=params)
                
                for hit in gene_result.get("hits", []):
                    if hit.get("_id") != disease_id:
                        # Find shared genes
                        hit_genes = hit.get("gene", [])
                        hit_genes = hit_genes if isinstance(hit_genes, list) else [hit_genes]
                        hit_symbols = {g.get("symbol") for g in hit_genes}
                        
                        shared = set(gene_symbols) & hit_symbols
                        if shared:
                            related_diseases["related_by_genes"].append({
                                "disease_id": hit.get("_id"),
                                "disease_name": hit.get("name"),
                                "shared_genes": list(shared),
                                "shared_count": len(shared)
                            })
        
        # Get diseases with shared phenotypes
        if relationship_type in ["all", "phenotypes"] and "phenotype_related_to_disease" in disease_result:
            phenotypes = disease_result["phenotype_related_to_disease"]
            phenotypes = phenotypes if isinstance(phenotypes, list) else [phenotypes]
            
            # Get top phenotypes
            hpo_ids = [p.get("hpo_id") for p in phenotypes if p.get("hpo_id")][:5]
            
            if hpo_ids:
                pheno_queries = [f'phenotype_related_to_disease.hpo_id:"{hpo}"' for hpo in hpo_ids]
                q = " OR ".join(pheno_queries)
                
                params = {
                    "q": q,
                    "fields": "_id,name,phenotype_related_to_disease",
                    "size": size
                }
                
                pheno_result = await client.get("query", params=params)
                
                for hit in pheno_result.get("hits", []):
                    if hit.get("_id") != disease_id:
                        related_diseases["related_by_phenotypes"].append({
                            "disease_id": hit.get("_id"),
                            "disease_name": hit.get("name"),
                            "relationship": "phenotypic_similarity"
                        })
        
        return {
            "success": True,
            "related_diseases": related_diseases
        }
    
    async def navigate_disease_hierarchy(
        self,
        client: MyDiseaseClient,
        disease_id: str,
        direction: str = "up",
        levels: int = 2
    ) -> Dict[str, Any]:
        """Navigate disease hierarchy up or down."""
        hierarchy = {
            "disease_id": disease_id,
            "path": []
        }
        
        current_id = disease_id
        
        for level in range(levels):
            params = {
                "fields": f"name,mondo.{'parents' if direction == 'up' else 'children'}"
            }
            
            result = await client.get(f"disease/{current_id}", params=params)
            
            if level == 0:
                hierarchy["path"].append({
                    "level": 0,
                    "disease_id": current_id,
                    "disease_name": result.get("name")
                })
            
            if "mondo" in result:
                mondo = result["mondo"]
                next_level = mondo.get("parents" if direction == "up" else "children", [])
                next_level = next_level if isinstance(next_level, list) else [next_level]
                
                if next_level:
                    # For parents, usually take the first one
                    # For children, return all
                    if direction == "up" and next_level:
                        next_item = next_level[0]
                        hierarchy["path"].append({
                            "level": level + 1,
                            "disease_id": next_item.get("id"),
                            "disease_name": next_item.get("label")
                        })
                        current_id = next_item.get("id")
                    else:
                        hierarchy["path"].append({
                            "level": level + 1,
                            "diseases": [
                                {
                                    "disease_id": item.get("id"),
                                    "disease_name": item.get("label")
                                }
                                for item in next_level
                            ]
                        })
                        break
                else:
                    break
        
        return {
            "success": True,
            "hierarchy": hierarchy,
            "direction": direction
        }


ONTOLOGY_TOOLS = [
    types.Tool(
        name="get_disease_ontology",
        description="Get ontology information and cross-references for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_disease_classification",
        description="Get disease classification hierarchy (parents, children, ancestors)",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="get_related_diseases",
        description="Get diseases related by hierarchy, genes, or phenotypes",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Disease ID"
                },
                "relationship_type": {
                    "type": "string",
                    "description": "Type of relationship",
                    "default": "all",
                    "enum": ["all", "hierarchy", "genes", "phenotypes"]
                },
                "size": {
                    "type": "integer",
                    "description": "Number of results per category",
                    "default": 20
                }
            },
            "required": ["disease_id"]
        }
    ),
    types.Tool(
        name="navigate_disease_hierarchy",
        description="Navigate disease hierarchy up to parents or down to children",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {
                    "type": "string",
                    "description": "Starting disease ID"
                },
                "direction": {
                    "type": "string",
                    "description": "Navigation direction",
                    "default": "up",
                    "enum": ["up", "down"]
                },
                "levels": {
                    "type": "integer",
                    "description": "Number of levels to navigate",
                    "default": 2
                }
            },
            "required": ["disease_id"]
        }
    )
]