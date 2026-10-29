"""ClinicalTrials.gov qualification uses actual retained/public adapters, without network."""

from copy import deepcopy

import httpx
import pytest
from clinical_trials_helpers import STUDY, documented_request, study
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

SENTINEL = "synthetic-provider-credential-query-body"


@pytest.fixture
def trials_http(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setenv("UBI_PROFILE", "local")

    def install(payload, *, inspect=True):
        calls = []

        def handler(request):
            calls.append(request)
            if inspect:
                documented_request(request)
            if callable(payload):
                return payload(request)
            return httpx.Response(200, json=deepcopy(payload))

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters(), calls

    return install


@pytest.mark.parametrize("payload", [{}, None, [], {"error": SENTINEL}, {"studies": None}, {"studies": [{}]}])
async def test_malformed_search_cannot_become_healthy_empty(trials_http, payload, caplog):
    adapters, calls = trials_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma"})
    assert caught.value.code == "invalid_source_response" and not caught.value.retryable
    assert SENTINEL not in str(caught.value) + caplog.text and len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"error": SENTINEL},
        {"protocolSection": None},
        {"protocolSection": {"identificationModule": {}}},
    ],
)
async def test_malformed_direct_record_is_failure(trials_http, payload, caplog):
    adapters, calls = trials_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "get_study_details", {"nct_id": "NCT04368728"})
    assert caught.value.code == "invalid_source_response" and not caught.value.retryable
    assert SENTINEL not in str(caught.value) + caplog.text and len(calls) == 1


@pytest.mark.parametrize(
    "path,value",
    [
        (("identificationModule", "nctId"), "wrong"),
        (("identificationModule", "briefTitle"), 42),
        (("statusModule", "overallStatus"), "unknown-provider-status"),
        (("designModule", "phases"), "PHASE3"),
        (("designModule", "phases"), ["Phase 3"]),
        (("designModule", "enrollmentInfo"), {"count": -1}),
        (("designModule", "enrollmentInfo"), {"count": True}),
        (("designModule", "enrollmentInfo"), {"count": 1.5}),
        (("conditionsModule", "conditions"), [None]),
        (("eligibilityModule", "stdAges"), ["CHILD", 3]),
        (("eligibilityModule", "sex"), "UNKNOWN"),
        (("eligibilityModule", "eligibilityCriteria"), []),
        (("contactsLocationsModule", "locations"), [None]),
        (("contactsLocationsModule", "locations"), [{"geoPoint": {"lat": 100, "lon": 0}}]),
        (("outcomesModule", "primaryOutcomes"), [{"measure": 42}]),
        (("armsInterventionsModule", "interventions"), [{"type": "UNKNOWN"}]),
        (("referencesModule", "references"), [{"pmid": []}]),
    ],
)
async def test_present_nested_fields_are_validated_before_evidence(trials_http, path, value):
    row = study()
    row["protocolSection"][path[0]][path[1]] = value
    adapters, _ = trials_http({"studies": [row], "totalCount": 1})
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma"})
    assert caught.value.code == "invalid_source_response"


async def test_valid_populated_and_explicit_empty_pages_stay_distinct(trials_http):
    from clinical_trials_mcp.server import search_studies

    _, calls = trials_http({"studies": [STUDY], "totalCount": 1})
    result = await search_studies(query="melanoma")
    assert result["studies"] == [STUDY] and result["totalCount"] == 1
    trials_http({"studies": [], "totalCount": 0})
    empty = await search_studies(query="melanoma")
    assert empty["studies"] == [] and empty["totalCount"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("totalCount", -1),
        ("totalCount", True),
        ("totalCount", "1"),
        ("nextPageToken", None),
        ("nextPageToken", ""),
        ("nextPageToken", []),
        ("nextPageToken", "x" * 8193),
    ],
)
async def test_invalid_provider_paging_is_not_success(trials_http, field, value):
    adapters, _ = trials_http({"studies": [], field: value})
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma"})
    assert caught.value.code == "invalid_source_response"


async def test_direct_identity_mismatch_cannot_enrich_requested_trial(trials_http):
    adapters, _ = trials_http(study("NCT04280705"))
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "get_study_details", {"nct_id": "NCT04368728"})
    assert caught.value.code == "invalid_source_response"


