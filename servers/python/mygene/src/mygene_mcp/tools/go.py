# src/mygene_mcp/tools/go.py
"""Gene Ontology (GO) tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyGeneClient


class GOApi:
    """Tools for Gene Ontology queries."""
    
    async def query_genes_by_go_term(
        self,
        client: MyGeneClient,
        go_id: Optional[str] = None,
        go_name: Optional[str] = None,
        evidence_codes: Optional[List[str]] = None,
        qualifier: Optional[str] = None,
        aspect: Optional[str] = None,
        species: Optional[str] = "human",
        size: Optional[int] = 10
    ) -> Dict[str, Any]:
        """Query genes by GO terms with evidence filtering."""
        query_parts = []
        
        # GO ID search
        if go_id:
            if aspect:
                query_parts.append(f'go.{aspect}:"{go_id}"')
            else:
                query_parts.append(
                    f'(go.BP:"{go_id}" OR go.MF:"{go_id}" OR go.CC:"{go_id}")'
                )
        
        # GO term name search
        if go_name:
            if aspect:
                query_parts.append(f'go.{aspect}.term:"{go_name}"')
            else:
                query_parts.append(
                    f'(go.BP.term:"{go_name}" OR '
                    f'go.MF.term:"{go_name}" OR '
                    f'go.CC.term:"{go_name}")'
                )
        
        # Evidence code filtering
        if evidence_codes:
            evidence_query = " OR ".join([f'go.evidence:"{code}"' for code in evidence_codes])
            query_parts.append(f'({evidence_query})')
        
        # Qualifier filtering (enables, NOT, contributes_to)
        if qualifier:
            query_parts.append(f'go.qualifier:"{qualifier}"')
        
        if not query_parts:
            query_parts.append("_exists_:go")
        
        q = " AND ".join(query_parts)
        
        params = {
            "q": q,
            "fields": "symbol,name,entrezgene,go",
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
    
    async def get_gene_go_annotations(
        self,
        client: MyGeneClient,
        gene_id: str,
        aspect: Optional[str] = None,
        evidence_codes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get GO annotations with evidence codes."""
        fields = "symbol,name,entrezgene,go"
        
        result = await client.get(f"gene/{gene_id}", params={"fields": fields})
        
        go_annotations = {
            "gene_id": gene_id,
            "symbol": result.get("symbol"),
            "name": result.get("name"),
            "annotations": {
                "BP": [],  # Biological Process
                "MF": [],  # Molecular Function
                "CC": []   # Cellular Component
            }
        }
        
        if "go" in result:
            go_data = result["go"]
            
            for go_aspect in ["BP", "MF", "CC"]:
                if aspect and go_aspect != aspect:
                    continue
                
                if go_aspect in go_data:
                    aspect_data = go_data[go_aspect]
                    
                    # Handle both list and single item
                    if not isinstance(aspect_data, list):
                        aspect_data = [aspect_data]
                    
                    for annotation in aspect_data:
                        # Filter by evidence codes if specified
                        if evidence_codes:
                            evidence = annotation.get("evidence")
                            if evidence not in evidence_codes:
                                continue
                        
                        go_annotations["annotations"][go_aspect].append({
                            "id": annotation.get("id"),
                            "term": annotation.get("term"),
                            "evidence": annotation.get("evidence"),
                            "qualifier": annotation.get("qualifier", []),
                            "pubmed": annotation.get("pubmed", [])
                        })
        
        # Count annotations
        total_annotations = sum(
            len(annotations) for annotations in go_annotations["annotations"].values()
        )
        
        return {
            "success": True,
            "total_annotations": total_annotations,
            "go_annotations": go_annotations
        }


GO_TOOLS = [
    types.Tool(
        name="query_genes_by_go_term",
        description="Find genes associated with specific GO terms and evidence",
        input_schema={
            "type": "object",
            "properties": {
                "go_id": {
                    "type": "string",
                    "description": "GO ID (e.g., 'GO:0006468' for protein phosphorylation)"
                },
                "go_name": {
                    "type": "string",
                    "description": "GO term name (e.g., 'protein kinase activity')"
                },
                "evidence_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence codes (e.g., ['EXP', 'IDA', 'IMP'])"
                },
                "qualifier": {
                    "type": "string",
                    "description": "GO qualifier",
                    "enum": ["enables", "NOT", "contributes_to", "involved_in", "located_in"]
                },
                "aspect": {
                    "type": "string",
                    "description": "GO aspect",
                    "enum": ["BP", "MF", "CC"]
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
        name="get_gene_go_annotations",
        description="Get detailed GO annotations for a gene with evidence codes",
        input_schema={
            "type": "object",
            "properties": {
                "gene_id": {
                    "type": "string",
                    "description": "Gene ID (Entrez, Ensembl, or symbol)"
                },
                "aspect": {
                    "type": "string",
                    "description": "Filter by GO aspect",
                    "enum": ["BP", "MF", "CC"]
                },
                "evidence_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by evidence codes"
                }
            },
            "required": ["gene_id"]
        }
    )
]