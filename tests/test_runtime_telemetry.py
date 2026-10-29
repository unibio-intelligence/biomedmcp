"""Terminal observations must reflect actual scientific and infrastructure outcomes."""

import asyncio
import json

import pytest

from biomedmcp import runtime as runtime_module
from biomedmcp.errors import ResearchError
from biomedmcp.runtime import ProviderRuntime


class Sink:
    def __init__(self):
        self.events = []

    def info(self, event, **fields):
        self.events.append({"event": event, **fields})


@pytest.fixture
def observed(monkeypatch):
    sink = Sink()
    monkeypatch.setattr(runtime_module, "log", sink)
    return ProviderRuntime(), sink


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"records": [{"id": "one"}]}, "data"),
        ({"records": []}, "empty"),
        ({"resolution": "ambiguous", "candidates": []}, "ambiguous"),
        ({"resolution": "empty"}, "empty"),
        ({"variant": None}, "empty"),
        ({"records": [{"id": "one"}], "section_outcomes": {"peer": {"outcome": "unavailable"}}}, "partial"),
        ({"section_outcomes": {"peer": {"outcome": "error"}}}, "partial"),
    ],
)
async def test_terminal_outcome_agrees_with_visible_scientific_section(observed, payload, expected):
    runtime, sink = observed

    async def call():
        return payload

    await runtime.invoke("mygene", {"operation": "search"}, call, scope="private-test-scope")
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["outcome"] == expected
    assert event["operation"] == "search"
    assert event["payload_bytes"] == len(json.dumps(payload, separators=(",", ":")).encode())
    assert len(event["correlation_id"]) == len(event["flight_id"]) == 32
    assert all(
        event[key] >= 0
        for key in ["queue_ms", "execution_ms", "rate_wait_ms", "cache_read_ms", "cache_write_ms"]
    )


async def test_cache_hit_retains_scientific_outcome_and_does_not_execute_provider(observed):
    runtime, sink = observed
    calls = []

    async def call():
        calls.append(True)
        return {"records": []}

    for _ in range(2):
        await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    events = [event for event in sink.events if event["event"] == "provider_result"]
    assert len(calls) == 1 and len(events) == 2
    assert events[1]["cache_state"] == "hit" and events[1]["outcome"] == "empty"
    assert events[1]["execution_ms"] == events[1]["queue_ms"] == 0


async def test_coalesced_cancellation_has_one_physical_terminal_and_distinct_waiters(observed):
    runtime, sink = observed
    gate = asyncio.Event()

    async def call():
        await gate.wait()
        return {"records": []}

    first = asyncio.create_task(runtime.invoke("mygene", {"operation": "search"}, call, scope="local"))
    second = asyncio.create_task(runtime.invoke("mygene", {"operation": "search"}, call, scope="local"))
    for _ in range(5):
        await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    gate.set()
    await second
    flights = [event for event in sink.events if event["event"] == "provider_result"]
    waiters = [event for event in sink.events if event["event"] == "provider_waiter"]
    assert len(flights) == 1 and flights[0]["coalesced_waiters"] == 1
    assert {event["outcome"] for event in waiters} == {"empty", "cancelled"}
    assert len({event["correlation_id"] for event in waiters}) == 2
    assert {event["flight_id"] for event in waiters} == {flights[0]["flight_id"]}
    assert runtime.metrics.snapshot()["sources"]["mygene"]["pending"] == 0


@pytest.mark.parametrize("stage", ["get", "put"])
async def test_cache_failures_are_distinguishable_without_exception_text(observed, stage):
    runtime, sink = observed

    async def fail(*args):
        raise ConnectionError("credential-query-body-sentinel")

    setattr(runtime.cache, stage, fail)

    async def call():
        return {"records": []}

    with pytest.raises(ResearchError):
        await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["error_type"] == "cache_unavailable" and event["outcome"] == "unavailable"
    assert event["cache_state"] == ("read_failed" if stage == "get" else "write_failed")
    assert runtime.metrics.snapshot()["sources"]["mygene"]["cache_failures"] == 1
    assert "sentinel" not in json.dumps(sink.events)


