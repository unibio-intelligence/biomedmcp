"""Bounded operator observations; input text and caller identities are never labels."""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from functools import lru_cache

correlation_id = ContextVar("ubi_correlation_id", default=None)
active_observation = ContextVar("ubi_source_observation", default=None)

# Only implementation-owned error codes may reach logs or metric labels.
# Unknown exception classes/codes are deliberately represented as internal_error.
ERROR_CODES = frozenset(
    [
        "evidence_invalid_data",
        "evidence_resource_budget",
        "evidence_timeout",
        "evidence_unavailable",
        "output_metadata_budget",
        "source_contract_changed",
        "access_denied",
        "deadline_exceeded",
        "expired_token",
        "idempotency_conflict",
        "invalid_idempotency_key",
        "invalid_resource",
        "quota_exceeded",
        "accounting_unresolved",
        "replay_denied",
        "request_failed",
        "replay_expired",
        "request_in_progress",
        "reservation_owner",
        "reservation_reconciled",
        "unauthenticated",
        "adapter_not_installed",
        "adapter_schema_changed",
        "ambiguous_gene",
        "ambiguous_identifier",
        "ambiguous_source",
        "authentication_failed",
        "cache_invalid_data",
        "cache_unavailable",
        "cancelled",
        "canonical_route_required",
        "chart_unavailable",
        "diagnosis_unavailable",
        "duplicate_section",
        "expired_cursor",
        "identity_mismatch",
        "inconsistent_provider_page",
        "internal_error",
        "invalid_adapter_schema",
        "invalid_assembly",
        "invalid_cursor",
        "invalid_identifier",
        "invalid_output",
        "invalid_parameters",
        "invalid_probe",
        "invalid_request",
        "invalid_sequence",
        "invalid_source_response",
        "invalid_study",
        "invalid_study_manifest",
        "local_io_error",
        "local_state_unavailable",
        "local_state_unsafe",
        "local_state_version",
        "missing_cohort",
        "missing_tissue",
        "normalization_required",
        "operation_timeout",
        "provider_budget_unavailable",
        "provider_busy",
        "remote_unavailable",
        "response_too_large",
        "source_access_denied",
        "source_authentication_failed",
        "source_connection_rejected",
        "source_not_found",
        "source_plan_conflict",
        "source_rate_limited",
        "source_restricted",
        "source_timeout",
        "source_unavailable",
        "source_url_rejected",
        "study_assay_unavailable",
        "study_budget_exceeded",
        "study_data_unavailable",
        "study_gene_unavailable",
        "study_measurements_unavailable",
        "study_not_ready",
        "study_unavailable",
        "study_version_changed",
        "unbounded_sections",
        "unknown_operation",
        "unknown_relation",
        "unknown_section",
        "unknown_source",
        "unknown_workflow",
        "unresolved_identity",
        "unsupported_assembly",
        "unsupported_cursor",
        "unsupported_filter",
        "unsupported_get",
        "unsupported_measurement_units",
        "unsupported_release",
        "unsupported_search",
        "unsupported_section_parameters",
        "unsupported_source",
        "unsupported_species",
        "unsupported_version_pin",
        "unused_source",
        "upstream_error",
    ]
)


@lru_cache(maxsize=1)
def labels():
    # Lazy imports avoid the adapter/runtime/evidence import cycle.
    from .extensions import MODELS
    from .native.catalog import ADVANCED, SECTIONS
    from .source_policy import source_names

    operations = {"search", "get", "relate", "gene_identity", "taxonomy_identity", "get:record"}
    operations.update(op for ops in ADVANCED.values() for op in ops)
    operations.update(op for ops in MODELS.values() for op in ops)
    operations.update("get:" + section for sections in SECTIONS.values() for section in sections)
    return frozenset([*source_names(), "ncbi", "article-content"]), frozenset(operations)


def safe_labels(source, params):
    sources, operations = labels()
    operation = params.get("operation") if isinstance(params, dict) else None
    return (
        source if isinstance(source, str) and source in sources else "unknown",
        operation if isinstance(operation, str) and operation in operations else "unknown",
    )


def safe_error(code):
    return code if isinstance(code, str) and code in ERROR_CODES else "internal_error"


def identifier():
    return uuid.uuid4().hex


