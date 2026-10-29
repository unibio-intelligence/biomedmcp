# Public documentation HTTP qualification

The CI and protected manual release workflows run `scripts/check-public-links.py`
after offline container qualification. CI treats external-link failures as
advisory: it emits a warning and preserves the failed observations, then requires
the security scan to pass. All deterministic/container tests and artifact
collection remain required. Protected manual releases still require both link
qualification and security scanning to pass before later release work.
The JSON report is retained on success or failure; missing evidence fails artifact
collection. The checker runs inside the qualified test image with a read-only
filesystem, dropped capabilities, no privilege escalation, temporary scratch space
and one writable output directory. The uv cache is confined to temporary scratch
space. It receives no provider credentials or repository mount. This is a separate
live gate: `scripts/test-local.sh` remains offline unless an explicit post-test command requests network access.

From the public distribution, choose a fresh output path:

```sh
uv run --frozen python scripts/check-public-links.py --output /tmp/ubi-links-new/report.json
```

For the same isolation used by CI, run the check inside the image lifecycle:

```sh
./scripts/test-local.sh -- bash -euo pipefail -c '
mkdir -p /tmp/ubi-links-new
docker run --label "$UBI_TEST_RUN_LABEL" --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,size=64m --env UV_CACHE_DIR=/tmp/uv-cache \
  -v /tmp/ubi-links-new:/output "$UBI_TEST_IMAGE" \
  uv run --frozen --no-sync python scripts/check-public-links.py --output /output/report.json
'
```

The checker parses Markdown inline/reference links, images and HTML link attributes
through the shared governance parser. Fenced code examples are excluded. HTTP
targets are deduplicated after removing fragments. Local paths and heading anchors
are checked by the separate offline [governance checker](../scripts/check-governance.py).
Symlink documents, oversized documents and links with credentials are rejected.

Every request and redirect must resolve only to public unicast IP addresses.
Multicast and obsolete IPv6 site-local addresses are explicitly rejected even
when the standard library labels them global. Connections
use the vetted addresses without resolving again; HTTPS verifies the original
hostname. Private addresses, credential query parameters, redirect cycles and
HTTPS downgrades fail. Requests use no cookies, authorization or environment
proxies; response bodies and raw transport exceptions are never retained.

HTTP 2xx establishes reachability. Authentication failures, missing pages and
other non-success responses remain failures. Transient connection failures and
HTTP 429/502/503/504 receive at most three attempts within each link's 12-second
deadline. All completed attempts, including failures preceding recovery, remain
in the report. Certificate validation failures are not retried. A subprocess
deadline bounds DNS and transport work; the whole run has a 240-second budget,
with at most 256 targets and five redirects per attempt. A deadline leaves the
unqualified target visible and fails the gate.

Reports bind document bytes, checker/parser hashes, normalized request hashes,
document link ordinals, redirect statuses and execution time. Displayed URLs omit
query strings and fragments; request hashes preserve their normalized identity.
Changed inputs fail the run. Existing report files are never overwritten.

A passing report establishes unauthenticated HTTP reachability at the recorded
time. It does not validate remote fragments, page contents, provider health,
scientific correctness or agent/client performance. A transient failure calls
for a new complete run with a fresh report, rather than editing earlier evidence
or deleting a valid link to obtain a passing result.
