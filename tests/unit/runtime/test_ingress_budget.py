"""Admission, slow-body and maximum public batch contracts."""

import asyncio

import pytest

from biomedmcp.mcp.http_security import RequestBudget

SCOPE = {"type": "http", "method": "POST", "headers": [(b"content-type", b"application/json")]}


async def ignore_app(scope, receive, send):
    await receive()


@pytest.mark.asyncio
async def test_overloaded_ingress_rejects_without_reading_and_recovers_after_cancel():
    budget = RequestBudget(ignore_app, max_active=2)
    gate = asyncio.Event()
    started = 0
    entered = asyncio.Event()

    async def blocked():
        nonlocal started
        started += 1
        if started == 2:
            entered.set()
        await gate.wait()

    async def send(message):
        pass

    tasks = [asyncio.create_task(budget(SCOPE, blocked, send)) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        responses = []

        async def forbidden_read():
            pytest.fail("Overloaded admission read the submitted body")

        async def capture(message):
            responses.append(message)

        await asyncio.wait_for(budget(SCOPE, forbidden_read, capture), 1)
        assert responses[0]["status"] == 503
        assert b"request_capacity_exceeded" in responses[1]["body"]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert budget.active == 0

    async def complete():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    await budget(SCOPE, complete, send)
    assert budget.active == 0


@pytest.mark.asyncio
async def test_slow_body_deadline_covers_all_chunks_and_does_not_echo_input():
    budget = RequestBudget(ignore_app, body_timeout=0.02)
    responses = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"credential-sentinel", "more_body": True}
        await asyncio.Event().wait()

    async def send(message):
        responses.append(message)

    await asyncio.wait_for(budget(SCOPE, receive, send), 0.2)
    assert responses[0]["status"] == 408
    assert b"request_body_timeout" in responses[1]["body"]
    assert b"credential-sentinel" not in responses[1]["body"]
    assert budget.active == 0


@pytest.mark.asyncio
async def test_admission_is_held_until_application_finishes_but_body_deadline_is_not():
    body_read = asyncio.Event()
    finish = asyncio.Event()

    async def app(scope, receive, send):
        assert (await receive())["body"] == b"{}"
        body_read.set()
        await finish.wait()

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    responses = []

    async def send(message):
        responses.append(message)

    budget = RequestBudget(app, max_active=1, body_timeout=0.01)
    task = asyncio.create_task(budget(SCOPE, receive, send))
    try:
        await body_read.wait()
        await asyncio.sleep(0.02)
        assert not task.done()
        await budget(SCOPE, receive, send)
        assert responses[0]["status"] == 503
        finish.set()
        await task
        assert budget.active == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["disconnect", "app_error"])
async def test_admission_is_released_on_disconnect_and_application_failure(case):
    async def app(scope, receive, send):
        raise RuntimeError("internal fixture failure")

    async def receive():
        return (
            {"type": "http.disconnect"} if case == "disconnect" else {"type": "http.request", "body": b"{}"}
        )

    budget = RequestBudget(app)

    async def send(message):
        pass

    if case == "app_error":
        with pytest.raises(RuntimeError):
            await budget(SCOPE, receive, send)
    else:
        await budget(SCOPE, receive, send)
    assert budget.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("chunked", [False, True])
async def test_actual_mcp_maximum_batch_and_http_budget_boundary(monkeypatch, chunked):
    import httpx
    from ingress_helpers import assert_batch, create_app, maximum_batch

    from biomedmcp.mcp.http_security import REQUEST_BYTES

    monkeypatch.setenv("UBI_PROFILE", "local")
    app, provider = create_app()
    raw = maximum_batch()
    assert len(raw) == REQUEST_BYTES

    async def chunks(body):
        for start in range(0, len(body), 8192):
            yield body[start : start + 8192]

    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-11-25",
    }
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client,
    ):
        good = await client.post("/mcp", content=chunks(raw) if chunked else raw, headers=headers)
        assert good.status_code == 200
        assert_batch(good.json())
        assert provider.calls == 10
        too_large = await client.post(
            "/mcp", content=chunks(raw + b" ") if chunked else raw + b" ", headers=headers
        )
        assert too_large.status_code == 413
        assert provider.calls == 10
        bad_item = raw.replace(b"A" * 256, b"A" * 257, 1).rstrip()
        invalid = await client.post("/mcp", content=bad_item, headers=headers)
        assert invalid.status_code == 200 and invalid.json()["result"]["isError"]
        assert invalid.json()["result"]["structuredContent"]["error"]["code"] == "invalid_parameters"
        assert provider.calls == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplied,expected",
    [
        (None, 128),
        ({"limit_concurrency": None}, 128),
        ({"limit_concurrency": 8}, 8),
        ({"limit_concurrency": 256, "access_log": False}, 128),
    ],
)
async def test_builtin_local_and_hosted_http_runner_cannot_disable_connection_bound(
    monkeypatch, supplied, expected
):
    from fastmcp import FastMCP

    from biomedmcp.mcp.server import create_server

    captured = {}

    async def run(self, *args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(FastMCP, "run_http_async", run)
    monkeypatch.setenv("UBI_PROFILE", "local")
    server = create_server(service=object())
    await server.run_http_async(uvicorn_config=supplied)
    assert captured["uvicorn_config"]["limit_concurrency"] == expected


@pytest.mark.parametrize(
    "arguments",
    [
        {"max_active": 0},
        {"max_active": True},
        {"body_timeout": 0},
        {"body_timeout": float("inf")},
        {"body_timeout": float("nan")},
    ],
)
def test_ingress_bound_configuration_cannot_be_invalid(arguments):
    with pytest.raises(ValueError):
        RequestBudget(ignore_app, **arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media", [b"application/json ; charset=utf-8", b"text/plain, application/json", b"application/json"]
)
async def test_every_sdk_admitted_json_media_type_has_a_depth_guard(media):
    body = b"[" * 33 + b"]" * 33
    responses = []

    async def app(scope, receive, send):
        pytest.fail("Deep JSON reached the SDK parser")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        responses.append(message)

    await RequestBudget(app)({**SCOPE, "headers": [(b"content-type", media)]}, receive, send)
    assert responses[0]["status"] == 400
    assert b"request_too_deep" in responses[1]["body"]
