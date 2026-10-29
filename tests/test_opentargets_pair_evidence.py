"""Actual pair evidence uses private signed state across direct and nested routes."""

import asyncio
import json
from copy import deepcopy

import pytest
from fastmcp import Client
from opentargets_mcp import queries
from test_opentargets_assessments import DISEASE, IDENTITY, evidence
from test_opentargets_partial import OptionalProvider

from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.opentargets_pair_evidence import PairContinuation
from biomedmcp.runtime import ProviderRuntime, ResultCache, digest

TOKEN = "SYNTHETIC_PAIR_SOURCE_TOKEN_MUST_STAY_PRIVATE"
SECOND = "SYNTHETIC_SECOND_PAIR_SOURCE_TOKEN"
PARAMS = {"source_id": IDENTITY, "target_id": DISEASE, "min_score": 0.5, "limit": 1}
ARGS = {"source": "opentargets", "operation": "analyze_association", "params": PARAMS}
ADVANCED = {
    "source": "opentargets",
    "operation": "analyze_advanced",
    "params": {"analysis_type": "validate", "entity_ids": [IDENTITY], "disease_id": DISEASE},
}


class PairProvider(OptionalProvider):
    def __init__(self, failures=(), mode="network"):
        super().__init__(failures, mode)
        self.pages = {
            None: {"count": 2, "cursor": TOKEN, "rows": [evidence("pair-0", 0.2)]},
            TOKEN: {"count": 2, "cursor": None, "rows": [evidence("pair-1", 0.9)]},
        }


@pytest.fixture
def provider(monkeypatch):
    p = PairProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    return p


async def test_actual_mcp_filtered_window_keeps_signed_next_action_and_no_raw_token(provider):
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", ARGS)).data
        pair = first["sections"]["opentargets"]["data"]
        assert pair["evidence"] == [] and pair["coverage"]["acquired_rows"] == 1
        assert pair["overall_score"] == 0.8 and pair["coverage"]["has_continuation"]
        assert "continuation" not in pair and TOKEN not in json.dumps(first)
        action = first["next_actions"][0]
        assert action["arguments"]["params"]["min_score"] == 0.5
        second = (await c.call_tool(action["tool"], action["arguments"])).data
        pair = second["sections"]["opentargets"]["data"]
        assert pair["evidence"][0]["id"] == "pair-1" and pair["biomarkers"][0]["evidence_id"] == "pair-1"
        assert not pair["coverage"]["exhaustive"] and second["next_actions"] == []
        assert TOKEN not in json.dumps(second)
    assert len(provider.calls) == 4
    assert provider.calls[-1][1]["json"]["variables"]["cursor"] == TOKEN


async def test_nested_validation_lifts_private_state_and_emits_canonical_pair_action(provider):
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", ADVANCED)).data
        report = first["sections"]["opentargets"]["data"]
        pair = report["association_analysis"]
        assert pair["evidence"][0]["id"] == "pair-0" and "_provider_pages" not in pair
        assert TOKEN not in json.dumps(first) and report["target_id"] == IDENTITY
        action = first["next_actions"][0]
        assert action["arguments"]["operation"] == "analyze_association"
        params = action["arguments"]["params"]
        assert params["source_id"] == IDENTITY and params["target_id"] == DISEASE
        assert params["limit"] == 100 and params["include_biomarkers"] is False
        assert params["min_score"] == 0.0 and "entity_ids" not in params
        before = len(provider.calls)
        second = (await c.call_tool(action["tool"], action["arguments"])).data
        pair = second["sections"]["opentargets"]["data"]
        assert pair["evidence"][0]["id"] == "pair-1" and "biomarkers" not in pair
        assert second["next_actions"] == [] and len(provider.calls) == before + 2
        assert TOKEN not in json.dumps(second)


