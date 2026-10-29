"""Bounded HTTP terminal observations; ASGI acceptance is not client delivery."""

import asyncio
import logging
import time
from collections import Counter

import structlog

from .telemetry import identifier

logger = logging.getLogger("biomedmcp.http")
logger.propagate = False
log = structlog.wrap_logger(logger, processors=[structlog.processors.JSONRenderer()])
metrics = Counter()


def route_label(path):
    if path in {"/mcp", "/mcp/"}:
        return "mcp"
    if path in {"/readyz", "/health"}:
        return "readiness" if path == "/readyz" else "liveness"
    if path.startswith("/.well-known/"):
        return "metadata"
    if path in {"/authorize", "/token", "/register", "/revoke", "/oauth/callback"}:
        return "authentication"
    if path.startswith("/consent"):
        return "consent"
    return "other"


class HTTPObservation:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status, body_bytes, completed, disconnected, error = None, 0, False, False, None
        expects_trailers = False
        metrics["pending"] += 1

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            disconnected |= message["type"] == "http.disconnect"
            return message

        async def observed_send(message):
            nonlocal status, body_bytes, completed, expects_trailers
            # Update only after the underlying ASGI send accepts this frame.
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
                expects_trailers = message.get("trailers", False)
            elif message["type"] == "http.response.body":
                body_bytes += len(message.get("body", b""))
                completed = not message.get("more_body", False) and not expects_trailers
            elif message["type"] == "http.response.trailers":
                completed = not message.get("more_trailers", False)

        try:
            await self.app(scope, observed_receive, observed_send)
        except asyncio.CancelledError:
            error = "cancelled"
            raise
        except Exception:
            error = "transport_error"
            raise
        finally:
            metrics["pending"] -= 1
            metrics["terminal"] += 1
            category = (
                "cancelled"
                if error == "cancelled"
                else "transport_error"
                if error
                else "incomplete"
                if not completed
                else "server_error"
                if status >= 500
                else "rejected"
                if status >= 400
                else "accepted"
            )
            metrics["outcome_" + category] += 1
            event = {
                "correlation_id": identifier(),
                "route": route_label(scope.get("path", "")),
                "method": scope.get("method")
                if scope.get("method") in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
                else "other",
                "status": status,
                "outcome": category,
                "error_type": error,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "asgi_body_bytes_accepted": body_bytes,
                "asgi_response_complete": completed,
                "disconnect_observed": disconnected,
                "client_delivery_confirmed": False,
                "scientific_outcome": "not_classified_at_transport_boundary",
            }
            try:
                log.info("http_request_result", **event)
            except Exception:  # noqa: BLE001 -- logging cannot change a response
                metrics["event_sink_failures"] += 1
