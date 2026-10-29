"""Actual variant evidence pagination retains identity, measurements and scope."""

import json
from copy import deepcopy

import pytest
from fastmcp import Client
from opentargets_helpers import project
from opentargets_mcp import queries
from test_opentargets_responses import Transport
from test_opentargets_workflows import DISEASE, IDENTITY, VARIANT, Provider, credible

from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.runtime import ProviderRuntime, ResultCache, digest

TOKEN = "SYNTHETIC_PROVIDER_CURSOR_MUST_STAY_PRIVATE"
PARAMS = {"query_type": "variant", "variant_id": VARIANT, "include_evidences": True, "limit": 1}
ARGS = {"source": "opentargets", "operation": "query_genetics", "params": PARAMS}


def evidence(index=0):
    return {
        "id": f"synthetic-evidence-{index}",
        "score": 0.5,
        "datasourceId": "synthetic-genetic-source",
        "datatypeId": "genetic_association",
        "variantRsId": None,
        "variantFunctionalConsequence": None,
        "confidence": None,
        "literature": [],
        "studyId": "synthetic-study",
        "beta": 0.2,
        "betaConfidenceIntervalLower": -0.4,
        "betaConfidenceIntervalUpper": 0.8,
        "pValueMantissa": 8.0,
        "pValueExponent": -9,
        "oddsRatio": None,
        "oddsRatioConfidenceIntervalLower": None,
        "oddsRatioConfidenceIntervalUpper": None,
        "target": {"id": IDENTITY, "approvedSymbol": "BRAF"},
        "disease": {"id": DISEASE, "name": "Synthetic disease"},
    }


class VariantProvider(Provider):
    def __init__(self, failures=(), mode="network"):
        super().__init__(failures, mode)
        self.pages = {
            None: {"count": 2, "cursor": TOKEN, "rows": [evidence()]},
            TOKEN: {"count": 2, "cursor": None, "rows": [evidence(1)]},
        }
        self.evidence_mutation = None
        self.loci = [credible(i) for i in range(2)]
        for row in self.loci:
            row.update(
                region=None,
                beta=None,
                zScore=None,
                standardError=None,
                credibleSetIndex=None,
                credibleSetlog10BF=None,
                purityMeanR2=None,
                purityMinR2=None,
            )

    async def post(self, url, **kwargs):
        body = kwargs["json"]
        if "VariantCredibleSets" in body["query"] and "VariantCredibleSets" not in self.failures:
            variables = body["variables"]
            start, size = variables["pageIndex"] * variables["pageSize"], variables["pageSize"]
            page = {"count": len(self.loci), "rows": self.loci[start : start + size]}
            self.payload = project(
                {"data": {"variant": {**self.variant, "credibleSets": page}}}, body["query"], variables
            )
            return await Transport.post(self, url, **kwargs)
        if "VariantEvidences" not in body["query"] or "VariantEvidences" in self.failures:
            return await super().post(url, **kwargs)
        page = deepcopy(self.pages[body["variables"].get("cursor")])
        payload = {"data": {"variant": {**self.variant, "evidences": page}}}
        self.payload = project(payload, body["query"], body["variables"])
        if self.evidence_mutation is not None:
            self.evidence_mutation(self.payload)
        return await Transport.post(self, url, **kwargs)


@pytest.fixture
def provider(monkeypatch):
    value = VariantProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: value)
    monkeypatch.setenv("UBI_PROFILE", "local")
    return value