async def test_phase_filter_uses_documented_advanced_selector(trials_http):
    from clinical_trials_mcp.server import search_studies

    _, calls = trials_http({"studies": [], "totalCount": 0})
    await search_studies(query="breast cancer", phase="PHASE3")
    params = calls[0].url.params
    assert params["filter.advanced"] == "AREA[Phase]PHASE3"
    assert "filter.phase" not in params and "filter.overallStatus" not in params


@pytest.mark.parametrize(
    "group_by,expected",
    [
        ("phase", {"PHASE2": 1, "PHASE3": 1}),
        ("status", {"COMPLETED": 1}),
        ("studyType", {"INTERVENTIONAL": 1}),
        ("condition", {"COVID-19": 1}),
        ("sponsor", {"Synthetic sponsor": 1}),
    ],
)
async def test_statistics_compute_unique_study_memberships_with_explicit_denominator(
    trials_http, group_by, expected
):
    from clinical_trials_mcp.server import get_trial_statistics

    _, calls = trials_http({"studies": [STUDY], "totalCount": 1})
    result = await get_trial_statistics(group_by=group_by, condition="lung cancer")
    assert result["counts"] == expected
    assert result["coverage"]["acquired_studies"] == 1
    assert result["coverage"]["complete"] is True and result["coverage"]["missing_group_fields"] == 0
    assert calls[0].url.params["countTotal"] == "true"
    assert "aggFilters" not in calls[0].url.params


async def test_statistics_missing_total_is_unknown_and_continuation_is_partial(trials_http):
    from clinical_trials_mcp.server import get_trial_statistics

    trials_http({"studies": [STUDY], "nextPageToken": "next"})
    result = await get_trial_statistics()
    assert result["total_count"] is None
    assert result["coverage"]["complete"] is False
    assert result["section_outcomes"]["coverage"]["outcome"] == "partial"
    assert result["_provider_page"]["continuation"] == "next"


async def test_statistics_missing_group_is_not_measured_zero(trials_http):
    from clinical_trials_mcp.server import get_trial_statistics

    row = study()
    del row["protocolSection"]["designModule"]["phases"]
    trials_http({"studies": [row], "totalCount": 1})
    result = await get_trial_statistics(group_by="phase")
    assert result["counts"] == {} and result["coverage"]["missing_group_fields"] == 1
    assert result["section_outcomes"]["groups"]["outcome"] == "unavailable"


async def test_comparison_preserves_successful_peer_and_safe_failure(trials_http, caplog):
    from clinical_trials_mcp.server import compare_trials

    def response(request):
        if request.url.path.endswith("NCT04368728"):
            return httpx.Response(200, json=study())
        raise httpx.ConnectError(SENTINEL, request=request)

    trials_http(response)
    result = await compare_trials(["NCT04368728", "NCT04280705"], comparison_fields=["phase", "enrollment"])
    assert result["results"][0]["data"]["protocolSection"]["identificationModule"]["nctId"] == "NCT04368728"
    assert result["results"][1]["error"]["code"] == "source_unavailable"
    assert result["section_outcomes"]["NCT04280705"]["outcome"] == "unavailable"
    assert SENTINEL not in str(result) + caplog.text


async def test_actual_mcp_invalid_search_is_not_cached_as_absence(trials_http):
    count = 0

    def response(request):
        nonlocal count
        count += 1
        return httpx.Response(200, json={} if count == 1 else {"studies": [STUDY], "totalCount": 1})

    _, calls = trials_http(response)
    async with Client(create_server(service=ResearchService())) as client:
        first_call = await client.call_tool("trial_search", {"query": "melanoma"}, raise_on_error=False)
        assert first_call.is_error
        first = first_call.structured_content
        second = (await client.call_tool("trial_search", {"query": "melanoma"})).data
    assert (
        first["outcome"] == "error"
        and first["sections"]["clinical-trials"]["error"]["code"] == "invalid_source_response"
    )
    assert second["outcome"] == "data" and len(calls) == 2


