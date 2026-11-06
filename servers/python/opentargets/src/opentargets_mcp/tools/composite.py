"""Multi-query compositions whose optional sections fail independently of the primary record."""

from biomedmcp.errors import ResearchError
from biomedmcp.native.opentargets import (
    ASSOCIATION_FIELDS,
    CLINICAL_FIELDS,
    TARGET_FIELDS,
    acquire_section,
    assessment,
)
from biomedmcp.native.opentargets_variant_evidence import cursor_parameter
from biomedmcp.native.opentargets_workflows import bounded, gene, invalid_request, selector, unit_interval
from biomedmcp.native.shapes import invalid_shape

from ..queries import relation
from .drug import DRUG_RECORD, drug_indications, drug_mechanisms

TARGET_PROFILE = f"query TargetProfile($ensemblId:String!){{target(ensemblId:$ensemblId){{{TARGET_FIELDS}}}}}"
TARGET_DISEASES = (
    "query TargetDiseases($ensemblId:String!,$size:Int!){target(ensemblId:$ensemblId){id "
    f"associatedDiseases(page:{{index:0,size:$size}}){{{ASSOCIATION_FIELDS}}}}}}}"
)
TARGET_DRUGS = (
    "query TargetDrugs($ensemblId:String!){target(ensemblId:$ensemblId){id "
    f"drugAndClinicalCandidates{{{CLINICAL_FIELDS}}}}}}}"
)
TARGET_ALTERNATIVE_GENES = (
    "query TargetAlternativeGenes($ensemblId:String!){target(ensemblId:$ensemblId){id alternativeGenes}}"
)
TARGET_INTERACTIONS = (
    "query TargetInteractions($ensemblId:String!,$size:Int!){target(ensemblId:$ensemblId){id "
    "interactions(page:{index:0,size:$size}){count rows{intA intB intABiologicalRole intBBiologicalRole score "
    "sourceDatabase targetA{id approvedSymbol} targetB{id approvedSymbol} speciesA{taxonId scientificName} "
    "speciesB{taxonId scientificName}}}}}"
)
DISEASE_PROFILE = (
    "query DiseaseProfile($efoId:String!){disease(efoId:$efoId){id name description synonyms{relation terms} "
    "therapeuticAreas{id name} dbXRefs}}"
)
DISEASE_TARGETS = (
    "query DiseaseTargets($efoId:String!,$size:Int!){disease(efoId:$efoId){id "
    "associatedTargets(page:{index:0,size:$size}){count rows{target{id approvedSymbol approvedName} score "
    "datatypeScores{id score}}}}}"
)
DISEASE_PHENOTYPES = (
    "query DiseasePhenotypes($efoId:String!,$size:Int!){disease(efoId:$efoId){id "
    "phenotypes(page:{index:0,size:$size}){count rows{phenotypeHPO{id name} phenotypeEFO{id name} "
    "evidence{resource frequency evidenceType references}}}}}"
)
DISEASE_PROJECTS = (
    "query DiseaseProjects($efoId:String!){disease(efoId:$efoId){id "
    "otarProjects{otarCode projectName status reference integratesInPPP}}}"
)
ASSOCIATION_SCORE = (
    "query AssociationScore($ensemblId:String!,$efoId:String!){disease(efoId:$efoId){id "
    "associatedTargets(Bs:[$ensemblId],page:{index:0,size:1}){count rows{target{id} score datatypeScores{id score}}}}}"
)
PAIR_EVIDENCE = (
    "query TargetDiseaseEvidence($ensemblId:String!,$efoId:String!,$size:Int!,$cursor:String){"
    "target(ensemblId:$ensemblId){id evidences(efoIds:[$efoId],size:$size,cursor:$cursor){count cursor rows{"
    "id target{id} disease{id name} score datasourceId datatypeId literature biomarkerList{name description}}}}}"
)
COMPARISON = {
    "tractability": "tractability{label modality value}",
    "safety": "safetyLiabilities{event effects{direction dosing} datasource}",
    "pathways": "pathways{pathway pathwayId}",
    "diseases": "associatedDiseases(page:{index:0,size:10}){" + ASSOCIATION_FIELDS + "}",
}
VARIABLE = {"target": "ensemblId", "disease": "efoId", "drug": "chemblId"}
WINDOW = 100