async def test_actual_mcp_consumes_signed_action_keeps_measurements_and_hides_provider_token(provider):
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", ARGS)).data
        data = first["sections"]["opentargets"]["data"]["evidences"]
        assert data["variant"]["id"] == VARIANT
        row = data["variant"]["evidences"]["rows"][0]
        assert row["beta"] == 0.2 and row["betaConfidenceIntervalLower"] == -0.4
        assert row["betaConfidenceIntervalUpper"] == 0.8 and "standardError" not in row
        assert row["oddsRatio"] is row["variantRsId"] is None
        assert data["coverage"]["exhaustive"] is False and TOKEN not in json.dumps(first)
        action = first["next_actions"][0]
        second = (await c.call_tool(action["tool"], action["arguments"])).data
        data = second["sections"]["opentargets"]["data"]["evidences"]
        assert data["variant"]["evidences"]["rows"][0]["id"] == "synthetic-evidence-1"
        assert data["coverage"]["exhaustive"] is False and second["next_actions"] == []
        assert TOKEN not in json.dumps(second)
    assert len(provider.calls) == 4
    assert provider.calls[-1][1]["json"]["variables"]["cursor"] == TOKEN


async def test_empty_nonterminal_window_preserves_action_and_later_records(provider):
    provider.pages[None]["rows"] = []
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", ARGS)).data
        data = first["sections"]["opentargets"]["data"]["evidences"]
        assert data["variant"]["evidences"]["rows"] == []
        assert data["coverage"]["provider_total"] == 2 and first["next_actions"]
        action = first["next_actions"][0]
        second = (await c.call_tool(action["tool"], action["arguments"])).data
        assert second["sections"]["opentargets"]["data"]["evidences"]["variant"]["evidences"]["rows"]
    assert len(provider.calls) == 4


@pytest.mark.parametrize(
    "change",
    [
        "variant",
        "limit",
        "flags",
        "tamper",
        "account",
        "expired",
        "lost_state",
        "invalid_state",
        "revision",
        "signing_key",
    ],
)
async def test_signed_cursor_rejects_wrong_context_before_provider_io(provider, change, monkeypatch):
    service = ResearchService()
    first = await service.source("opentargets", "query_genetics", PARAMS, scope="account-a")
    params = deepcopy(first.next_actions[0]["arguments"]["params"])
    scope = "account-a"
    if change == "variant":
        params["variant_id"] = "7_1002_A_T"
    elif change == "limit":
        params["limit"] = 2
    elif change == "flags":
        params["include_functional_consequences"] = False
    elif change == "tamper":
        original = params["evidence_cursor"]
        params["evidence_cursor"] = ("y" if original[0] == "x" else "x") + original[1:]
        assert params["evidence_cursor"] != original
    elif change == "account":
        scope = "account-b"
    elif change == "expired":
        from biomedmcp import runtime

        now = runtime.time.time()
        monkeypatch.setattr(runtime.time, "time", lambda: now + 3601)
    elif change == "lost_state":
        service.runtime.cache.values.clear()
    elif change == "revision":
        from biomedmcp.native import opentargets_variant_evidence

        monkeypatch.setattr(opentargets_variant_evidence, "REVISION", "biomedmcp/0.3.0")
    elif change == "signing_key":
        service.runtime.cursors.key = b"a different synthetic signing key"
    else:
        key = "opentargets-variant-page:" + digest(params["evidence_cursor"])
        await service.runtime.cache.put(key, {"after": TOKEN, "windows": 1, "scanned": 1, "seen": [{}]}, 3600)
    with pytest.raises(ResearchError) as caught:
        await service.source("opentargets", "query_genetics", params, scope=scope)
    assert caught.value.code in {"invalid_cursor", "expired_cursor", "cache_invalid_data"}
    assert len(provider.calls) == 2


async def test_independent_runtime_resumes_shared_store_and_signing_key(provider):
    cache = ResultCache()
    first_service = ResearchService(runtime=ProviderRuntime(cache=cache, cursor_key=b"x" * 32))
    second_service = ResearchService(runtime=ProviderRuntime(cache=cache, cursor_key=b"x" * 32))
    first = await first_service.source("opentargets", "query_genetics", PARAMS, scope="account-a")
    params = first.next_actions[0]["arguments"]["params"]
    second = await second_service.source("opentargets", "query_genetics", params, scope="account-a")
    assert (
        second.sections["opentargets"].data["evidences"]["variant"]["evidences"]["rows"][0]["id"]
        == "synthetic-evidence-1"
    )
    assert second.next_actions == [] and len(provider.calls) == 4


