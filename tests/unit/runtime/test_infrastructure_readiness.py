"""Readiness proves required public Redis operations, not provider health."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.runtime import ProviderRuntime

SENTINEL = "credential-query-body-sentinel"


class Backend:
    def __init__(self, fail=None):
        self.fail, self.calls, self.values = fail, [], {}

    def record(self, operation, *args):
        self.calls.append((operation, args))
        if self.fail == operation:
            raise OSError(SENTINEL)

    async def ping(self):
        self.record("ping")
        return True

    async def set(self, key, value, **kwargs):
        self.record("set", key, kwargs)
        self.values[key] = value.encode()
        return True

    async def get(self, key):
        self.record("get", key)
        return self.values.get(key) if self.fail != "wrong_value" else b"wrong"

    async def eval(self, script, count, key, *args):
        self.record("eval", count, key, args)
        return 0 if self.fail != "wrong_script_reply" else 1


@asynccontextmanager
async def client_for(runtime):
    app = create_server(service=ResearchService(runtime=runtime)).http_app(stateless_http=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client,
    ):
        yield client


@pytest.fixture(autouse=True)
def local(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setenv("UBI_MCP_BASE_URL", "http://localhost")


@pytest.mark.parametrize("failure", ["ping", "set", "get", "eval", "wrong_value", "wrong_script_reply"])
async def test_runtime_loss_or_missing_required_redis_permission_changes_only_readiness(failure):
    backend = Backend()
    async with client_for(ProviderRuntime(redis=backend)) as client:
        assert (await client.get("/readyz")).status_code == 200
        backend.fail = failure
        ready, live = await client.get("/readyz"), await client.get("/health")
        assert ready.status_code == 503 and ready.json()["ready"] is False
        assert live.status_code == 200 and live.json()["status"] == "alive"
        assert SENTINEL not in ready.text + live.text
        backend.fail = None
        assert (await client.get("/readyz")).status_code == 200


async def test_healthy_readiness_uses_expiring_isolated_keys_and_actual_pacing_script():
    from biomedmcp.runtime import ProviderBudget

    backend = Backend()
    async with client_for(ProviderRuntime(redis=backend)) as client:
        assert (await client.get("/readyz")).status_code == 200
    assert [operation for operation, _ in backend.calls] == ["ping", "set", "get", "eval"]
    set_args = next(args for op, args in backend.calls if op == "set")
    assert set_args[0].startswith("biomedmcp:result:readiness:") and set_args[1]["ex"] <= 5
    eval_args = next(args for op, args in backend.calls if op == "eval")
    assert eval_args[0] == 1 and eval_args[1].startswith("biomedmcp:budget:readiness-")
    assert "TIME" in ProviderBudget.LUA
    assert set_args[0] != eval_args[1]


async def test_separate_cache_and_pacing_connections_are_both_required():
    from biomedmcp.runtime import ResultCache

    cache_backend, pace_backend = Backend(), Backend()
    runtime = ProviderRuntime(redis=pace_backend, cache=ResultCache(cache_backend))
    async with client_for(runtime) as client:
        assert (await client.get("/readyz")).status_code == 200
        pace_backend.fail = "eval"
        assert (await client.get("/readyz")).status_code == 503
    assert any(op == "set" for op, _ in cache_backend.calls)
    assert any(op == "eval" for op, _ in pace_backend.calls)


async def test_local_readiness_needs_no_optional_provider_or_storage_configuration(monkeypatch):
    runtime = ProviderRuntime()

    async def provider(*args):
        raise AssertionError("Readiness must not acquire source quotas or call a provider")

    monkeypatch.setattr(runtime.budget, "acquire", provider)
    async with client_for(runtime) as client:
        assert (await client.get("/readyz")).status_code == 200
        assert (await client.get("/health")).status_code == 200


async def test_slow_dependency_is_bounded_and_does_not_block_liveness():
    backend = Backend()
    started, release = asyncio.Event(), asyncio.Event()

    async def ping():
        started.set()
        await release.wait()
        return True

    backend.ping = ping
    async with client_for(ProviderRuntime(redis=backend)) as client:
        task = asyncio.create_task(client.get("/readyz"))
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert (await asyncio.wait_for(client.get("/health"), 0.2)).status_code == 200
            ready = await asyncio.wait_for(task, 1.5)
            assert ready.status_code == 503
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


async def test_runtime_probe_deadline_covers_its_own_gate_and_recovers_after_cancellation():
    from biomedmcp.errors import ResearchError

    backend = Backend()
    runtime = ProviderRuntime(redis=backend)
    await runtime._readiness_gate.acquire()
    try:
        with pytest.raises(ResearchError) as caught:
            await asyncio.wait_for(runtime.check_dependencies(), 1.5)
        assert caught.value.code == "operation_timeout" and backend.calls == []
    finally:
        runtime._readiness_gate.release()
    await runtime.check_dependencies()


async def test_concurrent_route_probes_are_serialized_and_cancellation_releases_gate():
    backend = Backend()
    original = backend.ping
    started, release = asyncio.Event(), asyncio.Event()
    running, peak = 0, 0

    async def ping():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            started.set()
            await release.wait()
            return await original()
        finally:
            running -= 1

    backend.ping = ping
    async with client_for(ProviderRuntime(redis=backend)) as client:
        first = asyncio.create_task(client.get("/readyz"))
        await asyncio.wait_for(started.wait(), 1)
        second = asyncio.create_task(client.get("/readyz"))
        await asyncio.sleep(0.01)
        assert peak == running == 1
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        assert (await second).status_code == 200
        assert (await client.get("/readyz")).status_code == 200
        assert peak == 1 and running == 0


@pytest.mark.parametrize("role", ["cache", "pacing"])
async def test_runtime_requires_only_commands_for_the_configured_role(role):
    from biomedmcp.runtime import ResultCache

    backend = Backend()
    runtime = (
        ProviderRuntime(cache=ResultCache(backend))
        if role == "cache"
        else ProviderRuntime(redis=backend, cache=ResultCache())
    )
    await runtime.check_dependencies()
    assert [op for op, _ in backend.calls] == (
        ["ping", "set", "get"] if role == "cache" else ["ping", "eval"]
    )


@pytest.fixture
def startup_app(monkeypatch):
    from types import SimpleNamespace

    from redis.asyncio import Redis

    from biomedmcp import local_boundary, transport

    def build(backend, *, dependencies=None, cleanup_failure=None, ledger_cleanup=False):
        events = []

        async def ready(settings, ledger):
            events.append("dependencies")
            if dependencies is not None:
                await dependencies()

        async def close_auth(auth):
            events.append("close_auth")
            if cleanup_failure == "auth":
                raise OSError("Auth cleanup failed")

        async def close_ledger(ledger):
            events.append("close_ledger")

        async def close_redis():
            events.append("close_redis")
            if cleanup_failure == "redis":
                raise OSError("Redis cleanup failed")

        def configure(**kwargs):
            assert kwargs["redis"] is backend
            assert [op for op, _ in backend.calls] == ["ping", "set", "get", "eval"]
            events.append("configure")

        async def shutdown():
            events.append("shutdown")
            if cleanup_failure == "transport":
                raise OSError("Transport cleanup failed")

        backend.aclose = close_redis
        monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: backend)
        monkeypatch.setattr(transport, "configure", configure)
        monkeypatch.setattr(transport, "shutdown", shutdown)
        boundary = SimpleNamespace(
            **{
                name: getattr(local_boundary, name)
                for name in (
                    "AuthSettings",
                    "build_auth",
                    "build_ledger",
                    "current_context",
                    "accounted",
                    "ServiceError",
                )
            },
            dependencies_ready=ready,
            close_auth=close_auth,
            close_ledger=close_ledger if ledger_cleanup else None,
        )
        settings = local_boundary.AuthSettings("local", "http://localhost", "redis://unused")
        app = create_server(settings=settings, boundary=boundary).http_app(stateless_http=True)
        return app, events

    return build


@pytest.mark.parametrize("failure", [None, "auth", "redis", "transport"])
async def test_ledger_cleanup_survives_other_shutdown_failures(startup_app, failure):
    app, events = startup_app(Backend(), cleanup_failure=failure, ledger_cleanup=True)
    if failure:
        with pytest.raises(OSError):
            async with app.router.lifespan_context(app):
                pass
    else:
        async with app.router.lifespan_context(app):
            pass
    assert events[-2:] == ["close_auth", "close_ledger"]
    assert events.count("close_ledger") == 1


@pytest.mark.parametrize("failure", ["ping", "set", "get", "eval", "wrong_value", "wrong_script_reply"])
async def test_failed_startup_probe_closes_dependencies_without_shutting_down_unowned_transport(
    startup_app, failure, caplog
):
    from biomedmcp.errors import ResearchError

    app, events = startup_app(Backend(failure))
    with pytest.raises(ResearchError) as caught:
        async with app.router.lifespan_context(app):
            pytest.fail("Failed dependency must prevent startup")
    assert caught.value.code in {"cache_unavailable", "provider_budget_unavailable"}
    assert events == ["dependencies", "close_redis", "close_auth"]
    assert SENTINEL not in str(caught.value) + caplog.text


async def test_startup_proves_dependencies_before_readiness_and_closes_owned_transport(startup_app):
    backend = Backend()
    app, events = startup_app(backend)
    async with app.router.lifespan_context(app):
        assert events == ["dependencies", "configure"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost"
        ) as client:
            assert (await client.get("/readyz")).status_code == 200
    assert events == ["dependencies", "configure", "dependencies", "shutdown", "close_redis", "close_auth"]


async def test_healthy_remote_dependencies_may_take_more_than_one_second_at_startup(startup_app):
    async def remote_probe():
        await asyncio.sleep(1.1)

    app, events = startup_app(Backend(), dependencies=remote_probe)
    async with app.router.lifespan_context(app):
        assert events == ["dependencies", "configure"]


async def test_healthy_remote_dependencies_may_take_more_than_one_second_for_readiness(monkeypatch):
    from biomedmcp import local_boundary

    async def remote_probe(settings, ledger):
        await asyncio.sleep(1.1)

    monkeypatch.setattr(local_boundary, "dependencies_ready", remote_probe)
    async with client_for(ProviderRuntime()) as client:
        assert (await client.get('/readyz')).status_code == 200


async def test_blocked_remote_dependency_remains_bounded_without_blocking_liveness(monkeypatch):
    from biomedmcp import local_boundary

    started = asyncio.Event()

    async def blocked(settings, ledger):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(local_boundary, "dependencies_ready", blocked)
    async with client_for(ProviderRuntime()) as client:
        probe = asyncio.create_task(client.get('/readyz'))
        await asyncio.wait_for(started.wait(), 1)
        assert (await asyncio.wait_for(client.get('/health'), 0.2)).status_code == 200
        response = await asyncio.wait_for(probe, 2.5)
        assert response.status_code == 503 and response.json()['ready'] is False


@pytest.mark.parametrize("end", ["deadline", "cancellation"])
async def test_startup_auth_dependency_deadline_and_cancellation_close_auth(startup_app, end):
    entered = asyncio.Event()

    async def blocked():
        entered.set()
        await asyncio.Event().wait()

    backend = Backend()
    app, events = startup_app(backend, dependencies=blocked)

    async def start():
        async with app.router.lifespan_context(app):
            pytest.fail("Unfinished dependency must prevent startup")

    task = asyncio.create_task(start())
    await asyncio.wait_for(entered.wait(), 1)
    if end == "cancellation":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if end == "cancellation" else TimeoutError):
        await asyncio.wait_for(task, 2.5)
    assert events == ["dependencies", "close_auth"] and not backend.calls


async def test_cancelled_startup_public_probe_releases_owned_redis_and_auth(startup_app):
    backend = Backend()
    entered = asyncio.Event()

    async def blocked():
        entered.set()
        await asyncio.Event().wait()

    backend.ping = blocked
    app, events = startup_app(backend)

    async def start():
        async with app.router.lifespan_context(app):
            pytest.fail("Unfinished probe must prevent startup")

    task = asyncio.create_task(start())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["dependencies", "close_redis", "close_auth"]


@pytest.mark.parametrize("failure", ["transport", "redis"])
async def test_startup_cleanup_releases_remaining_resources_after_close_failure(startup_app, failure):
    app, events = startup_app(Backend(), cleanup_failure=failure)
    with pytest.raises(OSError, match="cleanup failed"):
        async with app.router.lifespan_context(app):
            pass
    assert events == ["dependencies", "configure", "shutdown", "close_redis", "close_auth"]
