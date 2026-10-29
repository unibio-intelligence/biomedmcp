# HTTP request budgets

Local and hosted HTTP apps enforce the same limits before MCP JSON parsing:

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

Admission is fail-fast: excess requests do not wait in a body-buffer queue.
Admission remains held until the application response finishes and is released
on disconnect, cancellation or failure. The body deadline covers upload only;
scientific operations keep their separate end-to-end deadlines. At most 32
admitted raw bodies, each at most 64 KiB, are retained by this middleware per
worker. SDK objects, response data, transport buffers and kernel memory have
their own allocations; 2 MiB is not a whole-process memory cap.

The built-in local and private hosted runners enforce at most 128 concurrent
connections/tasks; a supplied lower limit is honored. A custom ASGI host or
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
concurrency, transmitted bytes, server RSS and traced heap, and fixed 32 MiB RSS
and 24 MiB heap growth thresholds. Measurements qualify those workloads on that
worker, not arbitrary ASGI/proxy configurations or production latency SLOs.
