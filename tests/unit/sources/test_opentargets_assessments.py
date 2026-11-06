"""Selected advanced Open Targets interpretations, using synthetic source data."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from opentargets_helpers import IDENTITY, association, profile, project
from opentargets_mcp import queries
from opentargets_mcp.queries import OpenTargetsClient
from opentargets_mcp.tools.composite import CompositeTools
from test_opentargets_responses import Transport

from biomedmcp.errors import ResearchError
from biomedmcp.native.opentargets import assessment

DISEASE = "EFO_0000305"


def candidate():
    return {
        "id": "synthetic-candidate",
        "maxClinicalStage": "PHASE_II",
        "drug": {
            "id": "CHEMBL1",
            "name": "Synthetic candidate",
            "drugType": "Small molecule",
            "maximumClinicalStage": "PHASE_II",
        },
        "diseases": [],
        "clinicalReports": [],
    }


def evidence(identifier="synthetic-evidence", score=0.6):
    return {
        "id": identifier,
        "target": {"id": IDENTITY},
        "disease": {"id": DISEASE, "name": "Synthetic disease"},
        "score": score,
        "datasourceId": "synthetic-v1",
        "datatypeId": "genetic_association",
        "literature": ["123"],
        "biomarkerList": [{"name": "Synthetic marker", "description": "Source annotation"}],
    }


def source():
    p = profile(rows=[association()], count=10)
    p["clinical_candidates"] = {"count": 5, "rows": [candidate()]}
    return p


class Provider(Transport):
    def __init__(self, data=None, pages=None, associated=None):
        super().__init__(None)
        p = source() if data is None else data
        self.target = {
            **p["target"],
            "associatedDiseases": p["associated_diseases"],
            "drugAndClinicalCandidates": p["clinical_candidates"],
        }
        self.pages = pages or {None: {"count": 1, "cursor": None, "rows": [evidence()]}}
        self.associated = (
            associated
            if associated is not None
            else {
                "count": 1,
                "rows": [
                    {
                        "target": {"id": IDENTITY},
                        "score": 0.8,
                        "datatypeScores": [{"id": "genetic_association", "score": 0.2}],
                    }
                ],
            }
        )

    async def post(self, url, **kwargs):
        body = kwargs["json"]
        target = {**self.target, "evidences": self.pages.get(body["variables"].get("cursor"))}
        self.payload = project(
            {"data": {"target": target, "disease": {"id": DISEASE, "associatedTargets": self.associated}}},
            body["query"],
        )
        return await super().post(url, **kwargs)


async def test_assessment_keeps_actual_candidates_without_fabricated_safety_or_validation(monkeypatch):
    provider = Provider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    before = datetime.now(UTC)
    result = await CompositeTools().build_target_validation_report(OpenTargetsClient(), IDENTITY, DISEASE)
    assert before <= datetime.fromisoformat(result["generated_at"]) <= datetime.now(UTC)
    assert result["target_profile"]["clinical_candidates"] == source()["clinical_candidates"]
    summary = result["evidence_summary"]
    assert summary["clinical_candidates"]["provider_count"] == 5
    assert summary["clinical_candidates"]["returned_rows"] == 1
    assert summary["clinical_candidates"]["exhaustive"] is False
    assert summary["safety_annotations"]["reported_annotation_count"] == 0
    assert result["association_analysis"]["overall_score"] == 0.8
    assert result["association_analysis"]["datatype_scores"][0]["score"] == 0.2
    assert (
        not {"validation_scorecard", "overall_validation_score", "validation_date", "recommendations"}
        & result.keys()
    )
    assert "do not establish safety" in " ".join(result["warnings"])
    for component in summary.values():
        assert component["method"] and component["inputs"]
    assert len(provider.calls) == 5


def test_assessment_does_not_mutate_input():
    p = source()
    original = deepcopy(p)
    assessment(p, IDENTITY)
    assert p == original


@pytest.mark.parametrize("field", ["safetyLiabilities", "tractability"])
def test_null_required_annotation_collection_is_rejected(field):
    p = source()
    p["target"][field] = None
    with pytest.raises(ResearchError) as caught:
        assessment(p, IDENTITY)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("field", ["target", "associated_diseases", "clinical_candidates"])
def test_missing_assessment_inputs_fail_instead_of_receiving_default_scores(field):
    p = source()
    p.pop(field)
    with pytest.raises(ResearchError) as caught:
        assessment(p, IDENTITY)
    assert caught.value.code == "invalid_source_response"


async def test_exact_pair_query_and_absent_indexed_score_are_not_synthetic_zero(monkeypatch):
    provider = Provider(associated={"count": 0, "rows": []})
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().analyze_target_disease_association(OpenTargetsClient(), IDENTITY, DISEASE)
    assert result["overall_score"] is None and result["datatype_scores"] is None
    assert result["association_status"] == "not_indexed"
    body = provider.calls[0][1]["json"]
    assert "Bs: [$ensemblId]" in body["query"] and body["variables"]["ensemblId"] == IDENTITY
    assert result["biomarkers"] == [
        {"evidence_id": "synthetic-evidence", "annotations": evidence()["biomarkerList"]}
    ]


async def test_filtered_empty_page_retains_executable_mcp_continuation(monkeypatch):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    pages = {
        None: {"count": 2, "cursor": "synthetic-next", "rows": [evidence(score=0.2)]},
        "synthetic-next": {"count": 2, "cursor": None, "rows": [evidence("next-record", 0.9)]},
    }
    provider = Provider(pages=pages)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_association",
        "params": {
            "source_id": IDENTITY,
            "target_id": DISEASE,
            "min_score": 0.5,
            "limit": 1,
        },
    }
    async with Client(create_server(service=ResearchService())) as client:
        first = (await client.call_tool("query_source", args)).data
        data = first["sections"]["opentargets"]["data"]
        assert data["evidence"] == [] and data["coverage"]["acquired_rows"] == 1
        assert data["coverage"]["provider_total"] == 2 and not data["coverage"]["exhaustive"]
        action = first["next_actions"][0]
        second = (await client.call_tool(action["tool"], action["arguments"])).data
        next_data = second["sections"]["opentargets"]["data"]
        assert next_data["evidence"][0]["id"] == "next-record"
        assert "continuation" not in next_data and not next_data["coverage"]["exhaustive"]
    assert len(provider.calls) == 4


@pytest.mark.parametrize(
    "mutation", ["wrong_target", "wrong_disease", "wrong_association", "cursor_loop", "invalid_score"]
)
async def test_foreign_or_malformed_pair_evidence_is_rejected(monkeypatch, mutation):
    provider = Provider()
    row = provider.pages[None]["rows"][0]
    cursor = None
    if mutation == "wrong_target":
        row["target"]["id"] = "ENSG00000141510"
    elif mutation == "wrong_disease":
        row["disease"]["id"] = "EFO_0001645"
    elif mutation == "wrong_association":
        provider.associated["rows"][0]["target"]["id"] = "ENSG00000141510"
    elif mutation == "invalid_score":
        row["score"] = 1.1
    else:
        cursor = "synthetic-next"
        provider.pages = {cursor: {"count": 2, "cursor": cursor, "rows": [row]}}
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().analyze_target_disease_association(
        OpenTargetsClient(),
        IDENTITY,
        DISEASE,
        evidence_cursor=cursor,
    )
    failed = "association_record" if mutation == "wrong_association" else "evidence"
    retained = "evidence" if failed == "association_record" else "association_record"
    assert result[failed] is None
    assert result["section_outcomes"][failed]["error"]["code"] == "invalid_source_response"
    assert result[retained] and result["section_outcomes"][retained]["outcome"] == "data"


OTHER_TARGET = "ENSG00000141510"


class ComparisonProvider(Provider):
    def __init__(self, failed=()):
        super().__init__()
        self.failed = set(failed)

    async def post(self, url, **kwargs):
        body = kwargs["json"]
        identifier = body["variables"]["ensemblId"]
        if identifier in self.failed:
            self.payload = {}
        else:
            self.payload = project({"data": {"target": {**self.target, "id": identifier}}}, body["query"])
        return await Transport.post(self, url, **kwargs)


async def test_comparison_acquires_requested_diseases_and_only_requested_aspects(monkeypatch):
    provider = ComparisonProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().compare_targets(
        OpenTargetsClient(), [IDENTITY, OTHER_TARGET], ["diseases"]
    )
    for identifier, target in result["matrix"].items():
        assert target["id"] == identifier and "associatedDiseases" in target
        assert "tractability" not in target and "safetyLiabilities" not in target and "pathways" not in target
        assert result["coverage"][identifier]["provider_total"] == 10
        assert result["coverage"][identifier]["returned_rows"] == 1
        assert not result["coverage"][identifier]["exhaustive"]
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    "identifiers,aspects",
    [
        ([IDENTITY], None),
        ([IDENTITY] * 2, None),
        ([IDENTITY, "673"], None),
        ([f"ENSG{i:011}" for i in range(11)], None),
        ([IDENTITY, OTHER_TARGET], []),
        ([IDENTITY, OTHER_TARGET], ["safety", "safety"]),
        ([IDENTITY, OTHER_TARGET], ["invented"]),
    ],
)
async def test_comparison_rejects_invalid_scope_before_wire(monkeypatch, identifiers, aspects):
    provider = ComparisonProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    with pytest.raises(ResearchError) as caught:
        await CompositeTools().compare_targets(OpenTargetsClient(), identifiers, aspects)
    assert caught.value.code == "invalid_parameters" and not provider.calls


@pytest.mark.parametrize("all_failed", [False, True])
async def test_actual_mcp_comparison_retains_successful_peer_but_no_all_failed_evidence(
    monkeypatch, all_failed
):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    provider = ComparisonProvider([IDENTITY, OTHER_TARGET] if all_failed else [OTHER_TARGET])
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_advanced",
        "params": {
            "analysis_type": "compare",
            "entity_ids": [IDENTITY, OTHER_TARGET],
            "comparison_aspects": ["diseases"],
        },
    }
    async with Client(create_server(service=ResearchService())) as client:
        for _ in range(2):
            result = (await client.call_tool("query_source", args, raise_on_error=False)).structured_content
            section = result["sections"]["opentargets"]
            if all_failed:
                assert (
                    result["outcome"] == "error"
                    and section["evidence_ids"] == []
                    and result["provenance"] == []
                )
            else:
                assert result["outcome"] == "partial"
                assert set(section["data"]["matrix"]) == {IDENTITY}
                assert (
                    section["data"]["section_outcomes"][OTHER_TARGET]["error"]["code"]
                    == "invalid_source_response"
                )
                assert section["evidence_ids"] and all(not p["cached"] for p in result["provenance"])
    assert len(provider.calls) == 4