async def test_absent_optional_protocol_module_is_unavailable_with_primary_evidence(trials_http):
    row = study()
    del row["protocolSection"]["eligibilityModule"]
    trials_http(row)
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "get", {"entity": "trial", "id": "NCT04368728", "sections": ["record", "eligibility"]}
            )
        ).data
    assert result["outcome"] == "partial"
    assert result["sections"]["record"]["outcome"] == "data"
    assert result["sections"]["eligibility"]["outcome"] == "unavailable"
    assert result["provenance"] and result["sections"]["record"]["evidence_ids"]


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "source_authentication_failed", False),
        (403, "source_access_denied", False),
        (404, "source_not_found", False),
        (429, "source_rate_limited", True),
        (503, "source_unavailable", True),
    ],
)
async def test_http_failures_keep_safe_typed_errors(trials_http, caplog, status, code, retryable):
    adapters, _ = trials_http(lambda request: httpx.Response(status, text=SENTINEL))
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "get_study_details", {"nct_id": "NCT04368728"})
    assert caught.value.code == code and caught.value.retryable is retryable
    assert SENTINEL not in str(caught.value) + caplog.text


async def test_invalid_json_has_no_raw_body_or_exception_cause(trials_http, caplog):
    adapters, _ = trials_http(lambda request: httpx.Response(200, text=SENTINEL))
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma"})
    assert caught.value.code == "invalid_source_response"
    assert SENTINEL not in str(caught.value) + caplog.text


async def test_documented_nct_alias_preserves_actual_canonical_identity(trials_http):
    row = study("NCT04280705")
    row["protocolSection"]["identificationModule"]["nctIdAliases"] = ["NCT04368728"]
    adapters, _ = trials_http(row)
    result = await adapters.call("clinical-trials", "get_study_details", {"nct_id": "NCT04368728"})
    assert result["nct_id"] == "NCT04368728"
    assert result["protocolSection"]["identificationModule"]["nctId"] == "NCT04280705"
    assert result["url"] == "https://clinicaltrials.gov/study/NCT04280705"


async def test_multilabel_grouping_counts_each_study_once_per_label(trials_http):
    from clinical_trials_mcp.server import get_trial_statistics

    row = study()
    row["protocolSection"]["designModule"]["phases"] = ["PHASE2", "PHASE2", "PHASE3"]
    trials_http({"studies": [row, study("NCT04280705")], "totalCount": 2})
    result = await get_trial_statistics(group_by="phase")
    assert result["counts"] == {"PHASE2": 2, "PHASE3": 2}
    assert result["coverage"]["acquired_studies"] == result["coverage"]["grouped_studies"] == 2
    assert result["coverage"]["multi_label_groups"] is True


async def test_explicit_empty_statistics_are_zero_acquired_matches(trials_http):
    from clinical_trials_mcp.server import get_trial_statistics

    trials_http({"studies": [], "totalCount": 0})
    result = await get_trial_statistics()
    assert result["counts"] == {} and result["total_count"] == 0
    assert result["coverage"]["acquired_studies"] == 0 and result["coverage"]["complete"]


async def test_actual_mcp_statistics_recovery_retains_filters_and_counts_are_per_window(trials_http):
    calls = 0

    def response(request):
        nonlocal calls
        calls += 1
        assert request.url.params["query.cond"] == "lung cancer"
        assert request.url.params["filter.advanced"] == "AREA[Phase]PHASE3"
        if calls == 1:
            assert "pageToken" not in request.url.params
            return httpx.Response(200, json={"studies": [], "totalCount": 1, "nextPageToken": "NEXT"})
        assert request.url.params["pageToken"] == "NEXT"
        return httpx.Response(200, json={"studies": [STUDY]})

    _, requests = trials_http(response)
    async with Client(create_server(service=ResearchService())) as client:
        first = (
            await client.call_tool(
                "query_source",
                {
                    "source": "clinical-trials",
                    "operation": "get_trial_statistics",
                    "params": {
                        "group_by": "phase",
                        "condition": "lung cancer",
                        "phase": "PHASE3",
                        "page_size": 1,
                    },
                },
            )
        ).data
        assert first["outcome"] == "partial" and len(first["next_actions"]) == 1
        action = first["next_actions"][0]
        second = (await client.call_tool(action["tool"], action["arguments"])).data
        assert not second["next_actions"]
        data = second["sections"]["clinical-trials"]["data"]
        assert data["counts"] == {"PHASE2": 1, "PHASE3": 1}
        assert data["total_count"] is None and data["coverage"]["acquired_studies"] == 1
    assert len(requests) == 2


