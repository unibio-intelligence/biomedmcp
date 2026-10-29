"""Bounded Open Targets workflows with explicit scientific inputs and coverage."""

import math
import re

from ..errors import ResearchError
from ..pagination import MAX_PROVIDER_PAGE, PAGE_LIMIT_WARNING, page_continuation
from .opentargets import acquire_section, response
from .shapes import invalid_shape

GENE = re.compile(r"ENSG[0-9]{11}\Z")
WINDOW = 100
IDENTITY_FIELDS = "id approvedSymbol approvedName"
FEATURE_FIELDS = {
    "pathways": "pathways { pathwayId }",
    "go_terms": "geneOntology { term { id } }",
    "diseases": "associatedDiseases(enableIndirect: false, page: {index: 0, size: 100}) { count rows { disease { id } } }",
    "interactions": "interactions(page: {index: 0, size: 100}) { count rows { intA intB targetA {id} targetB {id} speciesA {taxonId} speciesB {taxonId} sourceDatabase } }",
}


def invalid_request():
    raise ResearchError(
        "invalid_parameters",
        "Use bounded, mode-specific selectors and exact human Ensembl target identifiers.",
    )


def gene(value, *, returned=False):
    if not isinstance(value, str) or not GENE.fullmatch(value):
        if returned:
            invalid_shape()
        invalid_request()
    return value


def bounded(value, minimum=1, maximum=WINDOW):
    if type(value) is not int or not minimum <= value <= maximum:
        invalid_request()


def unit_interval(value):
    try:
        valid = type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1
    except OverflowError:
        valid = False
    if not valid:
        invalid_request()


def selector(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        invalid_request()


def advanced_request(mode, ids, disease, criteria, aspects, threshold, limit):
    if not isinstance(mode, str) or mode not in {"compare", "similar", "validate", "prioritize", "metadata"}:
        invalid_request()
    if not isinstance(ids, list) or len(ids) > 10:
        invalid_request()
    for value in ids:
        gene(value)
    if len(set(ids)) != len(ids):
        invalid_request()
    bounded(limit)
    unit_interval(threshold)
    if disease is not None:
        selector(disease)
    if mode == "compare":
        if len(ids) < 2 or disease is not None or criteria != "pathways" or threshold != 0.5 or limit != 10:
            invalid_request()
    elif mode in {"similar", "validate"}:
        if len(ids) != 1 or aspects is not None:
            invalid_request()
        if mode == "similar":
            if not isinstance(criteria, str) or criteria not in FEATURE_FIELDS or disease is not None:
                invalid_request()
        elif criteria != "pathways" or threshold != 0.5 or limit != 10:
            invalid_request()
    elif mode == "prioritize":
        if disease is None or aspects is not None or criteria != "pathways" or threshold != 0.5:
            invalid_request()
    elif (
        ids
        or disease is not None
        or aspects is not None
        or criteria != "pathways"
        or threshold != 0.5
        or limit != 10
    ):
        invalid_request()


def features(target, criterion):
    """Deduplicate only acquired qualified annotations; never invent coverage."""
    gene(target["id"], returned=True)
    skipped = 0
    if criterion == "pathways":
        rows = target["pathways"]
        values = [row["pathwayId"] for row in rows]
        coverage = {"returned_rows": len(rows), "provider_total": None, "window_exhaustive": True}
    elif criterion == "go_terms":
        rows = target["geneOntology"]
        values = [row["term"]["id"] for row in rows]
        coverage = {"returned_rows": len(rows), "provider_total": None, "window_exhaustive": True}
    else:
        page = target["associatedDiseases" if criterion == "diseases" else "interactions"]
        if page is None:
            return None, {"status": "unavailable", "provider_total": None, "returned_rows": None}
        rows = page["rows"]
        if len(rows) > WINDOW:
            invalid_shape()
        coverage = {
            "provider_total": page["count"],
            "returned_rows": len(rows),
            "provider_page": 0,
            "requested_page_size": WINDOW,
            "window_exhaustive": page["count"] == len(rows),
        }
        if criterion == "diseases":
            values = [row["disease"]["id"] for row in rows]
        else:
            values = []
            for row in rows:
                a, b = row["targetA"], row["targetB"]
                if a is not None and b is not None and target["id"] not in {a["id"], b["id"]}:
                    invalid_shape()
                if a is not None and a["id"] == target["id"]:
                    peer, species = b, row["speciesB"]
                    own_species = row["speciesA"]
                elif b is not None and b["id"] == target["id"]:
                    peer, species = a, row["speciesA"]
                    own_species = row["speciesB"]
                else:
                    peer, species = None, None
                    own_species = None
                if own_species is not None and own_species["taxonId"] not in {None, 9606}:
                    invalid_shape()
                if peer is None or species is None or species["taxonId"] != 9606:
                    skipped += 1
                    continue
                values.append(gene(peer["id"], returned=True))
            coverage["excluded_unqualified_partner_rows"] = skipped
    if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in values):
        invalid_shape()
    return set(values), {"status": "reported", **coverage, "unique_annotation_count": len(set(values))}


