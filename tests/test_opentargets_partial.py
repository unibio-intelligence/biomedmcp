"""Optional acquisition failures retain independently retrieved source evidence."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from opentargets_helpers import expression, project, target
from opentargets_mcp import queries
from opentargets_mcp.queries import OpenTargetsClient
from opentargets_mcp.tools.composite import CompositeTools
from opentargets_mcp.tools.unified import UnifiedTools
from test_opentargets_assessments import DISEASE, IDENTITY, Provider, source
from test_opentargets_responses import Transport
from test_qualified_gene_identity import HUMAN

from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.identity import qualify_gene
from biomedmcp.native.opentargets import acquire_section, disease_associations, target_profile

SENTINEL = "SYNTHETIC_API_KEY_MUST_NOT_ESCAPE_OPTIONAL_FAILURE"


class OptionalProvider(Provider):
    def __init__(self, failures=(), mode="network"):
        super().__init__()
        self.failures = set(failures)
        self.mode = mode
        self.target["dbXrefs"] = []
        self.disease = {
            "id": DISEASE,
            "name": "Synthetic disease",
            "description": None,
            "synonyms": [],
            "therapeuticAreas": [],
            "dbXRefs": [],
            "associatedTargets": {
                "count": 1,
                "rows": [{"target": target(), "score": 0.5, "datatypeScores": []}],
            },
        }
        self.drug = {
            "id": "CHEMBL1",
            "name": "Synthetic drug",
            "description": None,
            "maximumClinicalStage": "PHASE_II",
            "mechanismsOfAction": {
                "rows": [
                    {
                        "mechanismOfAction": "Synthetic inhibition",
                        "targetName": "BRAF",
                        "actionType": "INHIBITOR",
                        "targets": [target()],
                        "references": [],
                    }
                ]
            },
            "indications": {
                "count": 1,
                "rows": [
                    {
                        "id": "synthetic-indication",
                        "maxClinicalStage": "PHASE_II",
                        "disease": {"id": DISEASE, "name": "Synthetic disease", "therapeuticAreas": []},
                        "clinicalReports": [],
                    }
                ],
            },
        }

    async def post(self, url, **kwargs):
        body = kwargs["json"]
        failed = any(marker in body["query"] for marker in self.failures)
        if failed and self.mode == "network":
            self.calls.append((url, kwargs))
            raise httpx.ConnectError(SENTINEL)
        if failed and self.mode == "malformed":
            self.payload = {}
            return await Transport.post(self, url, **kwargs)
        if "DiseaseProfile" in body["query"] or "DiseaseTargets" in body["query"]:
            self.payload = project({"data": {"disease": self.disease}}, body["query"])
            result = await Transport.post(self, url, **kwargs)
        elif (
            "DrugMechanism" in body["query"]
            or "DrugTargets" in body["query"]
            or "DrugIndications" in body["query"]
        ):
            self.payload = project({"data": {"drug": self.drug}}, body["query"])
            result = await Transport.post(self, url, **kwargs)
        else:
            result = await super().post(url, **kwargs)
        if failed and self.mode == "foreign":
            root = next(iter(self.payload["data"].values()))
            root["__ubi_requested_identity"] = "foreign-synthetic-entity"
        return result


@pytest.mark.parametrize(
    "section,marker",
    [
        ("associated_diseases", "TargetDiseases"),
        ("clinical_candidates", "TargetDrugs"),
    ],
)
@pytest.mark.parametrize("mode", ["network", "malformed", "foreign"])
async def test_target_profile_retains_primary_and_other_secondary_sections(
    monkeypatch, capsys, section, marker, mode
):
    provider = OptionalProvider([marker], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().get_target_profile(
        OpenTargetsClient(),
        IDENTITY,
        sections=["identity", "biology", "safety", "tractability"],
    )
    assert result["target"] == source()["target"]
    assert result[section] is None and result["section_outcomes"][section]["outcome"] == "error"
    other = "clinical_candidates" if section == "associated_diseases" else "associated_diseases"
    assert result[other] == source()[other]
    assert len(provider.calls) == 3
    assert SENTINEL not in json.dumps(result) + capsys.readouterr().out


@pytest.mark.parametrize("mode", ["network", "malformed", "foreign"])
async def test_disease_profile_retains_identity_when_targets_fail(monkeypatch, mode):
    provider = OptionalProvider(["DiseaseTargets"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().get_disease_profile(OpenTargetsClient(), DISEASE)
    assert result["disease"]["id"] == DISEASE
    assert result["associated_targets"] is None
    assert result["section_outcomes"]["associated_targets"]["outcome"] == "error"
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    "marker,failed,retained",
    [
        ("DrugTargets", "mechanisms_of_action", "indications"),
        ("DrugIndications", "indications", "mechanisms_of_action"),
    ],
)
async def test_drug_profile_retains_independently_acquired_records(monkeypatch, marker, failed, retained):
    provider = OptionalProvider([marker])
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().explore_drug_mechanism(OpenTargetsClient(), "CHEMBL1")
    assert result["drug"]["id"] == "CHEMBL1" and result[failed] is None
    assert result[retained]["rows"] and result["section_outcomes"][failed]["outcome"] == "error"
    if failed == "mechanisms_of_action":
        assert result["targets"] is None
    else:
        assert result["targets"][0]["id"] == IDENTITY
    assert len(provider.calls) == 3


@pytest.mark.parametrize(
    "marker", ["TargetDrugs", "TargetDiseases", "TargetDiseaseEvidence", "AssociationScore"]
)
async def test_assessment_preserves_profile_and_marks_nested_partial(monkeypatch, marker):
    provider = OptionalProvider([marker])
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().build_target_validation_report(OpenTargetsClient(), IDENTITY, DISEASE)
    assert result["target_profile"]["target"]["id"] == IDENTITY
    assert any(status["outcome"] in {"error", "partial"} for status in result["section_outcomes"].values())
    clinical = result["evidence_summary"]["clinical_candidates"]
    if marker == "TargetDrugs":
        assert clinical["status"] == "unavailable" and clinical["provider_count"] is None
        assert clinical["returned_rows"] is None and clinical["exhaustive"] is None
    else:
        assert clinical["provider_count"] == 5
    if marker == "TargetDiseaseEvidence":
        assert result["association_analysis"]["overall_score"] == 0.8
        assert result["association_analysis"]["evidence"] is None
    if marker == "AssociationScore":
        assert result["association_analysis"]["overall_score"] is None
        assert result["association_analysis"]["evidence"][0]["id"] == "synthetic-evidence"


@pytest.mark.parametrize("mode", ["network", "malformed", "foreign"])
async def test_actual_mcp_gene_retention_retry_cache_and_partial_recovery(monkeypatch, mode):
    class Adapters(SourceAdapters):
        async def call(self, source, operation, params):
            if source == "mygene":
                return {"hits": [deepcopy(HUMAN)]}
            return await super().call(source, operation, params)

    provider = OptionalProvider(["TargetDiseases"], mode)
    rows = [expression(i) for i in range(30)]
    provider.target["baselineExpression"] = {"count": 30, "rows": rows}
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    arguments = {
        "entity": "gene",
        "id": "673",
        "sections": ["record", "target_evidence", "diseases", "druggability"],
    }
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as client:
        first = (await client.call_tool("get", arguments)).data
        section = first["sections"]["target_evidence"]
        assert first["outcome"] == section["outcome"] == "partial"
        assert section["data"]["associated_diseases"] is None and section["evidence_ids"]
        assert first["sections"]["druggability"]["outcome"] == "data"
        assert first["sections"]["diseases"]["evidence_ids"] == []
        omission = next(
            o for o in section["recovery"]["omissions"] if o["pointer"] == "/target/baselineExpression/rows"
        )
        recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
        assert recovered["value"] == rows[25:] and recovered["evidence_ids"] == section["evidence_ids"]
        assert len(provider.calls) == 2
        provider.failures.clear()
        good = (await client.call_tool("get", arguments)).data
        cached = (await client.call_tool("get", arguments)).data
        assert good["outcome"] == cached["outcome"] == "data"
        assert good["sections"]["diseases"]["data"]["records"] == source()["associated_diseases"]["rows"]
        assert (
            cached["sections"]["target_evidence"]["evidence_ids"]
            == good["sections"]["target_evidence"]["evidence_ids"]
        )
        assert any(
            p["cached"]
            for p in good["provenance"]
            if p["evidence_id"] in good["sections"]["druggability"]["evidence_ids"]
        )
    assert len(provider.calls) == 4


async def test_all_failed_pair_acquisitions_issue_no_scientific_evidence(monkeypatch):
    provider = OptionalProvider(["AssociationScore", "TargetDiseaseEvidence"], "malformed")
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_association",
        "params": {"source_id": IDENTITY, "target_id": DISEASE},
    }
    async with Client(create_server(service=ResearchService())) as client:
        result = (await client.call_tool("query_source", args, raise_on_error=False)).structured_content
        assert result["outcome"] == "error" and result["sections"]["opentargets"]["evidence_ids"] == []
        assert result["provenance"] == []
    assert len(provider.calls) == 2


async def test_nested_partial_assessment_is_not_cached_as_healthy(monkeypatch):
    provider = OptionalProvider(["TargetDiseaseEvidence"])
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    args = {
        "source": "opentargets",
        "operation": "analyze_advanced",
        "params": {
            "analysis_type": "validate",
            "entity_ids": [IDENTITY],
            "disease_id": DISEASE,
        },
    }
    async with Client(create_server(service=ResearchService())) as client:
        for _ in range(2):
            result = (await client.call_tool("query_source", args)).data
            assert result["outcome"] == "partial"
            assert (
                result["sections"]["opentargets"]["data"]["section_outcomes"]["association_analysis"][
                    "outcome"
                ]
                == "partial"
            )
            assert all(not p["cached"] for p in result["provenance"])
    assert len(provider.calls) == 10


async def test_unavailable_specialty_preserves_primary_and_later_specialty(monkeypatch):
    provider = OptionalProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await UnifiedTools().get_entity(
        OpenTargetsClient(), "target", IDENTITY, sections=["identity", "tep", "alternative_genes"]
    )
    assert result["target"]["id"] == IDENTITY and result["specialized"]["tep"] is None
    assert result["specialized"]["alternative_genes"] is not None
    assert result["section_outcomes"]["specialized/tep"]["outcome"] == "error"
    assert len(provider.calls) == 2


@pytest.mark.parametrize("mutate", ["missing_status", "contradiction", "unknown_code", "wrong_retryable"])
def test_forged_or_incomplete_failure_metadata_cannot_bypass_source_shape(mutate):
    p = source()
    p["associated_diseases"] = None
    p["section_outcomes"] = {
        "associated_diseases": {
            "outcome": "error",
            "error": {
                "code": "source_unavailable",
                "retryable": True,
                "message": SENTINEL,
            },
        }
    }
    if mutate == "missing_status":
        p.pop("section_outcomes")
    elif mutate == "contradiction":
        p["associated_diseases"] = source()["associated_diseases"]
    elif mutate == "unknown_code":
        p["section_outcomes"]["associated_diseases"]["error"]["code"] = SENTINEL
    else:
        p["section_outcomes"]["associated_diseases"]["error"]["retryable"] = "true"
    with pytest.raises(ResearchError) as caught:
        target_profile(p, qualify_gene(HUMAN, 9606), IDENTITY)
    assert caught.value.code == "invalid_source_response"


async def test_error_text_is_discarded_and_failed_disease_section_cannot_mint_empty():
    p = source()
    p["associated_diseases"] = None
    p["section_outcomes"] = {
        "associated_diseases": {
            "outcome": "error",
            "error": {
                "code": "source_unavailable",
                "retryable": True,
                "message": SENTINEL,
                "correction": SENTINEL,
            },
        }
    }
    validated = target_profile(p, qualify_gene(HUMAN, 9606), IDENTITY)
    assert SENTINEL not in json.dumps(validated)
    with pytest.raises(ResearchError) as caught:
        disease_associations(validated)
    assert caught.value.code == "source_unavailable"


@pytest.mark.parametrize(
    "error",
    [ToolError(SENTINEL), ToolError("[]"), ToolError('{"code":{}}'), ResearchError("unexpected", SENTINEL)],
)
async def test_expected_tool_failures_have_only_sanitized_section_errors(error, capsys):
    async def fail():
        raise error

    value, status = await acquire_section(fail)
    assert value is None and status["outcome"] == "error"
    assert SENTINEL not in json.dumps(status) + capsys.readouterr().out


async def test_cancellation_is_not_converted_into_scientific_failure():
    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await acquire_section(cancelled)


@pytest.mark.parametrize(
    "entity,marker", [("target", "TargetProfile"), ("disease", "DiseaseProfile"), ("drug", "DrugMechanism")]
)
async def test_primary_failure_cannot_mint_identity_or_trigger_optional_calls(monkeypatch, entity, marker):
    provider = OptionalProvider([marker], "malformed")
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    identifier = {"target": IDENTITY, "disease": DISEASE, "drug": "CHEMBL1"}[entity]
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().get_entity(OpenTargetsClient(), entity, identifier)
    assert caught.value.code == "invalid_source_response"
    assert len(provider.calls) == 1


async def test_all_optional_sections_can_fail_without_discarding_primary(monkeypatch):
    provider = OptionalProvider(["TargetDiseases", "TargetDrugs"])
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().build_target_validation_report(OpenTargetsClient(), IDENTITY)
    assert result["target_profile"]["target"]["id"] == IDENTITY
    assert result["section_outcomes"]["target"] == {"outcome": "data"}
    assert result["evidence_summary"]["clinical_candidates"]["provider_count"] is None
    assert len(provider.calls) == 3


@pytest.mark.parametrize("moa", [None, {"rows": []}])
async def test_explicitly_nullable_and_empty_mechanisms_retain_distinct_meanings(monkeypatch, moa):
    provider = OptionalProvider()
    provider.drug["mechanismsOfAction"] = moa
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    result = await CompositeTools().explore_drug_mechanism(OpenTargetsClient(), "CHEMBL1")
    assert result["mechanisms_of_action"] == moa
    assert result["targets"] == (None if moa is None else [])
    assert result["section_outcomes"]["mechanisms_of_action"] == {"outcome": "data"}
    assert result["indications"]["count"] == 1


@pytest.mark.parametrize("fail", [False, True])
async def test_adverse_events_are_acquired_once_and_later_specialty_survives(monkeypatch, fail):
    from opentargets_mcp.tools.drug.safety import DrugSafetyApi

    calls = []

    async def adverse(self, client, identifier):
        calls.append(identifier)
        if fail:
            raise httpx.ConnectError(SENTINEL)
        return {"drug_id": identifier, "adverseEvents": None}

    async def references(client, identifier):
        return {"drug_id": identifier, "crossReferences": []}

    monkeypatch.setattr(DrugSafetyApi, "get_drug_adverse_events", adverse)
    provider = OptionalProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    tools = UnifiedTools()
    monkeypatch.setattr(tools._drug, "get_drug_cross_references", references)
    result = await tools.get_entity(
        OpenTargetsClient(), "drug", "CHEMBL1", sections=["identity", "adverse_events", "cross_references"]
    )
    assert calls == ["CHEMBL1"] and result["drug"]["id"] == "CHEMBL1"
    assert result["specialized"]["adverse_events"] == result["adverse_events"]
    assert result["specialized"]["cross_references"]["drug_id"] == "CHEMBL1"
    assert result["section_outcomes"]["adverse_events"]["outcome"] == ("error" if fail else "data")
    assert SENTINEL not in json.dumps(result)
