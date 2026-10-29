"""
Unified OpenTargets MCP Tools - Consolidates 42 tools into 5 flexible, parameter-driven tools.

This module provides high-level tools that intelligently route to underlying implementations
based on parameters, reducing tool count while maintaining full functionality.
"""

from typing import Any

from ..queries import OpenTargetsClient


class UnifiedTools:
    """
    Five unified tools that replace all 42 granular tools through parameter-based flexibility.
    Each tool is extensively documented to enable successful agent interaction.
    """

    def __init__(self):
        # Import dependencies lazily to avoid circular imports
        from .composite import CompositeTools
        from .disease import DiseaseApi
        from .drug import DrugApi
        from .evidence import EvidenceApi
        from .meta import MetaApi
        from .search import SearchApi
        from .study import StudyApi
        from .target import TargetApi
        from .variant import VariantApi

        self._composite = CompositeTools()
        self._target = TargetApi()
        self._disease = DiseaseApi()
        self._drug = DrugApi()
        self._evidence = EvidenceApi()
        self._search = SearchApi()
        self._variant = VariantApi()
        self._study = StudyApi()
        self._meta = MetaApi()

    # =========================================================================
    # TOOL 1: SEARCH
    # =========================================================================

    async def search(
        self,
        client: OpenTargetsClient,
        query: str,
        entity_types: list[str] | None = None,
        operation: str = "search",
        limit: int = 25,
        suggest: bool = False,
    ) -> dict[str, Any]:
        """
        Universal search across targets, diseases, and drugs with ID mapping and suggestions.

        This tool replaces:
        - search_biomedical_entities
        - map_ids

        Args:
            query (str): Search term (gene symbol, disease name, drug name, or ID to map)
            entity_types (list of str, optional): Filter by entity types. Pass as an ARRAY, not a JSON string.
                Valid values: ["target"], ["disease"], ["drug"], or combinations like ["target", "disease"]
                Default: None (searches all types)
                IMPORTANT: Pass ["target"] NOT "[\"target\"]"
            operation (str): Search mode - "search" (default), "map_ids", or "suggest"
                - "search": General search with optional suggestions
                - "map_ids": Resolve IDs/synonyms to canonical entities
                - "suggest": Autocomplete suggestions only
            limit (int): Maximum results to return (1-100, default: 25)
            suggest (bool): Include autocomplete suggestions with search results (default: False)

        Returns:
            dict: Unified search results with hits organized by entity type

        Examples:
            # Basic search for a gene (entity_types is an array)
            query="BRCA1", entity_types=["target"]

            # Search multiple entity types
            query="breast cancer", entity_types=["disease", "target"]

            # Search with suggestions
            query="breast cancer", suggest=True

            # ID mapping
            query="TP53", operation="map_ids"

            # Autocomplete only
            query="park", operation="suggest", limit=10
        """
        if operation == "map_ids":
            # Route to ID mapping
            return await self._meta.map_ids(client, query_terms=[query], entity_names=entity_types)

        elif operation == "suggest":
            # Route to autocomplete suggestions
            return await self._search.search_suggestions(
                client, query_prefix=query, entity_names=entity_types, max_suggestions=limit
            )

        else:  # operation == "search"
            # Route to unified biomedical search
            return await self._composite.search_biomedical_entities(
                client, query=query, entity_types=entity_types, limit=limit, suggest=suggest
            )

    # =========================================================================
    # TOOL 2: GET_ENTITY
    # =========================================================================

    async def get_entity(
        self,
        client: OpenTargetsClient,
        entity_type: str,
        entity_id: str,
        sections: list[str] | None = None,
        include_associations: bool = False,
        association_limit: int = 10,
    ) -> dict[str, Any]:
        """
        Retrieve comprehensive entity profile with flexible depth control.

        This tool replaces 21 specialized getters:
        - Target tools (15): get_target_profile, get_target_chemical_probes, get_target_depmap_essentiality,
          get_target_genetic_constraint, get_target_hallmarks, get_target_homologues, get_target_interactions,
          get_target_literature_occurrences, get_target_mouse_phenotypes, get_target_subcellular_locations,
          get_target_tep, get_target_alternative_genes, get_target_class, get_gene_ontology_terms
        - Disease tools (1): get_disease_profile
        - Drug tools (5): explore_drug_mechanism, get_drug_adverse_events, get_drug_cross_references,
          get_drug_pharmacovigilance, get_drug_warnings

        Args:
            entity_type (str): Type of entity - "target", "disease", or "drug"
            entity_id (str): Entity identifier (Ensembl ID for targets, EFO ID for diseases, ChEMBL ID for drugs)
            sections (list of str, optional): Data sections to include. Pass as an ARRAY, not a JSON string.
                Default: None (returns all applicable sections)
                IMPORTANT: Pass ["identity", "biology"] NOT "[\"identity\", \"biology\"]"

                TARGET sections:
                - "identity": Basic info, synonyms, genomic location, protein IDs
                - "biology": Pathways, GO terms, expression data
                - "safety": Safety liabilities, adverse events
                - "tractability": Druggability assessment
                - "interactions": Protein-protein interactions
                - "chemical_probes": Chemical probe data
                - "depmap": DepMap essentiality scores
                - "genetic_constraint": Genetic constraint metrics (gnomAD)
                - "hallmarks": Cancer hallmarks
                - "homologues": Ortholog information
                - "literature": Literature co-occurrence counts
                - "mouse_phenotypes": Mouse knockout phenotypes
                - "subcellular_locations": Cellular localization
                - "tep": Target Enabling Package status
                - "alternative_genes": Alternative gene symbols
                - "class": Target classification (enzyme, GPCR, etc.)

                DISEASE sections:
                - "identity": Basic info, synonyms, therapeutic areas
                - "targets": Associated targets with scores
                - "phenotypes": HPO phenotype annotations
                - "otar_projects": OTAR research projects

                DRUG sections:
                - "identity": Basic drug information
                - "mechanism": Mechanism of action details
                - "targets": Linked targets
                - "indications": Disease indications
                - "adverse_events": Adverse event data
                - "pharmacovigilance": Safety monitoring data
                - "warnings": Black box warnings and contraindications
                - "cross_references": External database IDs

            include_associations (bool): Include top associated entities (diseases for targets, targets for diseases/drugs)
            association_limit (int): Number of top associations to include (1-100, default: 10)

        Returns:
            dict: Comprehensive entity profile with requested data sections

        Examples:
            # Basic target info with biology (sections is an array)
            entity_type="target", entity_id="ENSG00000012048", sections=["identity", "biology"]

            # Full drug profile with safety data
            entity_type="drug", entity_id="CHEMBL1234", sections=["identity", "mechanism", "adverse_events", "warnings"]

            # Disease with top associated targets
            entity_type="disease", entity_id="EFO_0000305", sections=["identity", "phenotypes"], include_associations=True, association_limit=20

            # Target with all specialized data
            entity_type="target", entity_id="ENSG00000141510", sections=["identity", "depmap", "genetic_constraint", "hallmarks"]

            # Get all available data (no sections specified)
            entity_type="target", entity_id="ENSG00000079112"
        """
        if entity_type == "target":
            return await self._get_target_entity(
                client, entity_id, sections, include_associations, association_limit
            )
        elif entity_type == "disease":
            return await self._get_disease_entity(
                client, entity_id, sections, include_associations, association_limit
            )
        elif entity_type == "drug":
            return await self._get_drug_entity(
                client, entity_id, sections, include_associations, association_limit
            )
        else:
            return {"error": f"Invalid entity_type: {entity_type}. Must be 'target', 'disease', or 'drug'"}

    async def _get_target_entity(
        self,
        client: OpenTargetsClient,
        entity_id: str,
        sections: list[str] | None,
        include_associations: bool,
        association_limit: int,
    ) -> dict[str, Any]:
        """Internal handler for target entities."""
        # Use composite profile as base
        specialized_data = {}

        if sections is None:
            sections = ["identity", "biology"]

        # Map sections to profile sections and specialized calls
        profile_sections = []
        for section in sections:
            if section in ["identity", "biology", "safety", "tractability", "interactions"]:
                profile_sections.append(section)

        # Get base profile
        result = await self._composite.get_target_profile(
            client,
            ensembl_id=entity_id,
            sections=profile_sections if profile_sections else ["identity"],
            include_diseases=include_associations,
            include_drugs=False,
            top_n_associations=association_limit,
        )

        from biomedmcp.native.opentargets import acquire_section

        methods = {
            "chemical_probes": self._target.get_target_chemical_probes,
            "depmap": self._target.get_target_depmap_essentiality,
            "genetic_constraint": self._target.get_target_genetic_constraint,
            "hallmarks": self._target.get_target_hallmarks,
            "homologues": self._target.get_target_homologues,
            "literature": self._target.get_target_literature_occurrences,
            "mouse_phenotypes": self._target.get_target_mouse_phenotypes,
            "subcellular_locations": self._target.get_target_subcellular_locations,
            "tep": self._target.get_target_tep,
            "alternative_genes": self._target.get_target_alternative_genes,
            "class": self._target.get_target_class,
        }
        for name, method in methods.items():
            if name in sections:
                value, status = await acquire_section(lambda method=method: method(client, entity_id))
                specialized_data[name] = value
                result["section_outcomes"]["specialized/" + name] = status

        # Merge specialized data
        if specialized_data:
            result["specialized"] = specialized_data

        return result

    async def _get_disease_entity(
        self,
        client: OpenTargetsClient,
        entity_id: str,
        sections: list[str] | None,
        include_associations: bool,
        association_limit: int,
    ) -> dict[str, Any]:
        """Internal handler for disease entities."""
        if sections is None:
            sections = ["identity"]

        if include_associations and "targets" not in sections:
            sections = list(sections) + ["targets"]

        return await self._composite.get_disease_profile(
            client, efo_id=entity_id, sections=sections, top_n_targets=association_limit
        )

    async def _get_drug_entity(
        self,
        client: OpenTargetsClient,
        entity_id: str,
        sections: list[str] | None,
        include_associations: bool,
        association_limit: int,
    ) -> dict[str, Any]:
        """Internal handler for drug entities."""
        if sections is None:
            sections = ["identity", "mechanism"]

        # Get base drug mechanism
        result = await self._composite.explore_drug_mechanism(
            client,
            drug_id=entity_id,
            include_targets="mechanism" in sections or "targets" in sections or include_associations,
            include_indications="indications" in sections or include_associations,
            include_adverse_events="adverse_events" in sections,
        )

        from biomedmcp.native.opentargets import acquire_section

        specialized_data = {}
        if "adverse_events" in sections:
            # The composite already acquired this section; preserve it without another request.
            specialized_data["adverse_events"] = result["adverse_events"]
        methods = {
            "pharmacovigilance": self._drug.get_drug_pharmacovigilance,
            "warnings": self._drug.get_drug_warnings,
            "cross_references": self._drug.get_drug_cross_references,
        }
        for name, method in methods.items():
            if name in sections:
                value, status = await acquire_section(lambda method=method: method(client, entity_id))
                specialized_data[name] = value
                result["section_outcomes"]["specialized/" + name] = status

        if specialized_data:
            result["specialized"] = specialized_data

        return result

    # =========================================================================
    # TOOL 3: ANALYZE_ASSOCIATION
    # =========================================================================

    async def analyze_association(
        self,
        client: OpenTargetsClient,
        source_id: str,
        target_id: str | None = None,
        association_type: str = "target-disease",
        evidence_types: list[str] | None = None,
        min_score: float = 0.0,
        include_biomarkers: bool = True,
        ranking_strategy: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        evidence_cursor: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze associations and evidence between entities, or discover therapeutic opportunities.

        This tool replaces:
        - analyze_target_disease_association
        - get_target_disease_biomarkers
        - discover_therapeutic_opportunities
        - get_association_datasources

        Args:
            source_id (str): Source entity ID (target, disease, or drug)
            target_id (str, optional): Target entity ID (required for pair-specific analysis)
            association_type (str): Type of association to analyze:
                - "target-disease": Target-disease evidence and associations
                - "drug-target": Drug-target mechanism relationships
                - "drug-disease": Drug-disease indications
                - "discover-opportunities": Find and rank therapeutic targets for a disease
            evidence_types (list of str, optional): Filter by specific evidence types. Pass as an ARRAY.
                Examples: ["genetic_association"], ["somatic_mutation"], ["genetic_association", "known_drug"]
                IMPORTANT: Pass ["genetic_association"] NOT "[\"genetic_association\"]"
            min_score (float): Minimum association score threshold (0.0-1.0, default: 0.0)
            include_biomarkers (bool): Retain reported biomarkerList annotations from displayed evidence
            evidence_cursor (str, optional): Follow the service-signed target-disease next action unchanged.
                The action binds the original identities, filters, biomarker flag, limit and account.
            ranking_strategy (str, optional): Discovery supports "genetic_evidence",
                using the separately reported genetic_association component.
            filters (dict, optional): Discovery accepts only min_score for that component.
                Other modes reject discovery filters and ranking strategies.
            limit (int): Maximum results to return (1-100, default: 20)

        Returns:
            dict: Association analysis with evidence, scores, and optional biomarkers

        Examples:
            # Analyze specific target-disease pair
            source_id="ENSG00000012048", target_id="EFO_0000305", association_type="target-disease", include_biomarkers=True

            # Discover therapeutic opportunities for a disease
            source_id="EFO_0000305", association_type="discover-opportunities", ranking_strategy="genetic_evidence", limit=20

            # Filter by evidence type (evidence_types is an array)
            source_id="ENSG00000141510", target_id="EFO_0001645", association_type="target-disease", evidence_types=["genetic_association"], min_score=0.5

            # Multiple evidence types
            source_id="ENSG00000141510", target_id="EFO_0001645", evidence_types=["genetic_association", "somatic_mutation"]
        """
        from biomedmcp.native.opentargets_workflows import bounded, invalid_request, selector, unit_interval

        selector(source_id)
        bounded(limit)
        unit_interval(min_score)
        if (
            type(include_biomarkers) is not bool
            or not isinstance(association_type, str)
            or association_type
            not in {"discover-opportunities", "target-disease", "drug-target", "drug-disease"}
        ):
            invalid_request()
        if association_type == "discover-opportunities":
            if (
                target_id is not None
                or evidence_types is not None
                or evidence_cursor is not None
                or not include_biomarkers
            ):
                invalid_request()
            if filters is not None and (not isinstance(filters, dict) or set(filters) - {"min_score"}):
                invalid_request()
            if filters and "min_score" in filters and min_score != 0 and filters["min_score"] != min_score:
                invalid_request()
            filters = {"min_score": (filters or {}).get("min_score", min_score)}
            # Route to therapeutic opportunity discovery
            return await self._composite.discover_therapeutic_opportunities(
                client,
                disease_id=source_id,
                filters=filters,
                ranking_strategy=ranking_strategy or "genetic_evidence",
                limit=limit,
            )

        elif association_type == "target-disease":
            if target_id is None or ranking_strategy is not None or filters is not None:
                invalid_request()
            selector(target_id)

            # Route to target-disease association analysis
            return await self._composite.analyze_target_disease_association(
                client,
                ensembl_id=source_id,
                efo_id=target_id,
                evidence_types=evidence_types,
                include_biomarkers=include_biomarkers,
                min_score=min_score,
                limit=limit,
                evidence_cursor=evidence_cursor,
            )

        elif association_type in ["drug-target", "drug-disease"]:
            if (
                target_id is not None
                or evidence_types is not None
                or evidence_cursor is not None
                or min_score != 0
                or not include_biomarkers
                or ranking_strategy is not None
                or filters is not None
                or limit != 20
            ):
                invalid_request()
            # Use drug mechanism exploration
            return await self._composite.explore_drug_mechanism(
                client,
                drug_id=source_id,
                include_targets=(association_type == "drug-target"),
                include_indications=(association_type == "drug-disease"),
                include_adverse_events=False,
            )

        else:
            return {"error": f"Invalid association_type: {association_type}"}

    # =========================================================================
    # TOOL 4: QUERY_GENETICS
    # =========================================================================

    async def query_genetics(
        self,
        client: OpenTargetsClient,
        query_type: str,
        variant_id: str | None = None,
        study_id: str | None = None,
        credible_set_id: str | None = None,
        gene_id: str | None = None,
        disease_id: str | None = None,
        include_functional_consequences: bool = True,
        include_credible_sets: bool = False,
        include_pharmacogenomics: bool = False,
        include_evidences: bool = False,
        limit: int = 25,
        page_index: int = 0,
        evidence_cursor: str | None = None,
    ) -> dict[str, Any]:
        """
        Query genetic variants, GWAS studies, and credible sets.

        This tool replaces 10 genetics/variant tools:
        - analyze_genetic_variant, get_variant_info, get_variant_evidences,
          get_variant_credible_sets, get_variant_pharmacogenomics
        - explore_gwas_studies, get_studies_by_disease, get_study_info,
          get_study_credible_sets, get_credible_set_by_id

        Args:
            query_type (str): Type of genetics query:
                - "variant": Query variant information and annotations
                - "study": Query GWAS study information
                - "credible_set": Query fine-mapping credible sets
            variant_id (str, optional): Exact source variant ID, e.g. chromosome_position_ref_alt.
                rsIDs require a separately qualified identity lookup.
            study_id (str, optional): GWAS study identifier
            credible_set_id (str, optional): Credible set identifier
            gene_id (str, optional): Internal study discovery selector. Public gene genetics
                uses get(entity="gene", sections=["genetics"]) with qualified identity.
            disease_id (str, optional): One exact indexed disease ID for study discovery.
                Study mode requires exactly one of study_id, disease_id or gene_id.
            include_functional_consequences (bool): Include VEP functional predictions (variant queries)
            include_credible_sets (bool): Include associated credible sets (variant/study queries)
            include_pharmacogenomics (bool): Include pharmacogenomics data (variant queries)
            include_evidences (bool): Include evidence strings (variant queries)
            limit (int): Maximum results to return (1-100, default: 25)
            page_index (int): Source page index for paginated credible sets or study discovery.
            evidence_cursor (str, optional): Variant evidence continuation returned by the public service.
                It preserves the variant, flags and limit; it is independent of credible-set page_index.

        Returns:
            dict: Genetic data based on query type

        Examples:
            # Get variant information with all annotations
            query_type="variant", variant_id="7_140453136_A_T", include_functional_consequences=True, include_pharmacogenomics=True

            # Find GWAS studies for a disease
            query_type="study", disease_id="EFO_0000305", limit=50

            # Get credible set details
            query_type="credible_set", credible_set_id="CS123"

            # Variant evidence (no gene/disease filters are consumed in this mode)
            query_type="variant", variant_id="7_140453136_A_T", include_evidences=True
        """
        from biomedmcp.native.opentargets_workflows import bounded, invalid_request, selector

        bounded(limit)
        bounded(page_index, 0, 100000)
        from biomedmcp.native.opentargets_variant_evidence import credible_window, cursor_parameter, window

        cursor_parameter(evidence_cursor)
        if evidence_cursor is not None and (query_type != "variant" or not include_evidences):
            invalid_request()
        if any(
            type(flag) is not bool
            for flag in (
                include_functional_consequences,
                include_credible_sets,
                include_pharmacogenomics,
                include_evidences,
            )
        ):
            invalid_request()
        if query_type == "variant" and not variant_id:
            invalid_request()
        if query_type == "credible_set" and not credible_set_id:
            invalid_request()
        if not isinstance(query_type, str) or query_type not in {"variant", "study", "credible_set"}:
            invalid_request()
        for value in (variant_id, study_id, credible_set_id, disease_id):
            if value is not None:
                selector(value)
        if query_type == "variant":
            if (
                any(value is not None for value in (study_id, credible_set_id, gene_id, disease_id))
                or page_index
                and not include_credible_sets
                or limit != 25
                and not (include_credible_sets or include_evidences)
            ):
                invalid_request()
            result = await self._variant.get_variant_info(
                client, variant_id, include_functional_consequences=include_functional_consequences
            )
            from biomedmcp.native.opentargets import acquire_section

            result["section_outcomes"] = {"variant": {"outcome": "data"}}
            methods = {}
            if include_credible_sets:

                async def credible_page():
                    payload = await self._variant.get_variant_credible_sets(
                        client, variant_id, page_index=page_index, page_size=limit
                    )
                    return credible_window(payload, variant_id, limit, page_index)

                methods["credible_sets"] = credible_page
            if include_pharmacogenomics:
                methods["pharmacogenomics"] = lambda: self._variant.get_variant_pharmacogenomics(
                    client, variant_id
                )
            if include_evidences:

                async def evidence_window():
                    payload = await self._variant.get_variant_evidences(
                        client, variant_id, size=limit, cursor=evidence_cursor
                    )
                    value, outcome = window(payload, variant_id, limit, evidence_cursor)
                    value["_window_outcome"] = outcome
                    return value

                methods["evidences"] = evidence_window
            for name, method in methods.items():
                value, status = await acquire_section(method)
                if name == "evidences" and value is not None:
                    outcome = value.pop("_window_outcome")
                    if outcome == "partial":
                        status = {"outcome": outcome}
                    page = value.pop("_provider_page", None)
                    if page is not None:
                        result["_provider_pages"] = {"variant_evidence": page}
                result[name] = value
                result["section_outcomes"][name] = status
            return result

        elif query_type == "study":
            if (
                variant_id is not None
                or credible_set_id is not None
                or include_pharmacogenomics
                or include_evidences
                or not include_functional_consequences
            ):
                invalid_request()
            from biomedmcp.native.opentargets_workflows import bounded, invalid_request

            bounded(limit)
            bounded(page_index, 0, 100000)
            if (
                sum(value is not None for value in (study_id, disease_id, gene_id)) != 1
                or study_id is not None
                and not include_credible_sets
                and (page_index or limit != 25)
            ):
                invalid_request()
            if gene_id is not None or disease_id is not None:
                return await self._composite.explore_gwas_studies(
                    client,
                    trait=disease_id,
                    gene_id=gene_id,
                    limit=limit,
                    page_index=page_index,
                    include_credible_sets=include_credible_sets,
                )
            result = await self._study.get_study_info(client, study_id)
            from biomedmcp.native.opentargets_workflows import checked_study_counts

            checked_study_counts(result["study"])
            if include_credible_sets:
                from biomedmcp.native.opentargets import acquire_section
                from biomedmcp.native.opentargets_workflows import study_credible_sets

                value, status = await acquire_section(
                    lambda: study_credible_sets(client, study_id, limit, page_index)
                )
                result["credible_sets"] = value
                result["section_outcomes"] = {"study": {"outcome": "data"}, "credible_sets": status}
            return result

        elif query_type == "credible_set":
            if (
                any(value is not None for value in (variant_id, study_id, gene_id, disease_id))
                or page_index
                or limit != 25
                or include_credible_sets
                or include_pharmacogenomics
                or include_evidences
                or not include_functional_consequences
            ):
                invalid_request()
            return await self._study.get_credible_set_by_id(client, credible_set_id)

    # =========================================================================
    # TOOL 5: ANALYZE_ADVANCED
    # =========================================================================

    async def analyze_advanced(
        self,
        client: OpenTargetsClient,
        analysis_type: str,
        entity_ids: list[str],
        disease_id: str | None = None,
        similarity_criteria: str = "pathways",
        comparison_aspects: list[str] | None = None,
        threshold: float = 0.5,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Advanced analyses: compare targets, find similar entities, validate targets, prioritize.

        This tool replaces 5 advanced analysis tools:
        - compare_targets, find_similar_targets, build_target_validation_report,
          get_target_prioritization, get_api_metadata, get_interaction_resources

        Args:
            analysis_type (str): Type of advanced analysis:
                - "compare": Side-by-side comparison of multiple targets
                - "similar": Compare recorded annotation overlap within a bounded literature-model candidate window
                - "validate": Source evidence assessment with annotation counts and interpretation limits
                - "prioritize": Rank direct disease associations by their reported genetic component
                - "metadata": Get API and system metadata
            entity_ids (list of str): One or more entity IDs (targets for most analyses). Pass as an ARRAY.
                Examples: ["ENSG00000012048"], ["ENSG00000012048", "ENSG00000141510"]
                IMPORTANT: Pass ["ENSG00000012048"] NOT "[\"ENSG00000012048\"]"
            disease_id (str, optional): Disease context for validation/prioritization
            similarity_criteria (str): For similarity analysis:
                - "pathways": Similar pathway membership
                - "diseases": Similar disease associations
                - "go_terms": Similar GO term annotations
                - "interactions": Similar interaction partners
            comparison_aspects (list of str, optional): Aspects to compare (for compare mode). Pass as an ARRAY.
                Examples: ["tractability"], ["tractability", "safety"], ["diseases", "pathways"]
                Default: None (all aspects)
                IMPORTANT: Pass ["tractability", "safety"] NOT "[\"tractability\", \"safety\"]"
            threshold (float): Minimum annotation Jaccard for similar mode (0.0-1.0).
                Provider literature-model scores only discover candidates; they are not annotation overlap.
            limit (int): Display bound for similar/prioritize modes (1-100, default: 10).
                Other modes reject nondefault unrelated parameters. Prioritize accepts 0-10
                distinct targets; an empty array discovers within the bounded source window.

        Returns:
            dict: Analysis results based on analysis type

        Examples:
            # Compare multiple targets (entity_ids and comparison_aspects are arrays)
            analysis_type="compare", entity_ids=["ENSG00000012048", "ENSG00000141510"], comparison_aspects=["tractability", "safety"]

            # Find similar targets
            analysis_type="similar", entity_ids=["ENSG00000012048"], similarity_criteria="pathways", threshold=0.7, limit=20

            # Validate target for a disease
            analysis_type="validate", entity_ids=["ENSG00000141510"], disease_id="EFO_0000305"

            # Get API metadata
            analysis_type="metadata", entity_ids=[]
        """
        from biomedmcp.native.opentargets_workflows import advanced_request, prioritize_targets

        advanced_request(
            analysis_type, entity_ids, disease_id, similarity_criteria, comparison_aspects, threshold, limit
        )
        if analysis_type == "compare":
            if len(entity_ids) < 2:
                return {"error": "At least 2 entity_ids required for comparison"}

            return await self._composite.compare_targets(
                client, ensembl_ids=entity_ids, comparison_aspects=comparison_aspects
            )

        elif analysis_type == "similar":
            if len(entity_ids) != 1:
                return {"error": "Exactly 1 entity_id required for similarity analysis"}

            return await self._composite.find_similar_targets(
                client,
                ensembl_id=entity_ids[0],
                similarity_criteria=similarity_criteria,
                limit=limit,
                threshold=threshold,
            )

        elif analysis_type == "validate":
            if len(entity_ids) != 1:
                return {"error": "Exactly 1 entity_id required for validation"}

            return await self._composite.build_target_validation_report(
                client, ensembl_id=entity_ids[0], disease_id=disease_id
            )

        elif analysis_type == "prioritize":
            if not disease_id:
                return {"error": "disease_id required for prioritization"}

            return await prioritize_targets(client, disease_id, entity_ids, limit)

        elif analysis_type == "metadata":
            # Return API metadata
            return await self._composite.get_api_metadata(client)

        else:
            return {"error": f"Invalid analysis_type: {analysis_type}"}
