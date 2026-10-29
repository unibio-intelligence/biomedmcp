"""Request terminals describe actual public outputs, not earlier source success."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastmcp import Client

from biomedmcp import cli, local_boundary, request_telemetry, runtime
from biomedmcp.contracts import ResearchResult, Section
from biomedmcp.dispatch import execute
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.request_telemetry import active_request, phase, request_trace
from biomedmcp.telemetry import correlation_id

SENTINEL = "credential-query-account-body-sentinel"


class Sink:
    def __init__(self):
        self.events = []

    def info(self, event, **fields):
        self.events.append({"event": event, **fields})


@pytest.fixture
def observed(monkeypatch):
    sink = Sink()
    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setattr(request_telemetry, "log", sink)
    monkeypatch.setattr(runtime, "log", sink)
    monkeypatch.setattr(request_telemetry, "metrics", request_telemetry.RequestMetrics())
    return sink


class Service:
    def __init__(self):
        self.runtime = runtime.ProviderRuntime()
        self.calls = 0

    async def get(self, request, *, scope, _plan_only=False):
        if _plan_only:
            return

        async def acquire():
            self.calls += 1
            await asyncio.sleep(0.001)
            return {"records": [{"id": "one"}]}

        await self.runtime.invoke("mygene", {"operation": "get", "id": request.id}, acquire, scope=scope)
        if request.id == "invalid-output":
            return ResearchResult(
                entity="protein",
                outcome="error",
                sections={"record": Section(outcome="error", error={"message": SENTINEL})},
            )
        if request.id == "source-unavailable":
            return ResearchResult(
                entity="protein",
                outcome="unavailable",
                sections={
                    "record": Section(
                        outcome="unavailable", error=ResearchError("source_unavailable", SENTINEL).as_dict()
                    )
                },
            )
        return ResearchResult(
            entity="protein", outcome="data", sections={"record": Section(outcome="data", data={"id": "one"})}
        )


def terminals(sink):
    return [x for x in sink.events if x["event"] == "public_request_result"]


async def test_static_resources_and_prompt_have_terminal_auth_and_output_spans(observed):
    async with Client(create_server(service=Service())) as client:
        await client.read_resource("biomedmcp://guide")
        await client.read_resource("biomedmcp://schemas/result")
        await client.read_resource("biomedmcp://schemas/evidence")
        await client.read_resource("biomedmcp://schemas/records/study")
        await client.get_prompt("target_research", {"gene": SENTINEL})
    events = terminals(observed)
    assert len(events) == 5
    assert {event["operation"] for event in events} == {
        "resource_guide",
        "resource_result_schema",
        "resource_evidence_schema",
        "resource_record_schema",
        "prompt_target_research",
    }
    assert [event["boundary"] for event in events] == ["mcp_resource"] * 4 + ["mcp_prompt"]
    assert all(event["phase_calls"] == {"authentication": 1, "output_encoding": 1} for event in events)
    assert all(
        event["output_state"] == "static_output_constructed" and not event["delivery_confirmed"]
        for event in events
    )
    assert SENTINEL not in json.dumps(events)


async def call(client, identifier=SENTINEL):
    return await client.call_tool_mcp("get", {"entity": "protein", "id": identifier})


async def test_actual_mcp_has_one_terminal_after_accounting_and_output_with_source_correlation(observed):
    service = Service()
    async with Client(create_server(service=service)) as client:
        value = await call(client)
    events = terminals(observed)
    assert len(events) == 1
    terminal = events[0]
    assert (
        terminal["boundary"] == "mcp_tool"
        and terminal["outcome"] == value.structured_content["outcome"] == "data"
    )
    assert terminal["phase_calls"] == {
        "accounting": 1,
        "operation": 1,
        "dispatch": 1,
        "output_validation": 1,
        "output_encoding": 1,
    }
    assert terminal["phase_ms"]["accounting"] >= terminal["phase_ms"]["dispatch"] > 0
    assert terminal["output_state"] == "mcp_result_constructed" and not terminal["delivery_confirmed"]
    assert terminal["payload_bytes"] == len(
        json.dumps(value.structured_content, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert observed.events[-1] == terminal
    assert {x["correlation_id"] for x in observed.events} == {terminal["correlation_id"]}
    assert request_telemetry.metrics.snapshot()["boundaries"]["mcp_tool"]["pending"] == 0
    assert SENTINEL not in json.dumps(observed.events)
    assert active_request.get() is correlation_id.get() is None


async def test_output_validation_failure_does_not_relabel_earlier_provider_success(observed):
    async with Client(create_server(service=Service())) as client:
        result = await call(client, "invalid-output")
    event = terminals(observed)[0]
    assert result.is_error and event["outcome"] == "error" and event["error_type"] == "invalid_output"
    assert event["phase_failures"]["output_validation"] == 1
    assert next(x for x in observed.events if x["event"] == "provider_result")["outcome"] == "data"
    assert SENTINEL not in json.dumps(observed.events)


async def test_unavailable_scientific_output_reports_its_safe_section_error(observed):
    async with Client(create_server(service=Service())) as client:
        result = await call(client, "source-unavailable")
    event = terminals(observed)[0]
    assert result.is_error and event["outcome"] == "unavailable"
    assert event["result_error_codes"] == ["source_unavailable"]
    assert SENTINEL not in json.dumps(observed.events)


@pytest.mark.parametrize("stage", ["reserve", "settle"])
async def test_accounting_refusal_or_failure_after_science_never_emits_request_success(observed, stage):
    class Error(local_boundary.ServiceError):
        code = "quota_exceeded"

    async def accounted(ledger, context, name, params, operation, **kwargs):
        assert context.account_id == SENTINEL
        if stage == "settle":
            await operation()
        raise Error(SENTINEL)

    boundary = SimpleNamespace(
        **{
            key: getattr(local_boundary, key)
            for key in [
                "AuthSettings",
                "build_auth",
                "build_ledger",
                "dependencies_ready",
                "close_auth",
                "ServiceError",
            ]
        },
        accounted=accounted,
        current_context=lambda resource: SimpleNamespace(account_id=SENTINEL, cache_scope=SENTINEL),
    )
    service = Service()
    async with Client(create_server(service=service, boundary=boundary)) as client:
        result = await call(client)
    event = terminals(observed)[0]
    assert result.is_error and event["outcome"] == "error" and event["error_type"] == "quota_exceeded"
    assert event["phase_failures"]["accounting"] == 1
    assert service.calls == (1 if stage == "settle" else 0)
    assert SENTINEL not in json.dumps(observed.events)


async def test_batch_retains_final_partial_outcome_and_one_outer_request(observed):
    async with Client(create_server(service=Service())) as client:
        result = await client.call_tool_mcp(
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "protein", "id": identifier}}
                    for identifier in [SENTINEL, "source-unavailable"]
                ]
            },
        )
    event = terminals(observed)[0]
    assert len(terminals(observed)) == 1 and event["operation"] == "batch"
    assert event["outcome"] == result.structured_content["outcome"] == "partial"
    assert event["result_error_codes"] == ["source_unavailable"]
    assert event["phase_calls"]["accounting"] == event["phase_calls"]["dispatch"] == 1
    assert SENTINEL not in json.dumps(observed.events)


async def test_embedded_dispatch_creates_a_terminal_without_claiming_wire_delivery(observed):
    value = await execute(Service(), "get", {"entity": "protein", "id": SENTINEL}, scope=SENTINEL)
    event = terminals(observed)[0]
    assert event["outcome"] == value.outcome and event["boundary"] == "embedded"
    assert event["output_state"] == "scientific_result_constructed" and not event["delivery_confirmed"]


async def test_cli_owns_request_and_nested_dispatch_does_not_emit_another(observed, monkeypatch):
    async def command(*args, **kwargs):
        return (
            await execute(Service(), "get", {"entity": "protein", "id": SENTINEL}, scope=SENTINEL)
        ).model_dump(mode="json")

    monkeypatch.setattr(cli, "_execute", command)
    await cli.execute("get", {"entity": "protein", "id": SENTINEL})
    assert len(terminals(observed)) == 1 and terminals(observed)[0]["boundary"] == "cli"


@pytest.mark.parametrize(
    "error,expected",
    [
        (asyncio.CancelledError(), "cancelled"),
        (TimeoutError(SENTINEL), "operation_timeout"),
        (ResearchError(SENTINEL, SENTINEL), "internal_error"),
    ],
)
async def test_failure_cleanup_emits_one_safe_terminal_and_resets_context(observed, error, expected):
    with pytest.raises(type(error)), request_trace(SENTINEL, SENTINEL), phase("operation"):
        raise error
    event = terminals(observed)[0]
    assert event["operation"] == event["boundary"] == "unknown" and event["error_type"] == expected
    assert event["phase_failures"] == {"operation": 1}
    assert event["output_state"] == "not_constructed"
    assert active_request.get() is correlation_id.get() is None
    assert request_telemetry.metrics.snapshot()["boundaries"]["unknown"]["pending"] == 0
    assert SENTINEL not in json.dumps(observed.events)


async def test_coalesced_requests_keep_separate_terminal_ids_and_one_shared_flight(observed):
    service = Service()
    async with Client(create_server(service=service)) as client:
        await asyncio.gather(call(client), call(client))
    events = terminals(observed)
    assert len(events) == 2 and len({x["correlation_id"] for x in events}) == 2
    flights = [x for x in observed.events if x["event"] == "provider_result"]
    waiters = [x for x in observed.events if x["event"] == "provider_waiter"]
    assert len(flights) == 1 and service.calls == 1 and len(waiters) == 2
    assert {x["correlation_id"] for x in waiters} == {x["correlation_id"] for x in events}
    assert {x["flight_id"] for x in waiters} == {flights[0]["flight_id"]}


async def test_nonfinite_or_large_outputs_report_unknown_size_without_record_text(observed):
    for value in [{"value": float("nan")}, {"value": SENTINEL * 100000}]:
        with request_trace("get", "embedded") as observation:
            observation.complete(value, output_state="scientific_result_constructed")
    assert all(
        x["payload_size_capped_or_unknown"] and x["payload_bytes"] is None for x in terminals(observed)
    )
    assert SENTINEL not in json.dumps(observed.events)


async def test_evidence_resource_terminal_includes_accounting_and_json_output(observed):
    class EvidenceService(Service):
        async def read_evidence(self, uri, *, scope):
            return {"outcome": "data", "rows": [SENTINEL], "evidence_ids": ["ev_one"]}

    uri = "biomedmcp://evidence/" + "a" * 32 + "/root/0/1"
    async with Client(create_server(service=EvidenceService())) as client:
        result = await client.read_resource(uri)
    event = terminals(observed)[0]
    assert len(terminals(observed)) == 1 and event["boundary"] == "mcp_resource"
    assert event["operation"] == "evidence_read" and event["outcome"] == "data"
    assert event["phase_calls"] == {"accounting": 1, "operation": 1, "output_encoding": 1}
    assert event["output_state"] == "resource_json_constructed"
    assert json.loads(result[0].text)["rows"] == [SENTINEL]
    assert SENTINEL not in json.dumps(observed.events)


async def test_load_observations_reconcile_request_terminals_shared_flights_and_cache_hits(observed):
    service = Service()
    async with Client(create_server(service=service)) as client:
        for _ in range(4):
            await asyncio.gather(*(call(client, str(index % 3)) for index in range(12)))
    events = terminals(observed)
    assert len(events) == 48 and len({x["correlation_id"] for x in events}) == 48
    assert all(x["outcome"] == "data" and x["elapsed_ms"] > 0 for x in events)
    assert all(x["phase_ms"]["accounting"] >= x["phase_ms"]["dispatch"] for x in events)
    assert all(x["phase_calls"]["output_validation"] == 1 for x in events)
    flights = [x for x in observed.events if x["event"] == "provider_result"]
    waiters = [x for x in observed.events if x["event"] == "provider_waiter"]
    assert len(waiters) == 48 and service.calls == 3
    assert sum(x["cache_state"] == "hit" for x in flights) >= 9
    assert request_telemetry.metrics.snapshot()["boundaries"]["mcp_tool"]["terminal"] == 48
    assert request_telemetry.metrics.snapshot()["boundaries"]["mcp_tool"]["pending"] == 0
    assert SENTINEL not in json.dumps(observed.events)


async def test_operator_sink_failure_preserves_result_and_balanced_request_metrics(observed, monkeypatch):
    class Broken:
        def info(self, *args, **kwargs):
            raise RuntimeError(SENTINEL)

    monkeypatch.setattr(request_telemetry, "log", Broken())
    result = await execute(Service(), "get", {"entity": "protein", "id": SENTINEL}, scope=SENTINEL)
    assert result.outcome == "data"
    counts = request_telemetry.metrics.snapshot()["boundaries"]["embedded"]
    assert counts["terminal"] == counts["event_sink_failures"] == 1 and counts["pending"] == 0
    assert active_request.get() is correlation_id.get() is None


@pytest.mark.parametrize(
    "code",
    [
        "evidence_invalid_data",
        "evidence_resource_budget",
        "evidence_timeout",
        "evidence_unavailable",
        "output_metadata_budget",
        "source_contract_changed",
    ],
)
async def test_implementation_owned_evidence_and_contract_errors_remain_distinguishable(observed, code):
    with pytest.raises(ResearchError), request_trace("evidence_read", "mcp_resource"), phase("operation"):
        raise ResearchError(code, SENTINEL)
    event = terminals(observed)[0]
    assert event["error_type"] == code and event["outcome"] == "error"
    assert SENTINEL not in json.dumps(observed.events)
