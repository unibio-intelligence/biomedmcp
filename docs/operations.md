# Operations

This document describes how to check that a deployment works, which request limits the HTTP applications enforce, and how provider requests are retried.

## Qualification and live observations

Being configured, loading correctly, passing offline tests and working live are separate checks. `biomedmcp diagnose` reports those states independently without contacting providers. `get_capabilities` reports `health: "not_probed"`. Passing one check does not imply the others.

The distributed public test suite covers canonical dispatch, provider failure handling, identity, provenance, pagination, study missingness and example execution with synthetic evidence. [Adapter inventory tests](../tests/unit/adapters/test_adapter_inventory.py) check retained imports and every declared advanced operation. Endpoint-specific fixtures cover selected scientific provider contracts. Their exact scope is reported in the bundled offline qualification evidence when that evidence matches the installed implementation and dependencies. Missing or stale evidence is reported explicitly.

This release does not claim that every provider route currently works live, or that it is ready for every model or client. The [capability matrix](capability-readiness.json) retains those limitations and references only files supplied in the public export.

Live canary checks run separately and require operator authorization: `UBI_PROFILE=local uv run --frozen python scripts/live-canary.py --output /tmp/ubi-live.json`. `--validate-only` checks definitions without provider reads and never qualifies live health. Reports identify implementation, retrieval time, declared/participating sources, status and result/provenance hashes. A failed probe does not mean the evidence is absent. Review provider terms and configuration before running live checks.

An operator may point `UBI_PUBLIC_LIVE_QUALIFICATION` at a sanitized canary report. Diagnosis reads that receipt without running a probe. Only matching current definitions/implementation, successful executed source observations and timestamps within 24 hours qualify a recent observation. Stale, malformed, definition-only, mismatched or failed receipts remain distinct. The receipt is a point-in-time snapshot, not proof of current health.

## HTTP request budgets

Local and hosted HTTP applications enforce the same limits before Model Context Protocol (MCP) JSON parsing:

| Limit | Value | Failure |
| --- | --- | --- |
| Request body, including UTF-8 encoding and JSON framing | 65,536 bytes | HTTP 413 `request_too_large` |
| JSON container depth | 32 | HTTP 400 `request_too_deep` |
| Active POST/PUT/PATCH requests per worker | 32 | HTTP 503 `request_capacity_exceeded`, `Retry-After: 1` |
| Time to read the complete body | 10 seconds | HTTP 408 `request_body_timeout` |
| Built-in HTTP server connections/tasks per worker | 128 | HTTP 503 from Uvicorn |
| Public batch calls | 10 | Structured `invalid_parameters` |
| Disease/drug/author/journal filter strings | 256 characters per item | Structured `invalid_parameters` |

The total byte budget takes precedence over individual field limits. A ten-call
batch may use valid maximum-size fields while it fits the aggregate budget;
multi-byte text and JSON escapes count as their actual transmitted bytes.
Whitespace does not increase the allowed budget. Unsupported oversized inputs
fail before provider access or quota reservation.

Declared oversized lengths are rejected without reading a body. Chunked input
is checked before each received chunk is appended. JSON media types accepted
by the pinned SDK, including surrounding whitespace and comma-separated values,
receive the same nesting guard. Structural characters inside quoted JSON
strings are not nesting.

Admission fails immediately when capacity is exhausted: excess requests do not wait in a body-buffer queue.
Admission remains held until the application response finishes and is released
on disconnect, cancellation or failure. The body deadline covers upload only;
scientific operations keep their separate end-to-end deadlines. At most 32
admitted raw bodies, each at most 64 KiB, are retained by this middleware per
worker. SDK objects, response data, transport buffers and kernel memory have
their own allocations; 2 MiB is not a whole-process memory cap.

The built-in local and private hosted runners enforce at most 128 concurrent
connections/tasks; a supplied lower limit is honored. A custom Asynchronous Server Gateway Interface (ASGI) host or
reverse proxy must configure its own connection/task bounds, body-size ceiling
at most 65,536 bytes, and upload deadline at most 10 seconds. Avoid unlimited
request queues or full buffering before forwarding. Review proxy trust and
authenticated client behavior with the hosted owner before deployment.

Reduce concurrent uploads and retry a 503 after the stated delay. For a 408,
check upload progress and resend the complete request when the connection is
healthy. Narrow a 413 request, or split its batch while preserving scientific
scope. None of these failures is evidence of absent provider records.

Run `uv run python scripts/qualify-ingress.py --output /absolute/report.json`
from the public tree to measure one isolated loopback worker on macOS or Linux.
It uses synthetic Europe PMC responses through actual scientific dispatch, a
maximum ten-call 65,536-byte batch, declared sizes up to 1 GiB, and chunked
upload plans up to 64 MiB that stop after the early rejection. It also holds 32
incomplete 65,535-byte bodies, verifies 64 excess rejections, checks health and
post-load batch recovery, and measures the real ten-second timeout. The client
requires a complete HTTP rejection response even if the peer later resets the
connection.