@pytest.mark.parametrize("mode", ["network", "malformed"])
async def test_secondary_failure_keeps_primary_and_retries_without_healthy_cache(monkeypatch, mode):
    p = VariantProvider(["VariantEvidences"], mode)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as c:
        for _ in range(2):
            result = (await c.call_tool("query_source", ARGS)).data
            data = result["sections"]["opentargets"]["data"]
            assert result["outcome"] == "partial" and data["variant"]["id"] == VARIANT
            assert data["evidences"] is None and result["next_actions"] == []
            assert all(not value["cached"] for value in result["provenance"])
        p.failures.clear()
        good = (await c.call_tool("query_source", ARGS)).data
        assert good["outcome"] == "data" and good["next_actions"]
    assert len(p.calls) == 6


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "reverse_beta_interval",
        "wrong_pvalue",
        "negative_odds",
        "reverse_interval",
        "foreign_gene",
        "missing_field",
    ],
)
async def test_invalid_scientific_evidence_retains_primary_without_empty_substitution(provider, mutation):
    page = provider.pages[None]
    row = page["rows"][0]
    if mutation == "duplicate":
        page["rows"].append(deepcopy(row))
    elif mutation == "reverse_beta_interval":
        row.update(betaConfidenceIntervalLower=1.0, betaConfidenceIntervalUpper=0.5)
    elif mutation == "wrong_pvalue":
        row["pValueExponent"] = 1
    elif mutation == "negative_odds":
        row["oddsRatio"] = -1
    elif mutation == "reverse_interval":
        row.update(oddsRatioConfidenceIntervalLower=2.0, oddsRatioConfidenceIntervalUpper=1.0)
    elif mutation == "foreign_gene":
        row["target"]["id"] = "ENSMUSG00000000001"
    else:
        provider.evidence_mutation = lambda payload: payload["data"]["variant"]["evidences"]["rows"][0].pop(
            "betaConfidenceIntervalLower"
        )
    service = ResearchService()
    result = await service.source("opentargets", "query_genetics", {**PARAMS, "limit": 2}, scope="local")
    data = result.sections["opentargets"].data
    assert result.outcome == "partial" and data["variant"]["id"] == VARIANT and data["evidences"] is None
    assert data["section_outcomes"]["evidences"]["error"]["code"] == "invalid_source_response"


async def test_terminal_incomplete_first_page_is_partial_uncached(provider):
    provider.pages[None]["cursor"] = None
    service = ResearchService()
    for _ in range(2):
        result = await service.source("opentargets", "query_genetics", PARAMS, scope="local")
        assert result.outcome == "partial"
        data = result.sections["opentargets"].data["evidences"]
        assert data["coverage"]["continuation_status"] == "unavailable"
        assert len(data["variant"]["evidences"]["rows"]) == 1 and result.next_actions == []
    assert len(provider.calls) == 4


async def test_provider_cycle_stops_with_partial_coverage(provider):
    provider.pages[TOKEN]["cursor"] = "SYNTHETIC-SECOND-CURSOR"
    provider.pages["SYNTHETIC-SECOND-CURSOR"] = {"count": 3, "cursor": TOKEN, "rows": [evidence(2)]}
    service = ResearchService()
    first = await service.source("opentargets", "query_genetics", PARAMS, scope="local")
    second = await service.source(
        "opentargets", "query_genetics", first.next_actions[0]["arguments"]["params"], scope="local"
    )
    third = await service.source(
        "opentargets", "query_genetics", second.next_actions[0]["arguments"]["params"], scope="local"
    )
    assert third.outcome == "partial" and third.next_actions == []
    assert (
        third.sections["opentargets"].data["evidences"]["coverage"]["continuation_status"] == "provider_cycle"
    )
    assert len(provider.calls) == 6
    provider.pages["SYNTHETIC-SECOND-CURSOR"]["cursor"] = None
    retried = await service.source(
        "opentargets", "query_genetics", second.next_actions[0]["arguments"]["params"], scope="local"
    )
    assert retried.outcome == "data" and retried.next_actions == []
    assert len(provider.calls) == 8 and all(not item.cached for item in retried.provenance)


