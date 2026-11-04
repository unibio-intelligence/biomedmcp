# Qualification and live observations

Being configured, loading correctly, passing offline tests and working live are separate checks. `biomedmcp diagnose` reports those states independently without contacting providers. `get_capabilities` continues to report `health: "not_probed"`. Passing one check does not imply the others.

The distributed public test suite covers canonical dispatch, provider failure handling, identity, provenance, pagination, study missingness and example execution with synthetic evidence. [Adapter inventory tests](../tests/test_adapter_inventory.py) check retained imports and every declared advanced operation. Endpoint-specific fixtures cover selected scientific provider contracts. Their exact scope is reported in the bundled offline qualification evidence when that evidence matches the installed implementation and dependencies. Missing or stale evidence is reported explicitly.

This release does not claim that every provider route currently works live, or that it is ready for every model or client. The [capability matrix](capability-readiness.json) retains those limitations and references only files supplied in the public export.

Live canaries are a separate operator-authorized activity: `UBI_PROFILE=local uv run --frozen python scripts/live-canary.py --output /tmp/ubi-live.json`. `--validate-only` checks definitions without provider reads and never qualifies live health. Reports identify implementation, retrieval time, declared/participating sources, status and result/provenance hashes. A failed probe does not mean the evidence is absent. Review provider terms and configuration before running live checks.

An operator may point `UBI_PUBLIC_LIVE_QUALIFICATION` at a sanitized canary report. Diagnosis reads that receipt without running a probe. Only matching current definitions/implementation, successful executed source observations and timestamps within 24 hours qualify a recent observation. Stale, malformed, definition-only, mismatched or failed receipts remain distinct. The receipt is a point-in-time snapshot, not proof of current health.
