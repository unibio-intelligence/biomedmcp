# Public provider retry and infrastructure policy

Public scientific egress permits at most one automatic retry (two attempts total), within the original end-to-end request deadline. Every attempt passes shared provider pacing and current destination validation. Each attempt's connection/read/write/pool timeouts shrink with remaining time; the final response stream retains that deadline and its 24 MB byte budget. Cancellation stops a backoff immediately. Retries do not create additional tool/accounting calls.

Replay-safe GET/HEAD requests must have an empty, buffered body. Buffered read POSTs up to 65,536 bytes are qualified only for the exact routes below with the required query/identifier/criteria shape. Streaming bodies and other methods/routes are single-attempt. BioThings `scroll_id`, `_scroll_id` and `fetch_all` requests are single-attempt in URL parameters and POST bodies: scrolling can advance server-side retrieval state. Scientific failure and missing measurement remain distinct from a healthy empty response.

| Read POST host | Exact path | Read contract |
| --- | --- | --- |
| `mygene.info` | `/v3/query`, `/v3/gene` | Batch query/annotation by supplied identifiers ([query](https://docs.mygene.info/en/latest/doc/query_service.html#batch-queries-via-post), [annotation](https://docs.mygene.info/en/latest/doc/annotation_service.html)). |
| `mychem.info` | `/v1/query`, `/v1/chem` | Batch chemical query/annotation ([query](https://docs.mychem.info/en/latest/doc/chem_query_service.html#batch-queries-via-post), [provider interface](https://mychem.info/)). |
| `mydisease.info` | `/v1/query`, `/v1/disease` | Batch disease query/annotation ([query](https://docs.mydisease.info/en/latest/doc/disease_query_service.html#batch-queries-via-post), [annotation](https://docs.mydisease.info/en/latest/doc/disease_annotation_service.html)). |
| `api.reporter.nih.gov` | `/v2/projects/search` | Public scientific award search ([provider contract](https://api.reporter.nih.gov/)); pacing is one request per second. |

These qualifications concern replay semantics, not exhaustive scientific response validation or current live availability. OAuth grants, jobs, unqualified GraphQL/analysis POSTs and write methods have no automatic replay. Adding a route requires explicit read semantics, a bounded replayable body and failure/replay fixtures, rather than assuming every POST is safe.

Automatic retry conditions are HTTP 429/502/503/504, connection failures/timeouts, header-read timeouts and remote protocol failures before response delivery. A provider `Retry-After` is a minimum delay: both non-negative integer seconds and HTTP dates are honored as defined in [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after). Absent headers use 250–500 ms jitter, followed by provider pacing. Invalid or unaffordable delays return the classified failure promptly, without an early retry. HTTP 400/401/403/404/422/500/501, invalid arguments, malformed JSON/application-error payloads, pool contention, DNS/TLS policy rejection and partially delivered response bodies are not automatically retried. Final HTTP failures preserve authentication/access/not-found/rate-limit/outage classifications. DNS/TLS rejection is `source_connection_rejected`, with `retryable: false`.

Failed responses close before backoff. Repeated failures cannot exceed two attempts per eligible request; existing bounded source/global worker and pending-request limits still apply. All DNS addresses are checked before any TCP connection. Up to four validated public IPs may be tried within one DNS/TCP budget, without another DNS lookup. HTTP Host and TLS server hostname retain the original provider name. Mixed private/public DNS answers and certificate verification failures fail closed.

| Infrastructure failure | Explicit behavior |
| --- | --- |
| Result-cache read failure | Fail with `cache_unavailable` before provider execution. |
| Result-cache write failure after a provider read | Fail with `cache_unavailable`; do not silently return an uncached success or retry the provider. |
| Invalid stored cache data | Fail with `cache_invalid_data`; explicitly refresh/restart rather than interpreting it as absent evidence. |
| Shared rate-limiter failure | Fail with `provider_budget_unavailable`; no provider request or local admission fallback. |

These policies preserve cross-replica admission during infrastructure loss. HTTP retry never catches or bypasses cache/admission failures. The [deterministic transport tests](../tests/test_transport_retries.py), [cache/admission tests](../tests/test_runtime_admission.py) and [required real-Redis integration](../tests/redis/test_runtime_redis.py) exercise the boundaries without provider traffic. No production latency, live availability or model success claim follows from fixture results.