@pytest.mark.parametrize("snapshot_available", [True, False])
async def test_default_statistics_keeps_counts_and_reproducible_memberships_with_large_protocols(
    trials_http, monkeypatch, snapshot_available
):
    import json
    from collections import Counter

    rows = [study(f"NCT{i:08d}") for i in range(1, 26)]
    for row in rows:
        row["protocolSection"]["descriptionModule"] = {"briefSummary": "Large protocol text. " * 1800}
    trials_http({"studies": rows, "totalCount": 200, "nextPageToken": "NEXT"})
    service = ResearchService()
    if not snapshot_available:

        async def unavailable(*args, **kwargs):
            return {"snapshot_status": "unavailable", "reason": "snapshot_worker_unavailable"}

        monkeypatch.setattr(service.evidence, "publish", unavailable)
    async with Client(create_server(service=service)) as client:
        value = (
            await client.call_tool(
                "query_source",
                {
                    "source": "clinical-trials",
                    "operation": "get_trial_statistics",
                    "params": {"condition": "lung cancer", "group_by": "phase", "page_size": 25},
                },
            )
        ).data
        section = value["sections"]["clinical-trials"]
        data = section["data"]
        assert data["counts"] == {"PHASE2": 25, "PHASE3": 25}
        assert data["coverage"]["acquired_studies"] == data["coverage"]["grouped_studies"] == 25
        assert not data["coverage"]["complete"] and data["total_count"] == 200
        assert len(data["records"]) == 25 and len({r["nct_id"] for r in data["records"]}) == 25
        assert dict(Counter(v for r in data["records"] for v in r["group_values"])) == data["counts"]
        assert "Large protocol" not in json.dumps(value)
        assert len(json.dumps(value).encode()) < 20000
        assert value["next_actions"][0]["arguments"]["params"]["page_token"] == "NEXT"
        assert section["evidence_ids"]
        if snapshot_available:
            assert section["recovery"]["snapshot_status"] == "available"
            recovered = json.loads((await client.read_resource(section["recovery"]["uri"]))[0].text)
            assert recovered["value"]["counts"] == data["counts"]
        else:
            assert section["recovery"]["reason"] == "snapshot_worker_unavailable"


async def test_failed_comparison_is_not_cached_as_healthy_and_recovers(trials_http):
    phase = 0

    def response(request):
        identifier = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200, json={} if phase == 0 and identifier == "NCT04280705" else study(identifier)
        )

    _, calls = trials_http(response)
    service = ResearchService()
    params = {"nct_ids": ["NCT04368728", "NCT04280705"]}
    first = await service.source("clinical-trials", "compare_trials", params, scope="trial-test")
    assert first.outcome == "partial"
    phase = 1
    second = await service.source("clinical-trials", "compare_trials", params, scope="trial-test")
    assert second.outcome == "data" and len(calls) == 4
    cached = await service.source("clinical-trials", "compare_trials", params, scope="trial-test")
    assert cached.provenance[0].cached and len(calls) == 4


async def test_requested_enrollment_preserves_measured_zero_and_estimate_type(trials_http):
    from clinical_trials_mcp.server import compare_trials

    def response(request):
        row = study(request.url.path.rsplit("/", 1)[-1])
        row["protocolSection"]["designModule"]["enrollmentInfo"] = {"count": 0, "type": "ESTIMATED"}
        return httpx.Response(200, json=row)

    trials_http(response)
    result = await compare_trials(["NCT04368728", "NCT04280705"], comparison_fields=["enrollment"])
    assert all(
        row["fields"]["enrollment"] == {"outcome": "data", "value": {"count": 0, "type": "ESTIMATED"}}
        for row in result["results"]
    )