@pytest.mark.parametrize(
    "change",
    [
        "target",
        "disease",
        "limit",
        "score",
        "types",
        "biomarkers",
        "account",
        "tamper",
        "expiry",
        "state",
        "revision",
        "operation",
    ],
)
async def test_pair_cursor_binds_full_request_and_rejects_before_http(provider, monkeypatch, change):
    service = ResearchService()
    first = await service.source("opentargets", "analyze_association", PARAMS, scope="a")
    params = deepcopy(first.next_actions[0]["arguments"]["params"])
    scope, operation = "a", "analyze_association"
    if change == "target":
        params["source_id"] = "ENSG00000141510"
    elif change == "disease":
        params["target_id"] = "EFO_0000001"
    elif change == "limit":
        params["limit"] = 2
    elif change == "score":
        params["min_score"] = 0.0
    elif change == "types":
        params["evidence_types"] = ["genetic_association"]
    elif change == "biomarkers":
        params["include_biomarkers"] = False
    elif change == "account":
        scope = "b"
    elif change == "tamper":
        original = params["evidence_cursor"]
        params["evidence_cursor"] = ("y" if original[0] == "x" else "x") + original[1:]
        assert params["evidence_cursor"] != original
    elif change == "expiry":
        from biomedmcp import runtime

        now = runtime.time.time()
        monkeypatch.setattr(runtime.time, "time", lambda: now + 3601)
    elif change == "state":
        service.runtime.cache.values.clear()
    elif change == "revision":
        from biomedmcp.native import opentargets_variant_evidence

        monkeypatch.setattr(opentargets_variant_evidence, "REVISION", "biomedmcp/test-other-revision")
    else:
        operation = "query_genetics"
        params = {
            "query_type": "variant",
            "variant_id": "7_1001_A_T",
            "include_evidences": True,
            "limit": 1,
            "evidence_cursor": params["evidence_cursor"],
        }
    with pytest.raises(ResearchError) as error:
        await service.source("opentargets", operation, params, scope=scope)
    assert error.value.code in {"invalid_cursor", "expired_cursor"} and len(provider.calls) == 2


async def test_pair_cursor_raw_submission_and_batch_tamper_do_no_provider_io(provider):
    invalid = {**ARGS, "params": {**PARAMS, "evidence_cursor": TOKEN}}
    async with Client(create_server(service=ResearchService())) as c:
        for tool, arguments in [
            ("query_source", invalid),
            (
                "batch",
                {
                    "requests": [
                        {"tool": "query_source", "arguments": ARGS},
                        {"tool": "query_source", "arguments": invalid},
                    ]
                },
            ),
        ]:
            result = await c.call_tool(tool, arguments, raise_on_error=False)
            assert result.structured_content["outcome"] == "error"
    assert provider.calls == []


async def test_empty_nonterminal_pair_window_keeps_later_evidence_reachable(provider):
    provider.pages[None]["rows"] = []
    service = ResearchService()
    first = await service.source("opentargets", "analyze_association", PARAMS, scope="a")
    pair = first.sections["opentargets"].data
    assert pair["evidence"] == [] and pair["coverage"]["acquired_rows"] == 0 and first.next_actions
    second = await service.source(
        "opentargets", "analyze_association", first.next_actions[0]["arguments"]["params"], scope="a"
    )
    assert second.sections["opentargets"].data["evidence"][0]["id"] == "pair-1"
    assert second.next_actions == [] and len(provider.calls) == 4


async def test_pair_cycle_is_partial_before_cache_and_provider_recovery_retries(provider):
    provider.pages[TOKEN]["cursor"] = SECOND
    provider.pages[SECOND] = {"count": 3, "cursor": TOKEN, "rows": [evidence("pair-2", 0.9)]}
    service = ResearchService()
    first = await service.source("opentargets", "analyze_association", PARAMS, scope="a")
    second = await service.source(
        "opentargets", "analyze_association", first.next_actions[0]["arguments"]["params"], scope="a"
    )
    params = second.next_actions[0]["arguments"]["params"]
    third = await service.source("opentargets", "analyze_association", params, scope="a")
    assert third.outcome == "partial" and third.next_actions == []
    assert third.sections["opentargets"].data["coverage"]["continuation_status"] == "provider_cycle"
    assert third.sections["opentargets"].data["evidence"][0]["id"] == "pair-2"
    provider.pages[SECOND]["cursor"] = None
    retried = await service.source("opentargets", "analyze_association", params, scope="a")
    assert retried.outcome == "data" and retried.next_actions == [] and len(provider.calls) == 8
    assert all(not p.cached for p in retried.provenance)


@pytest.mark.parametrize("bound", ["rows", "windows"])
async def test_pair_scan_admission_stops_without_erasing_acquired_records(provider, bound):
    provider.pages[TOKEN]["cursor"] = SECOND
    service = ResearchService()
    position = 1 if bound == "rows" else 63
    cursor = service.runtime.cursors.encode(
        query=PairContinuation.binding(PARAMS), scope="a", offset=position
    )
    seen = [digest("earlier-" + str(i)) for i in range(position - 1)] + [digest(TOKEN)]
    await service.runtime.cache.put(
        PairContinuation.cache_prefix + digest(cursor),
        {"after": TOKEN, "scanned": 999 if bound == "rows" else 0, "windows": position, "seen": seen},
        3600,
    )
    result = await service.source(
        "opentargets", "analyze_association", {**PARAMS, "evidence_cursor": cursor}, scope="a"
    )
    assert result.outcome == "partial" and result.next_actions == []
    pair = result.sections["opentargets"].data
    assert pair["evidence"][0]["id"] == "pair-1" and pair["coverage"]["continuation_status"] == "scan_limit"
    assert not pair["coverage"]["exhaustive"]
    # Simulated well-formed budget state; no claim that earlier source rows were acquired.


