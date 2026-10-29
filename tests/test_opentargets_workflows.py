"""Advertised workflows acquire records and keep their scientific meanings."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from opentargets_helpers import IDENTITY, project, target
from opentargets_mcp import queries
from opentargets_mcp.queries import OpenTargetsClient
from opentargets_mcp.tools.unified import UnifiedTools
from test_opentargets_responses import Transport
from test_qualified_gene_identity import HUMAN

from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.opentargets_workflows import gene_credible_sets, similar_targets

PEER = "ENSG00000141510"
BEST = "ENSG00000142208"
PARTNERS = ["ENSG00000000001", "ENSG00000000002", "ENSG00000000003"]
DISEASE = "MONDO_0000001"
VARIANT = "7_1001_A_T"
SENTINEL = "SYNTHETIC_API_KEY_MUST_NOT_ESCAPE_WORKFLOW_FAILURE"


def interaction(identifier, partner, species=9606):
    return {
        "intA": "synthetic-protein-A",
        "intB": "synthetic-protein-B",
        "targetA": {"id": identifier},
        "targetB": {"id": partner},
        "speciesA": {"taxonId": 9606},
        "speciesB": {"taxonId": species},
        "sourceDatabase": "synthetic-interaction-source",
    }


def annotated(identifier, positions):
    result = target(identifier, "BRAF" if identifier == IDENTITY else "SYNTHETIC")
    result["pathways"] = [{"pathwayId": f"R-HSA-{i}"} for i in positions]
    result["geneOntology"] = [{"term": {"id": f"GO:{i:07d}"}} for i in positions]
    result["associatedDiseases"] = {
        "count": len(positions),
        "rows": [{"disease": {"id": f"EFO_{i:07d}"}} for i in positions],
    }
    result["interactions"] = {
        "count": len(positions),
        "rows": [interaction(identifier, PARTNERS[i - 1]) for i in positions],
    }
    return result


def study():
    return {
        "id": "synthetic-study",
        "studyType": "gwas",
        "projectId": "synthetic-project",
        "traitFromSource": "Synthetic trait",
        "pubmedId": None,
        "nSamples": 1000,
        "nCases": 400,
        "nControls": 600,
        "target": None,
        "diseases": [{"id": DISEASE, "name": "Synthetic disease", "therapeuticAreas": []}],
        "condition": None,
        "publicationTitle": None,
        "publicationJournal": None,
        "publicationFirstAuthor": None,
        "publicationDate": None,
        "cohorts": [],
        "hasSumstats": False,
        "summarystatsLocation": None,
        "initialSampleSize": None,
        "analysisFlags": [],
        "qualityControls": [],
        "ldPopulationStructure": [],
        "discoverySamples": [],
        "replicationSamples": [],
        "sumstatQCValues": [],
        "biosample": None,
        "backgroundTraits": [],
    }


def credible(index=0):
    return {
        "studyLocusId": f"synthetic-locus-{index}",
        "studyId": "synthetic-study",
        "studyType": "gwas",
        "chromosome": "7",
        "position": 1001,
        "pValueMantissa": 8.0,
        "pValueExponent": -9,
        "finemappingMethod": "Synthetic method",
        "confidence": None,
        "qtlGeneId": None,
        "variant": {
            "id": VARIANT,
            "chromosome": "7",
            "position": 1001,
            "referenceAllele": "A",
            "alternateAllele": "T",
            "rsIds": [],
        },
        "study": study(),
    }


class Provider(Transport):
    def __init__(self, failures=(), mode="network", total=1):
        super().__init__({})
        self.failures = set(failures)
        self.mode = mode
        self.wire_mutation = None
        self.reference = annotated(IDENTITY, [1, 2])
        self.reference["similarEntities"] = [
            {"id": IDENTITY, "category": "target", "score": 1.0},
            {"id": PEER, "category": "target", "score": 0.95},
            {"id": BEST, "category": "target", "score": 0.1},
        ]
        self.candidates = [annotated(PEER, [1, 3]), annotated(BEST, [1, 2])]
        self.loci = [credible(i) for i in range(total)]
        self.disease = {
            "id": DISEASE,
            "name": "Synthetic disease",
            "associatedTargets": {
                "count": 2,
                "rows": [
                    {
                        "target": self.candidates[0],
                        "score": 0.99,
                        "datatypeScores": [
                            {"id": "genetic_association", "score": 0.2},
                            {"id": "somatic_mutation", "score": 0.9},
                        ],
                    },
                    {
                        "target": self.candidates[1],
                        "score": 0.1,
                        "datatypeScores": [{"id": "genetic_association", "score": 0.8}],
                    },
                ],
            },
        }
        self.variant = {
            "id": VARIANT,
            "variantDescription": "Synthetic variant",
            "chromosome": "7",
            "position": 1001,
            "referenceAllele": "A",
            "alternateAllele": "T",
            "hgvsId": None,
            "rsIds": [],
            "dbXrefs": [],
            "alleleFrequencies": [],
            "mostSevereConsequence": None,
            "transcriptConsequences": [],
            "variantEffect": [],
        }
        self.studies = [{**study(), "credibleSets": {"count": 1, "rows": [credible()]}}]

    async def post(self, url, **kwargs):
        body = kwargs["json"]
        query, variables = body["query"], body["variables"]
        fail = any(marker in query for marker in self.failures)
        if fail and self.mode == "network":
            self.calls.append((url, kwargs))
            raise httpx.ConnectError(SENTINEL)
        if fail and self.mode == "malformed":
            self.payload = {}
        else:
            if "SimilarityReference" in query:
                payload = {"data": {"target": self.reference}}
            elif "SimilarityCandidates" in query:
                payload = {"data": {"targets": self.candidates}}
            elif "GeneCredibleSets" in query or "GeneStudies" in query:
                start, size = variables["index"] * variables["size"], variables["size"]
                payload = {
                    "data": {
                        "target": {
                            **self.reference,
                            "credibleSets": {
                                "count": len(self.loci),
                                "rows": self.loci[start : start + size],
                            },
                        }
                    }
                }
            elif "PrioritizeTargets" in query or "StudyDisease" in query:
                payload = {"data": {"disease": self.disease}}
            elif "DiseaseStudies" in query:
                start, size = variables["index"] * variables["size"], variables["size"]
                rows = deepcopy(self.studies[start : start + size])
                for row in rows:
                    row["credibleSets"]["rows"] = row["credibleSets"]["rows"][:10]
                payload = {"data": {"studies": {"count": len(self.studies), "rows": rows}}}
            elif "StudyCredibleEvidence" in query:
                value = next(row for row in self.studies if row["id"] == variables["id"])
                start, size = variables["index"] * variables["size"], variables["size"]
                payload = {
                    "data": {
                        "study": {
                            **value,
                            "credibleSets": {
                                "count": value["credibleSets"]["count"],
                                "rows": value["credibleSets"]["rows"][start : start + size],
                            },
                        }
                    }
                }
            elif "StudyInfo" in query:
                payload = {
                    "data": {"study": next(row for row in self.studies if row["id"] == variables["studyId"])}
                }
            elif "VariantInfo" in query:
                payload = {"data": {"variant": self.variant}}
            else:
                raise AssertionError("Undeclared synthetic provider query")
            self.payload = project(payload, query, variables)
            if self.wire_mutation is not None:
                self.wire_mutation(self.payload)
        return await super().post(url, **kwargs)


@pytest.fixture
def provider(monkeypatch):
    p = Provider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    return p


@pytest.mark.parametrize("criterion", ["pathways", "go_terms", "diseases", "interactions"])
async def test_similarity_uses_actual_annotation_overlap_not_candidate_model_score(provider, criterion):
    result = await UnifiedTools().analyze_advanced(
        OpenTargetsClient(), "similar", [IDENTITY], similarity_criteria=criterion, threshold=0.3
    )
    assert [row["target_id"] for row in result["similar_targets"]] == [BEST, PEER]
    best, other = result["similar_targets"]
    assert best["annotation_jaccard"] == 1.0 and best["literature_model_score"] == 0.1
    assert other["annotation_jaccard"] == pytest.approx(1 / 3) and other["literature_model_score"] == 0.95
    assert best["intersection_count"] == best["union_count"] == 2
    assert other["intersection_count"] == 1 and other["union_count"] == 3
    assert result["coverage"]["exhaustive"] is False
    assert result["reference_target"]["id"] == IDENTITY and result["candidate_annotations"]
    assert len(provider.calls) == 2


@pytest.mark.parametrize("threshold,limit,ids", [(0.34, 10, [BEST]), (0, 1, [BEST]), (1, 10, [BEST])])
async def test_threshold_and_display_limit_are_applied_to_the_requested_measure(
    provider, threshold, limit, ids
):
    result = await similar_targets(OpenTargetsClient(), IDENTITY, threshold=threshold, limit=limit)
    assert [row["target_id"] for row in result["similar_targets"]] == ids
    assert len(result["comparisons"]) == 2


@pytest.mark.parametrize(
    "mutation", ["duplicate", "foreign", "wrong_category", "negative", "over_one", "nan", "missing"]
)
async def test_invalid_candidate_index_cannot_mint_healthy_similarity(provider, mutation):
    rows = provider.reference["similarEntities"]
    if mutation == "duplicate":
        rows.append(deepcopy(rows[-1]))
    elif mutation == "foreign":
        rows[-1]["id"] = "ENSMUSG00000000001"
    elif mutation == "wrong_category":
        rows[-1]["category"] = "disease"
    elif mutation == "missing":
        provider.wire_mutation = lambda payload: payload["data"]["target"]["similarEntities"][-1].pop("score")
    else:
        rows[-1]["score"] = {"negative": -0.1, "over_one": 1.1, "nan": float("nan")}[mutation]
    with pytest.raises(ResearchError):
        await similar_targets(OpenTargetsClient(), IDENTITY)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_failed_candidate_acquisition_preserves_primary_without_zero_scores(monkeypatch, mode, capsys):
    p = Provider(["SimilarityCandidates"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    result = await similar_targets(OpenTargetsClient(), IDENTITY)
    assert result["reference_target"]["id"] == IDENTITY
    assert result["candidate_annotations"] is result["comparisons"] is result["similar_targets"] is None
    assert result["coverage"]["eligible_candidates"] is None
    assert result["section_outcomes"]["candidate_annotations"]["outcome"] == "error"
    assert SENTINEL not in json.dumps(result) + capsys.readouterr().out


async def test_missing_candidate_and_undefined_empty_union_are_unavailable(provider):
    provider.candidates = provider.candidates[:1]
    provider.reference["pathways"] = []
    provider.candidates[0]["pathways"] = []
    result = await similar_targets(OpenTargetsClient(), IDENTITY)
    assert result["similar_targets"] == []
    assert all(row["annotation_jaccard"] is None for row in result["comparisons"])
    assert result["section_outcomes"][BEST]["outcome"] == "unavailable"
    assert result["coverage"]["measurable_candidates"] == 0


async def test_interaction_overlap_excludes_unqualified_species_and_retains_coverage(provider):
    page = provider.reference["interactions"]
    page["rows"].append(interaction(IDENTITY, "ENSMUSG00000000001", 10090))
    page["rows"].append(interaction(IDENTITY, PARTNERS[2], None))
    page["count"] = 104
    result = await similar_targets(OpenTargetsClient(), IDENTITY, "interactions")
    coverage = result["reference_annotation_coverage"]
    assert coverage["excluded_unqualified_partner_rows"] == 2
    assert coverage["unique_annotation_count"] == 2 and coverage["window_exhaustive"] is False
    assert result["similar_targets"][0]["annotation_jaccard"] == 1


@pytest.mark.parametrize("outcome", [None, []])
async def test_unavailable_interactions_differ_from_an_empty_index(provider, outcome):
    if outcome is None:
        provider.reference["interactions"] = None
        result = await similar_targets(OpenTargetsClient(), IDENTITY, "interactions")
        assert (
            result["similar_targets"] is None
            and result["section_outcomes"]["reference_features"]["outcome"] == "unavailable"
        )
    else:
        provider.reference["similarEntities"] = []
        result = await similar_targets(OpenTargetsClient(), IDENTITY)
        assert result["similar_targets"] == [] and result["coverage"]["exhaustive"] is False
    assert len(provider.calls) == 1


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_actual_mcp_partial_similarity_retries_then_caches_valid_measurements(monkeypatch, mode):
    p = Provider(["SimilarityCandidates"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_advanced",
        "params": {"analysis_type": "similar", "entity_ids": [IDENTITY], "threshold": 0.9},
    }
    async with Client(create_server(service=ResearchService())) as c:
        for _ in range(2):
            result = (await c.call_tool("query_source", args)).data
            assert result["outcome"] == "partial"
            assert result["sections"]["opentargets"]["data"]["reference_target"]["id"] == IDENTITY
            assert all(not v["cached"] for v in result["provenance"])
        p.failures.clear()
        good = (await c.call_tool("query_source", args)).data
        cached = (await c.call_tool("query_source", args)).data
        assert good["outcome"] == cached["outcome"] == "data"
        assert good["sections"]["opentargets"]["data"]["similar_targets"][0]["annotation_jaccard"] == 1
        assert any(v["cached"] for v in cached["provenance"])
    assert len(p.calls) == 6


@pytest.mark.parametrize(
    "params",
    [
        {"analysis_type": "similar", "entity_ids": []},
        {"analysis_type": "similar", "entity_ids": [IDENTITY, PEER]},
        {"analysis_type": "similar", "entity_ids": [IDENTITY], "threshold": True},
        {"analysis_type": "similar", "entity_ids": [IDENTITY], "threshold": -1},
        {"analysis_type": "similar", "entity_ids": [IDENTITY], "threshold": float("nan")},
        {"analysis_type": "similar", "entity_ids": [IDENTITY], "similarity_criteria": "unknown"},
        {"analysis_type": "similar", "entity_ids": [IDENTITY], "limit": 101},
        {"analysis_type": "compare", "entity_ids": [IDENTITY, PEER], "disease_id": DISEASE},
        {"analysis_type": "prioritize", "entity_ids": [IDENTITY, IDENTITY], "disease_id": DISEASE},
        {"analysis_type": "prioritize", "entity_ids": [], "disease_id": DISEASE, "threshold": 0.9},
        {"analysis_type": "metadata", "entity_ids": [IDENTITY]},
    ],
)
async def test_invalid_or_unconsumed_advanced_parameters_fail_before_wire(provider, params):
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().analyze_advanced(OpenTargetsClient(), **params)
    assert caught.value.code == "invalid_parameters" and provider.calls == []


async def test_prioritization_uses_genetic_component_and_every_requested_target(provider):
    result = await UnifiedTools().analyze_advanced(
        OpenTargetsClient(), "prioritize", [PEER, BEST], disease_id=DISEASE, limit=1
    )
    assert result["ranked_targets"][0]["target"]["id"] == BEST
    assert result["ranked_targets"][0]["genetic_association_score"] == 0.8
    assert result["ranked_targets"][0]["overall_association_score"] == 0.1
    assert provider.calls[0][1]["json"]["variables"]["ids"] == [PEER, BEST]
    assert result["source_disease"]["associatedTargets"]["rows"][0]["score"] == 0.99


async def test_missing_genetic_component_is_not_overall_or_somatic_score(provider):
    provider.disease["associatedTargets"]["rows"][0]["datatypeScores"] = [
        {"id": "somatic_mutation", "score": 0.9}
    ]
    result = await UnifiedTools().analyze_advanced(OpenTargetsClient(), "prioritize", [], disease_id=DISEASE)
    assert result["coverage"]["unreported_genetic_rows"] == 1
    assert result["unreported_genetic_score"][0]["genetic_association_score"] is None
    assert len(result["ranked_targets"]) == 1
    assert result["section_outcomes"][PEER]["outcome"] == "unavailable"


async def test_gene_studies_and_detailed_credible_sets_are_distinct_executable_projections(provider):
    tools = UnifiedTools()
    minimal = await tools.query_genetics(OpenTargetsClient(), "study", gene_id=IDENTITY)
    detailed = await tools.query_genetics(
        OpenTargetsClient(), "study", gene_id=IDENTITY, include_credible_sets=True
    )
    assert (
        minimal["record_type"] == "opentargets_gene_studies"
        and minimal["records"][0]["id"] == "synthetic-study"
    )
    assert (
        detailed["record_type"] == "opentargets_gene_credible_sets"
        and detailed["records"][0]["studyId"] == "synthetic-study"
    )
    assert "variant" not in minimal["target"]["credibleSets"]["rows"][0]
    assert detailed["records"][0]["variant"]["id"] == VARIANT


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_study",
        "wrong_variant",
        "wrong_position",
        "invalid_pvalue",
        "negative_samples",
        "incoherent_samples",
        "duplicate",
    ],
)
async def test_invalid_credible_record_cannot_be_healthy_gene_genetics(provider, mutation):
    row = provider.loci[0]
    if mutation == "wrong_study":
        row["study"]["id"] = "foreign-study"
    elif mutation == "wrong_variant":
        row["variant"]["id"] = "7_1001_A_C"
    elif mutation == "wrong_position":
        row["variant"]["position"] = 1002
    elif mutation == "invalid_pvalue":
        row["pValueExponent"] = 1
    elif mutation == "negative_samples":
        row["study"]["nSamples"] = -1
    elif mutation == "incoherent_samples":
        row["study"]["nSamples"] = 900
    else:
        provider.loci.append(deepcopy(row))
    with pytest.raises(ResearchError) as caught:
        await gene_credible_sets(OpenTargetsClient(), IDENTITY)
    assert caught.value.code == "invalid_source_response"


async def test_actual_mcp_qualified_gene_genetics_and_continuation_keep_loci_and_studies(monkeypatch):
    class Adapters(SourceAdapters):
        async def call(self, source, operation, params):
            if source == "mygene":
                return {"hits": [deepcopy(HUMAN)]}
            return await super().call(source, operation, params)

    p = Provider(total=12)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as c:
        result = (
            await c.call_tool("get", {"entity": "gene", "id": "673", "sections": ["record", "genetics"]})
        ).data
        section = result["sections"]["genetics"]
        assert section["outcome"] == "data" and section["evidence_ids"]
        data = section["data"]
        assert data["qualified_identity"]["symbol"] == "BRAF" and len(data["records"]) == 10
        next_action = data["continuation"]
        next_page = (await c.call_tool(next_action["tool"], next_action["arguments"])).data
        records = next_page["sections"]["genetics"]["data"]["records"]
        assert [row["studyLocusId"] for row in records] == ["synthetic-locus-10", "synthetic-locus-11"]
        assert next_page["sections"]["genetics"]["data"]["continuation"] is None
    assert len(p.calls) == 2


@pytest.mark.parametrize("functional", [True, False])
async def test_variant_functional_flag_controls_selected_wire_fields(provider, functional):
    result = await UnifiedTools().query_genetics(
        OpenTargetsClient(), "variant", variant_id=VARIANT, include_functional_consequences=functional
    )
    assert ("transcriptConsequences" in result["variant"]) is functional
    assert ("variantEffect" in result["variant"]) is functional
    assert provider.calls[0][1]["json"]["variables"]["functional"] is functional


@pytest.mark.parametrize(
    "params",
    [
        {"query_type": "variant"},
        {"query_type": "study"},
        {"query_type": "credible_set"},
        {"query_type": "study", "gene_id": IDENTITY, "disease_id": DISEASE},
        {"query_type": "variant", "variant_id": VARIANT, "gene_id": IDENTITY},
        {"query_type": "study", "gene_id": IDENTITY, "page_index": -1},
        {"query_type": "study", "gene_id": IDENTITY, "include_evidences": True},
    ],
)
async def test_missing_or_conflicting_genetics_selectors_cannot_return_placeholders(provider, params):
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().query_genetics(OpenTargetsClient(), **params)
    assert caught.value.code == "invalid_parameters" and provider.calls == []


@pytest.mark.parametrize("include", [False, True])
async def test_disease_study_projection_consumes_credible_set_flag(provider, include):
    result = await UnifiedTools().query_genetics(
        OpenTargetsClient(), "study", disease_id=DISEASE, include_credible_sets=include
    )
    assert result["source_disease"]["id"] == DISEASE
    assert result["records"][0]["id"] == "synthetic-study"
    assert ("credibleSets" in result["records"][0]) is include
    assert result["credible_set_coverage"] == (
        {"synthetic-study": {"provider_total": 1, "returned_loci": 1, "exhaustive": True}}
        if include
        else None
    )
    assert len(provider.calls) == 2


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_disease_study_failure_retains_verified_disease_and_unavailable_counts(monkeypatch, mode):
    p = Provider(["DiseaseStudies"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    result = await UnifiedTools().query_genetics(OpenTargetsClient(), "study", disease_id=DISEASE)
    assert result["source_disease"]["id"] == DISEASE
    assert result["records"] is result["coverage"] is None
    assert result["section_outcomes"]["studies"]["outcome"] == "error"
    assert SENTINEL not in json.dumps(result)


class GeneAdapters(SourceAdapters):
    async def call(self, source, operation, params):
        if source == "mygene":
            return {"hits": [deepcopy(HUMAN)]}
        return await super().call(source, operation, params)


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_actual_mcp_gene_failure_cannot_mint_empty_genetics_and_retries(monkeypatch, mode):
    p = Provider(["GeneCredibleSets"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {"entity": "gene", "id": "673", "sections": ["record", "genetics"]}
    async with Client(create_server(service=ResearchService(adapters=GeneAdapters()))) as c:
        first = (await c.call_tool("get", args)).data
        assert first["outcome"] == "partial" and first["sections"]["record"]["evidence_ids"]
        assert (
            first["sections"]["genetics"]["outcome"] == ("unavailable" if mode == "network" else "error")
            and first["sections"]["genetics"]["evidence_ids"] == []
        )
        p.failures.clear()
        good = (await c.call_tool("get", args)).data
        cached = (await c.call_tool("get", args)).data
        assert good["sections"]["genetics"]["data"]["records"][0]["studyLocusId"] == "synthetic-locus-0"
        assert good["outcome"] == cached["outcome"] == "data"
        assert good["sections"]["genetics"]["evidence_ids"] == cached["sections"]["genetics"]["evidence_ids"]
    assert len(p.calls) == 2


@pytest.mark.parametrize("malformed", [True, False])
async def test_wrong_gene_symbol_or_empty_composed_payload_cannot_mint_genetic_evidence(
    monkeypatch, malformed
):
    class Adapters(GeneAdapters):
        async def call(self, source, operation, params):
            if malformed and source == "opentargets":
                return {}
            return await super().call(source, operation, params)

    p = Provider()
    p.reference["approvedSymbol"] = "FOREIGN_SYMBOL"
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as c:
        for _ in range(2):
            result = (
                await c.call_tool("get", {"entity": "gene", "id": "673", "sections": ["record", "genetics"]})
            ).data
            assert result["outcome"] == "partial" and result["sections"]["genetics"]["evidence_ids"] == []
            assert result["sections"]["genetics"]["error"]["code"] == "invalid_source_response"
    assert len(p.calls) == (0 if malformed else 2)


@pytest.mark.parametrize("mutation", ["wrong_id", "duplicate_id", "invalid_type", "foreign_interaction"])
async def test_invalid_bulk_candidate_annotations_do_not_replace_primary_with_empty(provider, mutation):
    if mutation == "wrong_id":
        provider.candidates[0]["id"] = "ENSG00000000001"
    elif mutation == "duplicate_id":
        provider.candidates.append(deepcopy(provider.candidates[0]))
    elif mutation == "invalid_type":
        provider.candidates[0]["pathways"] = None
    else:
        provider.candidates[0]["interactions"]["rows"][0]["speciesA"]["taxonId"] = 10090
    result = await similar_targets(
        OpenTargetsClient(), IDENTITY, "interactions" if mutation == "foreign_interaction" else "pathways"
    )
    assert result["reference_target"]["id"] == IDENTITY
    assert result["section_outcomes"]["candidate_annotations"]["error"]["code"] == "invalid_source_response"
    assert result["similar_targets"] is None


async def test_explicit_missing_credible_metadata_are_not_zero_samples(provider):
    provider.loci[0]["study"] = None
    provider.loci[0]["variant"] = None
    result = await gene_credible_sets(OpenTargetsClient(), IDENTITY)
    assert result["records"][0]["study"] is result["records"][0]["variant"] is None
    assert result["coverage"]["provider_total"] == 1


@pytest.mark.parametrize("mantissa,exponent", [(0.0, -100), (0.08, 1), (80.0, -3)])
async def test_credible_pvalue_components_are_retained_without_invented_normalization(
    provider, mantissa, exponent
):
    provider.loci[0].update(pValueMantissa=mantissa, pValueExponent=exponent)
    result = await gene_credible_sets(OpenTargetsClient(), IDENTITY)
    returned = result["records"][0]
    assert (returned["pValueMantissa"], returned["pValueExponent"]) == (mantissa, exponent)


async def test_discovery_minimum_score_filters_genetic_component_and_keeps_acquired_records(provider):
    result = await UnifiedTools().analyze_association(
        OpenTargetsClient(), DISEASE, association_type="discover-opportunities", filters={"min_score": 0.5}
    )
    assert [row["target"]["id"] for row in result["ranked_targets"]] == [BEST]
    assert len(result["source_disease"]["associatedTargets"]["rows"]) == 2
    assert result["filtering"]["excluded_below_threshold"] == 1


@pytest.mark.parametrize("strategy", ["safety", "novelty", "approved_drugs", "unknown"])
async def test_unqualified_therapeutic_rankings_are_not_fabricated_from_overall_scores(provider, strategy):
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().analyze_association(
            OpenTargetsClient(), DISEASE, association_type="discover-opportunities", ranking_strategy=strategy
        )
    assert caught.value.code == "invalid_parameters" and provider.calls == []


async def test_actual_mcp_disease_study_and_locus_continuations_recover_separate_windows(
    provider, monkeypatch
):
    provider.studies[0]["credibleSets"] = {"count": 12, "rows": [credible(i) for i in range(12)]}
    second = {**study(), "id": "synthetic-second-study", "credibleSets": {"count": 0, "rows": []}}
    provider.studies.append(second)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as c:
        first = (
            await c.call_tool(
                "query_source",
                {
                    "source": "opentargets",
                    "operation": "query_genetics",
                    "params": {
                        "query_type": "study",
                        "disease_id": DISEASE,
                        "include_credible_sets": True,
                        "limit": 1,
                    },
                },
            )
        ).data
        data = first["sections"]["opentargets"]["data"]
        assert len(data["records"][0]["credibleSets"]["rows"]) == 10
        assert data["credible_set_coverage"]["synthetic-study"]["exhaustive"] is False
        action = data["continuation"]
        next_study = (await c.call_tool(action["tool"], action["arguments"])).data
        assert next_study["sections"]["opentargets"]["data"]["records"][0]["id"] == second["id"]
        action = data["credible_set_continuations"]["synthetic-study"]
        next_locus = (await c.call_tool(action["tool"], action["arguments"])).data
        detail = next_locus["sections"]["opentargets"]["data"]
        assert detail["study"]["id"] == "synthetic-study"
        assert [row["studyLocusId"] for row in detail["credible_sets"]["records"]] == [
            "synthetic-locus-10",
            "synthetic-locus-11",
        ]
        assert detail["credible_sets"]["coverage"]["exhaustive"] is False
        assert detail["credible_sets"]["continuation"] is None
    assert len(provider.calls) == 6


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_study_locus_failure_keeps_primary_and_retries_actual_mcp(monkeypatch, mode):
    p = Provider(["StudyCredibleEvidence"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "query_genetics",
        "params": {"query_type": "study", "study_id": "synthetic-study", "include_credible_sets": True},
    }
    async with Client(create_server(service=ResearchService())) as c:
        for _ in range(2):
            result = (await c.call_tool("query_source", args)).data
            data = result["sections"]["opentargets"]["data"]
            assert result["outcome"] == "partial" and data["study"]["nSamples"] == 1000
            assert (
                data["credible_sets"] is None
                and data["section_outcomes"]["credible_sets"]["outcome"] == "error"
            )
            assert SENTINEL not in json.dumps(result)
        p.failures.clear()
        good = (await c.call_tool("query_source", args)).data
        cached = (await c.call_tool("query_source", args)).data
        assert good["outcome"] == cached["outcome"] == "data"
        assert (
            cached["sections"]["opentargets"]["evidence_ids"]
            == good["sections"]["opentargets"]["evidence_ids"]
        )
    assert len(p.calls) == 6


@pytest.mark.parametrize(
    "mutation",
    ["wrong_size", "wrong_index", "false_exhaustive", "missing_continuation", "foreign_continuation"],
)
async def test_native_gene_composition_rejects_forged_coverage_and_recovery(monkeypatch, mutation):
    class Adapters(GeneAdapters):
        async def call(self, source, operation, params):
            value = await super().call(source, operation, params)
            if source == "opentargets":
                if mutation == "wrong_size":
                    value["coverage"]["requested_page_size"] = 20
                elif mutation == "wrong_index":
                    value["coverage"]["provider_page"] = 1
                elif mutation == "false_exhaustive":
                    value["coverage"]["exhaustive"] = True
                elif mutation == "missing_continuation":
                    value["continuation"] = None
                else:
                    value["continuation"]["arguments"]["id"] = PEER
            return value

    p = Provider(total=12)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as c:
        result = (
            await c.call_tool("get", {"entity": "gene", "id": "673", "sections": ["record", "genetics"]})
        ).data
        assert result["outcome"] == "partial" and result["sections"]["genetics"]["evidence_ids"] == []
        assert result["sections"]["genetics"]["error"]["code"] == "invalid_source_response"


@pytest.mark.parametrize(
    "params",
    [
        {"association_type": "discover-opportunities", "target_id": PEER},
        {"association_type": "discover-opportunities", "evidence_types": ["genetic_association"]},
        {"association_type": "discover-opportunities", "evidence_cursor": "unconsumed"},
        {"association_type": "discover-opportunities", "min_score": 0.8, "filters": {"min_score": 0.2}},
        {"association_type": "target-disease", "target_id": DISEASE, "filters": {}},
        {"association_type": "target-disease", "target_id": DISEASE, "ranking_strategy": "genetic_evidence"},
        {"association_type": "drug-target", "target_id": PEER},
        {"association_type": "drug-disease", "limit": 2},
    ],
)
async def test_association_modes_reject_unconsumed_parameters_before_wire(provider, params):
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().analyze_association(OpenTargetsClient(), DISEASE, **params)
    assert caught.value.code == "invalid_parameters" and provider.calls == []


async def test_discovery_min_score_parameter_is_actually_consumed(provider):
    result = await UnifiedTools().analyze_association(
        OpenTargetsClient(), DISEASE, association_type="discover-opportunities", min_score=0.5
    )
    assert [row["target"]["id"] for row in result["ranked_targets"]] == [BEST]
    assert result["filtering"]["genetic_min_score"] == 0.5


async def test_actual_mcp_missing_genetic_scores_stay_partial_and_uncached(provider, monkeypatch):
    provider.disease["associatedTargets"]["rows"][0]["datatypeScores"] = []
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_advanced",
        "params": {"analysis_type": "prioritize", "entity_ids": [], "disease_id": DISEASE},
    }
    async with Client(create_server(service=ResearchService())) as c:
        for _ in range(2):
            result = (await c.call_tool("query_source", args)).data
            assert result["outcome"] == "partial"
            assert (
                result["sections"]["opentargets"]["data"]["unreported_genetic_score"][0][
                    "genetic_association_score"
                ]
                is None
            )
            assert all(not row["cached"] for row in result["provenance"])
    assert len(provider.calls) == 2


async def test_explicit_empty_gene_window_retains_indexed_count_and_absence_caveat(provider):
    provider.loci = []
    result = await gene_credible_sets(OpenTargetsClient(), IDENTITY)
    assert result["records"] == [] and result["coverage"]["provider_total"] == 0
    assert result["continuation"] is None and any("absence" in value for value in result["warnings"])


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_actual_mcp_primary_similarity_failure_issues_no_identity_or_evidence(monkeypatch, mode):
    p = Provider(["SimilarityReference"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as c:
        result = (
            await c.call_tool(
                "query_source",
                {
                    "source": "opentargets",
                    "operation": "analyze_advanced",
                    "params": {"analysis_type": "similar", "entity_ids": [IDENTITY]},
                },
                raise_on_error=False,
            )
        ).structured_content
        assert result["outcome"] in {"error", "unavailable"}
        assert all(not row["evidence_ids"] for row in result["sections"].values())
        assert SENTINEL not in json.dumps(result)
    assert len(p.calls) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"query_type": "study", "study_id": "synthetic-study", "page_index": 1},
        {"query_type": "study", "study_id": "synthetic-study", "limit": 10},
        {"query_type": "variant", "variant_id": VARIANT, "limit": 10},
        {"query_type": "variant", "variant_id": VARIANT, "include_credible_sets": "false"},
    ],
)
async def test_unconsumed_genetics_windows_and_nonboolean_flags_fail_before_wire(provider, params):
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().query_genetics(OpenTargetsClient(), **params)
    assert caught.value.code == "invalid_parameters" and provider.calls == []


@pytest.mark.parametrize("mode", ["gene", "study", "disease"])
async def test_actual_mcp_page_limit_keeps_source_rows_and_safe_partial_result(provider, monkeypatch, mode):
    monkeypatch.setenv("UBI_PROFILE", "local")
    provider.loci = [credible()] * 100002
    provider.studies = [{**study(), "credibleSets": {"count": 100002, "rows": provider.loci}}] * 100002

    class Adapters(SourceAdapters):
        async def call(self, source, operation, params):
            if source == "mygene":
                return {"hits": [deepcopy(HUMAN)]}
            return await super().call(source, operation, params)

    tool = "get" if mode == "gene" else "query_source"
    args = (
        {
            "entity": "gene",
            "id": IDENTITY,
            "sections": ["genetics"],
            "section_parameters": {"genetics": {"limit": 1, "page": 100000}},
        }
        if mode == "gene"
        else {
            "source": "opentargets",
            "operation": "query_genetics",
            "params": {
                "query_type": "study",
                "limit": 1,
                "page_index": 100000,
                **(
                    {"study_id": "synthetic-study", "include_credible_sets": True}
                    if mode == "study"
                    else {"disease_id": DISEASE}
                ),
            },
        }
    )
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as client:
        result = (await client.call_tool(tool, args)).structured_content
        repeated = (await client.call_tool(tool, args)).structured_content
    assert result["outcome"] == repeated["outcome"] == "partial" and result["next_actions"] == []
    data = result["sections"]["genetics" if mode == "gene" else "opentargets"]["data"]
    if mode == "study":
        assert data["study"]["id"] == "synthetic-study"
        data = data["credible_sets"]
    assert len(data["records"]) == 1
    assert data["coverage"]["continuation_reason"] == "supported_page_range_exceeded"
    assert data["coverage"]["next_provider_page"] == 100001 and data["continuation"] is None
    assert len(result["provenance"]) >= 1
    assert (
        sum(
            "GeneCredibleSets" in c[1]["json"]["query"]
            or "StudyCredibleEvidence" in c[1]["json"]["query"]
            or "DiseaseStudies" in c[1]["json"]["query"]
            for c in provider.calls
        )
        == 2
    )


async def test_internal_gene_study_window_limit_retains_acquired_study(provider):
    from biomedmcp.native.opentargets_workflows import gene_studies

    provider.loci = [credible()] * 100002
    result = await gene_studies(OpenTargetsClient(), IDENTITY, limit=1, page_index=100000)
    assert result["records"][0]["id"] == "synthetic-study"
    assert result["continuation"] is None
    assert result["coverage"]["continuation_reason"] == "supported_page_range_exceeded"
    assert result["section_outcomes"]["continuation"]["outcome"] == "partial"