async def test_full_admission_records_rejection_without_claiming_provider_execution(monkeypatch):
    sink = Sink()
    monkeypatch.setattr(runtime_module, "log", sink)
    runtime = ProviderRuntime(max_pending=1)
    gate = asyncio.Event()

    async def call():
        await gate.wait()
        return {"records": []}

    running = asyncio.create_task(runtime.invoke("mygene", {"id": 1}, call, scope="local"))
    for _ in range(5):
        await asyncio.sleep(0)
    try:
        with pytest.raises(ResearchError, match="admission"):
            await runtime.invoke("mygene", {"id": 2}, call, scope="local")
        rejected = [event for event in sink.events if event.get("error_type") == "provider_busy"]
        assert any(event["event"] == "provider_result" and event["execution_ms"] == 0 for event in rejected)
        assert runtime.metrics.snapshot()["sources"]["mygene"]["rejected"] == 1
    finally:
        gate.set()
        await running


async def test_dynamic_labels_exception_codes_and_inputs_never_enter_telemetry(observed):
    runtime, sink = observed
    sentinel = "credential_query_body_sentinel"

    async def call():
        raise ResearchError(sentinel, sentinel)

    with pytest.raises(ResearchError):
        await runtime.invoke(sentinel, {"operation": sentinel, "query": sentinel}, call, scope=sentinel)
    assert sentinel not in json.dumps(sink.events)
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["source"] == event["operation"] == "unknown"
    assert event["error_type"] == "internal_error"


async def test_cancel_before_fetch_starts_releases_gauge_and_emits_once(observed, monkeypatch):
    runtime, sink = observed
    original = asyncio.create_task

    def cancelled(coroutine):
        async def defer():
            try:
                await asyncio.sleep(0)
                return await coroutine
            finally:
                coroutine.close()

        task = original(defer())
        asyncio.get_running_loop().call_soon(task.cancel)
        return task

    monkeypatch.setattr(runtime_module.asyncio, "create_task", cancelled)

    async def call():
        raise AssertionError("A cancelled queued task must not execute")

    with pytest.raises(asyncio.CancelledError):
        await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    await asyncio.sleep(0)
    events = [event for event in sink.events if event["event"] == "provider_result"]
    assert len(events) == 1 and events[0]["outcome"] == "cancelled"
    assert events[0]["cache_state"] == "not_started"
    assert runtime.metrics.snapshot()["sources"]["mygene"]["pending"] == 0
    assert not runtime.observations and not runtime.flights


async def test_eager_task_completion_has_no_pending_gauge_leak(observed):
    runtime, sink = observed
    loop = asyncio.get_running_loop()
    before = loop.get_task_factory()
    loop.set_task_factory(asyncio.eager_task_factory)

    async def call():
        return {"records": []}

    try:
        await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
        assert runtime.metrics.snapshot()["sources"]["mygene"]["pending"] == 0
        assert len([event for event in sink.events if event["event"] == "provider_result"]) == 1
    finally:
        loop.set_task_factory(before)


async def test_rate_wait_is_measured_and_waiting_gauge_recovers(observed):
    runtime, sink = observed

    async def call():
        await runtime.budget.acquire("mygene", requests_per_second=50)
        await runtime.budget.acquire("mygene", requests_per_second=50)
        return {"records": []}

    await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["rate_wait_ms"] > 0 and event["execution_ms"] >= event["rate_wait_ms"]
    metrics = runtime.metrics.snapshot()["sources"]["mygene"]
    assert metrics["rate_waiting"] == metrics["pending"] == 0 and metrics["rate_wait_ms"] > 0


