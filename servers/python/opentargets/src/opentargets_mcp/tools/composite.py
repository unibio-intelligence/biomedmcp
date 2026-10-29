"""
Composite tools for OpenTargets Platform - Intent-driven, workflow-oriented tools.

This module provides high-level tools that combine multiple GraphQL queries
to support common research workflows, rather than exposing individual API endpoints.
"""

from typing import Any

from ..queries import OpenTargetsClient


class CompositeTools:
    """
    Intent-driven tools that intelligently combine multiple data sources.
    Designed for research workflows, not just API access.
    """

    # =========================================================================
    # Entity Discovery & Profiling
    # =========================================================================

    async def search_biomedical_entities(
        self,
        client: OpenTargetsClient,
        query: str,
        entity_types: list[str] | None = None,
        limit: int = 25,
        suggest: bool = True,
    ) -> dict[str, Any]:
        """
        Unified search across targets, diseases, and drugs with optional suggestions.

        Args:
            query: Search term (gene symbol, disease name, drug name)
            entity_types: Filter by types: ["target", "disease", "drug"]. Default: all types
            limit: Max results per entity type (1-100)
            suggest: Include autocomplete suggestions

        Returns:
            {
                "results": {
                    "targets": [...],
                    "diseases": [...],
                    "drugs": [...]
                },
                "suggestions": [...] if suggest=True
            }
        """
        if entity_types is None:
            entity_types = ["target", "disease", "drug"]

        limit = max(1, min(limit, 100))

        # Build unified search query
        graphql_query = """
        query UnifiedSearch($queryString: String!, $pageSize: Int!) {
            search(queryString: $queryString, page: {index: 0, size: $pageSize}) {
                total
                hits {
                    id
                    entity
                    name
                    description
                    score
                }
            }
        }
        """

        result = await client._query(
            graphql_query, {"queryString": query, "pageSize": limit * len(entity_types)}
        )

        # Organize by entity type
        organized = {
            "results": {"targets": [], "diseases": [], "drugs": []},
            "query": query,
            "total_hits": result.get("search", {}).get("total", 0),
        }

        for hit in result.get("search", {}).get("hits", []):
            entity_type = hit.get("entity", "").lower()
            if entity_type in entity_types:
                # Map entity type to plural key (target -> targets, etc.)
                plural_key = entity_type + "s"
                if plural_key in organized["results"]:
                    organized["results"][plural_key].append(hit)

        # Add suggestions if requested
        if suggest and query:
            suggestions_query = """
            query SearchSuggestions($queryString: String!) {
                search(queryString: $queryString, page: {index: 0, size: 5}) {
                    hits {
                        name
                        entity
                        score
                    }
                }
            }
            """
            suggestions_result = await client._query(suggestions_query, {"queryString": query})
            organized["suggestions"] = suggestions_result.get("search", {}).get("hits", [])

        return organized

    async def get_target_profile(
        self,
        client: OpenTargetsClient,
        ensembl_id: str,
        sections: list[str] | None = None,
        include_diseases: bool = True,
        include_drugs: bool = True,
        top_n_associations: int = 10,
    ) -> dict[str, Any]:
        """
        Get comprehensive target profile with flexible depth control.

        Args:
            ensembl_id: Ensembl gene ID (e.g., ENSG00000012048)
            sections: Data sections to include:
                - "identity": Basic info, synonyms, genomic location
                - "biology": Pathways, GO terms, expression
                - "safety": Safety information, adverse events
                - "tractability": Druggability assessment
                - "interactions": Protein-protein interactions
                Default: ["identity", "biology"]
            include_diseases: Include associated diseases (top N)
            include_drugs: Include known drugs
            top_n_associations: Number of top disease associations to include (1-100)

        Returns:
            Composite profile with requested sections
        """
        if sections is None:
            sections = ["identity", "biology"]

        from biomedmcp.native.opentargets import acquire_section

        profile = {"ensembl_id": ensembl_id, "sections_included": sections}

        # Build dynamic GraphQL query based on requested sections
        query_fragments = []

        # Always include basic identity
        query_fragments.append("""
            id
            approvedSymbol
            approvedName
            biotype
            functionDescriptions
        """)

        if "identity" in sections:
            query_fragments.append("""
                synonyms { label, source }
                genomicLocation { chromosome, start, end, strand }
                proteinIds { id, source }
                alternativeGenes
                transcriptIds
            """)

        if "biology" in sections:
            query_fragments.append("""
                geneOntology {
                    aspect
                    term { id, label }
                }
                pathways { pathway, pathwayId }
                baselineExpression { count rows { unit median min max q1 q3 datasourceId datatypeId tissueBiosampleFromSource celltypeBiosampleFromSource tissueBiosample { biosampleId biosampleName } } }
            """)

        if "safety" in sections:
            query_fragments.append("""
                safetyLiabilities {
                    event
                    effects { direction, dosing }
                    datasource
                }
            """)

        if "tractability" in sections:
            query_fragments.append("""
                tractability {
                    label
                    modality
                    value
                }
            """)

        if "interactions" in sections:
            query_fragments.append("""
                interactions {
                    count
                    rows { intA targetB { approvedSymbol } count sourceDatabase }
                }
            """)

        # Main target query
        graphql_query = f"""
        query TargetProfile($ensemblId: String!) {{
            target(ensemblId: $ensemblId) {{
                {" ".join(query_fragments)}
            }}
        }}
        """

        result = await client._query(graphql_query, {"ensemblId": ensembl_id})
        profile["target"] = result.get("target", {})
        profile["section_outcomes"] = {"target": {"outcome": "data"}}

        # Add associated diseases if requested
        if include_diseases:
            diseases_query = """
            query TargetDiseases($ensemblId: String!, $size: Int!) {
                target(ensemblId: $ensemblId) {
                    associatedDiseases(page: {index: 0, size: $size}) {
                        count
                        rows {
                            disease { id, name }
                            score
                            datatypeScores { id, score }
                        }
                    }
                }
            }
            """
            diseases_result, status = await acquire_section(
                lambda: client._query(
                    diseases_query, {"ensemblId": ensembl_id, "size": min(top_n_associations, 100)}
                )
            )
            profile["associated_diseases"] = (
                diseases_result.get("target", {}).get("associatedDiseases", {})
                if diseases_result is not None
                else None
            )
            profile["section_outcomes"]["associated_diseases"] = status

        # Add known drugs if requested
        if include_drugs:
            drugs_query = """
        query TargetDrugs($ensemblId: String!) { target(ensemblId: $ensemblId) { drugAndClinicalCandidates { count rows { id maxClinicalStage drug { id name drugType maximumClinicalStage } diseases { diseaseFromSource disease { id name } } clinicalReports { id source clinicalStage trialPhase trialOverallStatus url } } } } }
        """
            drugs_result, status = await acquire_section(
                lambda: client._query(drugs_query, {"ensemblId": ensembl_id})
            )
            profile["clinical_candidates"] = (
                drugs_result.get("target", {}).get("drugAndClinicalCandidates", {})
                if drugs_result is not None
                else None
            )
            profile["section_outcomes"]["clinical_candidates"] = status

        return profile

    async def get_disease_profile(
        self,
        client: OpenTargetsClient,
        efo_id: str,
        sections: list[str] | None = None,
        top_n_targets: int = 10,
    ) -> dict[str, Any]:
        """
        Get comprehensive disease profile with flexible depth control.

        Args:
            efo_id: EFO disease ID (e.g., EFO_0000305)
            sections: Data sections to include:
                - "identity": Basic info, synonyms, therapeutic areas
                - "targets": Associated targets with scores
                - "phenotypes": HPO phenotype associations
                - "otar_projects": OTAR research projects
                Default: ["identity", "targets"]
            top_n_targets: Number of top target associations (1-100)

        Returns:
            Composite disease profile with requested sections
        """
        if sections is None:
            sections = ["identity", "targets"]

        from biomedmcp.native.opentargets import acquire_section

        profile = {"efo_id": efo_id, "sections_included": sections}

        # Build dynamic query
        query_fragments = []

        # Always include basic identity
        query_fragments.append("""
            id
            name
            description
        """)

        if "identity" in sections:
            query_fragments.append("""
                synonyms {
                    relation
                    terms
                }
                therapeuticAreas {
                    id
                    name
                }
                dbXRefs
            """)

        if "phenotypes" in sections:
            query_fragments.append("""
                phenotypes {
                    rows {
                        phenotypeHPO { id, name }
                        evidence { resource }
                    }
                }
            """)

        if "otar_projects" in sections:
            query_fragments.append("""
                otarProjects {
                    otarCode
                    projectName
                    reference
                    status
                    integratesInPPP
                }
            """)

        # Main disease query
        graphql_query = f"""
        query DiseaseProfile($efoId: String!) {{
            disease(efoId: $efoId) {{
                {" ".join(query_fragments)}
            }}
        }}
        """

        result = await client._query(graphql_query, {"efoId": efo_id})
        profile["disease"] = result.get("disease", {})
        profile["section_outcomes"] = {"disease": {"outcome": "data"}}

        # Add associated targets if requested
        if "targets" in sections:
            targets_query = """
            query DiseaseTargets($efoId: String!, $size: Int!) {
                disease(efoId: $efoId) {
                    associatedTargets(page: {index: 0, size: $size}) {
                        count
                        rows {
                            target { id, approvedSymbol, approvedName }
                            score
                            datatypeScores { id, score }
                        }
                    }
                }
            }
            """
            targets_result, status = await acquire_section(
                lambda: client._query(targets_query, {"efoId": efo_id, "size": min(top_n_targets, 100)})
            )
            profile["associated_targets"] = (
                targets_result.get("disease", {}).get("associatedTargets", {})
                if targets_result is not None
                else None
            )
            profile["section_outcomes"]["associated_targets"] = status

        return profile

    # =========================================================================
    # Association & Evidence Analysis
    # =========================================================================

    async def analyze_target_disease_association(
        self,
        client: OpenTargetsClient,
        ensembl_id: str,
        efo_id: str,
        evidence_types: list[str] | None = None,
        include_biomarkers: bool = True,
        min_score: float = 0.0,
        limit: int = 100,
        evidence_cursor: str | None = None,
    ) -> dict[str, Any]:
        """
        Deep analysis of target-disease association with comprehensive evidence.

        Args:
            ensembl_id: Target Ensembl ID
            efo_id: Disease EFO ID
            evidence_types: Filter evidence types (default: all)
            include_biomarkers: Include biomarker information
            min_score: Minimum evidence score threshold (0.0-1.0)

        Returns:
            Comprehensive association analysis with scored evidence
        """
        import math

        from biomedmcp.errors import ResearchError
        from biomedmcp.native.opentargets import acquire_section
        from biomedmcp.native.shapes import invalid_shape

        if (
            type(min_score) not in {int, float}
            or not math.isfinite(min_score)
            or not 0 <= min_score <= 1
            or type(limit) is not int
            or not 1 <= limit <= 100
            or evidence_types is not None
            and (
                not isinstance(evidence_types, list)
                or any(not isinstance(value, str) or not value for value in evidence_types)
            )
            or evidence_cursor is not None
            and (not isinstance(evidence_cursor, str) or not evidence_cursor or len(evidence_cursor) > 8192)
        ):
            raise ResearchError("invalid_parameters", "Invalid bounded association request.")
        analysis = {"target_id": ensembl_id, "disease_id": efo_id, "min_score": min_score}
        assoc_query = """
        query AssociationScore($efoId: String!, $ensemblId: String!) {
            disease(efoId: $efoId) {
                associatedTargets(Bs: [$ensemblId], page: {index: 0, size: 1}) {
                    count
                    rows { target { id } score datatypeScores { id score } }
                }
            }
        }
        """

        async def matched_association():
            result = await client._query(assoc_query, {"efoId": efo_id, "ensemblId": ensembl_id})
            page = result["disease"]["associatedTargets"]
            if (
                page["count"] != len(page["rows"])
                or len(page["rows"]) > 1
                or any(row["target"]["id"] != ensembl_id for row in page["rows"])
            ):
                invalid_shape()
            return result

        assoc_result, assoc_status = await acquire_section(matched_association)
        rows = assoc_result["disease"]["associatedTargets"]["rows"] if assoc_result is not None else None
        association = rows[0] if rows else None
        analysis["association_status"] = (
            "unavailable" if rows is None else "reported" if association else "not_indexed"
        )
        analysis["overall_score"] = association["score"] if association else None
        analysis["datatype_scores"] = association["datatypeScores"] if association else None
        analysis["association_record"] = association
        analysis["section_outcomes"] = {"association_record": assoc_status}
        analysis["warnings"] = [
            "Missing indexed associations do not establish biological absence; an unreported score remains null.",
            "Overall association scores combine evidence types and are not genetic-specific scores or proof of causality.",
            "Displayed evidence may be filtered or paged; counts refer to the specified provider window.",
        ]

        evidence_query = """
        query TargetDiseaseEvidence($ensemblId: String!, $efoId: String!, $size: Int!, $cursor: String) {
            target(ensemblId: $ensemblId) {
                evidences(efoIds: [$efoId], size: $size, cursor: $cursor) {
                    count
                    cursor
                    rows {
                        id target { id } disease { id name }
                        score datasourceId datatypeId literature
                        biomarkerList { name description }
                    }
                }
            }
        }
        """

        async def matched_evidence():
            result = await client._query(
                evidence_query,
                {
                    "ensemblId": ensembl_id,
                    "efoId": efo_id,
                    "size": limit,
                    "cursor": evidence_cursor,
                },
            )
            page = result["target"]["evidences"]
            rows = page["rows"]
            if (
                len(rows) > limit
                or len(rows) > page["count"]
                or len({row["id"] for row in rows}) != len(rows)
                or any(ev["target"]["id"] != ensembl_id or ev["disease"]["id"] != efo_id for ev in rows)
            ):
                invalid_shape()
            if page["cursor"] is not None and (
                not page["cursor"] or page["cursor"] == evidence_cursor or len(page["cursor"]) > 8192
            ):
                invalid_shape()
            return result

        evidence_result, evidence_status = await acquire_section(matched_evidence)
        analysis["section_outcomes"]["evidence"] = evidence_status
        if assoc_result is None and evidence_result is None:
            failures = [assoc_status["error"], evidence_status["error"]]
            codes = {error["code"] for error in failures}
            raise ResearchError(
                next(iter(codes)) if len(codes) == 1 else "source_unavailable",
                "No requested Open Targets pair evidence was acquired.",
                retryable=any(error["retryable"] for error in failures),
            )
        if evidence_result is None:
            analysis.update({"evidence": None, "evidence_count": None, "coverage": None})
            if include_biomarkers:
                analysis["biomarkers"] = None
            return analysis
        page = evidence_result["target"]["evidences"]
        evidences = page["rows"]
        filtered = [
            ev
            for ev in evidences
            if ev["score"] >= min_score and (evidence_types is None or ev["datatypeId"] in evidence_types)
        ]
        analysis["evidence_count"] = len(filtered)
        analysis["evidence"] = filtered
        analysis["coverage"] = {
            "provider_total": page["count"],
            "acquired_rows": len(evidences),
            "returned_rows": len(filtered),
            "requested_page_size": limit,
            "filtered": min_score > 0 or evidence_types is not None,
            "exhaustive": evidence_cursor is None
            and page["cursor"] is None
            and page["count"] == len(evidences),
        }
        if include_biomarkers:
            analysis["biomarkers"] = [
                {"evidence_id": ev["id"], "annotations": ev["biomarkerList"]}
                for ev in filtered
                if ev["biomarkerList"] is not None
            ]
            analysis["warnings"].append(
                "Biomarkers retain only reported biomarkerList annotations from displayed evidence; this is not an exhaustive biomarker search."
            )
        missing_cursor = evidence_cursor is None and page["cursor"] is None and page["count"] > len(evidences)
        analysis["coverage"]["has_continuation"] = page["cursor"] is not None
        analysis["coverage"]["continuation_status"] = (
            "provider_token"
            if page["cursor"] is not None
            else "unavailable"
            if missing_cursor
            else "terminal"
        )
        if missing_cursor:
            analysis["section_outcomes"]["evidence"] = {"outcome": "partial"}
            analysis["warnings"].append(
                "The first source window is incomplete and has no continuation token; omitted pair evidence is unavailable."
            )
        if page["cursor"] is not None:
            request = {
                "source_id": ensembl_id,
                "target_id": efo_id,
                "association_type": "target-disease",
                "min_score": min_score,
                "include_biomarkers": include_biomarkers,
                "limit": limit,
            }
            if evidence_types is not None:
                request["evidence_types"] = list(evidence_types)
            analysis["_provider_pages"] = {
                "pair_evidence": {
                    "next_token": page["cursor"],
                    "raw_count": len(evidences),
                    "request": request,
                }
            }
        return analysis

    async def discover_therapeutic_opportunities(
        self,
        client: OpenTargetsClient,
        disease_id: str,
        filters: dict[str, Any] | None = None,
        ranking_strategy: str = "genetic_evidence",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Rank an acquired direct-association window by its reported genetic component."""
        from biomedmcp.native.opentargets_workflows import (
            bounded,
            invalid_request,
            prioritize_targets,
            unit_interval,
        )

        if (
            ranking_strategy != "genetic_evidence"
            or filters is not None
            and (not isinstance(filters, dict) or set(filters) - {"min_score"})
        ):
            invalid_request()
        bounded(limit)
        threshold = (filters or {}).get("min_score", 0.0)
        unit_interval(threshold)
        result = await prioritize_targets(client, disease_id, limit=100)
        ranked = result["ranked_targets"]
        selected = [row for row in ranked if row["genetic_association_score"] >= threshold]
        result["ranked_targets"] = selected[:limit]
        result["filtering"] = {
            "genetic_min_score": threshold,
            "excluded_below_threshold": len(ranked) - len(selected),
        }
        result["coverage"]["eligible_genetic_rows"] = len(selected)
        result["coverage"]["returned_ranked_rows"] = len(result["ranked_targets"])
        return result

    # =========================================================================
    # Drug Mechanism Tools
    # =========================================================================

    async def explore_drug_mechanism(
        self,
        client: OpenTargetsClient,
        drug_id: str,
        include_targets: bool = True,
        include_indications: bool = True,
        include_adverse_events: bool = False,
    ) -> dict[str, Any]:
        """
        Explore drug mechanism of action, targets, and clinical applications.

        Args:
            drug_id: ChEMBL ID (e.g., CHEMBL1234)
            include_targets: Include target information
            include_indications: Include disease indications
            include_adverse_events: Include adverse event data

        Returns:
            Comprehensive drug mechanism profile
        """
        mechanism = {"drug_id": drug_id}
        from biomedmcp.native.opentargets import acquire_section

        # Get drug information with mechanism
        drug_query = """
        query DrugMechanism($chemblId: String!) {
            drug(chemblId: $chemblId) {
                id
                name
                description
                maximumClinicalStage


            }
        }
        """

        result = await client._query(drug_query, {"chemblId": drug_id})
        mechanism["drug"] = result.get("drug", {})
        mechanism["section_outcomes"] = {"drug": {"outcome": "data"}}

        # Get mechanism of action and targets
        if include_targets:
            moa_query = """
        query DrugTargets($chemblId: String!) { drug(chemblId: $chemblId) { id name mechanismsOfAction { rows { mechanismOfAction targetName actionType targets { id approvedSymbol approvedName biotype } references { source ids urls } } } } }
        """
            moa_result, status = await acquire_section(
                lambda: client._query(moa_query, {"chemblId": drug_id})
            )
            drug_data = moa_result.get("drug", {}) if moa_result is not None else None
            moa = drug_data.get("mechanismsOfAction") if drug_data is not None else None
            mechanism["targets"] = (
                [target for row in moa["rows"] for target in row.get("targets", [])]
                if moa is not None
                else None
            )
            mechanism["mechanisms_of_action"] = moa
            mechanism["section_outcomes"]["mechanisms_of_action"] = status

        # Get disease indications
        if include_indications:
            indications_query = """
        query DrugIndications($chemblId: String!) { drug(chemblId: $chemblId) { id name indications { count rows { id maxClinicalStage disease { id name therapeuticAreas { id name } } clinicalReports { id source clinicalStage url } } } } }
        """
            ind_result, status = await acquire_section(
                lambda: client._query(indications_query, {"chemblId": drug_id})
            )
            mechanism["indications"] = (
                ind_result.get("drug", {}).get("indications") if ind_result is not None else None
            )
            mechanism["section_outcomes"]["indications"] = status

        # Get adverse events
        if include_adverse_events:
            # Note: Would query adverse events if available in GraphQL schema
            from .drug.safety import DrugSafetyApi

            value, status = await acquire_section(
                lambda: DrugSafetyApi().get_drug_adverse_events(client, drug_id)
            )
            mechanism["adverse_events"] = value
            mechanism["section_outcomes"]["adverse_events"] = status

        return mechanism

    # =========================================================================
    # Variant & Study Tools
    # =========================================================================

    async def explore_gwas_studies(
        self,
        client: OpenTargetsClient,
        trait: str | None = None,
        gene_id: str | None = None,
        limit: int = 25,
        page_index: int = 0,
        include_credible_sets: bool = True,
    ) -> dict[str, Any]:
        """Retrieve gene-linked credible sets or studies for one indexed disease ID."""
        from biomedmcp.native.opentargets_workflows import (
            bounded,
            disease_studies,
            gene_credible_sets,
            gene_studies,
            invalid_request,
        )

        bounded(limit)
        bounded(page_index, 0, 100000)
        if gene_id is not None and trait is None:
            return await (gene_credible_sets if include_credible_sets else gene_studies)(
                client, gene_id, limit, page_index
            )
        if trait is not None and gene_id is None:
            return await disease_studies(client, trait, limit, page_index, include_credible_sets)
        invalid_request()

    # =========================================================================
    # Advanced Analysis Tools
    # =========================================================================

    async def compare_targets(
        self, client: OpenTargetsClient, ensembl_ids: list[str], comparison_aspects: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Side-by-side comparison of multiple targets.

        Args:
            ensembl_ids: List of Ensembl IDs to compare (2-10)
            comparison_aspects: Aspects to compare:
                - "tractability": Druggability comparison
                - "safety": Safety profile comparison
                - "diseases": Disease association overlap
                - "pathways": Pathway membership
                Default: all aspects

        Returns:
            Comparative analysis matrix
        """
        import json
        import re

        from fastmcp.exceptions import ToolError

        from biomedmcp.errors import ResearchError, provider_boundary

        fields = {
            "tractability": "tractability { label modality value }",
            "safety": "safetyLiabilities { event datasource effects { direction dosing } }",
            "diseases": "associatedDiseases(page: {index: 0, size: 10}) { count rows { disease { id name } score datatypeScores { id score } } }",
            "pathways": "pathways { pathway pathwayId }",
        }
        aspects = list(fields) if comparison_aspects is None else comparison_aspects
        if (
            not isinstance(ensembl_ids, list)
            or not 2 <= len(ensembl_ids) <= 10
            or any(
                not isinstance(value, str) or not re.fullmatch(r"ENSG[0-9]{11}", value)
                for value in ensembl_ids
            )
            or len(set(ensembl_ids)) != len(ensembl_ids)
            or not isinstance(aspects, list)
            or not aspects
            or any(not isinstance(value, str) or value not in fields for value in aspects)
            or len(set(aspects)) != len(aspects)
        ):
            raise ResearchError(
                "invalid_parameters", "Compare 2–10 distinct human target IDs with supported aspects."
            )
        selection = " ".join(fields[a] for a in aspects)
        query = f"""query CompareTarget($ensemblId: String!) {{
            target(ensemblId: $ensemblId) {{ id approvedSymbol approvedName {selection} }}
        }}"""
        comparison = {
            "record_type": "opentargets_target_comparison",
            "targets": ensembl_ids,
            "comparison_aspects": aspects,
            "matrix": {},
            "section_outcomes": {},
            "coverage": {},
            "warnings": [
                "Compare retrieved source annotations; no clinically validated safety or efficacy ranking is computed.",
                "Empty annotations do not establish absence. Disease overlap is limited to each target's first 10 associations.",
            ],
        }
        for ens_id in ensembl_ids:
            try:
                with provider_boundary("opentargets"):
                    result = await client._query(query, {"ensemblId": ens_id})
            except ToolError as exc:
                comparison["section_outcomes"][ens_id] = {"outcome": "error", "error": json.loads(str(exc))}
                continue
            target_data = result["target"]
            comparison["matrix"][ens_id] = target_data
            comparison["section_outcomes"][ens_id] = {"outcome": "data"}
            if "diseases" in aspects:
                page = target_data["associatedDiseases"]
                comparison["coverage"][ens_id] = {
                    "provider_total": page["count"],
                    "returned_rows": len(page["rows"]),
                    "provider_page": 0,
                    "requested_page_size": 10,
                    "exhaustive": page["count"] == len(page["rows"]),
                }
        if not comparison["matrix"]:
            failures = [value["error"] for value in comparison["section_outcomes"].values()]
            codes = {error["code"] for error in failures}
            raise ResearchError(
                next(iter(codes)) if len(codes) == 1 else "source_unavailable",
                "No requested Open Targets comparison record was acquired.",
                retryable=any(error["retryable"] for error in failures),
            )
        return comparison

    async def find_similar_targets(
        self,
        client: OpenTargetsClient,
        ensembl_id: str,
        similarity_criteria: str = "pathways",
        limit: int = 10,
        threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Compare acquired annotation sets over bounded literature-model candidates."""
        from biomedmcp.native.opentargets_workflows import similar_targets

        return await similar_targets(client, ensembl_id, similarity_criteria, threshold, limit)

    async def build_target_validation_report(
        self, client: OpenTargetsClient, ensembl_id: str, disease_id: str | None = None
    ) -> dict[str, Any]:
        """
        Automated target validation workflow combining multiple data sources.

        Args:
            ensembl_id: Target Ensembl ID
            disease_id: Optional disease context for validation

        Returns:
            Traceable source evidence assessment; no clinical validation score
        """
        from biomedmcp.native.opentargets import acquire_section, assessment

        target_profile = await self.get_target_profile(
            client,
            ensembl_id,
            sections=["identity", "biology", "safety", "tractability"],
            include_diseases=True,
            include_drugs=True,
        )
        association = None
        association_status = None
        if disease_id:
            association, association_status = await acquire_section(
                lambda: self.analyze_target_disease_association(
                    client,
                    ensembl_id,
                    disease_id,
                    include_biomarkers=False,
                )
            )
        return assessment(target_profile, ensembl_id, disease_id, association, association_status)

    # =========================================================================
    # System Metadata
    # =========================================================================

    async def get_api_metadata(self, client: OpenTargetsClient) -> dict[str, Any]:
        """
        Get OpenTargets Platform API metadata and version information.

        Returns:
            API metadata including version, data releases, and capabilities
        """
        metadata_query = """
        query Metadata {
            meta {
                name
                apiVersion {
                    x
                    y
                    z
                }
                dataVersion {
                    year
                    month
                }
            }
        }
        """

        result = await client._query(metadata_query, {})
        metadata = result.get("meta", {})

        return {
            "platform": metadata.get("name", "Open Targets Platform"),
            "api_version": metadata.get("apiVersion", {}),
            "data_version": metadata.get("dataVersion", {}),
            "composite_tools_version": "1.0.0",
        }