def retired(name):
    async def unavailable(client, identifier):
        raise ResearchError(
            "source_contract_changed", f"The {name} field is not part of the reviewed Open Targets contract."
        )

    return unavailable


def relation_section(query, root, field, **extra):
    async def acquire(client, identifier):
        return relation(await client._query(query, {VARIABLE[root]: identifier, **extra}), root, field)

    return acquire


# Specialty sections live under ``specialized`` with ``specialized/<name>`` outcomes.
SPECIALTY = {
    "target": {
        "alternative_genes": relation_section(TARGET_ALTERNATIVE_GENES, "target", "alternativeGenes"),
        "interactions": relation_section(TARGET_INTERACTIONS, "target", "interactions", size=WINDOW),
        "tep": retired("Target Enabling Package (tep)"),
    },
    "disease": {
        "phenotypes": relation_section(DISEASE_PHENOTYPES, "disease", "phenotypes", size=WINDOW),
        "otar_projects": relation_section(DISEASE_PROJECTS, "disease", "otarProjects"),
    },
}
DEFAULT = {
    "target": ["identity", "biology", "safety", "tractability"],
    "disease": ["identity", "targets"],
    "drug": ["identity"],
}
KNOWN = {
    "target": set(DEFAULT["target"]) | set(SPECIALTY["target"]),
    "disease": set(DEFAULT["disease"]) | set(SPECIALTY["disease"]),
    "drug": {"identity", "mechanisms_of_action", "indications", "adverse_events", "cross_references"},
}


def chosen_sections(entity, sections):
    if sections is None:
        return list(DEFAULT[entity])
    known = KNOWN[entity]
    if (
        not isinstance(sections, list)
        or not sections
        or len(set(sections)) != len(sections)
        or any(name not in known for name in sections)
    ):
        invalid_request()
    return list(sections)


async def specialties(client, entity, identifier, sections, result):
    for name in sections:
        if name in SPECIALTY[entity]:
            value, status = await acquire_section(lambda n=name: SPECIALTY[entity][n](client, identifier))
            result.setdefault("specialized", {})[name] = value
            result["section_outcomes"]["specialized/" + name] = status
    return result