@pytest.mark.parametrize("status", ["source_rate_limited", "source_timeout"])
async def test_source_rate_limit_and_timeout_failures_have_distinct_counters(observed, status):
    runtime, sink = observed

    async def call():
        raise ResearchError(status, "body-credential-sentinel")

    with pytest.raises(ResearchError):
        await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    metrics = runtime.metrics.snapshot()["sources"]["mygene"]
    assert metrics["rate_limited_failures" if status == "source_rate_limited" else "timeouts"] == 1
    assert "sentinel" not in json.dumps(sink.events)


async def test_retry_success_preserves_actual_429_attempt_count(observed, monkeypatch):
    from test_transport_retries import Pool

    from biomedmcp import transport
    from biomedmcp.native.http import ProviderHTTP

    runtime, sink = observed
    public = transport.PublicTransport()
    public.pool = Pool([429, 200])
    monkeypatch.setattr(transport, "_transport", public)

    async def admit(_url):
        return None

    monkeypatch.setattr(transport, "admit", admit)

    async def call():
        return await ProviderHTTP().get("https://mygene.info/v3/query")

    await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["outcome"] == "data" and event["http_429"] == 1
    assert runtime.metrics.snapshot()["sources"]["mygene"]["http_429"] == 1


def test_payload_sizes_are_utf8_bounded_and_unknown_is_not_zero():
    from biomedmcp.telemetry import payload_size

    assert payload_size({"title": "λ"}) == len('{"title":"λ"}'.encode())
    assert payload_size({"body": "x" * 1_000_001}) is None
    assert payload_size(float("nan")) is None


async def test_metrics_snapshot_is_defensive_and_unknown_labels_are_bounded(observed):
    runtime, _ = observed

    async def call():
        return {"records": []}

    for i in range(20):
        await runtime.invoke(f"input-sentinel-{i}", {"operation": str(i)}, call, scope="local")
    snapshot = runtime.metrics.snapshot()
    assert set(snapshot["sources"]) == {"unknown"}
    snapshot["sources"]["unknown"]["pending"] = 999
    assert runtime.metrics.snapshot()["sources"]["unknown"]["pending"] == 0


async def test_retry_success_preserves_actual_timeout_attempt_count(observed, monkeypatch):
    import httpcore
    from test_transport_retries import Pool

    from biomedmcp import transport
    from biomedmcp.native.http import ProviderHTTP

    runtime, sink = observed
    public = transport.PublicTransport()
    public.pool = Pool([httpcore.ReadTimeout("body-credential-sentinel"), 200])
    monkeypatch.setattr(transport, "_transport", public)

    async def admit(_url):
        return None

    monkeypatch.setattr(transport, "admit", admit)

    async def call():
        return await ProviderHTTP().get("https://mygene.info/v3/query")

    await runtime.invoke("mygene", {"operation": "search"}, call, scope="local")
    event = next(event for event in sink.events if event["event"] == "provider_result")
    assert event["outcome"] == "data" and event["http_timeout_attempts"] == 1
    assert runtime.metrics.snapshot()["sources"]["mygene"]["http_timeout_attempts"] == 1
    assert "sentinel" not in json.dumps(sink.events)


async def test_one_public_dispatch_groups_source_work_without_logging_scope_or_identity(observed):
    from test_qualified_gene_identity import GeneAdapters

    from biomedmcp.dispatch import execute
    from biomedmcp.domain import ResearchService

    runtime, sink = observed
    result = await execute(
        ResearchService(adapters=GeneAdapters(), runtime=runtime),
        "get",
        {"entity": "gene", "id": "673", "sections": ["protein"]},
        scope="private-account-sentinel",
    )
    assert result.outcome == "data"
    events = [event for event in sink.events if event["event"] == "provider_result"]
    assert len(events) == 2
    assert len({event["correlation_id"] for event in events}) == 1
    assert len({event["flight_id"] for event in events}) == 2
    assert {event["operation"] for event in events} == {"gene_identity", "get:protein"}
    assert "sentinel" not in json.dumps(sink.events)