async def similar_targets(client, identifier, criterion="pathways", threshold=0.5, limit=10):
    gene(identifier)
    bounded(limit)
    unit_interval(threshold)
    if not isinstance(criterion, str) or criterion not in FEATURE_FIELDS:
        invalid_request()
    fields = FEATURE_FIELDS[criterion]
    query = (
        "query SimilarityReference($id:String!){target(ensemblId:$id){"
        + IDENTITY_FIELDS
        + " "
        + fields
        + ' similarEntities(entityNames:["target"],threshold:0,size:100){id category score}}}'
    )
    reference = (await client._query(query, {"id": identifier}))["target"]
    index = reference["similarEntities"]
    if len(index) > WINDOW or len({row["id"] for row in index}) != len(index):
        invalid_shape()
    for row in index:
        gene(row["id"], returned=True)
        if row["category"] != "target" or not 0 <= row["score"] <= 1:
            invalid_shape()
    candidate_ids = [row["id"] for row in index if row["id"] != identifier]
    ref_features, ref_coverage = features(reference, criterion)
    result = {
        "record_type": "opentargets_annotation_similarity",
        "reference_target": reference,
        "similarity_criteria": criterion,
        "threshold": threshold,
        "limit": limit,
        "candidate_annotations": None,
        "comparisons": None,
        "similar_targets": None,
        "section_outcomes": {"reference": {"outcome": "data"}},
        "reference_annotation_coverage": ref_coverage,
        "coverage": {
            "candidate_discovery": "Open Targets PubMed word-embedding similarity index",
            "requested_candidate_size": WINDOW,
            "returned_index_rows": len(index),
            "excluded_reference_rows": len(index) - len(candidate_ids),
            "candidate_count": len(candidate_ids),
            "provider_total": None,
            "exhaustive": False,
        },
        "method": {
            "name": "Jaccard overlap of acquired unique annotation identifiers",
            "formula": "intersection_count / union_count; undefined when union_count is zero",
            "threshold_operator": ">=",
            "ranking": "Defined annotation Jaccard descending, then human Ensembl ID ascending",
            "inputs": ["/reference_target", "/candidate_annotations"],
            "candidate_discovery_inputs": ["/reference_target/similarEntities"],
            "provider_model_score_usage": "Candidate discovery only; it is not a pathway, GO, disease or interaction overlap score.",
        },
        "warnings": [
            "Candidate discovery is restricted to 100 source literature-model rows; this is not an exhaustive search or a global overlap ranking.",
            "Empty or missing annotations do not establish biological absence. Scores compare recorded annotations, not physical binding, causality, efficacy or clinical similarity.",
            "Disease and interaction annotations are limited to each target's first 100 source rows. Interaction overlap uses only explicitly human, resolved Ensembl partners.",
            "Live source annotations and model scores are time-dependent; the API schema is not a data release pin.",
        ],
    }
    if ref_features is None:
        result["section_outcomes"]["reference_features"] = {"outcome": "unavailable"}
        return result
    if not candidate_ids:
        result.update({"candidate_annotations": [], "comparisons": [], "similar_targets": []})
        result["coverage"].update(
            {
                "acquired_candidates": 0,
                "measurable_candidates": 0,
                "eligible_candidates": 0,
                "returned_candidates": 0,
            }
        )
        result["warnings"].append(
            "No candidate labels were returned; the source index may not contain this target. No biological absence is inferred."
        )
        return result
    candidates_query = (
        "query SimilarityCandidates($ids:[String!]!){targets(ensemblIds:$ids){"
        + IDENTITY_FIELDS
        + " "
        + fields
        + "}}"
    )

    async def acquire_candidates():
        rows = (await client._query(candidates_query, {"ids": candidate_ids}))["targets"]
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)) or set(ids) - set(candidate_ids):
            invalid_shape()
        for row in rows:
            features(row, criterion)
        return rows

    candidates, status = await acquire_section(acquire_candidates)
    result["section_outcomes"]["candidate_annotations"] = status
    if candidates is None:
        result["coverage"].update(
            {
                "acquired_candidates": None,
                "measurable_candidates": None,
                "eligible_candidates": None,
                "returned_candidates": None,
            }
        )
        return result
    result["candidate_annotations"] = candidates
    by_id = {row["id"]: row for row in candidates}
    index_by_id = {row["id"]: (i, row) for i, row in enumerate(index)}
    comparisons = []
    for candidate_id in candidate_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            result["section_outcomes"][candidate_id] = {"outcome": "unavailable"}
            comparisons.append(
                {
                    "target_id": candidate_id,
                    "status": "unavailable",
                    "annotation_jaccard": None,
                    "reason": "The source did not return candidate annotations.",
                }
            )
            continue
        candidate_features, coverage = features(candidate, criterion)
        intersection = ref_features & candidate_features if candidate_features is not None else None
        union = ref_features | candidate_features if candidate_features is not None else None
        score = len(intersection) / len(union) if union else None
        result["section_outcomes"][candidate_id] = {"outcome": "data" if score is not None else "unavailable"}
        index_position, discovery = index_by_id[candidate_id]
        comparisons.append(
            {
                "target_id": candidate_id,
                "status": "reported" if score is not None else "unavailable",
                "annotation_jaccard": score,
                "literature_model_score": discovery["score"],
                "reference_annotation_count": len(ref_features),
                "candidate_annotation_count": len(candidate_features)
                if candidate_features is not None
                else None,
                "intersection_count": len(intersection) if intersection is not None else None,
                "union_count": len(union) if union is not None else None,
                "shared_annotation_ids": sorted(intersection) if intersection is not None else None,
                "candidate_annotation_coverage": coverage,
                "inputs": ["/reference_target", "/candidate_annotations/" + str(candidates.index(candidate))],
                "candidate_discovery_input": "/reference_target/similarEntities/" + str(index_position),
            }
        )
    ranked = sorted(
        (
            row
            for row in comparisons
            if row["annotation_jaccard"] is not None and row["annotation_jaccard"] >= threshold
        ),
        key=lambda row: (-row["annotation_jaccard"], row["target_id"]),
    )
    result.update({"comparisons": comparisons, "similar_targets": ranked[:limit]})
    result["coverage"].update(
        {
            "acquired_candidates": len(candidates),
            "measurable_candidates": sum(row["annotation_jaccard"] is not None for row in comparisons),
            "eligible_candidates": len(ranked),
            "returned_candidates": len(ranked[:limit]),
        }
    )
    return result