def payload_size(value):
    """Exact compact JSON bytes up to 1 MiB; larger/unencodable values are unknown."""
    total = 0
    try:
        for chunk in json.JSONEncoder(
            ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str
        ).iterencode(value):
            total += len(chunk.encode())
            if total > 1_000_000:
                return None
    except (ValueError, TypeError, RecursionError):
        return None
    return total


class RuntimeMetrics:
    """Process-local counters/gauges with a finite source-label vocabulary."""

    def __init__(self):
        self.sources = {}

    def add(self, source, key, value=1):
        counters = self.sources.setdefault(source, Counter())
        counters[key] += value

    def snapshot(self):
        return {
            "scope": "process_local_logical_source_flights",
            "sources": {source: dict(values) for source, values in sorted(self.sources.items())},
        }


class Observation:
    def __init__(self, metrics, source, params):
        self.metrics = metrics
        self.source, self.operation = safe_labels(source, params)
        self.correlation_id = correlation_id.get() or identifier()
        self.flight_id = identifier()
        self.started = self.stage_started = time.monotonic()
        self.stage = "scheduler"
        self.durations = Counter()
        self.cache_state = "miss"
        self.outcome = "unavailable"
        self.payload_bytes = None
        self.coalesced_waiters = 0
        self.rate_wait_ms = 0.0
        self.http_429 = 0
        self.http_timeout_attempts = 0
        self.admitted = False
        self.finished = False
        self.terminal_event = None

    def enter(self, stage):
        now = time.monotonic()
        self.durations[self.stage] += (now - self.stage_started) * 1000
        self.stage, self.stage_started = stage, now

    def start(self):
        self.admitted = True
        self.metrics.add(self.source, "pending")
        self.metrics.add(self.source, "flights_started")

    def fields(self, error=None):
        self.enter(self.stage)
        if error:
            self.outcome = "cancelled" if error == "cancelled" else "unavailable"
        return {
            "source": self.source,
            "operation": self.operation,
            "correlation_id": self.correlation_id,
            "flight_id": self.flight_id,
            "cache_hit": self.cache_state == "hit",
            "cache_state": self.cache_state,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000, 3),
            "queue_ms": round(self.durations["admission"], 3),
            "scheduler_ms": round(self.durations["scheduler"], 3),
            "execution_ms": round(self.durations["provider"], 3),
            "cache_read_ms": round(self.durations["cache_read"], 3),
            "cache_write_ms": round(self.durations["cache_write"], 3),
            "classification_ms": round(self.durations["classification"], 3),
            "rate_wait_ms": round(self.rate_wait_ms, 3),
            "http_429": self.http_429,
            "http_timeout_attempts": self.http_timeout_attempts,
            "coalesced_waiters": self.coalesced_waiters,
            "payload_bytes": self.payload_bytes,
            "payload_size_capped_or_unknown": self.payload_bytes is None,
            "error_type": error,
            "outcome": self.outcome,
            "stage": self.stage,
        }

    def finish(self, error=None):
        if self.finished:
            return self.terminal_event
        self.finished = True
        error = safe_error(error) if error else None
        event = self.fields(error)
        self.terminal_event = event
        if self.admitted:
            self.metrics.add(self.source, "pending", -1)
        self.metrics.add(self.source, "terminal_flights")
        self.metrics.add(self.source, "outcome_" + self.outcome)
        if self.cache_state in {"read_failed", "write_failed"}:
            self.metrics.add(self.source, "cache_failures")
        if self.cache_state == "hit":
            self.metrics.add(self.source, "cache_hits")
        if error in {"operation_timeout", "source_timeout"}:
            self.metrics.add(self.source, "timeouts")
        if error == "provider_busy":
            self.metrics.add(self.source, "rejected")
        if error == "source_rate_limited":
            self.metrics.add(self.source, "rate_limited_failures")
        self.metrics.add(self.source, "http_429", self.http_429)
        self.metrics.add(self.source, "http_timeout_attempts", self.http_timeout_attempts)
        self.metrics.add(self.source, "rate_wait_ms", self.rate_wait_ms)
        for name in ["queue_ms", "execution_ms", "cache_read_ms", "cache_write_ms"]:
            self.metrics.add(self.source, name, event[name])
        return event
