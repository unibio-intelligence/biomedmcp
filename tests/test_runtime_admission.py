import asyncio

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.runtime import ProviderRuntime


@pytest.mark.asyncio
async def test_queue_wait_is_inside_operation_deadline():
    runtime = ProviderRuntime()
    runtime.operation_timeout = 0.03
    for _ in range(8):
        await runtime.budget.parallel.acquire()
    invoked = []

    async def call():
        invoked.append(True)
        return {"records": []}

    task = asyncio.create_task(runtime.invoke("busy", {}, call, scope="local"))
    try:
        done, _ = await asyncio.wait([task], timeout=0.1)
        assert done, "Queue admission escaped the deadline"
        with pytest.raises(ResearchError) as error:
            await task
        assert error.value.code == "operation_timeout"
        assert error.value.retryable
        assert not invoked
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for _ in range(8):
            runtime.budget.parallel.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get", "put"])
async def test_cache_io_is_inside_operation_deadline(stage):
    runtime = ProviderRuntime()
    runtime.operation_timeout = 0.03
    gate = asyncio.Event()

    async def hang(*args):
        await gate.wait()

    setattr(runtime.cache, stage, hang)

    async def call():
        return {"records": []}

    task = asyncio.create_task(runtime.invoke("busy", {}, call, scope="local"))
    try:
        done, _ = await asyncio.wait([task], timeout=0.1)
        assert done, "Cache access escaped the deadline"
        with pytest.raises(ResearchError) as error:
            await task
        assert error.value.code == "operation_timeout"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_distinct_pending_calls_are_bounded_and_fast_source_is_isolated():
    runtime = ProviderRuntime()
    runtime.max_pending = 4
    runtime.max_source_pending = 3
    runtime.source_concurrency = 1
    gate, started = asyncio.Event(), asyncio.Event()

    async def slow():
        started.set()
        await gate.wait()
        return {"records": []}

    tasks = [asyncio.create_task(runtime.invoke("slow", {"id": i}, slow, scope="local")) for i in range(3)]
    try:
        await started.wait()
        with pytest.raises(ResearchError) as caught:
            await runtime.invoke("slow", {"id": 99}, slow, scope="local")
        assert caught.value.code == "provider_busy"
        assert len(runtime.flights) <= 4

        async def fast():
            return {"records": [{"id": "fast"}]}

        record, _ = await asyncio.wait_for(runtime.invoke("fast", {}, fast, scope="local"), 0.1)
        assert record["payload"]["records"][0]["id"] == "fast"
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert not runtime.flights


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get", "put"])
async def test_cache_loss_is_safe_and_never_emits_terminal_success(stage, capsys):
    runtime = ProviderRuntime()

    async def fail(*args):
        raise ConnectionError("provider-body-and-credential-sentinel")

    setattr(runtime.cache, stage, fail)

    async def call():
        return {"records": []}

    with pytest.raises(ResearchError) as caught:
        await runtime.invoke("test", {}, call, scope="local")
    assert caught.value.code == "cache_unavailable"
    assert caught.value.retryable
    assert "sentinel" not in str(caught.value)
    captured = capsys.readouterr()
    assert "error_type=None" not in captured.out + captured.err


@pytest.mark.asyncio
async def test_distributed_admission_loss_fails_closed():
    from biomedmcp.runtime import ProviderBudget

    class Redis:
        async def eval(self, *args):
            raise ConnectionError("credential-sentinel")

    with pytest.raises(ResearchError) as caught:
        await ProviderBudget(Redis()).acquire("test")
    assert caught.value.code == "provider_budget_unavailable"
    assert "sentinel" not in str(caught.value)


@pytest.mark.asyncio
async def test_composed_deadline_covers_preflight_and_resets_context(monkeypatch):
    from biomedmcp import dispatch
    from biomedmcp.runtime import operation_deadline

    monkeypatch.setattr(dispatch, "COMPOSED_TIMEOUT", 0.02)

    async def slow_prepare(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(dispatch, "prepare", slow_prepare)
    with pytest.raises(ResearchError) as caught:
        await dispatch.execute(
            object(),
            "batch",
            {"calls": [{"operation": "get", "arguments": {"entity": "gene", "id": "BRAF"}}]},
            scope="local",
        )
    assert caught.value.code == "operation_timeout"
    assert operation_deadline.get() is None


@pytest.mark.asyncio
async def test_global_pending_limit_includes_distinct_cache_reads():
    runtime = ProviderRuntime(max_pending=3)
    gate = asyncio.Event()

    async def cache_get(key):
        await gate.wait()

    runtime.cache.get = cache_get

    async def call():
        return []

    tasks = [asyncio.create_task(runtime.invoke(str(i), {}, call, scope="local")) for i in range(3)]
    try:
        for _ in range(3):
            await asyncio.sleep(0)
        with pytest.raises(ResearchError) as caught:
            await runtime.invoke("extra", {}, call, scope="local")
        assert caught.value.code == "provider_busy"
        assert caught.value.retryable
        assert len(runtime.flights) == 3
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert not runtime.flights
