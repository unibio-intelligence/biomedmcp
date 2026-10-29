import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from biomedmcp import http_telemetry
from biomedmcp.local_boundary import AuthSettings
from biomedmcp.mcp.server import create_server

SENTINEL = "credential-query-body-sentinel"


@pytest.fixture
def events(monkeypatch):
    values = []
    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setattr(
        http_telemetry, "log", SimpleNamespace(info=lambda name, **kw: values.append({"event": name, **kw}))
    )
    monkeypatch.setattr(http_telemetry, "metrics", http_telemetry.Counter())
    return values


@pytest.mark.parametrize(
    "host,origin,status",
    [("evil.example", None, 421), ("localhost", "https://evil.example", 403), ("localhost", None, 404)],
)
async def test_outer_actual_http_rejections_are_observed_without_secrets(events, host, origin, status):
    server = create_server(service=object(), settings=AuthSettings("local", "http://localhost"))
    app = server.http_app(stateless_http=True)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client,
    ):
        headers = {"Host": host, "Authorization": "Bearer " + SENTINEL}
        if origin:
            headers["Origin"] = origin
        response = await client.get("/unknown/" + SENTINEL, params={"code": SENTINEL}, headers=headers)
    assert response.status_code == status
    assert len(events) == 1 and events[0]["status"] == status
    assert events[0]["outcome"] == "rejected" and events[0]["asgi_response_complete"]
    assert events[0]["route"] == "other" and not events[0]["client_delivery_confirmed"]
    assert SENTINEL not in json.dumps(events)


@pytest.mark.parametrize("mode", ["send_error", "cancel", "disconnect", "complete", "incomplete_trailers"])
async def test_transport_terminal_does_not_claim_delivery_or_scientific_success(events, mode):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "trailers": mode == "incomplete_trailers"})
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode == "disconnect":
            await receive()
            return
        await send({"type": "http.response.body", "body": b"abcd", "more_body": False})

    async def send(message):
        if mode == "send_error" and message["type"] == "http.response.body":
            raise RuntimeError(SENTINEL)

    async def receive():
        return {"type": "http.disconnect"}

    wrapped = http_telemetry.HTTPObservation(app)
    error = RuntimeError if mode == "send_error" else asyncio.CancelledError if mode == "cancel" else None
    if error:
        with pytest.raises(error):
            await wrapped({"type": "http", "method": "GET", "path": "/mcp"}, receive, send)
    else:
        await wrapped({"type": "http", "method": "GET", "path": "/mcp"}, receive, send)
    assert len(events) == 1 and http_telemetry.metrics["pending"] == 0
    event = events[0]
    assert (
        event["outcome"]
        == {
            "send_error": "transport_error",
            "cancel": "cancelled",
            "disconnect": "incomplete",
            "complete": "accepted",
            "incomplete_trailers": "incomplete",
        }[mode]
    )
    assert event["asgi_body_bytes_accepted"] == (4 if mode in {"complete", "incomplete_trailers"} else 0)
    assert (
        not event["client_delivery_confirmed"]
        and event["scientific_outcome"] == "not_classified_at_transport_boundary"
    )
    assert SENTINEL not in json.dumps(events)