@pytest.mark.parametrize("bound", ["rows", "windows"])
async def test_stored_continuation_budget_stops_without_claiming_exhaustiveness(provider, bound):
    provider.pages[TOKEN]["cursor"] = "SYNTHETIC-NEXT-AFTER-BUDGET"
    service = ResearchService()
    first = await service.source("opentargets", "query_genetics", PARAMS, scope="local")
    params = first.next_actions[0]["arguments"]["params"]
    from biomedmcp.native.opentargets_variant_evidence import VariantContinuation

    position = 1 if bound == "rows" else 63
    token = service.runtime.cursors.encode(
        query=VariantContinuation.binding(PARAMS), scope="local", offset=position
    )
    seen = [digest("synthetic-earlier-" + str(i)) for i in range(position - 1)] + [digest(TOKEN)]
    await service.runtime.cache.put(
        "opentargets-variant-page:" + digest(token),
        {"after": TOKEN, "scanned": 999 if bound == "rows" else 0, "windows": position, "seen": seen},
        3600,
    )
    # Simulated well-formed boundary state, not a claim that prior source rows were acquired.
    params = {**params, "evidence_cursor": token}
    result = await service.source("opentargets", "query_genetics", params, scope="local")
    assert result.outcome == "partial" and result.next_actions == []
    data = result.sections["opentargets"].data["evidences"]
    assert data["coverage"]["exhaustive"] is False and data["coverage"]["continuation_status"] == "scan_limit"
    assert data["variant"]["evidences"]["rows"][0]["id"] == "synthetic-evidence-1"


async def test_nullable_and_measured_zero_effects_remain_distinct(provider):
    row = provider.pages[None]["rows"][0]
    row.update(
        beta=0.0,
        oddsRatio=0.0,
        oddsRatioConfidenceIntervalLower=0.0,
        oddsRatioConfidenceIntervalUpper=1.0,
        pValueMantissa=None,
        pValueExponent=None,
    )
    result = await ResearchService().source("opentargets", "query_genetics", PARAMS, scope="local")
    returned = result.sections["opentargets"].data["evidences"]["variant"]["evidences"]["rows"][0]
    assert returned["beta"] == returned["oddsRatio"] == 0.0
    assert returned["pValueMantissa"] is returned["pValueExponent"] is None
    assert result.outcome == "data" and result.next_actions


async def test_raw_cursor_cannot_be_submitted_through_the_public_operation(provider):
    with pytest.raises(ResearchError) as caught:
        await ResearchService().source(
            "opentargets", "query_genetics", {**PARAMS, "evidence_cursor": TOKEN}, scope="local"
        )
    assert caught.value.code == "invalid_cursor" and provider.calls == []


@pytest.mark.parametrize("mantissa,exponent", [(0.0, -100), (0.08, 1), (80.0, -3)])
async def test_reported_pvalue_components_keep_mathematical_meaning_without_normalization(
    provider, mantissa, exponent
):
    provider.pages[None]["rows"][0].update(pValueMantissa=mantissa, pValueExponent=exponent)
    result = await ResearchService().source("opentargets", "query_genetics", PARAMS, scope="local")
    returned = result.sections["opentargets"].data["evidences"]["variant"]["evidences"]["rows"][0]
    assert result.outcome == "data"
    assert (returned["pValueMantissa"], returned["pValueExponent"]) == (mantissa, exponent)


