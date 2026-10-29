"""Phenotype and clinical feature tools."""

from typing import Any, Dict, Optional, List
import mcp.types as types
from ..client import MyDiseaseClient


from biomedmcp.native.biothings import partial_outcome


class PhenotypeApi:
    """Tools for phenotype and clinical features."""

    async def get_disease_phenotypes(
        self, client: MyDiseaseClient, disease_id: str, include_frequency: bool = True
    ) -> Dict[str, Any]:
        """Get phenotypes/clinical features for a disease."""
        params = {"fields": "hpo,phenotype_related_to_disease,clinical_features"}

        result = await client.get(f"disease/{disease_id}", params=params)

        phenotypes = {"disease_id": disease_id, "hpo_phenotypes": [], "clinical_features": []}

        # Extract HPO phenotypes
        if "hpo" in result:
            hpo_data = result["hpo"]
            if isinstance(hpo_data, list):
                phenotypes["hpo_phenotypes"] = hpo_data
            elif isinstance(hpo_data, dict) and "phenotype" in hpo_data:
                phenotypes["hpo_phenotypes"] = hpo_data["phenotype"]

        # Extract phenotype relations
        if "phenotype_related_to_disease" in result:
            pheno_rel = result["phenotype_related_to_disease"]
            pheno_rel = pheno_rel if isinstance(pheno_rel, list) else [pheno_rel]

            for rel in pheno_rel:
                phenotypes["clinical_features"].append(
                    {
                        "hpo_id": rel.get("hpo_id"),
                        "hpo_term": rel.get("hpo_phenotype"),
                        "frequency": rel.get("frequency") if include_frequency else None,
                        "source": rel.get("source"),
                    }
                )

        # Extract general clinical features
        if "clinical_features" in result:
            features = result["clinical_features"]
            features = features if isinstance(features, list) else [features]
            phenotypes["clinical_features"].extend(features)

        return {"success": True, "phenotypes": phenotypes}

    async def search_by_hpo_term(
        self, client: MyDiseaseClient, hpo_id: str, include_descendants: bool = False, size: int = 20
    ) -> Dict[str, Any]:
        """Search diseases by HPO term."""
        # Build query
        if hpo_id.startswith("HP:"):
            q = f'hpo.hpo_id:"{hpo_id}" OR phenotype_related_to_disease.hpo_id:"{hpo_id}"'
        else:
            q = f'hpo.phenotype_name:"{hpo_id}" OR phenotype_related_to_disease.hpo_phenotype:"{hpo_id}"'

        params = {"q": q, "fields": "_id,name,hpo,phenotype_related_to_disease", "size": size}

        result = await client.get("query", params=params)

        # Process results
        diseases = []
        for hit in result.get("hits", []):
            disease_info = {
                "disease_id": hit.get("_id"),
                "disease_name": hit.get("name"),
                "phenotype_matches": [],
            }

            # Check HPO matches
            if "hpo" in hit:
                hpo = hit["hpo"]
                if isinstance(hpo, dict) and hpo.get("hpo_id") == hpo_id:
                    disease_info["phenotype_matches"].append(
                        {"source": "hpo", "hpo_id": hpo_id, "match_type": "exact"}
                    )

            # Check phenotype relations
            if "phenotype_related_to_disease" in hit:
                relations = hit["phenotype_related_to_disease"]
                relations = relations if isinstance(relations, list) else [relations]

                for rel in relations:
                    if rel.get("hpo_id") == hpo_id or rel.get("hpo_phenotype") == hpo_id:
                        disease_info["phenotype_matches"].append(
                            {
                                "source": "phenotype_relation",
                                "hpo_id": rel.get("hpo_id"),
                                "frequency": rel.get("frequency"),
                                "match_type": "exact",
                            }
                        )

            if disease_info["phenotype_matches"]:
                diseases.append(disease_info)

        return {"success": True, "hpo_term": hpo_id, "total_diseases": len(diseases), "diseases": diseases}

    @partial_outcome
    async def get_phenotype_similarity(
        self,
        client: MyDiseaseClient,
        phenotype_list: List[str],
        algorithm: str = "jaccard",
        min_similarity: float = 0.5,
        size: int = 20,
    ) -> Dict[str, Any]:
        """Rank annotation-set overlap within one source window, not clinical similarity."""
        import math
        import re
        from biomedmcp.errors import ResearchError
        from biomedmcp.native.biothings import attribution, objects, record, response_contract

        if (
            not phenotype_list
            or len(phenotype_list) > 100
            or any(not re.fullmatch(r"HP:[0-9]{7}", item) for item in phenotype_list)
            or algorithm not in {"jaccard", "dice"}
            or type(size) is not int
            or not 1 <= size <= 100
            or type(min_similarity) not in (int, float)
            or not math.isfinite(min_similarity)
            or not 0 <= min_similarity <= 1
        ):
            raise ResearchError(
                "invalid_parameters",
                "Use HPO identifiers, jaccard/dice, size 1–100 and a finite threshold 0–1.",
            )
        query = sorted(set(phenotype_list))
        terms = [
            f'{field}:"{identifier}"'
            for identifier in query
            for field in ("hpo.hpo_id", "phenotype_related_to_disease.hpo_id")
        ]
        raw = await client.get(
            "query",
            params={
                "q": " OR ".join(terms),
                "fields": "_id,name,hpo,phenotype_related_to_disease",
                "size": 100,
            },
        )
        response_contract("GET", "query", raw)
        scores, unavailable = [], []
        for hit in raw["hits"]:
            record(hit)
            annotations = objects(hit.get("hpo")) + objects(hit.get("phenotype_related_to_disease"))
            ids = {
                node["hpo_id"]
                for node in annotations
                if isinstance(node.get("hpo_id"), str) and re.fullmatch(r"HP:[0-9]{7}", node["hpo_id"])
            }
            if not ids:
                unavailable.append(hit["_id"])
                continue
            intersection = set(query) & ids
            denominator = len(set(query) | ids) if algorithm == "jaccard" else len(query) + len(ids)
            numerator = len(intersection) if algorithm == "jaccard" else 2 * len(intersection)
            score = numerator / denominator
            if score >= min_similarity:
                scores.append(
                    {
                        "disease_id": hit["_id"],
                        "disease_name": hit.get("name"),
                        "similarity_score": score,
                        "numerator": numerator,
                        "denominator": denominator,
                        "matching_phenotypes": sorted(intersection),
                        "total_phenotypes": len(ids),
                        "provenance": attribution(hit, "/query/hits"),
                    }
                )
        scores.sort(key=lambda row: (-row["similarity_score"], row["disease_id"]))
        return {
            "success": True,
            "status": "partial",
            "query_phenotypes": query,
            "algorithm": algorithm,
            "min_similarity": min_similarity,
            "diseases": scores[:size],
            "matches_in_window": len(scores),
            "returned": min(len(scores), size),
            "unavailable_annotation_ids": unavailable,
            "source_window": {
                "offset": 0,
                "size": 100,
                "examined": len(raw["hits"]),
                "source_total": raw["total"],
                "has_more": raw["total"] > len(raw["hits"]),
            },
            "limitations": [
                "Annotation-set overlap is not a clinical similarity or diagnosis.",
                "Ranking covers this source window; incomplete annotations and omitted windows cannot establish absence.",
            ],
        }

    @partial_outcome
    async def get_phenotype_frequency(
        self, client: MyDiseaseClient, disease_id: str, phenotype_id: str
    ) -> Dict[str, Any]:
        """Preserve every exact HPO annotation and its reported frequency units."""
        import re
        from biomedmcp.errors import ResearchError
        from biomedmcp.native.biothings import attribution, objects

        if not re.fullmatch(r"HP:[0-9]{7}", phenotype_id):
            raise ResearchError("invalid_parameters", "Use an exact HPO identifier for phenotype frequency.")
        row = await client.get(f"disease/{disease_id}", params={"fields": "phenotype_related_to_disease,hpo"})
        annotations = []
        for field in ("phenotype_related_to_disease", "hpo"):
            for index, node in enumerate(objects(row.get(field))):
                if node.get("hpo_id") == phenotype_id:
                    annotations.append(
                        {
                            "reported_annotation": node,
                            "frequency": node.get("frequency"),
                            "frequency_hp": node.get("frequency_hp"),
                            "measurement_status": "reported_value"
                            if node.get("frequency") is not None or node.get("frequency_hp") is not None
                            else "unavailable",
                            "provenance": attribution(row, f"/{field}/{index}"),
                        }
                    )
        return {
            "success": True,
            "status": "partial",
            "disease_id": disease_id,
            "record_id": row["_id"],
            "phenotype_id": phenotype_id,
            "annotations": annotations,
            "measurement_status": "reported_values"
            if any(item["measurement_status"] == "reported_value" for item in annotations)
            else "unavailable",
            "limitations": [
                "Reported frequency strings and HPO terms are preserved without conversion to percentages.",
                "Missing annotations or frequency measurements do not establish a negative result.",
            ],
        }