@pytest.mark.parametrize("failure", ["storage_limit", "cache_unavailable"])
@pytest.mark.parametrize("nested", [False, True])
async def test_pair_storage_failure_retains_acquired_direct_and_nested_evidence(
    provider, monkeypatch, failure, nested
):
    service = ResearchService()
    original = service.runtime.cache.put

    async def failing(key, value, ttl):
        if key.startswith(PairContinuation.cache_prefix):
            if failure == "storage_limit":
                return False
            raise ResearchError("cache_unavailable", "Synthetic private failure", retryable=True)
        return await original(key, value, ttl)

    monkeypatch.setattr(service.runtime.cache, "put", failing)
    args = ADVANCED if nested else {**ARGS, "params": {**PARAMS, "min_score": 0.0}}
    result = await service.source(args["source"], args["operation"], args["params"], scope="a")
    data = result.sections["opentargets"].data
    pair = data["association_analysis"] if nested else data
    assert result.outcome == "partial" and result.next_actions == []
    assert pair["evidence"][0]["id"] == "pair-0" and pair["coverage"]["continuation_status"] == failure
    assert TOKEN not in result.model_dump_json() and "private failure" not in result.model_dump_json()
    count = len(provider.calls)
    monkeypatch.setattr(service.runtime.cache, "put", original)
    recovered = await service.source(args["source"], args["operation"], args["params"], scope="a")
    assert recovered.outcome == "data" and recovered.next_actions and len(provider.calls) == count