STUDY_FIELDS = "id studyType projectId traitFromSource pubmedId nSamples nCases nControls target{id approvedSymbol} diseases{id name}"
CREDIBLE_FIELDS = (
    """studyLocusId studyId studyType chromosome position pValueMantissa pValueExponent
finemappingMethod confidence qtlGeneId
variant{id chromosome position referenceAllele alternateAllele rsIds}
study{"""
    + STUDY_FIELDS
    + "}"
)
GENE_QUERY = (
    "query GeneCredibleSets($id:String!,$index:Int!,$size:Int!){target(ensemblId:$id){"
    + IDENTITY_FIELDS
    + " credibleSets(page:{index:$index,size:$size}){count rows{"
    + CREDIBLE_FIELDS
    + "}}}}"
)


def checked_credible_rows(page, limit):
    rows = page["rows"]
    if len(rows) > limit or len({row["studyLocusId"] for row in rows}) != len(rows):
        invalid_shape()
    for row in rows:
        if not row["studyLocusId"].strip() or not row["studyId"].strip() or row["position"] < 1:
            invalid_shape()
        mantissa, exponent = row["pValueMantissa"], row["pValueExponent"]
        if mantissa < 0 or mantissa > 0 and math.log10(mantissa) + exponent > 0:
            invalid_shape()
        variant, study = row["variant"], row["study"]
        if variant is not None and (
            variant["chromosome"] != row["chromosome"]
            or variant["position"] != row["position"]
            or not variant["referenceAllele"]
            or not variant["alternateAllele"]
            or variant["id"]
            != f"{variant['chromosome']}_{variant['position']}_{variant['referenceAllele']}_{variant['alternateAllele']}"
        ):
            invalid_shape()
        if study is not None:
            if study["id"] != row["studyId"] or (
                study["studyType"] is not None
                and row["studyType"] is not None
                and study["studyType"] != row["studyType"]
            ):
                invalid_shape()
            checked_study_counts(study)
    return rows


