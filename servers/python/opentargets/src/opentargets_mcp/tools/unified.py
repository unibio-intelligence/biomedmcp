"""Public operation surface: entity records, advanced analyses, associations and genetics."""

from biomedmcp.errors import ResearchError
from biomedmcp.native.opentargets import acquire_section
from biomedmcp.native.opentargets_variant_evidence import credible_window, cursor_parameter, window
from biomedmcp.native.opentargets_workflows import (
    CREDIBLE_FIELDS,
    MAX_PROVIDER_PAGE,
    STUDY_FIELDS,
    advanced_request,
    bounded,
    checked_credible_rows,
    disease_studies,
    gene_credible_sets,
    gene_studies,
    invalid_request,
    prioritize_targets,
    selector,
    similar_targets,
    study_credible_sets,
    unit_interval,
)

from .composite import DRUG_RECORD, CompositeTools, chosen_sections, drug_indications, drug_mechanisms
from .drug.safety import DrugSafetyApi

LOCUS_EXTRA = "region beta zScore standardError credibleSetIndex credibleSetlog10BF purityMeanR2 purityMinR2"
VARIANT_INFO = (
    "query VariantInfo($variantId:String!,$functional:Boolean!,$pharmacogenomics:Boolean!){"
    "variant(variantId:$variantId){id variantDescription chromosome position referenceAllele alternateAllele "
    "hgvsId rsIds dbXrefs{id source} alleleFrequencies{populationName alleleFrequency} mostSevereConsequence{id label} "
    "transcriptConsequences @include(if:$functional){transcriptId isEnsemblCanonical impact consequenceScore "
    "aminoAcidChange lofteePrediction siftPrediction polyphenPrediction distanceFromTss distanceFromFootprint "
    "uniprotAccessions target{id approvedSymbol} variantConsequences{id label}} "
    "variantEffect @include(if:$functional){method assessment assessmentFlag score normalisedScore} "
    "pharmacogenomics @include(if:$pharmacogenomics){datasourceId evidenceLevel pgxCategory phenotypeText genotype "
    "genotypeId variantRsId isDirectTarget literature target{id approvedSymbol} drugs{drugId drugFromSource}}}}"
)
VARIANT_EVIDENCES = (
    "query VariantEvidences($variantId:String!,$size:Int!,$cursor:String){variant(variantId:$variantId){id "
    "evidences(size:$size,cursor:$cursor){count cursor rows{id score datasourceId datatypeId variantRsId "
    "variantFunctionalConsequence{id label} confidence literature studyId beta betaConfidenceIntervalLower "
    "betaConfidenceIntervalUpper pValueMantissa pValueExponent oddsRatio oddsRatioConfidenceIntervalLower "
    "oddsRatioConfidenceIntervalUpper target{id approvedSymbol} disease{id name}}}}}"
)
VARIANT_CREDIBLE_SETS = (
    "query VariantCredibleSets($variantId:String!,$pageIndex:Int!,$pageSize:Int!){variant(variantId:$variantId){id "
    f"credibleSets(page:{{index:$pageIndex,size:$pageSize}}){{count rows{{{CREDIBLE_FIELDS} {LOCUS_EXTRA}}}}}}}}}"
)
STUDY_INFO = (
    f"query StudyInfo($studyId:String!){{study(studyId:$studyId){{{STUDY_FIELDS} condition publicationTitle "
    "publicationJournal publicationFirstAuthor publicationDate cohorts hasSumstats summarystatsLocation "
    "initialSampleSize analysisFlags qualityControls ldPopulationStructure{ldPopulation relativeSampleSize} "
    "discoverySamples{ancestry sampleSize} replicationSamples{ancestry sampleSize} "
    "sumstatQCValues{QCCheckName QCCheckValue} biosample{biosampleId biosampleName} backgroundTraits{id name}}}"
)
CREDIBLE_SET = (
    "query CredibleSetInfo($studyLocusId:String!){credibleSet(studyLocusId:$studyLocusId){"
    f"{CREDIBLE_FIELDS} {LOCUS_EXTRA} locusStart locusEnd sampleSize isTransQtl effectAlleleFrequencyFromSource}}}}"
)
API_METADATA = (
    "query ApiMetadata{meta{name product apiVersion{x y z suffix} dataVersion{year month iteration}}}"
)
SEARCH_DRUGS = (
    'query SearchDrugs($queryString:String!,$size:Int!){search(queryString:$queryString,entityNames:["drug"],'
    "page:{index:0,size:$size}){total hits{id name entity score description "
    "object{...on Drug{id name drugType maximumClinicalStage}}}}}"
)
GENETICS_SELECTORS = {
    "variant": {"variant_id"},
    "study": {"study_id", "gene_id", "disease_id"},
    "credible_set": {"credible_set_id"},
}
ASSOCIATION_TYPES = {"target-disease", "drug-target", "drug-disease", "discover-opportunities"}
DRUG_SECTIONS = {"mechanisms_of_action", "indications", "adverse_events"}  # also top-level keys