@pytest.mark.parametrize("failure", ["storage_limit", "cache_unavailable"])
async def test_cursor_storage_failure_retains_acquired_evidence_and_can_recover(
    provider, monkeypatch, failure
):
    service = ResearchService()
    original = service.runtime.cache.put

    async def failing(key, value, ttl):
        if key.startswith("opentargets-variant-page:"):
            if failure == "storage_limit":
                return False
            raise ResearchError("cache_unavailable", "Synthetic private failure text", retryable=True)
        return await original(key, value, ttl)

    monkeypatch.setattr(service.runtime.cache, "put", failing)
    result = await service.source("opentargets", "query_genetics", PARAMS, scope="local")
    assert result.outcome == "partial" and result.next_actions == []
    data = result.sections["opentargets"].data["evidences"]
    assert data["variant"]["evidences"]["rows"][0]["id"] == "synthetic-evidence-0"
    assert data["coverage"]["continuation_status"] == failure
    assert "private failure" not in result.model_dump_json() and TOKEN not in result.model_dump_json()
    monkeypatch.setattr(service.runtime.cache, "put", original)
    recovered = await service.source("opentargets", "query_genetics", PARAMS, scope="local")
    assert recovered.outcome == "data" and recovered.next_actions
    assert len(provider.calls) == 2  # Healthy acquired bytes are reusable; missing cursor storage is retried.


async def test_variant_credible_pages_and_evidence_cursor_continue_independently(provider):
    # Requested locus member and source lead variant are distinct identities.
    for row in provider.loci:
        row["variant"].update(id="7_1002_G_C", position=1002, referenceAllele="G", alternateAllele="C")
        row["position"] = 1002
    arguments = {**ARGS, "params": {**PARAMS, "include_credible_sets": True}}
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", arguments)).data
        loci = first["sections"]["opentargets"]["data"]["credible_sets"]
        assert loci["variant"]["id"] == VARIANT and loci["records"][0]["variant"]["id"] == "7_1002_G_C"
        assert loci["coverage"]["provider_total"] == 2 and len(first["next_actions"]) == 2
        action = next(a for a in first["next_actions"] if a["arguments"]["params"].get("page_index") == 1)
        assert action["arguments"]["params"]["include_evidences"] is False
        assert "evidence_cursor" not in action["arguments"]["params"]
        second = (await c.call_tool(action["tool"], action["arguments"])).data
        assert second["outcome"] == "data" and second["next_actions"] == []
        assert (
            second["sections"]["opentargets"]["data"]["credible_sets"]["records"][0]["studyLocusId"]
            == "synthetic-locus-1"
        )
        assert "evidences" not in second["sections"]["opentargets"]["data"]
    assert len(provider.calls) == 5


@pytest.mark.parametrize(
    "mutation", ["negative_error", "purity", "reverse_purity", "lead_identity", "study_identity"]
)
async def test_invalid_credible_science_keeps_primary_and_independent_evidence(provider, mutation):
    row = provider.loci[0]
    if mutation == "negative_error":
        row["standardError"] = -1.0
    elif mutation == "purity":
        row["purityMeanR2"] = 1.1
    elif mutation == "reverse_purity":
        row.update(purityMeanR2=0.2, purityMinR2=0.8)
    elif mutation == "lead_identity":
        row["variant"]["position"] += 1
    else:
        row["study"]["id"] = "another-study"
    result = await ResearchService().source(
        "opentargets", "query_genetics", {**PARAMS, "include_credible_sets": True}, scope="local"
    )
    data = result.sections["opentargets"].data
    assert result.outcome == "partial" and data["variant"]["id"] == VARIANT
    assert data["credible_sets"] is None and data["evidences"]["variant"]["evidences"]["rows"]
    assert len(result.next_actions) == 1 and result.next_actions[0]["arguments"]["params"].get(
        "evidence_cursor"
    )


