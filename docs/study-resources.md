# Interactive study resources

A default installation includes `ubi_synthetic`, a checksummed demonstration with invented patients and measurements. It is explicitly labeled synthetic in release metadata and analysis warnings. It is useful for exercising `study_analysis`, and supplies no biological cohort evidence. Discover its ID through `capabilities(source="study")`. Configure both `UBI_PUBLIC_STUDY_MANIFEST` and `UBI_PUBLIC_STUDY_DIR` to select reviewed real public releases instead; an explicitly empty manifest disables all installed studies. Partial configuration fails closed. See [source access](source-access.md) for operator configuration.


Study analysis uses a process-wide cache shared by service instances. A request loads clinical samples and only its required modalities. Mutation operations retain projected event fields, a gene index and event counts per sample. Survival additionally loads patient records. Expression/CNA operations stream a checksummed gene-to-row index and retain only requested gene rows. Structural-variant queries load that modality and return independent record dictionaries.

Initial release verification hashes **every approved member** once and shares an immutable registry snapshot across discovery and analysis. A changed manifest requires full verification of the newly declared release; changed inventory metadata requires checksum validation of changed members. Independent reads run outside the registry/cache mutation locks. Each analysis checksums every consumed member before use and again before returning, including cache hits: same-size writes with restored timestamps can otherwise remain undetected. A mutation-only analysis reads sample and mutation files; it does not read unchanged expression/CNA or patient files after initialization. An ordinary metadata change in an unused file still triggers its checksum check and fails closed if its bytes differ.

These checks prove the consumed evidence matches the declared release. Metadata checks alone cannot prove that **unconsumed** files still have identical bytes. `biomedmcp diagnose '{"source":"study"}'` explicitly rechecks every member, even with unchanged metadata; it is separate from normal discovery/analysis and may read large unused modalities. Operators should mount reviewed installations read-only and replace releases through a reviewed manifest. First use of a matrix indexes its rows; subsequent requested rows are read at their recorded offsets and checked against their individual hashes. Parsed tables must match the manifest before entering the cache. Release metadata is private to each analysis and checked again before returning a successful result. Verification uses 1 MiB blocks and a 2,000,000,000-byte member ceiling. Representative-study latency remains a separate qualification measurement.

Study operations recompute results from the shared parsed-input cache on every request. The final-result cache is bypassed so it cannot hide consumed-file tampering behind an earlier healthy result. Concurrent identical requests still coalesce under the existing account scope and execution deadline; this does not bypass worker or memory admission. Other providers retain their normal freshness policy.

## Admission policy

The cache enforces these fixed limits per Python process:

| Resource | Limit or reservation |
| --- | --- |
| Aggregate retained payload plus active reservations | 256 MiB |
| Cache entries, including entries being built | 64 |
| Active analysis workspace reservation | 32 MiB per analysis |
| Parsing reservation | 32 MiB per component being built |
| Clinical sample population | 10,000 samples |
| Table file | 200,000,000 bytes |
| Physical table record, checked before decoding | 2 MiB |
| Columns | 50,000 |
| Non-clinical table rows | 1,000,000 |
| Sample, patient and gene identifiers in cached tables | 256 characters |
| Returned Python result payload | 8 MiB |
| Dedicated executor | Two running workers; four total running/queued tasks |

Retained payload sizes use Python object sizes, with a backing-dictionary allowance for immutable mappings. Aliased objects are conservatively charged again. Builders charge row/index growth while parsing; their reservations share the same aggregate ledger as cached entries and active analyses. Idle entries can be evicted to admit work. An active lease prevents eviction and keeps its payload charged. A cache lock covers admission, initialization and mutation; it does not cover scientific analysis. Concurrent initialization of the same component is shared.

These limits bound admission of supported interactive payloads. They are **not a process RSS limit**: interpreter/library allocations, allocator retention, verified-registry metadata, native numerical work and results retained by callers are outside the retained-cache metric. Parsing and analysis workspace reservations are conservative allowances, not measured per-call allocation counters. Use container/process memory limits for a hard runtime RSS ceiling; multiplying processes or replicas multiplies their independent budgets. The [resource profiler](study-resource-benchmark.md) measures cold/warm/concurrent workloads and controlled cancellation with explicit Linux cgroup limits. Representative public-study qualification results remain separate from the policy. The [algorithm profiler](study-algorithm-benchmark.md) measures algorithm scaling separately.

Cancellation can remove queued work. A running thread keeps its executor slot and cache/workspace reservations until it actually finishes, even if the caller times out. Repeated timeouts therefore cannot admit unlimited continuing threads. Resource exhaustion returns `study_budget_exceeded` with a platform handoff; it never becomes a measured negative or a healthy empty cohort. Larger studies/results belong in platform analytics.

Tables require a unique header and matching column counts. Multiline quoted fields and invalid UTF-8 fail explicitly. Normal tab-delimited quoted fields are supported subject to the CSV parser's field-size limit. Duplicate clinical identities, undeclared mutation samples and ambiguous gene rows remain invalid/unavailable. Missing assays and measurements retain their scientific [missingness and statistical interpretation](statistical-methods.md).

## Install a reviewed immutable release

`python -m biomedmcp.study_installation --manifest reviewed.json --root /reviewed/studies --destination /managed/releases` creates a checksummed, content-addressed installation without changing the running service's configured registry. Each enabled study must contain `data_rights` with exactly `license`, `evidence_url` and `scope`: the supported data licenses are `CC0-1.0` and `CC-BY-4.0`, the evidence URL must be public HTTPS, and scope must be `all_declared_files`. The operator must review the original data rights; an API key, an integration-code license or a file format does not establish permission. Restricted, unknown and missing rights fail before installation.

The installer verifies the original manifest and all members, checksums again while copying, verifies the complete staged release, then publishes its directory atomically inside an exclusively reserved identity directory. Files and directories are made read-only. A successful repeat verifies identical manifest and member bytes; conflicting bytes fail. An incomplete reserved identity fails with a retryable busy outcome for operator reconciliation. It is never overwritten or silently repaired. No downloads, source-license overrides or live-pointer updates occur. The returned directory contains `manifest.json` and `studies/`; configure both paths together when deliberately switching the service to that verified release. Existing running analyses retain their own release checks and fail if their consumed source changes.
