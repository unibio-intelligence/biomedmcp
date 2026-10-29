"""Bounded cache, opaque cursors and provider operation budgets."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog
from redis.exceptions import RedisError

from .errors import ResearchError
from .telemetry import (
    Observation,
    RuntimeMetrics,
    active_observation,
    correlation_id,
    identifier,
    payload_size,
    safe_error,
)

log = structlog.get_logger(__name__)
operation_deadline = ContextVar("ubi_operation_deadline", default=None)
_anonymous_pagination = ContextVar("biomedmcp_anonymous_pagination", default=None)


@contextmanager
def anonymous_pagination(*, scope: str, resource: str):
    """Trusted hosting opt-in for query-bound public continuation capabilities.

    The cursor grants one query's public continuation, not the original guest
    identity. Evidence snapshots, account data and personal keys keep their own
    scopes. Never infer this context from client metadata, parameters or IPs.
    """
    token = _anonymous_pagination.set((scope, resource))
    try:
        yield
    finally:
        _anonymous_pagination.reset(token)


def remaining_budget(default: float) -> float:
    deadline = operation_deadline.get()
    return default if deadline is None else max(0.001, min(default, deadline - time.monotonic()))


def public_continuation_resource(scope):
    """Return the trusted public resource only for a credential-free guest request."""
    from .provider_credentials import active_credentials

    context = _anonymous_pagination.get()
    if (
        context is not None
        and context[0] == scope
        and scope.startswith("anonymous:")
        and active_credentials.get() is None
    ):
        return context[1]
    return None


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


class CursorCodec:
    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("Cursor signing key must have at least 32 bytes")
        self.key = key

    @staticmethod
    def scope_hash(scope):
        resource = public_continuation_resource(scope)
        if resource is not None:
            return digest({"public_query_continuation": 1, "resource": resource})
        return digest(scope)

    def encode(self, *, query: Any, scope: str, offset: int) -> str:
        payload = json.dumps(
            {
                "q": digest(query),
                "s": self.scope_hash(scope),
                "o": offset,
                "e": int(time.time()) + 3600,
                "n": os.urandom(16).hex(),
            },
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self.key, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def decode(self, cursor: str, *, query: Any, scope: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            signature, payload = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.new(self.key, payload, hashlib.sha256).digest()):
                raise ValueError("signature")
            value = json.loads(payload)
            if (
                value["q"] != digest(query)
                or value["s"] not in {digest(scope), self.scope_hash(scope)}
                or value["e"] < time.time()
                or not 0 <= value["o"] <= 1000
            ):
                raise ValueError("scope")
            return int(value["o"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ResearchError(
                "invalid_cursor", "Cursor is invalid, expired, or belongs to a different query/account."
            ) from exc


class ResultCache:
    def __init__(self, redis=None, *, max_entries: int = 256):
        self.redis = redis
        self.max_entries = max_entries
        self.values: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def get(self, key: str) -> Any | None:
        from .provider_credentials import cache_key

        key = cache_key(key)
        if self.redis:
            try:
                value = await self.redis.get("biomedmcp:result:" + key)
            except (RedisError, OSError):
                raise ResearchError(
                    "cache_unavailable", "The result cache is unavailable; retry later.", retryable=True
                ) from None
            if value is None:
                return None

            def reject_constant(_value):
                raise ValueError("Nonfinite cached value")

            def finite_float(value):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("Nonfinite cached value")
                return number

            try:
                return json.loads(value, parse_constant=reject_constant, parse_float=finite_float)
            except (ValueError, TypeError):
                raise ResearchError(
                    "cache_invalid_data", "Stored result data are invalid; refresh or restart the request."
                ) from None
        value = self.values.get(key)
        if value and value[0] > time.monotonic():
            self.values.move_to_end(key)
            return json.loads(json.dumps(value[1]))
        self.values.pop(key, None)
        return None

    async def put(self, key: str, value: Any, ttl: int):
        from .provider_credentials import cache_key

        key = cache_key(key)
        encoded = json.dumps(value, allow_nan=False, default=str)
        if len(encoded.encode()) > 1_000_000:
            return False
        if self.redis:
            try:
                await self.redis.set("biomedmcp:result:" + key, encoded, ex=ttl)
            except (RedisError, OSError):
                raise ResearchError(
                    "cache_unavailable", "The result cache is unavailable; retry later.", retryable=True
                ) from None
        else:
            self.values[key] = (time.monotonic() + ttl, json.loads(encoded))
            self.values.move_to_end(key)
            while len(self.values) > self.max_entries:
                self.values.popitem(last=False)
        return True


class ProviderBudget:
    """Distributed pacing for a shared provider credential pool.

    Atomic Redis admission limits all replicas; local mode uses the same policy
    in memory. Caller identity is deliberately not part of a provider quota key.
    """

    LUA = """