PHENOTYPE_TOOLS = [
    types.Tool(
        name="get_disease_phenotypes",
        description="Get phenotypes and clinical features for a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {"type": "string", "description": "Disease ID"},
                "include_frequency": {
                    "type": "boolean",
                    "description": "Include frequency information",
                    "default": True,
                },
            },
            "required": ["disease_id"],
        },
    ),
    types.Tool(
        name="search_by_hpo_term",
        description="Search diseases by HPO (Human Phenotype Ontology) term",
        input_schema={
            "type": "object",
            "properties": {
                "hpo_id": {"type": "string", "description": "HPO ID (e.g., 'HP:0001250') or term name"},
                "include_descendants": {
                    "type": "boolean",
                    "description": "Include descendant terms",
                    "default": False,
                },
                "size": {"type": "integer", "description": "Number of results", "default": 20},
            },
            "required": ["hpo_id"],
        },
    ),
    types.Tool(
        name="get_phenotype_similarity",
        description="Find diseases with similar phenotype profiles",
        input_schema={
            "type": "object",
            "properties": {
                "phenotype_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of phenotypes (HPO IDs or terms)",
                },
                "algorithm": {
                    "type": "string",
                    "description": "Similarity algorithm",
                    "default": "jaccard",
                    "enum": ["jaccard", "dice"],
                },
                "min_similarity": {
                    "type": "number",
                    "description": "Minimum similarity score (0-1)",
                    "default": 0.5,
                },
                "size": {"type": "integer", "description": "Number of results", "default": 20},
            },
            "required": ["phenotype_list"],
        },
    ),
    types.Tool(
        name="get_phenotype_frequency",
        description="Get frequency information for a phenotype in a disease",
        input_schema={
            "type": "object",
            "properties": {
                "disease_id": {"type": "string", "description": "Disease ID"},
                "phenotype_id": {"type": "string", "description": "Phenotype ID (HPO ID or term)"},
            },
            "required": ["disease_id", "phenotype_id"],
        },
    ),
]