class UnifiedTools:
    def __init__(self):
        self._composite = CompositeTools()
        self._drug = DrugSafetyApi()

    async def get_entity(
        self, client, entity_type, entity_id, sections=None, include_associations=False, association_limit=10
    ):
        composite = self._composite
        if entity_type == "target":
            return await composite.get_target_profile(
                client,
                entity_id,
                sections,
                include_associations=include_associations,
                association_limit=association_limit,
                clinical=False,
            )
        if entity_type == "disease":
            return await composite.get_disease_profile(
                client, entity_id, sections, association_limit=association_limit
            )
        if entity_type != "drug":
            invalid_request()
        selector(entity_id)
        bounded(association_limit)
        sections = chosen_sections("drug", sections)
        drug = (await client._query(DRUG_RECORD, {"chemblId": entity_id})).get("drug")
        result = {"drug_id": entity_id, "sections_included": sections, "drug": drug}
        result["section_outcomes"] = {"drug": {"outcome": "data"}}
        acquisitions = {
            "mechanisms_of_action": lambda: drug_mechanisms(client, entity_id),
            "indications": lambda: drug_indications(client, entity_id),
            "adverse_events": lambda: self._drug.get_drug_adverse_events(client, entity_id),
            "cross_references": lambda: self._drug.get_drug_cross_references(client, entity_id),
        }
        for name in sections:
            if name == "identity":
                continue
            value, status = await acquire_section(acquisitions[name])
            result.setdefault("specialized", {})[name] = value
            if name in DRUG_SECTIONS:
                result[name], result["section_outcomes"][name] = value, status
            else:
                result["section_outcomes"]["specialized/" + name] = status
        return result

    async def search_drugs(self, client, query, limit=10):
        selector(query)
        bounded(limit)
        page = (await client._query(SEARCH_DRUGS, {"queryString": query, "size": limit}))["search"]
        return {
            "record_type": "opentargets_drug_search",
            "query": query,
            "records": page["hits"],
            "coverage": {
                "provider_total": page["total"],
                "returned_rows": len(page["hits"]),
                "requested_page_size": limit,
                "exhaustive": page["total"] == len(page["hits"]),
            },
            "warnings": ["Search scores rank text matches; they carry no pharmacological meaning."],
        }

    async def analyze_advanced(
        self,
        client,
        analysis_type,
        entity_ids,
        disease_id=None,
        similarity_criteria="pathways",
        comparison_aspects=None,
        threshold=0.5,
        limit=10,
    ):
        advanced_request(
            analysis_type, entity_ids, disease_id, similarity_criteria, comparison_aspects, threshold, limit
        )
        if analysis_type == "compare":
            return await self._composite.compare_targets(client, entity_ids, comparison_aspects)
        if analysis_type == "similar":
            return await similar_targets(client, entity_ids[0], similarity_criteria, threshold, limit)
        if analysis_type == "validate":
            return await self._composite.build_target_validation_report(client, entity_ids[0], disease_id)
        if analysis_type == "prioritize":
            return await prioritize_targets(client, disease_id, entity_ids, limit)
        meta = (await client._query(API_METADATA))["meta"]
        return {
            "record_type": "opentargets_api_metadata",
            "meta": meta,
            "warnings": [
                "The reported data version is what the API served at request time; results are not pinned."
            ],
        }

    async def analyze_association(
        self,
        client,
        source_id,
        association_type="target-disease",
        target_id=None,
        evidence_types=None,
        filters=None,
        min_score=0.0,
        limit=20,
        include_biomarkers=True,
        ranking_strategy=None,
        evidence_cursor=None,
    ):
        if association_type not in ASSOCIATION_TYPES:
            invalid_request()
        selector(source_id)
        bounded(limit)
        unit_interval(min_score)
        cursor_parameter(evidence_cursor)
        if association_type == "target-disease":
            if target_id is None or filters is not None or ranking_strategy is not None:
                invalid_request()
            return await self._composite.analyze_target_disease_association(
                client,
                source_id,
                target_id,
                evidence_cursor=evidence_cursor,
                evidence_types=evidence_types,
                min_score=min_score,
                limit=limit,
                include_biomarkers=include_biomarkers,
            )
        if (target_id, evidence_types, evidence_cursor) != (
            None,
            None,
            None,
        ) or include_biomarkers is not True:
            invalid_request()
        if association_type == "discover-opportunities":
            if ranking_strategy not in {None, "genetic_evidence"}:
                invalid_request()
            if filters is not None:
                if not isinstance(filters, dict) or set(filters) != {"min_score"} or min_score != 0.0:
                    invalid_request()
                min_score = filters["min_score"]
                unit_interval(min_score)
            ranking = await prioritize_targets(client, source_id, (), limit)
            kept = [row for row in ranking["ranked_targets"] if row["genetic_association_score"] >= min_score]
            ranking["coverage"]["returned_ranked_rows"] = len(kept)
            return {
                **ranking,
                "record_type": "opentargets_target_discovery",
                "ranked_targets": kept,
                "ranking_strategy": "genetic_evidence",
                "filtering": {
                    "genetic_min_score": min_score,
                    "excluded_below_threshold": len(ranking["ranked_targets"]) - len(kept),
                },
            }
        if filters is not None or ranking_strategy is not None or min_score != 0.0 or limit != 20:
            invalid_request()
        if association_type == "drug-target":
            return await self._composite.explore_drug_mechanism(client, source_id)
        indications = await drug_indications(client, source_id)
        return {
            "record_type": "opentargets_drug_indications",
            "drug_id": source_id,
            "indications": indications,
            "coverage": {
                "provider_total": indications["count"],
                "returned_rows": len(indications["rows"]),
                "exhaustive": indications["count"] == len(indications["rows"]),
            },
            "warnings": ["Indications are source clinical records, not evidence of approval or efficacy."],
        }

    async def query_genetics(
        self,
        client,
        query_type,
        variant_id=None,
        study_id=None,
        credible_set_id=None,
        gene_id=None,
        disease_id=None,
        include_credible_sets=False,
        include_evidences=False,
        include_functional_consequences=True,
        include_pharmacogenomics=False,
        limit=25,
        page_index=0,
        evidence_cursor=None,
    ):
        flags = (
            include_credible_sets,
            include_evidences,
            include_functional_consequences,
            include_pharmacogenomics,
        )
        if any(type(flag) is not bool for flag in flags):
            invalid_request()
        bounded(limit)
        bounded(page_index, 0, MAX_PROVIDER_PAGE)
        cursor_parameter(evidence_cursor)
        given = {
            name: value
            for name, value in {
                "variant_id": variant_id,
                "study_id": study_id,
                "credible_set_id": credible_set_id,
                "gene_id": gene_id,
                "disease_id": disease_id,
            }.items()
            if value is not None
        }
        if len(given) != 1 or next(iter(given)) not in GENETICS_SELECTORS.get(query_type, ()):
            invalid_request()
        ((name, identifier),) = given.items()
        selector(identifier)
        windowed = (
            include_credible_sets
            or (query_type == "variant" and include_evidences)
            or name in {"gene_id", "disease_id"}
        )
        if (
            (limit != 25 or page_index != 0)
            and not windowed
            or page_index != 0
            and query_type == "variant"
            and not include_credible_sets
            or evidence_cursor is not None
            and not (query_type == "variant" and include_evidences)
            or query_type != "variant"
            and (include_evidences or not include_functional_consequences or include_pharmacogenomics)
        ):
            invalid_request()
        if name == "gene_id":
            acquire = gene_credible_sets if include_credible_sets else gene_studies
            return await acquire(client, identifier, limit, page_index)
        if name == "disease_id":
            return await disease_studies(client, identifier, limit, page_index, include_credible_sets)
        if name == "credible_set_id":
            if include_credible_sets:
                invalid_request()
            row = (await client._query(CREDIBLE_SET, {"studyLocusId": identifier}))["credibleSet"]
            if row is None:
                raise ResearchError(
                    "source_not_found", "Open Targets did not return the requested credible set."
                )
            if row["studyLocusId"] != identifier:
                raise ResearchError(
                    "invalid_source_response", "The returned credible set has another identity."
                )
            checked_credible_rows({"rows": [row]}, 1)
            return {
                "record_type": "opentargets_credible_set",
                "credible_set_id": identifier,
                "credible_set": row,
                "section_outcomes": {"credible_set": {"outcome": "data"}},
                "warnings": ["A fine-mapped locus is not proof of a causal variant or gene."],
            }
        outcomes = {}
        if name == "study_id":
            study = (await client._query(STUDY_INFO, {"studyId": identifier}))["study"]
            result = {"record_type": "opentargets_study_genetics", "study_id": identifier, "study": study}
            outcomes["study"] = {"outcome": "data"}
            if include_credible_sets:
                result["credible_sets"], outcomes["credible_sets"] = await acquire_section(
                    lambda: study_credible_sets(client, identifier, limit, page_index)
                )
            return {**result, "section_outcomes": outcomes}
        variables = {
            "variantId": identifier,
            "functional": include_functional_consequences,
            "pharmacogenomics": include_pharmacogenomics,
        }
        variant = (await client._query(VARIANT_INFO, variables))["variant"]
        result = {"record_type": "opentargets_variant_genetics", "variant_id": identifier, "variant": variant}
        outcomes["variant"] = {"outcome": "data"}
        if include_evidences:

            async def evidences():
                variables = {"variantId": identifier, "size": limit, "cursor": evidence_cursor}
                return window(
                    await client._query(VARIANT_EVIDENCES, variables), identifier, limit, evidence_cursor
                )

            acquired, status = await acquire_section(evidences)
            result["evidences"], outcomes["evidences"] = None, status
            if acquired is not None:
                result["evidences"], outcome = acquired
                outcomes["evidences"] = {"outcome": outcome}
                page = result["evidences"].pop("_provider_page", None)
                if page is not None:
                    result["_provider_pages"] = {"variant_evidence": page}
        if include_credible_sets:

            async def loci():
                variables = {"variantId": identifier, "pageIndex": page_index, "pageSize": limit}
                return credible_window(
                    await client._query(VARIANT_CREDIBLE_SETS, variables), identifier, limit, page_index
                )

            result["credible_sets"], outcomes["credible_sets"] = await acquire_section(loci)
            if (result["credible_sets"] or {}).get("coverage", {}).get(
                "continuation_status"
            ) == "unavailable":
                outcomes["credible_sets"] = {"outcome": "partial"}
        result["section_outcomes"] = outcomes
        result["warnings"] = [
            "Variant annotations and linked evidence are source records; no causal effect or genome-build qualification is inferred.",
        ]
        return result