class CompositeTools:
    async def get_target_profile(
        self,
        client,
        ensembl_id,
        sections=None,
        *,
        include_associations=True,
        association_limit=10,
        clinical=True,
    ):
        """One validated target record plus independently acquired disease and clinical relations."""
        gene(ensembl_id)
        bounded(association_limit)
        chosen = chosen_sections("target", sections)
        target = (await client._query(TARGET_PROFILE, {"ensemblId": ensembl_id})).get("target")
        result = {
            "ensembl_id": ensembl_id,
            "sections_included": chosen,
            "target": target,
            "section_outcomes": {"target": {"outcome": "data"}},
        }
        parts = []
        if include_associations:
            size = {"ensemblId": ensembl_id, "size": association_limit}
            parts.append(("associated_diseases", TARGET_DISEASES, size, "associatedDiseases"))
        if clinical:
            parts.append(
                ("clinical_candidates", TARGET_DRUGS, {"ensemblId": ensembl_id}, "drugAndClinicalCandidates")
            )
        for name, query, variables, field in parts:
            result[name], result["section_outcomes"][name] = await acquire_section(
                lambda q=query, v=variables, f=field: relation_of(client, q, v, "target", f)
            )
        return await specialties(client, "target", ensembl_id, chosen, result)

    async def get_disease_profile(self, client, efo_id, sections=None, *, association_limit=10):
        """One disease record plus its independently acquired associated targets and specialties."""
        selector(efo_id)
        bounded(association_limit)
        chosen = chosen_sections("disease", sections)
        disease = (await client._query(DISEASE_PROFILE, {"efoId": efo_id})).get("disease")
        result = {"disease_id": efo_id, "sections_included": chosen, "disease": disease}
        result["section_outcomes"] = {"disease": {"outcome": "data"}}
        if "targets" in chosen:
            variables = {"efoId": efo_id, "size": association_limit}
            (
                result["associated_targets"],
                result["section_outcomes"]["associated_targets"],
            ) = await acquire_section(
                lambda: relation_of(client, DISEASE_TARGETS, variables, "disease", "associatedTargets")
            )
        return await specialties(client, "disease", efo_id, chosen, result)

    async def explore_drug_mechanism(self, client, chembl_id):
        """Drug record with mechanism rows, their distinct targets and indications."""
        selector(chembl_id)
        drug = (await client._query(DRUG_RECORD, {"chemblId": chembl_id})).get("drug")
        mechanisms, mechanism_status = await acquire_section(lambda: drug_mechanisms(client, chembl_id))
        indications, indication_status = await acquire_section(lambda: drug_indications(client, chembl_id))
        targets = None
        if mechanisms is not None:
            seen = {}
            for row in mechanisms["rows"]:
                for target in row["targets"]:
                    seen.setdefault(target["id"], target)
            targets = list(seen.values())
        return {
            "record_type": "opentargets_drug_mechanism",
            "drug_id": chembl_id,
            "drug": drug,
            "mechanisms_of_action": mechanisms,
            "targets": targets,
            "indications": indications,
            "section_outcomes": {
                "drug": {"outcome": "data"},
                "mechanisms_of_action": mechanism_status,
                "indications": indication_status,
            },
            "warnings": [
                "Mechanism rows are curated source annotations; a null mechanism collection is unreported, not absent.",
                "Indications and clinical reports are source records, not evidence of approval or efficacy.",
            ],
        }

    async def compare_targets(self, client, identifiers, aspects=None):
        """Acquire the same requested aspects for 2-10 targets; a failed target never empties the matrix."""
        if not isinstance(identifiers, list) or not 2 <= len(identifiers) <= 10:
            invalid_request()
        for identifier in identifiers:
            gene(identifier)
        aspects = list(COMPARISON) if aspects is None else aspects
        if (
            not isinstance(aspects, list)
            or not aspects
            or len(set(identifiers)) != len(identifiers)
            or len(set(aspects)) != len(aspects)
            or any(aspect not in COMPARISON for aspect in aspects)
        ):
            invalid_request()
        fields = " ".join(COMPARISON[aspect] for aspect in aspects)
        query = f"query CompareTarget($ensemblId:String!){{target(ensemblId:$ensemblId){{id approvedSymbol approvedName {fields}}}}}"
        matrix, coverage, outcomes = {}, {}, {}
        for identifier in identifiers:
            value, outcomes[identifier] = await acquire_section(
                lambda i=identifier: client._query(query, {"ensemblId": i})
            )
            if value is None:
                continue
            matrix[identifier] = value["target"]
            if "diseases" in aspects:
                page = value["target"]["associatedDiseases"]
                coverage[identifier] = {
                    "provider_total": page["count"],
                    "returned_rows": len(page["rows"]),
                    "provider_page": 0,
                    "requested_page_size": 10,
                    "exhaustive": page["count"] == len(page["rows"]),
                }
        if not matrix:
            error = next(iter(outcomes.values()))["error"]
            raise ResearchError(
                error["code"], "No compared target was acquired.", retryable=error["retryable"]
            )
        return {
            "record_type": "opentargets_target_comparison",
            "requested_targets": identifiers,
            "aspects": aspects,
            "matrix": matrix,
            "coverage": coverage,
            "section_outcomes": outcomes,
            "method": {
                "name": "Side-by-side retrieval of the selected aspects; no aggregate ranking is computed."
            },
            "warnings": [
                "Disease associations are limited to each target's first ten source rows.",
                "Annotation counts compare recorded source annotations, not biological importance.",
            ],
        }

    async def analyze_target_disease_association(
        self,
        client,
        ensembl_id,
        efo_id,
        *,
        evidence_cursor=None,
        evidence_types=None,
        min_score=0.0,
        limit=20,
        include_biomarkers=True,
    ):
        """Indexed pair score and one window of pair evidence, each acquired independently."""
        gene(ensembl_id)
        selector(efo_id)
        cursor_parameter(evidence_cursor)
        bounded(limit)
        unit_interval(min_score)
        types = evidence_type_parameter(evidence_types)
        if type(include_biomarkers) is not bool:
            invalid_request()
        request = {
            "source_id": ensembl_id,
            "target_id": efo_id,
            "association_type": "target-disease",
            "min_score": min_score,
            "limit": limit,
            "include_biomarkers": include_biomarkers,
        }
        if types is not None:
            request["evidence_types"] = types

        async def score():
            data = await client._query(ASSOCIATION_SCORE, {"ensemblId": ensembl_id, "efoId": efo_id})
            page = data["disease"]["associatedTargets"]
            if len(page["rows"]) > 1 or any(row["target"]["id"] != ensembl_id for row in page["rows"]):
                invalid_shape()
            return page

        async def evidence():
            variables = {"ensemblId": ensembl_id, "efoId": efo_id, "size": limit, "cursor": evidence_cursor}
            page = (await client._query(PAIR_EVIDENCE, variables))["target"]["evidences"]
            rows, following = page["rows"], page["cursor"]
            if (
                len(rows) > limit
                or len({row["id"] for row in rows}) != len(rows)
                or any(row["target"]["id"] != ensembl_id or row["disease"]["id"] != efo_id for row in rows)
                or following is not None
                and (not 1 <= len(following) <= 8192 or following == evidence_cursor)
            ):
                invalid_shape()
            return page

        record, record_status = await acquire_section(score)
        page, evidence_status = await acquire_section(evidence)
        if record is None and page is None:
            error = record_status["error"]
            raise ResearchError(error["code"], "No pair section was acquired.", retryable=error["retryable"])
        row = record["rows"][0] if record and record["rows"] else None
        result = {
            "record_type": "opentargets_target_disease_association",
            "target_id": ensembl_id,
            "disease_id": efo_id,
            "association_status": None if record is None else "indexed" if row else "not_indexed",
            "overall_score": row["score"] if row else None,
            "datatype_scores": row["datatypeScores"] if row else None,
            "association_record": record,
            "evidence": None,
            "coverage": None,
            "filtering": None,
            "section_outcomes": {"association_record": record_status, "evidence": evidence_status},
            "method": {
                "name": "Retain the indexed pair association row and distinct evidence rows filtered by score and type.",
                "inputs": ["/association_record/rows", "/evidence"],
            },
            "warnings": [
                "Association scores aggregate source evidence types; they are not causal confidence or clinical efficacy.",
                "An unindexed pair or an empty evidence window does not establish absence. Live data are unpinned.",
            ],
        }
        if page is None:
            return result
        rows, following = page["rows"], page["cursor"]
        kept = [
            row for row in rows if row["score"] >= min_score and (types is None or row["datatypeId"] in types)
        ]
        missing = evidence_cursor is None and following is None and page["count"] > len(rows)
        result["evidence"] = kept
        result["filtering"] = {
            "min_score": min_score,
            "evidence_types": types,
            "excluded_below_threshold": sum(row["score"] < min_score for row in rows),
            "excluded_by_type": sum(types is not None and row["datatypeId"] not in types for row in rows),
        }
        result["coverage"] = {
            "provider_total": page["count"],
            "acquired_rows": len(rows),
            "displayed_rows": len(kept),
            "requested_page_size": limit,
            "has_continuation": following is not None,
            "exhaustive": evidence_cursor is None and following is None and page["count"] == len(rows),
            "continuation_status": "provider_token"
            if following
            else "unavailable"
            if missing
            else "terminal",
        }
        if include_biomarkers:
            result["biomarkers"] = [
                {"evidence_id": row["id"], "annotations": row["biomarkerList"]}
                for row in kept
                if row["biomarkerList"]
            ]
        if missing:
            result["section_outcomes"]["evidence"] = {"outcome": "partial"}
            result["warnings"].append(
                "The first evidence window is incomplete and has no continuation token."
            )
        if following is not None:
            result["_provider_pages"] = {
                "pair_evidence": {"next_token": following, "raw_count": len(rows), "request": request}
            }
        return result

    async def build_target_validation_report(self, client, ensembl_id, disease_id=None):
        """Count acquired annotations and candidates; no aggregate validation score is computed."""
        gene(ensembl_id)
        if disease_id is not None:
            selector(disease_id)
        profile = await self.get_target_profile(client, ensembl_id)
        association = status = None
        if disease_id is not None:
            association, status = await acquire_section(
                lambda: self.analyze_target_disease_association(
                    client, ensembl_id, disease_id, limit=WINDOW, include_biomarkers=False
                )
            )
        return assessment(profile, ensembl_id, disease_id, association, status)


async def relation_of(client, query, variables, root, field):
    return relation(await client._query(query, variables), root, field)


def evidence_type_parameter(value):
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 20
        or len(set(value)) != len(value)
        or any(not isinstance(item, str) or not item.strip() or len(item) > 64 for item in value)
    ):
        invalid_request()
    return list(value)