def checked_study_counts(study):
    counts = [study[name] for name in ("nSamples", "nCases", "nControls")]
    if any(value is not None and value < 0 for value in counts):
        invalid_shape()
    if all(value is not None for value in counts) and sum(counts[1:]) > counts[0]:
        invalid_shape()


def continuation_outcomes(coverage):
    return (
        {"continuation": {"outcome": "partial"}}
        if coverage.get("continuation_status") == "unavailable"
        else {}
    )


def checked_window(page, limit, index):
    rows = page["rows"]
    offset = index * limit
    if (
        len(rows) > limit
        or offset + len(rows) > page["count"]
        or offset < page["count"]
        and len(rows) < min(limit, page["count"] - offset)
    ):
        invalid_shape()
    more = offset + len(rows) < page["count"]
    next_page, boundary = page_continuation(index + 1 if more else None)
    return {
        "provider_total": page["count"],
        "returned_rows": len(rows),
        "provider_page": index,
        "requested_page_size": limit,
        "exhaustive": index == 0 and page["count"] == len(rows),
        **boundary,
    }, next_page


async def gene_credible_sets(client, identifier, limit=10, page_index=0):
    gene(identifier)
    bounded(limit)
    bounded(page_index, 0, MAX_PROVIDER_PAGE)
    target = (await client._query(GENE_QUERY, {"id": identifier, "index": page_index, "size": limit}))[
        "target"
    ]
    page = target["credibleSets"]
    rows = checked_credible_rows(page, limit)
    coverage, next_page = checked_window(page, limit, page_index)
    continuation = gene_page_action(identifier, limit, next_page) if next_page is not None else None
    return {
        "record_type": "opentargets_gene_credible_sets",
        "gene_id": identifier,
        "target": target,
        "records": rows,
        "coverage": coverage,
        "section_outcomes": continuation_outcomes(coverage),
        "continuation": continuation,
        "method": {
            "name": "Retain the source target.credibleSets relation, distinct study-locus records and their reported study metadata.",
            "inputs": ["/target/credibleSets/rows"],
            "gene_relation_basis": "Open Targets target.credibleSets linkage; no causal gene assignment or study.target match is inferred.",
        },
        "warnings": [
            "GWAS and molecular-QTL credible sets retain their separately reported study types. A linked credible set is not proof of a causal gene, variant or disease mechanism.",
            "Unreported variant, study, counts or QTL gene remain null; no zero sample size or allele/build identity is invented.",
            "An empty indexed window does not establish biological absence. Live data are unpinned; continuation pages do not summarize earlier pages.",
            *([PAGE_LIMIT_WARNING] if continuation_outcomes(coverage) else []),
        ],
    }


def gene_page_action(identifier, limit, index):
    return {
        "tool": "get",
        "arguments": {
            "entity": "gene",
            "id": identifier,
            "species": 9606,
            "sections": ["genetics"],
            "section_parameters": {"genetics": {"limit": limit, "page": index}},
        },
    }