@pytest.mark.parametrize("ids", [["NCT04368728"], ["NCT04368728", "NCT04368728"], ["NCT04368728", "wrong"]])
async def test_invalid_comparison_identities_fail_before_provider_io(trials_http, ids):
    adapters, calls = trials_http(STUDY)
    with pytest.raises(ResearchError):
        await adapters.call("clinical-trials", "compare_trials", {"nct_ids": ids})
    assert not calls


async def test_empty_nested_object_cannot_claim_an_outcome_measure(trials_http):
    row = study()
    row["protocolSection"]["outcomesModule"]["primaryOutcomes"] = [{}]
    adapters, _ = trials_http(row)
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "get_study_details", {"nct_id": "NCT04368728"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "params",
    [
        {"phase": "Phase 3"},
        {"status": SENTINEL},
        {"phase": []},
        {"status": {}},
        {"page_token": ""},
        {"page_token": "x" * 8193},
    ],
)
async def test_invalid_statistics_selectors_fail_safe_preflight(trials_http, params):
    adapters, calls = trials_http({"studies": [], "totalCount": 0})
    with pytest.raises(ResearchError) as caught:
        await adapters.validate("clinical-trials", "get_trial_statistics", params)
    assert caught.value.code == "invalid_parameters" and SENTINEL not in str(caught.value)
    assert not calls


async def test_statistics_status_and_phase_enums_match_official_contract():
    from clinical_trials_mcp.contracts import PHASES, STATUSES

    schema = next(
        tool
        for tool in await SourceAdapters().catalog("clinical-trials")
        if tool["name"] == "get_trial_statistics"
    )["input_schema"]
    assert set(schema["properties"]["phase"]["anyOf"][0]["enum"]) == PHASES
    assert set(schema["properties"]["status"]["anyOf"][0]["enum"]) == STATUSES


@pytest.mark.parametrize(
    "selector,missing", [("status", False), ("status", True), ("phase", False), ("phase", True)]
)
async def test_filtered_rows_cannot_claim_wrong_or_unverified_scope(trials_http, selector, missing):
    row = study()
    if selector == "status":
        module, field, requested = "statusModule", "overallStatus", "RECRUITING"
    else:
        module, field, requested = "designModule", "phases", "PHASE4"
    if missing:
        del row["protocolSection"][module][field]
    adapters, _ = trials_http({"studies": [row], "totalCount": 1})
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma", selector: requested})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("query", ["NCT04368728", "NCT04368728, NCT04280705", "nct04368728 nct04280705"])
async def test_identifier_only_queries_cannot_silently_ignore_requested_filters(trials_http, query):
    adapters, calls = trials_http({"studies": [STUDY], "totalCount": 1})
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": query, "phase": "PHASE3"})
    assert caught.value.code == "invalid_parameters" and not calls


@pytest.mark.parametrize(
    "payload",
    [
        {"studies": [STUDY], "totalCount": 2},
        {"studies": [STUDY], "totalCount": 1, "nextPageToken": "NEXT"},
        {"studies": [], "totalCount": 0, "nextPageToken": "NEXT"},
    ],
)
async def test_first_page_total_and_continuation_must_agree(trials_http, payload):
    adapters, _ = trials_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapters.call("clinical-trials", "search_studies", {"query": "melanoma"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "enrollment,expected", [({"type": "ACTUAL"}, "unavailable"), ({"count": 100}, "partial")]
)
async def test_incomplete_enrollment_cannot_be_a_complete_measurement(trials_http, enrollment, expected):
    from clinical_trials_mcp.server import compare_trials

    def response(request):
        row = study(request.url.path.rsplit("/", 1)[-1])
        row["protocolSection"]["designModule"]["enrollmentInfo"] = enrollment
        return httpx.Response(200, json=row)

    trials_http(response)
    result = await compare_trials(["NCT04368728", "NCT04280705"], comparison_fields=["enrollment"])
    for row in result["results"]:
        assert row["fields"]["enrollment"]["outcome"] == expected
        assert row["data"]["protocolSection"]["designModule"]["enrollmentInfo"] == enrollment
    assert all(value["outcome"] == "partial" for value in result["section_outcomes"].values())
