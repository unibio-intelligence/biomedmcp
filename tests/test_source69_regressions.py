"""Synthetic regressions for observed Reactome serialization and trial discovery failures."""

from copy import deepcopy

import httpx
import pytest
from clinical_trials_helpers import documented_request, study
from fastmcp import Client
from test_reactome_contracts import PARTICIPANT, PATHWAY, PID
from test_reactome_contracts import reactome_http as _reactome_http

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt
from biomedmcp.trial_records import rank_trials

reactome_http = _reactome_http


async def test_actual_mcp_pathway_review_accepts_namespaced_references_and_document_identity(
    reactome_http, monkeypatch
):
    participant = deepcopy(PARTICIPANT)
    participant["refEntities"][0]["stId"] = "uniprot:P00533"
    child = {**PATHWAY, "dbId": 2, "stId": "R-HSA-900002", "schemaClass": "Reaction"}
    parent = {**PATHWAY, "dbId": 1, "hasEvent": [child]}
    reactome_http["payloads"][f"/ContentService/data/participants/{PID}"] = [participant]
    reactome_http["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [parent, 2]
    service = ResearchService()

    async def no_papers(*args, **kwargs):
        from biomedmcp.pagination import page_payload

        return page_payload([], raw_count=0, exhausted=True)

    monkeypatch.setattr(service.providers.literature, "search_source", no_papers)
    async with Client(create_server(service=service)) as client:
        result = await client.call_tool_mcp("research", {"workflow": "pathway_review", "focus": PID})
    value = result.structured_content
    assert value["sections"]["genes"]["outcome"] == value["sections"]["events"]["outcome"] == "data"
    assert value["sections"]["genes"]["data"]["participants"][0] == participant
    assert value["sections"]["events"]["data"]["hierarchy"] == [parent, child]
    assert verify_receipt(value)


@pytest.mark.parametrize("reference", [0, -2, True, 99, "2"])
def test_unresolved_or_malformed_event_references_never_become_empty(reference):
    from reactome_mcp.contracts import events

    with pytest.raises(ResearchError) as caught:
        events([{**PATHWAY, "dbId": 1}, reference])
    assert caught.value.code == "invalid_source_response"


def test_conflicting_document_identity_is_rejected():
    from reactome_mcp.contracts import events

    with pytest.raises(ResearchError):
        events([{**PATHWAY, "dbId": 1}, {**PATHWAY, "dbId": 1, "displayName": "conflicting"}])


@pytest.mark.parametrize("reference", ["uniprot:", "https://example.test/P00533", "uniprot:OTHER"])
def test_malformed_reference_entity_identity_is_rejected(reference):
    from reactome_mcp.contracts import participants

    row = deepcopy(PARTICIPANT)
    row["refEntities"][0]["stId"] = reference
    with pytest.raises(ResearchError):
        participants([row])


async def test_trial_relevance_uses_bounded_candidate_window_and_retains_overflow(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []
    rows = [study(f"NCT090000{i:02d}") for i in range(1, 21)]
    for row in rows:
        row["protocolSection"]["identificationModule"]["briefTitle"] = "Broad cancer surveillance"
        row["protocolSection"]["conditionsModule"]["conditions"] = ["Cancer"]
    for row, title in zip(rows[-2:], ["Melanoma treatment", "Advanced melanoma immunotherapy"]):
        row["protocolSection"]["identificationModule"]["briefTitle"] = title
        row["protocolSection"]["conditionsModule"]["conditions"] = ["Melanoma"]

    def respond(request):
        documented_request(request)
        calls.append(request)
        assert request.url.params["sort"] == "@relevance"
        size = int(request.url.params["pageSize"])
        return httpx.Response(200, json={"studies": rows[:size], "totalCount": len(rows)})

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = await client.call_tool_mcp("trial_search", {"query": "melanoma", "limit": 2})
        value = result.structured_content
        assert not result.is_error and len(value["records"]) == 2
        assert {r["title"] for r in value["records"]} == {
            "Melanoma treatment", "Advanced melanoma immunotherapy"
        }
        assert value["query"]["execution"]["source_pagination"]["clinical-trials"]["raw_rows_scanned"] == 20
        assert value["next_cursor"] and verify_receipt(value)
        assert value["query"]["execution"]["sort_scope"] == "window"
        continuation = await client.call_tool_mcp(
            "trial_search", {"query": "melanoma", "limit": 2, "cursor": value["next_cursor"]}
        )
    assert len(calls) == 1 and len(continuation.structured_content["records"]) == 2
    assert not {
        tuple((i["namespace"], i["value"]) for i in r["identities"]) for r in value["records"]
    } & {
        tuple((i["namespace"], i["value"]) for i in r["identities"])
        for r in continuation.structured_content["records"]
    }


def test_trial_direct_plural_title_beats_incidental_condition_mention():
    rows = [
        {"title": "Broad surveillance", "conditions": ["Melanoma", "Lung cancer"]},
        {"title": "Treatment of malignant melanomas", "conditions": ["Melanoma"]},
        {"title": "Iris tumors", "conditions": ["Ocular melanoma"]},
    ]
    ranked = rank_trials(rows, "melanoma")
    assert ranked[0]["title"] == "Treatment of malignant melanomas" and len(ranked) == 3