def qualified_gene_genetics(payload, identity, identifier, *, limit=10, page_index=0):
    """Validate the native gene composition as well as the actual source client."""
    if (
        not isinstance(payload, dict)
        or payload.get("record_type") != "opentargets_gene_credible_sets"
        or payload.get("gene_id") != identifier
        or not isinstance(payload.get("target"), dict)
        or payload["target"].get("approvedSymbol") != identity["symbol"]
        or not isinstance(payload.get("coverage"), dict)
    ):
        invalid_shape()
    coverage = payload["coverage"]
    index, size = coverage.get("provider_page"), coverage.get("requested_page_size")
    if (
        type(index) is not int
        or not 0 <= index <= MAX_PROVIDER_PAGE
        or type(size) is not int
        or not 1 <= size <= WINDOW
    ):
        invalid_shape()
    if index != page_index or size != limit:
        invalid_shape()
    response(
        {"data": {"target": payload["target"]}}, GENE_QUERY, {"id": identifier, "index": index, "size": size}
    )
    rows = checked_credible_rows(payload["target"]["credibleSets"], size)
    expected, next_page = checked_window(payload["target"]["credibleSets"], size, index)
    action = gene_page_action(identifier, size, next_page) if next_page is not None else None
    if (
        payload.get("records") != rows
        or coverage != expected
        or type(coverage.get("exhaustive")) is not bool
        or payload.get("continuation") != action
        or payload.get("section_outcomes", {}) != continuation_outcomes(expected)
    ):
        invalid_shape()
    return {**payload, "qualified_identity": identity}


def study_page_action(identifier, limit, index):
    return {
        "tool": "query_source",
        "arguments": {
            "source": "opentargets",
            "operation": "query_genetics",
            "params": {
                "query_type": "study",
                "study_id": identifier,
                "include_credible_sets": True,
                "page_index": index,
                "limit": limit,
            },
        },
    }


async def study_credible_sets(client, identifier, limit=25, page_index=0):
    selector(identifier)
    bounded(limit)
    bounded(page_index, 0, MAX_PROVIDER_PAGE)
    query = (
        "query StudyCredibleEvidence($id:String!,$index:Int!,$size:Int!){study(studyId:$id){id credibleSets(page:{index:$index,size:$size}){count rows{"
        + CREDIBLE_FIELDS
        + "}}}}"
    )
    study = (await client._query(query, {"id": identifier, "index": page_index, "size": limit}))["study"]
    page = study["credibleSets"]
    rows = checked_credible_rows(page, limit)
    if any(row["studyId"] != identifier for row in rows):
        invalid_shape()
    coverage, next_page = checked_window(page, limit, page_index)
    return {
        "record_type": "opentargets_study_credible_sets",
        "study": study,
        "records": rows,
        "coverage": coverage,
        "section_outcomes": continuation_outcomes(coverage),
        "continuation": study_page_action(identifier, limit, next_page) if next_page is not None else None,
        "method": {
            "name": "Retain distinct study-locus records for one exact study identifier.",
            "inputs": ["/study/credibleSets/rows"],
        },
        "warnings": [
            "Study-locus evidence is not proof of a causal variant or gene. Nullable source measurements remain unreported.",
            "Live data remain unpinned; later pages do not summarize earlier pages.",
            *([PAGE_LIMIT_WARNING] if continuation_outcomes(coverage) else []),
        ],
    }


async def gene_studies(client, identifier, limit=10, page_index=0):
    """Study discovery needs gene-linked loci, without unrequested fine-mapping fields."""
    gene(identifier)
    bounded(limit)
    bounded(page_index, 0, MAX_PROVIDER_PAGE)
    query = (
        "query GeneStudies($id:String!,$index:Int!,$size:Int!){target(ensemblId:$id){"
        + IDENTITY_FIELDS
        + " credibleSets(page:{index:$index,size:$size}){count rows{studyLocusId studyId study{"
        + STUDY_FIELDS
        + "}}}}}"
    )
    target = (await client._query(query, {"id": identifier, "index": page_index, "size": limit}))["target"]
    page = target["credibleSets"]
    links = page["rows"]
    if len(links) > limit or len({row["studyLocusId"] for row in links}) != len(links):
        invalid_shape()
    studies = {}
    for row in links:
        if not row["studyLocusId"].strip() or not row["studyId"].strip():
            invalid_shape()
        study = row["study"]
        if study is not None:
            checked_study_counts(study)
            if study["id"] != row["studyId"] or study["id"] in studies and studies[study["id"]] != study:
                invalid_shape()
            studies[study["id"]] = study
    offset = page_index * limit
    if (
        offset + len(links) > page["count"]
        or offset < page["count"]
        and len(links) < min(limit, page["count"] - offset)
    ):
        invalid_shape()
    next_index, boundary = page_continuation(page_index + 1 if offset + len(links) < page["count"] else None)
    next_page = gene_page_action(identifier, limit, next_index) if next_index is not None else None
    return {
        "record_type": "opentargets_gene_studies",
        "gene_id": identifier,
        "target": target,
        "records": list(studies.values()),
        "section_outcomes": continuation_outcomes(boundary),
        "coverage": {
            "provider_credible_set_total": page["count"],
            "acquired_gene_linked_loci": len(links),
            "unique_returned_studies": len(studies),
            "unreported_study_metadata_loci": sum(row["study"] is None for row in links),
            "provider_page": page_index,
            "requested_page_size": limit,
            "exhaustive_gene_link_window": page_index == 0 and page["count"] == len(links),
            **boundary,
        },
        "continuation": next_page,
        "method": {
            "name": "Retain target.credibleSets linkage and deduplicate equal acquired study metadata by study ID; provider counts refer to credible sets, not unique studies.",
            "inputs": ["/target/credibleSets/rows"],
        },
        "warnings": [
            "Gene-linked study discovery is a source linkage, not causal assignment. Unreported study metadata remain visible as null links.",
            "This bounded locus window is not necessarily the complete set of studies for the gene. Live source data remain unpinned.",
            *([PAGE_LIMIT_WARNING] if boundary else []),
        ],
    }