@pytest.mark.parametrize("marker", ["AssociationScore", "TargetDiseaseEvidence"])
@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_failed_peer_retains_independent_acquisition_and_retries(monkeypatch, marker, mode):
    p = PairProvider([marker], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    service = ResearchService()
    for _ in range(2):
        result = await service.source(
            "opentargets", "analyze_association", {**PARAMS, "min_score": 0.0}, scope="a"
        )
        assert result.outcome == "partial" and all(not proof.cached for proof in result.provenance)
        pair = result.sections["opentargets"].data
        if marker == "AssociationScore":
            assert pair["overall_score"] is None and pair["evidence"][0]["id"] == "pair-0"
            assert result.next_actions
        else:
            assert pair["overall_score"] == 0.8 and pair["evidence"] is None and result.next_actions == []
    p.failures.clear()
    recovered = await service.source(
        "opentargets", "analyze_association", {**PARAMS, "min_score": 0.0}, scope="a"
    )
    assert recovered.outcome == "data" and recovered.next_actions and len(p.calls) == 6


@pytest.mark.parametrize("mutation", ["duplicate", "count", "target", "disease", "limit"])
async def test_malformed_pair_window_preserves_only_valid_association(provider, mutation):
    page = provider.pages[None]
    if mutation == "duplicate":
        page["rows"].append(deepcopy(page["rows"][0]))
    elif mutation == "count":
        page["count"] = 0
    elif mutation == "target":
        page["rows"][0]["target"]["id"] = "ENSG00000141510"
    elif mutation == "disease":
        page["rows"][0]["disease"]["id"] = "EFO_0000001"
    else:
        page["rows"].append(evidence("pair-extra"))
    result = await ResearchService().source("opentargets", "analyze_association", PARAMS, scope="a")
    pair = result.sections["opentargets"].data
    assert result.outcome == "partial" and pair["overall_score"] == 0.8 and pair["evidence"] is None
    assert pair["section_outcomes"]["evidence"]["error"]["code"] == "invalid_source_response"
    assert result.next_actions == []


@pytest.mark.parametrize("nested", [False, True])
async def test_incomplete_first_terminal_pair_window_is_partial_uncached(provider, nested):
    provider.pages[None]["cursor"] = None
    service = ResearchService()
    args = ADVANCED if nested else ARGS
    for _ in range(2):
        result = await service.source(args["source"], args["operation"], args["params"], scope="a")
        pair = result.sections["opentargets"].data
        pair = pair["association_analysis"] if nested else pair
        assert result.outcome == "partial" and result.next_actions == []
        assert pair["coverage"]["continuation_status"] == "unavailable"
        assert all(not p.cached for p in result.provenance)
    assert len(provider.calls) == (10 if nested else 4)


async def test_pair_state_resumes_across_independent_runtimes(provider):
    cache = ResultCache()
    one, two = [ResearchService(runtime=ProviderRuntime(cache=cache, cursor_key=b"x" * 32)) for _ in range(2)]
    first = await one.source("opentargets", "analyze_association", PARAMS, scope="a")
    second = await two.source(
        "opentargets", "analyze_association", first.next_actions[0]["arguments"]["params"], scope="a"
    )
    assert second.sections["opentargets"].data["evidence"][0]["id"] == "pair-1" and len(provider.calls) == 4


async def test_coalesced_pair_cancellation_keeps_remaining_waiter_and_signed_action(provider, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original = provider.post

    async def delayed(url, **kwargs):
        if "TargetDiseaseEvidence" in kwargs["json"]["query"]:
            entered.set()
            await release.wait()
        return await original(url, **kwargs)

    monkeypatch.setattr(provider, "post", delayed)
    service = ResearchService()
    first = asyncio.create_task(service.source("opentargets", "analyze_association", PARAMS, scope="a"))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(service.source("opentargets", "analyze_association", PARAMS, scope="a"))
    async with asyncio.timeout(1):
        while not any(entry[1] == 2 for entry in service.runtime.flights.values()):
            await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await asyncio.wait_for(second, 1)
    assert result.outcome == "data" and result.next_actions and len(provider.calls) == 2


@pytest.mark.parametrize("nested", [False, True])
async def test_actual_mcp_pair_recovery_retains_ids_and_hides_private_state(provider, nested):
    provider.pages[None] = {
        "count": 31,
        "cursor": TOKEN,
        "rows": [evidence("pair-" + str(i), 0.9) for i in range(30)],
    }
    args = ADVANCED if nested else {**ARGS, "params": {**PARAMS, "limit": 30}}
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", args)).data
        section = first["sections"]["opentargets"]
        pointer = "/association_analysis/evidence" if nested else "/evidence"
        omission = next(o for o in section["recovery"]["omissions"] if o["pointer"] == pointer)
        recovered = json.loads((await c.read_resource(omission["uri"]))[0].text)
        assert [row["id"] for row in recovered["value"]] == ["pair-" + str(i) for i in range(25, 30)]
        assert recovered["evidence_ids"] == section["evidence_ids"] and first["next_actions"]
        assert TOKEN not in json.dumps([first, recovered])
    assert len(provider.calls) == (5 if nested else 2)


@pytest.mark.parametrize("nested", [False, True])
def test_actual_local_cli_processes_resume_pair_state(tmp_path, nested):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "UBI_PROFILE": "local",
        "PYTHONPATH": os.pathsep.join(
            str(root / p) for p in ("src", "tests", "servers/python/opentargets/src")
        ),
    }
    script = """
import asyncio,json,sys
from opentargets_mcp import queries
from test_opentargets_pair_evidence import PairProvider
from biomedmcp.cli import execute
p=PairProvider()
queries.httpx.AsyncClient=lambda **kwargs:p
async def main():
 result=await execute('query_source',json.loads(sys.argv[1]),state_dir=sys.argv[2])
 print(json.dumps({'result':result,'http_calls':len(p.calls)}))
asyncio.run(main())
"""

    def run(arguments):
        result = subprocess.run(
            [sys.executable, "-c", script, json.dumps(arguments), str(tmp_path / "state")],
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    first = run(ADVANCED if nested else ARGS)
    second = run(first["result"]["next_actions"][0]["arguments"])
    assert first["http_calls"] == (5 if nested else 2) and second["http_calls"] == 2
    assert second["result"]["sections"]["opentargets"]["data"]["evidence"][0]["id"] == "pair-1"
    assert second["result"]["next_actions"] == [] and TOKEN not in json.dumps([first, second])


@pytest.mark.parametrize("mutation", ["position", "digest", "token", "duplicate_digest"])
async def test_pair_invalid_stored_state_fails_without_provider_io(provider, mutation):
    service = ResearchService()
    first = await service.source("opentargets", "analyze_association", PARAMS, scope="a")
    params = first.next_actions[0]["arguments"]["params"]
    key = PairContinuation.cache_prefix + digest(params["evidence_cursor"])
    state = await service.runtime.cache.get(key)
    if mutation == "position":
        state["windows"] = 2
    elif mutation == "digest":
        state["seen"] = ["not-a-sha256-digest"]
    elif mutation == "token":
        state["after"] = ""
    else:
        state["seen"] *= 2
    await service.runtime.cache.put(key, state, 3600)
    with pytest.raises(ResearchError) as error:
        await service.source("opentargets", "analyze_association", params, scope="a")
    assert error.value.code == "cache_invalid_data" and len(provider.calls) == 2
