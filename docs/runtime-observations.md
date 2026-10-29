# Runtime observations

The public runtime records logical source work separately from callers waiting for shared work. These observations describe this process; they do not establish provider health, clinical correctness or production service objectives.

`provider_result` is one terminal event for each admitted or refused logical source flight. It is emitted after scientific classification and cache completion/failure. Its `outcome` agrees with evidence-section semantics: `data`, `empty`, `ambiguous` and `partial` stay distinct. Infrastructure/provider failures are `unavailable`; abandoned work is `cancelled`. An unavailable secondary section cannot produce a terminal `completed` success. A failed cache read/write retains its own error and cache state.

`provider_waiter` describes each admitted caller, including coalesced callers and cancelled/timed-out waiters. A waiter can time out while another caller still receives the shared result. The physical flight therefore has one terminal observation, while each caller has its own waiting outcome. Refused admissions have a zero-execution `provider_result`; they did not contact a provider.

A server-generated 32-character correlation ID groups source work within one canonical dispatch, including composed research and batch operations. Each shared flight has a separate generated flight ID. Coalesced callers retain their own correlation IDs and refer to that shared flight. The runtime does not use account IDs, request headers, query/body values, cache keys, cursor tokens, identifiers or credentials as telemetry labels. Source/operation labels come from the implemented catalog; unknown labels and error codes are represented by fixed safe values.

Events include:

- `scheduler_ms`, `cache_read_ms`, `queue_ms`, `execution_ms`, `classification_ms` and `cache_write_ms`: wall time for consecutive runtime phases. `queue_ms` covers source/global execution admission. `execution_ms` includes provider work, pacing, retries and nested acquisition. Small unclassified interpreter overhead can remain in total elapsed time.
- `rate_wait_ms`: accumulated time sleeping for source pacing. It is a component of execution time, not an additional disjoint phase. Concurrent nested acquisitions can have overlapping waits; their accumulated wait can exceed the flight's execution wall time.
- `http_429` and `http_timeout_attempts`: actual 429 responses and connect/read timeouts observed by the public HTTP transport, including attempts followed by successful retries. Injected adapters or alternative HTTP clients do not contribute these attempt counts. Source-level terminal rate-limit/timeouts and individual waiter timeouts are separate metrics.
- `cache_state`, `cache_hit` and `coalesced_waiters`: terminal storage/reuse decision and total extra callers joining this flight. Failed scientific sections are labeled when they prevent caching. A cache entry above its existing storage budget is explicitly `write_skipped`.
- `payload_bytes`: compact UTF-8 JSON bytes for the source payload before public evidence bounding, measured up to 1,000,000 bytes. Larger or unencodable payloads have a null size and an explicit unknown/capped flag; null is not zero. This is not the final MCP envelope or network transfer size.

An embedding operator can read `service.runtime.metrics.snapshot()`. It returns defensive process-local source counters and gauges: pending flights, pacing waiters, started/terminal flights, scientific outcomes, cache hits/failures, refused admissions, terminal timeouts/rate limits, actual HTTP 429/timeout attempts, coalesced waiters, caller cancellations/timeouts and accumulated phase/pacing durations. Labels have a finite catalog vocabulary. No new public MCP tool or unauthenticated metrics endpoint is added. Integrate the snapshot or safe event stream with an operator-owned collector; replicas have independent metrics and counters reset on process restart. Counters are observations, not promises of a complete distributed request trace.

`public_request_result` records one terminal at the outer public boundary: MCP tool,
evidence resource, CLI execution or direct embedded dispatch. Nested dispatch
shares its outer request and generated correlation ID. It records the final
constructed result's outcome and safe error-code set after accounting and tool
output validation/encoding. An earlier source success can coexist with a later
request failure; the source observation is retained. Batches have one outer
terminal, while shared source flights and callers keep their separate events.

Request phases are inclusive spans for dispatch, the accounting wrapper,
scientific operation, output validation and output construction. Accounting
includes the scientific operation and does not independently time reservation
versus settlement inside the hosting integration. Concurrent/nested spans are
not additive wall time. Failed phases retain counts and elapsed time; cancellation
emits a cancelled terminal and clears request context. Request payload bytes count
the constructed compact JSON value, capped at one MiB, with null for unknown or
oversized values. Resource-link blocks, protocol framing and actual network bytes
are outside that count. `output_state` distinguishes scientific, CLI, MCP and
resource construction. `delivery_confirmed` is always false: constructing a
response does not prove client receipt. Remote CLI and server events belong to
separate processes; no client-supplied correlation header is accepted.

Request events use the dedicated Python logger `biomedmcp.request`, with
propagation disabled and no implicit console handler. An operator may attach a
handler and set its level to `logging.INFO`, for example an existing private log
collector. This preserves CLI JSON and MCP stdio streams. A collector failure
increments `event_sink_failures` without changing the scientific result.
`biomedmcp.request_telemetry.metrics.snapshot()` returns defensive process-local
started/terminal/pending/outcome/duration counters for finite boundary labels.
Counters reset on process restart and cannot establish distributed delivery,
real-client correctness or an operational objective. No account IDs, body text,
query values, provider records, resource handles or caller-selected labels enter
these events. Unknown operations/errors use fixed safe labels.

`/health` reports process liveness. `/readyz` reports service startup and required authentication/accounting and public-runtime dependencies; dependency failure is sanitized and returns 503. Startup proves the configured dependencies before becoming ready and closes acquired resources on failure or cancellation. Neither endpoint probes biomedical providers. Read-only diagnosis separates configuration/importability, matching offline qualification and operator-supplied point-in-time canary evidence. Provider health requires separate authorized live canaries and does not follow from a healthy process or infrastructure readiness.

When Redis backs public cache or pacing, readiness checks the commands that the configured role actually uses. Each distinct connection must answer `PING`; cache must round-trip `SET`/`GET`, and pacing must execute its actual `EVAL` script (including Redis `TIME`, `GET` and `SET`). A working `PING` alone is insufficient. Cache-only or pacing-only compositions require only their respective commands. Anonymous local operation without Redis requires no optional storage or provider configuration.

Probes use random isolated keys within the existing `biomedmcp:result:` and `biomedmcp:budget:` namespaces. The cache probe expires after two seconds; the pacing probe after one second. They need no `DEL` permission, do not contact providers and do not advance a real source quota. A readiness probe has a one-second safety deadline covering gate admission and all dependency work; concurrent probes within one server/runtime are serialized. This deadline is not a measured service objective. Connection loss, denied commands, invalid replies or deadline expiry make readiness return 503; subsequent recovery can restore 200 without restarting the process. Liveness stays available while a readiness probe awaits I/O.

Operational latency/availability objectives still require measured representative request, queue, pacing and dependency workloads. The [study resource profiler](study-resource-benchmark.md) measures native study work only and does not supply an end-to-end MCP/provider SLO. Do not turn deterministic delay fixtures or native microbenchmarks into production latency targets.
