"""Terminal public-boundary observations, without input or account labels."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

from .telemetry import correlation_id, identifier, payload_size, safe_error

# Operator-owned handlers avoid contaminating CLI JSON or MCP stdio streams.
logger = logging.getLogger("biomedmcp.request")
logger.propagate = False
log = structlog.wrap_logger(logger, processors=[structlog.processors.JSONRenderer()])
active_request = ContextVar("ubi_request_observation", default=None)
BOUNDARIES = frozenset({"mcp_tool", "mcp_resource", "mcp_prompt", "cli", "embedded"})
PHASES = frozenset(
    {"authentication", "dispatch", "accounting", "operation", "output_validation", "output_encoding"}
)
OUTCOMES = frozenset({"data", "empty", "partial", "unavailable", "ambiguous", "error", "completed"})


def operation_label(operation):
    from .public_catalog import MODELS
    from .utility_contracts import PROTOCOL_MODELS, UTILITY_MODELS

    allowed = {
        *MODELS,
        *UTILITY_MODELS,
        *PROTOCOL_MODELS,
        "diagnose",
        "evidence_read",
        "resource_guide",
        "resource_result_schema",
        "resource_evidence_schema",
        "resource_record_schema",
        "prompt_target_research",
    }
    return operation if isinstance(operation, str) and operation in allowed else "unknown"


class RequestMetrics:
    """Finite process-local request counts, separate from shared source flights."""

    def __init__(self):
        self.boundaries = {}

    def add(self, boundary, key, value=1):
        self.boundaries.setdefault(boundary, Counter())[key] += value

    def snapshot(self):
        return {
            "scope": "process_local_public_boundaries",
            "boundaries": {key: dict(value) for key, value in sorted(self.boundaries.items())},
        }


metrics = RequestMetrics()


class RequestObservation:
    def __init__(self, operation, boundary):
        self.operation = operation_label(operation)
        self.boundary = boundary if isinstance(boundary, str) and boundary in BOUNDARIES else "unknown"
        self.correlation_id = identifier()
        self.started = time.monotonic()
        self.durations = Counter()
        self.calls = Counter()
        self.failures = Counter()
        self.output_state = "not_constructed"
        self.outcome = "unavailable"
        self.error_type = None
        self.error_codes = []
        self.payload_bytes = None
        self.finished = False
        metrics.add(self.boundary, "started")
        metrics.add(self.boundary, "pending")

    def complete(self, value, *, output_state):
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        self.output_state = output_state
        self.payload_bytes = payload_size(value)
        outcome = value.get("outcome") if isinstance(value, dict) else None
        self.outcome = outcome if isinstance(outcome, str) and outcome in OUTCOMES else "completed"
        codes = set()
        items = value.get("results", [value]) if isinstance(value, dict) else []
        for item in items[:10] if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            sections = item.get("sections", {})
            candidates = [item, *list(sections.values())[:32]] if isinstance(sections, dict) else [item]
            for candidate in candidates:
                error = candidate.get("error") if isinstance(candidate, dict) else None
                if isinstance(error, dict):
                    codes.add(safe_error(error.get("code")))
        self.error_codes = sorted(codes)[:16]
        self.error_type = self.error_codes[0] if len(self.error_codes) == 1 else None

    def finish(self, error=None):
        if self.finished:
            return
        self.finished = True
        if error:
            self.error_type = safe_error(error)
            self.outcome = "cancelled" if error == "cancelled" else "error"
        event = {
            "boundary": self.boundary,
            "operation": self.operation,
            "correlation_id": self.correlation_id,
            "outcome": self.outcome,
            "error_type": self.error_type,
            "result_error_codes": self.error_codes,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000, 3),
            "phase_ms": {key: round(value, 3) for key, value in sorted(self.durations.items())},
            "phase_calls": dict(self.calls),
            "phase_failures": dict(self.failures),
            "phase_timing_basis": "inclusive spans; concurrent or nested durations are not additive wall time",
            "payload_bytes": self.payload_bytes,
            "payload_size_capped_or_unknown": self.payload_bytes is None,
            "output_state": self.output_state,
            "delivery_confirmed": False,
        }
        metrics.add(self.boundary, "pending", -1)
        metrics.add(self.boundary, "terminal")
        metrics.add(self.boundary, "outcome_" + self.outcome)
        metrics.add(self.boundary, "elapsed_ms", event["elapsed_ms"])
        try:
            log.info("public_request_result", **event)
        except Exception:  # noqa: BLE001 -- an operator sink cannot change scientific results
            metrics.add(self.boundary, "event_sink_failures")


@contextmanager
def request_trace(operation, boundary):
    """Nested dispatch shares the outer boundary and its generated correlation ID."""
    existing = active_request.get()
    if existing is not None:
        yield existing
        return
    observation = RequestObservation(operation, boundary)
    request_token = active_request.set(observation)
    correlation_token = correlation_id.set(observation.correlation_id)
    error = None
    try:
        yield observation
    except asyncio.CancelledError:
        error = "cancelled"
        raise
    except TimeoutError:
        error = "operation_timeout"
        raise
    except Exception as exc:
        from .errors import ResearchError

        error = exc.code if isinstance(exc, ResearchError) else "internal_error"
        raise
    finally:
        observation.finish(error)
        correlation_id.reset(correlation_token)
        active_request.reset(request_token)


@contextmanager
def phase(name):
    """Measure only fixed service phases; keep provider timings in source events."""
    observation = active_request.get()
    if observation is None or not isinstance(name, str) or name not in PHASES:
        yield
        return
    started = time.monotonic()
    observation.calls[name] += 1
    try:
        yield
    except BaseException:
        observation.failures[name] += 1
        raise
    finally:
        observation.durations[name] += (time.monotonic() - started) * 1000
