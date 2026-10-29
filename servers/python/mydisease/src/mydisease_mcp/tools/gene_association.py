"""Gene-disease association tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


from biomedmcp.native.biothings import partial_outcome


class GeneAssociationApi:
    """Tools for gene-disease associations."""

    async def get_diseases_by_gene(
        self,
        client: MyDiseaseClient,
        gene_symbol: str,
        source: Optional[str] = None,
        min_score: Optional[float] = None,
        size: int = 20,
    ) -> Dict[str, Any]:
        """Get diseases associated with a specific gene."""
        # Build query for gene
        query_parts = []

        # Search in multiple gene fields
        gene_fields = [
            f'gene.symbol:"{gene_symbol}"',
            f'causal_gene.symbol:"{gene_symbol}"',
            f'disgenet.gene.gene_name:"{gene_symbol}"',
            f'ctd.gene_info.symbol:"{gene_symbol}"',
        ]
        query_parts.append(f"({' OR '.join(gene_fields)})")

        if source:
            query_parts.append(f"_exists_:{source}")

        q = " AND ".join(query_parts)

        params = {"q": q, "fields": "_id,name,gene,causal_gene,disgenet.gene,ctd.gene_info", "size": size}

        result = await client.get("query", params=params)

        # Process results
        diseases = []
        for hit in result.get("hits", []):
            disease_info = {
                "disease_id": hit.get("_id"),
                "disease_name": hit.get("name"),
                "gene_associations": [],
            }

            # Extract gene associations from different sources
            if "gene" in hit:
                genes = hit["gene"] if isinstance(hit["gene"], list) else [hit["gene"]]
                for gene in genes:
                    if gene.get("symbol") == gene_symbol:
                        disease_info["gene_associations"].append(
                            {"source": "primary", "symbol": gene.get("symbol"), "id": gene.get("id")}
                        )

            if "causal_gene" in hit:
                causal = hit["causal_gene"] if isinstance(hit["causal_gene"], list) else [hit["causal_gene"]]
                for gene in causal:
                    if gene.get("symbol") == gene_symbol:
                        disease_info["gene_associations"].append(
                            {"source": "causal", "symbol": gene.get("symbol"), "relationship": "causal"}
                        )

            if "disgenet" in hit and "gene" in hit["disgenet"]:
                genes = hit["disgenet"]["gene"]
                genes = genes if isinstance(genes, list) else [genes]
                for gene in genes:
                    if gene.get("gene_name") == gene_symbol:
                        disease_info["gene_associations"].append(
                            {
                                "source": "disgenet",
                                "symbol": gene.get("gene_name"),
                                "score": gene.get("score"),
                                "gene_id": gene.get("gene_id"),
                            }
                        )

            if min_score is None or any(
                assoc.get("score", 1.0) >= min_score for assoc in disease_info["gene_associations"]
            ):
                diseases.append(disease_info)

        return {
            "success": True,
            "gene_symbol": gene_symbol,
            "total_diseases": len(diseases),
            "diseases": diseases,
        }

    async def get_disease_genes(
        self, client: MyDiseaseClient, disease_id: str, include_scores: bool = True
    ) -> Dict[str, Any]:
        """Get all genes associated with a disease."""
        params = {"fields": "gene,causal_gene,disgenet.gene,ctd.gene_info"}

        result = await client.get(f"disease/{disease_id}", params=params)

        genes = {"disease_id": disease_id, "primary_genes": [], "causal_genes": [], "associated_genes": []}

        # Extract primary genes
        if "gene" in result:
            primary = result["gene"] if isinstance(result["gene"], list) else [result["gene"]]
            genes["primary_genes"] = primary

        # Extract causal genes
        if "causal_gene" in result:
            causal = (
                result["causal_gene"] if isinstance(result["causal_gene"], list) else [result["causal_gene"]]
            )
            genes["causal_genes"] = causal

        # Extract DisGeNET associations
        if "disgenet" in result and "gene" in result["disgenet"]:
            disgenet = result["disgenet"]["gene"]
            disgenet = disgenet if isinstance(disgenet, list) else [disgenet]
            for gene in disgenet:
                genes["associated_genes"].append(
                    {
                        "source": "disgenet",
                        "symbol": gene.get("gene_name"),
                        "gene_id": gene.get("gene_id"),
                        "score": gene.get("score") if include_scores else None,
                        "pmids": gene.get("pmids", []),
                    }
                )

        # Extract CTD associations
        if "ctd" in result and "gene_info" in result["ctd"]:
            ctd = result["ctd"]["gene_info"]
            ctd = ctd if isinstance(ctd, list) else [ctd]
            for gene in ctd:
                genes["associated_genes"].append(
                    {
                        "source": "ctd",
                        "symbol": gene.get("symbol"),
                        "gene_id": gene.get("gene_id"),
                        "inference_score": gene.get("inference_score") if include_scores else None,
                    }
                )

        return {"success": True, "genes": genes}

    async def search_by_gene_panel(
        self, client: MyDiseaseClient, gene_symbols: List[str], match_all: bool = False, size: int = 50
    ) -> Dict[str, Any]:
        """Search diseases by a panel of genes."""
        # Build query for gene panel
        gene_queries = []
        for gene in gene_symbols:
            gene_queries.append(
                f'(gene.symbol:"{gene}" OR causal_gene.symbol:"{gene}" OR disgenet.gene.gene_name:"{gene}")'
            )

        operator = " AND " if match_all else " OR "
        q = operator.join(gene_queries)

        params = {"q": q, "fields": "_id,name,gene,causal_gene,disgenet.gene", "size": size}

        result = await client.get("query", params=params)

        # Process results to show which genes match
        diseases = []
        for hit in result.get("hits", []):
            matching_genes = set()

            # Check primary genes
            if "gene" in hit:
                genes = hit["gene"] if isinstance(hit["gene"], list) else [hit["gene"]]
                for gene in genes:
                    if gene.get("symbol") in gene_symbols:
                        matching_genes.add(gene.get("symbol"))

            # Check causal genes
            if "causal_gene" in hit:
                genes = hit["causal_gene"] if isinstance(hit["causal_gene"], list) else [hit["causal_gene"]]
                for gene in genes:
                    if gene.get("symbol") in gene_symbols:
                        matching_genes.add(gene.get("symbol"))

            # Check DisGeNET genes
            if "disgenet" in hit and "gene" in hit["disgenet"]:
                genes = hit["disgenet"]["gene"]
                genes = genes if isinstance(genes, list) else [genes]
                for gene in genes:
                    if gene.get("gene_name") in gene_symbols:
                        matching_genes.add(gene.get("gene_name"))

            diseases.append(
                {
                    "disease_id": hit.get("_id"),
                    "disease_name": hit.get("name"),
                    "matching_genes": list(matching_genes),
                    "match_count": len(matching_genes),
                }
            )

        # Sort by match count if using OR operator
        if not match_all:
            diseases.sort(key=lambda x: x["match_count"], reverse=True)

        return {
            "success": True,
            "gene_panel": gene_symbols,
            "match_mode": "all" if match_all else "any",
            "total_diseases": len(diseases),
            "diseases": diseases,
        }

    @partial_outcome
    async def get_gene_disease_evidence(
        self, client: MyDiseaseClient, gene_symbol: str, disease_id: str
    ) -> Dict[str, Any]:
        """Retrieve source assertions without inventing confidence or an aggregate score."""
        import re
        from biomedmcp.errors import ResearchError
        from biomedmcp.native.biothings import attribution, objects

        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,63}", gene_symbol):
            raise ResearchError("invalid_parameters", "Use a qualified gene symbol for annotation matching.")
        paths = {
            "gene": "symbol",
            "causal_gene": "symbol",
            "disgenet.genes_related_to_disease": "gene_name",
            "ctd.gene_info": "symbol",
        }
        row = await client.get(f"disease/{disease_id}", params={"fields": ",".join(paths)})
        matches = []
        available = []
        for path, symbol_field in paths.items():
            nodes = [row]
            for key in path.split("."):
                nodes = [item for node in nodes for item in objects(node.get(key))]
            if nodes:
                available.append(path)
            for index, node in enumerate(nodes):
                if node.get(symbol_field) == gene_symbol:
                    matches.append(
                        {
                            "source_field": path,
                            "reported_assertion": node,
                            "provenance": attribution(row, f"/{path.replace('.', '/')}/{index}"),
                        }
                    )
        return {
            "success": True,
            "status": "partial",
            "gene_symbol": gene_symbol,
            "requested_disease_id": disease_id,
            "record_id": row["_id"],
            "assertions": matches,
            "available_annotation_fields": available,
            "is_associated": None,
            "aggregate_score": None,
            "evidence_status": "reported_matches"
            if matches
            else "no_matches_in_available_annotations"
            if available
            else "unavailable",
            "limitations": [
                "Symbol matches do not independently qualify gene namespace or species.",
                "No causal, clinical or statistical confidence is inferred; absent annotations are not evidence of absence.",
            ],
        }


GENE_ASSOCIATION_TOOLS = [
    types.Tool(
        name="get_diseases_by_gene",
        description="Find diseases associated with a specific gene",
        input_schema={
            "type": "object",
            "properties": {
                "gene_symbol": {"type": "string", "description": "Gene symbol (e.g., 'BRCA1', 'TP53')"},
                "source": {
                    "type": "string",
                    "description": "Filter by data source (e.g., 'disgenet', 'ctd')",
                },
                "min_score": {"type": "number", "description": "Minimum association score"},
                "size": {"type": "integer", "description": "Number of results", "default": 20},
            },
            "required": ["gene_symbol"],
        },
    ),
    types.Tool(
        name="get_disease_genes",
        description="Get all genes associated with a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {"type": "string", "description": "Disease ID"},
                "include_scores": {
                    "type": "boolean",
                    "description": "Include association scores",
                    "default": True,
                },
            },
            "required": ["disease_id"],
        },
    ),
    types.Tool(
        name="search_by_gene_panel",
        description="Search diseases by a panel of genes",
        input_schema={
            "type": "object",
            "properties": {
                "gene_symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of gene symbols",
                },
                "match_all": {
                    "type": "boolean",
                    "description": "Require all genes to be associated",
                    "default": False,
                },
                "size": {"type": "integer", "description": "Number of results", "default": 50},
            },
            "required": ["gene_symbols"],
        },
    ),
    types.Tool(
        name="get_gene_disease_evidence",
        description="Retrieve reported gene–disease assertions without inferred confidence",
        input_schema={
            "type": "object",
            "properties": {
                "gene_symbol": {"type": "string", "description": "Gene symbol"},
                "disease_id": {"type": "string", "description": "Disease ID"},
            },
            "required": ["gene_symbol", "disease_id"],
        },
    ),
]