local clock=redis.call("TIME"); local now=tonumber(clock[1])*1000+math.floor(tonumber(clock[2])/1000); local interval=tonumber(ARGV[2])
local next=tonumber(redis.call('GET',KEYS[1]) or '0')
if next>now then return next-now end
redis.call('SET',KEYS[1],now+interval,'PX',math.max(interval*2,1000))
return 0
"""

    def __init__(self, redis=None):
        self.redis = redis
        self.next: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self.parallel = asyncio.Semaphore(8)

    async def acquire(self, source: str, *, requests_per_second: float = 3):
        interval = 1 / requests_per_second
        deadline = time.monotonic() + remaining_budget(20)
        while True:
            if self.redis:
                try:
                    async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                        wait = await self.redis.eval(
                            self.LUA,
                            1,
                            "biomedmcp:budget:" + source,
                            int(time.time() * 1000),
                            int(interval * 1000),
                        )
                except Exception:  # noqa: BLE001 -- fail closed on distributed admission loss
                    raise ResearchError(
                        "provider_budget_unavailable",
                        "Shared provider admission is unavailable; retry later.",
                        retryable=True,
                    ) from None
                wait = float(wait) / 1000
            else:
                async with self.lock:
                    now = time.monotonic()
                    wait = max(0, self.next.get(source, 0) - now)
                    if wait == 0:
                        self.next[source] = now + interval
            if wait <= 0:
                return
            if time.monotonic() + wait > deadline:
                raise ResearchError(
                    "provider_busy", "The shared provider budget is busy; retry later.", retryable=True
                )
            observation = active_observation.get()
            started = time.monotonic()
            if observation:
                observation.metrics.add(observation.source, "rate_waiting")
            try:
                await asyncio.sleep(min(wait, 1))
            finally:
                if observation:
                    observation.rate_wait_ms += (time.monotonic() - started) * 1000
                    observation.metrics.add(observation.source, "rate_waiting", -1)


class ProviderRuntime:
    def __init__(
        self,
        *,
        redis=None,
        cache=None,
        cursor_key: bytes | None = None,
        operation_timeout=50,
        max_pending=64,
        max_source_pending=16,
        source_concurrency=2,
    ):
        if min(operation_timeout, max_pending, max_source_pending, source_concurrency) <= 0:
            raise ValueError("Runtime deadlines and admission limits must be positive.")
        self.flights = {}
        self.metrics = RuntimeMetrics()
        self.observations = {}
        self.flight_sources = {}
        self.source_slots = {}
        self.operation_timeout = operation_timeout
        self.max_pending = max_pending
        self.max_source_pending = max_source_pending
        self.source_concurrency = source_concurrency
        self.cache = cache if cache is not None else ResultCache(redis)
        self.budget = ProviderBudget(redis)
        key = cursor_key or os.getenv("UBI_CURSOR_KEY", "").encode()
        if not key:
            key = os.urandom(32)
        self.cursors = CursorCodec(key)
        self._readiness_gate = asyncio.Lock()

    async def check_dependencies(self):
        """Prove required cache/pacing commands on isolated expiring probe keys."""
        try:
            async with asyncio.timeout(1), self._readiness_gate:
                await self._check_dependencies()
        except TimeoutError:
            raise ResearchError(
                "operation_timeout",
                "Required public runtime readiness exceeded its deadline.",
                retryable=True,
            ) from None

    async def _check_dependencies(self):
        cache_backend = getattr(self.cache, "redis", None)
        pacing_backend = self.budget.redis
        checked = set()
        for backend in (cache_backend, pacing_backend):
            if backend is None or id(backend) in checked:
                continue
            try:
                if await backend.ping() is not True:
                    raise ValueError("Unexpected dependency reply")
            except (RedisError, OSError, TypeError, ValueError):
                raise ResearchError(
                    "cache_unavailable" if backend is cache_backend else "provider_budget_unavailable",
                    "A required public runtime dependency is unavailable.",
                    retryable=True,
                ) from None
            checked.add(id(backend))
        if cache_backend is not None:
            key = "biomedmcp:result:readiness:" + identifier()
            value = json.dumps({"probe": identifier()}, separators=(",", ":"))
            try:
                if await cache_backend.set(key, value, ex=2) is not True:
                    raise ValueError("Unexpected dependency reply")
                stored = await cache_backend.get(key)
                if stored not in (value, value.encode()):
                    raise ValueError("Unexpected dependency reply")
            except (RedisError, OSError, TypeError, ValueError):
                raise ResearchError(
                    "cache_unavailable",
                    "Required public cache operations are unavailable.",
                    retryable=True,
                ) from None
        if pacing_backend is not None:
            try:
                value = await pacing_backend.eval(
                    ProviderBudget.LUA, 1, "biomedmcp:budget:readiness-" + identifier(), 0, 1
                )
                if type(value) is not int or value != 0:
                    raise ValueError("Unexpected dependency reply")
            except (RedisError, OSError, TypeError, ValueError):
                raise ResearchError(
                    "provider_budget_unavailable",
                    "Required public pacing operations are unavailable.",
                    retryable=True,
                ) from None

    async def invoke(
        self,
        source: str,
        params: Any,
        call: Callable[[], Awaitable[Any]],
        *,
        scope: str,
        freshness: str = "cached_if_fresh",
        ttl: int | None = None,
    ):
        from .receipts import observe_source

        observe_source(source)
        if ttl is None:
            ttl = (
                1800
                if any(part in source for part in ("trial", "openfda", "adverse"))
                else 86400
                if source in {"gtex", "ensembl", "uniprot", "alphamissense", "eve"}
                else 3600
            )
        from .provider_credentials import coalescing_scope

        cache_scope = scope
        public_resource = public_continuation_resource(scope)
        if (
            public_resource is not None
            and isinstance(params, dict)
            and (source, params.get("operation"))
            in {("alphamissense", "get:predictions"), ("eve", "get:eve")}
        ):
            # Only trusted, credential-free public predictor acquisition shares
            # cache/admission. Snapshots, cursors and accounting retain caller scope.
            cache_scope = "public-predictors-v1:" + digest(public_resource)
        key = digest({"source": source, "params": params, "scope": coalescing_scope(cache_scope)})
        flight_key = key + ":" + freshness
        caller_id = correlation_id.get() or identifier()
        coalesced = flight_key in self.flights
        observation = self.observations.get(flight_key)
        if flight_key not in self.flights:
            observation = Observation(self.metrics, source, params)
            observation.correlation_id = caller_id
            if (
                len(self.flights) >= self.max_pending
                or list(self.flight_sources.values()).count(source) >= self.max_source_pending
            ):
                observation.enter("admission")
                log.info("provider_result", **observation.finish("provider_busy"))
                raise ResearchError(
                    "provider_busy", "Provider admission is full; retry later.", retryable=True
                )
            slots = self.source_slots.setdefault(source, asyncio.Semaphore(self.source_concurrency))

            async def fetch():
                from .evidence import scientific_outcome

                error, stage = None, "cache_read"
                deadline = time.monotonic() + remaining_budget(self.operation_timeout)
                token = operation_deadline.set(deadline)
                observation_token = active_observation.set(observation)
                observation.enter("cache_read")
                try:
                    async with asyncio.timeout_at(deadline):
                        if freshness != "fresh":
                            cached = await self.cache.get(key)
                            if cached is not None:
                                observation.cache_state = "hit"
                                observation.enter("classification")
                                observation.outcome = scientific_outcome(cached["payload"])
                                observation.payload_bytes = payload_size(cached["payload"])
                                return cached, True
                        else:
                            observation.cache_state = "bypassed"
                        stage = "admission"
                        observation.enter(stage)
                        # Acquire source capacity first: queued requests for one
                        # source must not occupy the global execution permits.
                        async with slots, self.budget.parallel:
                            stage = "provider"
                            observation.enter(stage)
                            value = await call()
                        stage = "classification"
                        observation.enter(stage)
                        if isinstance(value, dict) and (value.get("error") or value.get("success") is False):
                            raise ResearchError(
                                "upstream_error",
                                "The source could not complete the operation.",
                                retryable=True,
                            )
                        record = {"payload": value, "retrieved_at": time.time()}
                        statuses = value.get("section_outcomes", {}) if isinstance(value, dict) else {}
                        if not isinstance(statuses, dict):
                            raise ResearchError(
                                "invalid_source_response", "Source section status metadata is malformed."
                            )
                        outcomes = [
                            (status.get("outcome") if isinstance(status, dict) else status)
                            for status in statuses.values()
                        ]
                        if any(outcome is not None and not isinstance(outcome, str) for outcome in outcomes):
                            raise ResearchError(
                                "invalid_source_response", "Source section status metadata is malformed."
                            )
                        failed_section = any(
                            outcome in {"error", "unavailable", "failed", "timeout", "partial", "degraded"}
                            for outcome in outcomes
                        )
                        observation.outcome = scientific_outcome(value)
                        observation.payload_bytes = payload_size(value)
                        if not failed_section:
                            stage = "cache_write"
                            observation.enter(stage)
                            stored = await self.cache.put(key, record, ttl)
                            observation.cache_state = "stored" if stored is not False else "write_skipped"
                        else:
                            observation.cache_state = "scientific_failure_not_cached"
                        return record, False
                except TimeoutError:
                    error = "operation_timeout"
                    raise ResearchError(
                        "operation_timeout",
                        "The end-to-end source deadline elapsed; no absence can be inferred.",
                        retryable=True,
                    ) from None
                except BaseException as exc:
                    if (
                        isinstance(exc, Exception)
                        and stage in {"cache_read", "cache_write"}
                        and not isinstance(exc, ResearchError)
                    ):
                        error = "cache_unavailable"
                        raise ResearchError(
                            error, "The result cache is unavailable; retry later.", retryable=True
                        ) from None
                    error = (
                        exc.code
                        if isinstance(exc, ResearchError)
                        else "cancelled"
                        if isinstance(exc, asyncio.CancelledError)
                        else "internal_error"
                    )
                    raise
                finally:
                    operation_deadline.reset(token)
                    active_observation.reset(observation_token)
                    if error and stage in {"cache_read", "cache_write"}:
                        observation.cache_state = "read_failed" if stage == "cache_read" else "write_failed"
                    log.info("provider_result", **observation.finish(error))

            self.observations[flight_key] = observation
            observation.start()
            self.flights[flight_key] = [asyncio.create_task(fetch()), 0]
            self.flight_sources[flight_key] = source

            def cleanup(task):
                if not observation.finished:
                    observation.cache_state = "not_started"
                    log.info("provider_result", **observation.finish("cancelled"))
                entry = self.flights.get(flight_key)
                if entry is not None and entry[0] is task and entry[1] == 0:
                    self._remove_flight(flight_key)
                # Consume an abandoned task's exception without logging its text.
                if not task.cancelled():
                    task.exception()

            self.flights[flight_key][0].add_done_callback(cleanup)
        entry = self.flights[flight_key]
        if entry[0].cancelling():
            rejection = Observation(self.metrics, source, params)
            rejection.correlation_id = caller_id
            rejection.enter("admission")
            log.info("provider_result", **rejection.finish("provider_busy"))
            raise ResearchError(
                "provider_busy", "An abandoned operation is shutting down; retry later.", retryable=True
            )
        entry[1] += 1
        if coalesced:
            observation.coalesced_waiters += 1
            self.metrics.add(observation.source, "coalesced_waiters")
        waiter_started, waiter_error = time.monotonic(), None
        try:
            # Each coalesced caller retains its own remaining request budget.
            async with asyncio.timeout(remaining_budget(self.operation_timeout)):
                return await asyncio.shield(entry[0])
        except TimeoutError:
            waiter_error = "operation_timeout"
            self.metrics.add(observation.source, "waiter_timeouts")
            raise ResearchError(
                "operation_timeout",
                "The end-to-end source deadline elapsed; no absence can be inferred.",
                retryable=True,
            ) from None
        except BaseException as exc:
            waiter_error = (
                safe_error(exc.code)
                if isinstance(exc, ResearchError)
                else "cancelled"
                if isinstance(exc, asyncio.CancelledError)
                else "internal_error"
            )
            if isinstance(exc, asyncio.CancelledError):
                self.metrics.add(observation.source, "waiter_cancellations")
            raise
        finally:
            log.info(
                "provider_waiter",
                source=observation.source,
                operation=observation.operation,
                correlation_id=caller_id,
                flight_id=observation.flight_id,
                coalesced=coalesced,
                elapsed_ms=round((time.monotonic() - waiter_started) * 1000, 3),
                outcome="cancelled"
                if waiter_error == "cancelled"
                else "unavailable"
                if waiter_error
                else observation.outcome,
                error_type=waiter_error,
            )
            entry[1] -= 1
            if entry[1] == 0:
                if entry[0].done():
                    self._remove_flight(flight_key)
                else:
                    entry[0].cancel()

    def _remove_flight(self, key):
        self.flights.pop(key, None)
        self.observations.pop(key, None)
        source = self.flight_sources.pop(key, None)
        if source not in self.flight_sources.values():
            self.source_slots.pop(source, None)