async def test_local_persistent_state_resumes_after_reopening(provider, tmp_path):
    from biomedmcp.local_state import LocalState

    state = await LocalState.open(tmp_path / "state")
    first_service = ResearchService(runtime=ProviderRuntime(cache=state, cursor_key=state.signing_key))
    first = await first_service.source("opentargets", "query_genetics", PARAMS, scope=state.scope)
    reopened = await LocalState.open(tmp_path / "state")
    second_service = ResearchService(runtime=ProviderRuntime(cache=reopened, cursor_key=reopened.signing_key))
    second = await second_service.source(
        "opentargets", "query_genetics", first.next_actions[0]["arguments"]["params"], scope=reopened.scope
    )
    assert second.outcome == "data" and second.next_actions == []
    assert (
        second.sections["opentargets"].data["evidences"]["variant"]["evidences"]["rows"][0]["id"]
        == "synthetic-evidence-1"
    )
    assert len(provider.calls) == 4


async def test_actual_mcp_recovers_display_omissions_without_new_provider_io(provider):
    provider.pages[None] = {"count": 31, "cursor": TOKEN, "rows": [evidence(i) for i in range(30)]}
    async with Client(create_server(service=ResearchService())) as c:
        first = (await c.call_tool("query_source", {**ARGS, "params": {**PARAMS, "limit": 30}})).data
        section = first["sections"]["opentargets"]
        assert (
            len(section["data"]["evidences"]["variant"]["evidences"]["rows"]) == 25 and section["truncated"]
        )
        omission = next(
            o for o in section["recovery"]["omissions"] if o["pointer"] == "/evidences/variant/evidences/rows"
        )
        recovered = json.loads((await c.read_resource(omission["uri"]))[0].text)
        assert [r["id"] for r in recovered["value"]] == [
            "synthetic-evidence-" + str(i) for i in range(25, 30)
        ]
        assert recovered["evidence_ids"] == section["evidence_ids"]
        assert TOKEN not in json.dumps(recovered) and first["next_actions"]
    assert len(provider.calls) == 2


async def test_batch_rejects_tampered_cursor_before_any_provider_request(provider):
    async with Client(create_server(service=ResearchService())) as c:
        invalid = {**ARGS, "params": {**PARAMS, "evidence_cursor": TOKEN}}
        result = await c.call_tool(
            "batch",
            {
                "requests": [
                    {"tool": "query_source", "arguments": ARGS},
                    {"tool": "query_source", "arguments": invalid},
                ]
            },
            raise_on_error=False,
        )
        assert result.structured_content["outcome"] == "error"
    assert provider.calls == []


async def test_cancelled_waiter_does_not_cancel_shared_acquisition_or_continuation(provider, monkeypatch):
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()
    original = provider.post

    async def delayed(url, **kwargs):
        if "VariantEvidences" in kwargs["json"]["query"]:
            entered.set()
            await release.wait()
        return await original(url, **kwargs)

    monkeypatch.setattr(provider, "post", delayed)
    service = ResearchService()
    first = asyncio.create_task(service.source("opentargets", "query_genetics", PARAMS, scope="local"))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(service.source("opentargets", "query_genetics", PARAMS, scope="local"))
    async with asyncio.timeout(1):
        while not any(entry[1] == 2 for entry in service.runtime.flights.values()):
            await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await asyncio.wait_for(second, 1)
    assert result.outcome == "data" and result.next_actions and len(provider.calls) == 2
    resumed = await service.source(
        "opentargets", "query_genetics", result.next_actions[0]["arguments"]["params"], scope="local"
    )
    assert resumed.outcome == "data" and resumed.next_actions == [] and len(provider.calls) == 4


def test_real_local_cli_processes_resume_one_persistent_cursor(tmp_path):
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
from test_opentargets_variant_evidence import VariantProvider
from biomedmcp.cli import execute
p=VariantProvider()
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

    first = run(ARGS)
    second = run(first["result"]["next_actions"][0]["arguments"])
    assert first["http_calls"] == second["http_calls"] == 2
    assert first["result"]["outcome"] == second["result"]["outcome"] == "data"
    assert second["result"]["next_actions"] == []
    assert (
        second["result"]["sections"]["opentargets"]["data"]["evidences"]["variant"]["evidences"]["rows"][0][
            "id"
        ]
        == "synthetic-evidence-1"
    )
    assert TOKEN not in json.dumps(first) and TOKEN not in json.dumps(second)