The report binds unchanged code/fixture/lockfile inputs, hardware/runtime,
concurrency, transmitted bytes, server resident set size (RSS) and traced heap, and fixed 32 MiB RSS
and 24 MiB heap growth thresholds. Measurements qualify those workloads on that
worker, not arbitrary ASGI/proxy configurations or production latency service-level objectives (SLOs).

## Public provider retry and infrastructure policy

A failed provider request is retried automatically at most once (two attempts total), within the original request deadline. Every attempt passes shared provider pacing and current destination validation. Each attempt's connection/read/write/pool timeouts shrink with remaining time; the final response stream retains that deadline and its 24 MB byte budget. Cancellation stops a backoff immediately. Retries do not create additional tool/accounting calls.

Replay-safe GET/HEAD requests must have an empty, buffered body. Buffered read POSTs up to 65,536 bytes are qualified only for the exact routes below with the required query/identifier/criteria shape. Streaming bodies and other methods/routes are single-attempt. BioThings `scroll_id`, `_scroll_id` and `fetch_all` requests are single-attempt in URL parameters and POST bodies: scrolling can advance server-side retrieval state. Scientific failure and missing measurement remain distinct from a healthy empty response.

| Read POST host | Exact path | Read contract |
| --- | --- | --- |
| `mygene.info` | `/v3/query`, `/v3/gene` | Batch query/annotation by supplied identifiers ([query](https://docs.mygene.info/en/latest/doc/query_service.html#batch-queries-via-post), [annotation](https://docs.mygene.info/en/latest/doc/annotation_service.html)). |
| `mychem.info` | `/v1/query`, `/v1/chem` | Batch chemical query/annotation ([query](https://docs.mychem.info/en/latest/doc/chem_query_service.html#batch-queries-via-post), [provider interface](https://mychem.info/)). |
| `mydisease.info` | `/v1/query`, `/v1/disease` | Batch disease query/annotation ([query](https://docs.mydisease.info/en/latest/doc/disease_query_service.html#batch-queries-via-post), [annotation](https://docs.mydisease.info/en/latest/doc/disease_annotation_service.html)). |
| `api.reporter.nih.gov` | `/v2/projects/search` | Public scientific award search ([provider contract](https://api.reporter.nih.gov/)); pacing is one request per second. |

OAuth grants, jobs, unqualified GraphQL/analysis POSTs and write methods have no automatic replay. Adding a route requires explicit read semantics, a bounded replayable body and failure/replay fixtures, rather than assuming every POST is safe.

Automatic retry conditions are HTTP 429/502/503/504, connection failures/timeouts, header-read timeouts and remote protocol failures before response delivery. A provider `Retry-After` is a minimum delay: both non-negative integer seconds and HTTP dates are honored as defined in [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after). Absent headers use 250–500 ms jitter, followed by provider pacing. Invalid or unaffordable delays return the classified failure promptly, without an early retry. HTTP 400/401/403/404/422/500/501, invalid arguments, malformed JSON/application-error payloads, pool contention, DNS/TLS policy rejection and partially delivered response bodies are not automatically retried. Final HTTP failures preserve authentication/access/not-found/rate-limit/outage classifications. DNS/TLS rejection is `source_connection_rejected`, with `retryable: false`.

Failed responses close before backoff. Repeated failures cannot exceed two attempts per eligible request; existing bounded source/global worker and pending-request limits still apply. All DNS addresses are checked before any TCP connection. Up to four validated public IPs may be tried within one DNS/TCP budget, without another DNS lookup. HTTP Host and TLS server hostname retain the original provider name. Mixed private/public DNS answers and certificate verification failures are rejected.

| Infrastructure failure | Explicit behavior |
| --- | --- |
| Result-cache read failure | Fail with `cache_unavailable` before provider execution. |
| Result-cache write failure after a provider read | Fail with `cache_unavailable`; do not silently return an uncached success or retry the provider. |
| Invalid stored cache data | Fail with `cache_invalid_data`; explicitly refresh/restart rather than interpreting it as absent evidence. |
| Shared rate-limiter failure | Fail with `provider_budget_unavailable`; no provider request or local admission fallback. |

These policies preserve cross-replica admission during infrastructure loss. HTTP retry never catches or bypasses cache/admission failures. The [deterministic transport tests](../tests/unit/runtime/test_transport_retries.py), [cache/admission tests](../tests/unit/runtime/test_runtime_admission.py) and [required real-Redis integration](../tests/redis/test_runtime_redis.py) cover this behavior without calling providers.