async def disease_studies(client, identifier, limit=25, page_index=0, include_credible_sets=False):
    selector(identifier)
    bounded(limit)
    bounded(page_index, 0, MAX_PROVIDER_PAGE)
    disease = (
        await client._query(
            "query StudyDisease($id:String!){disease(efoId:$id){id name}}", {"id": identifier}
        )
    )["disease"]
    fields = STUDY_FIELDS + (
        " credibleSets(page:{index:0,size:10}){count rows{" + CREDIBLE_FIELDS + "}}"
        if include_credible_sets
        else ""
    )
    query = (
        "query DiseaseStudies($disease:[String!],$index:Int!,$size:Int!){studies(diseaseIds:$disease,enableIndirect:false,page:{index:$index,size:$size}){count rows{"
        + fields
        + "}}}"
    )

    async def acquired_studies():
        page = (await client._query(query, {"disease": [identifier], "index": page_index, "size": limit}))[
            "studies"
        ]
        rows = page["rows"]
        if len(rows) > limit or len({row["id"] for row in rows}) != len(rows):
            invalid_shape()
        offset = page_index * limit
        if (
            offset + len(rows) > page["count"]
            or offset < page["count"]
            and len(rows) < min(limit, page["count"] - offset)
        ):
            invalid_shape()
        for row in rows:
            checked_study_counts(row)
            if include_credible_sets:
                loci = checked_credible_rows(row["credibleSets"], 10)
                checked_window(row["credibleSets"], 10, 0)
                if any(locus["studyId"] != row["id"] for locus in loci):
                    invalid_shape()
        return page

    page, status = await acquire_section(acquired_studies)
    continuation = None
    boundary = {}
    if page is not None and page_index * limit + len(page["rows"]) < page["count"]:
        next_index, boundary = page_continuation(page_index + 1)
        continuation = (
            {
                "tool": "query_source",
                "arguments": {
                    "source": "opentargets",
                    "operation": "query_genetics",
                    "params": {
                        "query_type": "study",
                        "disease_id": identifier,
                        "include_credible_sets": include_credible_sets,
                        "page_index": next_index,
                        "limit": limit,
                    },
                },
            }
            if next_index is not None
            else None
        )
    return {
        "record_type": "opentargets_disease_studies",
        "disease_id": identifier,
        "source_disease": disease,
        "records": page["rows"] if page is not None else None,
        "source_studies": page,
        "section_outcomes": {
            "disease": {"outcome": "data"},
            "studies": status,
            **continuation_outcomes(boundary),
        },
        "coverage": {
            "provider_study_total": page["count"],
            "returned_studies": len(page["rows"]),
            "provider_page": page_index,
            "requested_page_size": limit,
            "exhaustive": page_index == 0 and page["count"] == len(page["rows"]),
            **boundary,
        }
        if page is not None
        else None,
        "credible_set_coverage": {
            row["id"]: {
                "provider_total": row["credibleSets"]["count"],
                "returned_loci": len(row["credibleSets"]["rows"]),
                "exhaustive": row["credibleSets"]["count"] == len(row["credibleSets"]["rows"]),
            }
            for row in page["rows"]
        }
        if page is not None and include_credible_sets
        else None,
        "credible_set_continuations": {
            row["id"]: study_page_action(row["id"], 10, 1)
            for row in page["rows"]
            if row["credibleSets"]["count"] > len(row["credibleSets"]["rows"])
        }
        if page is not None and include_credible_sets
        else None,
        "continuation": continuation,
        "method": {
            "name": "Retain studies selected by one indexed disease identifier with indirect propagation disabled; optional credible-set evidence is bounded to ten loci per study.",
            "inputs": ["/source_disease", "/source_studies/rows"],
        },
        "warnings": [
            "Study/disease linkage is not proof of causality. Source study types and unreported counts retain their meanings.",
            "Credible-set windows are independent of study pagination. Inspect each study's locus coverage; a study continuation cannot recover omitted loci.",
            "Empty indexed collections do not establish absence; live data remain unpinned.",
            *([PAGE_LIMIT_WARNING] if boundary else []),
        ],
    }


async def prioritize_targets(client, disease_id, identifiers=(), limit=10):
    selector(disease_id)
    bounded(limit)
    if not isinstance(identifiers, (tuple, list)) or len(identifiers) > 10:
        invalid_request()
    for identifier in identifiers:
        gene(identifier)
    if len(set(identifiers)) != len(identifiers):
        invalid_request()
    query = (
        "query PrioritizeTargets($disease:String!,$ids:[String!]){disease(efoId:$disease){id name associatedTargets(Bs:$ids,enableIndirect:false,page:{index:0,size:100}){count rows{target{"
        + IDENTITY_FIELDS
        + "} score datatypeScores{id score}}}}}"
    )
    disease = (await client._query(query, {"disease": disease_id, "ids": list(identifiers) or None}))[
        "disease"
    ]
    page = disease["associatedTargets"]
    rows = page["rows"]
    ids = [row["target"]["id"] for row in rows]
    if len(rows) > WINDOW or len(ids) != len(set(ids)) or identifiers and set(ids) - set(identifiers):
        invalid_shape()
    ranked, unreported = [], []
    for index, row in enumerate(rows):
        gene(row["target"]["id"], returned=True)
        components = row["datatypeScores"]
        if len({c["id"] for c in components}) != len(components):
            invalid_shape()
        component = next((c for c in components if c["id"] == "genetic_association"), None)
        item = {
            "target": row["target"],
            "genetic_association_score": component["score"] if component else None,
            "overall_association_score": row["score"],
            "inputs": [f"/source_disease/associatedTargets/rows/{index}"],
        }
        (ranked if component else unreported).append(item)
    ranked.sort(key=lambda row: (-row["genetic_association_score"], row["target"]["id"]))
    return {
        "record_type": "opentargets_genetic_association_ranking",
        "disease_id": disease_id,
        "requested_targets": list(identifiers),
        "source_disease": disease,
        "ranked_targets": ranked[:limit],
        "unreported_genetic_score": unreported,
        "unindexed_requested_targets": [identifier for identifier in identifiers if identifier not in ids],
        "section_outcomes": {
            row["target"]["id"]: {
                "outcome": "data" if row["genetic_association_score"] is not None else "unavailable"
            }
            for row in ranked + unreported
        },
        "coverage": {
            "provider_total": page["count"],
            "acquired_rows": len(rows),
            "measured_genetic_rows": len(ranked),
            "unreported_genetic_rows": len(unreported),
            "returned_ranked_rows": len(ranked[:limit]),
            "provider_page": 0,
            "requested_page_size": WINDOW,
            "candidate_window_exhaustive": page["count"] == len(rows),
        },
        "method": {
            "name": "Rank acquired candidates by the separately reported genetic_association datatype score, then Ensembl ID.",
            "inputs": ["/source_disease/associatedTargets/rows"],
            "missing_score_policy": "Retain unreported genetic scores separately; never substitute the overall or somatic-mutation score.",
        },
        "warnings": [
            "Ranking is limited to the first 100 direct source associations. Overall provider ordering determines this candidate window; this is not a global genetic ranking when coverage is incomplete.",
            "Genetic association scores are source evidence heuristics, not causal confidence, clinical efficacy, target safety or therapeutic recommendations.",
            "Unindexed targets and unreported genetic scores do not establish absence. Live data remain unpinned.",
        ],
    }
