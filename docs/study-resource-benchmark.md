# Measure installed-study resources

`scripts/benchmark-study-resources.py` measures native study work in the actual two-worker/four-total-admitted-task executor. It accepts an operator-reviewed public release and an explicit bounded workload plan. It downloads no data and sends no provider requests. Choose supported operations and expected scientific outcomes before running; a missing assay or oversized member must remain an explicit unavailable outcome.

The plan is a JSON list of at most 16 objects, each with a distinct bounded `id`, `operation`, `params` and `expected`. Parameters use the current study operation contracts. Chart rendering is outside this native benchmark. For example, the synthetic demo's declared assay coverage permits:

```json
[
  {"id":"mutation","operation":"query","params":{"study":"ubi_synthetic","gene":"TP53"},"expected":"success"},
  {"id":"cna","operation":"query","params":{"study":"ubi_synthetic","gene":"ERBB2","type":"cna"},"expected":"success"}
]
```

With a Linux public **test** image containing the script, mount the reviewed installation and plan read-only and a new output directory writable:

```sh
export study_install plan_file report_dir
./scripts/test-local.sh -- bash -euo pipefail -c '
docker run --label "$UBI_TEST_RUN_LABEL" --rm --network none --read-only --cpus 1 --memory 512m --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,noexec,size=32m \
  -e OPENBLAS_NUM_THREADS=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 \
  -v "$study_install:/input:ro" -v "$plan_file:/plan.json:ro" -v "$report_dir:/output:rw" \
  --entrypoint python "$UBI_TEST_IMAGE" scripts/benchmark-study-resources.py \
  --manifest /input/manifest.json --root /input/studies --plan /plan.json \
  --output /output/resources.json --repeats 5 --require-container-limits
'
```

Supply absolute host paths. The script verifies the observed cgroup memory, CPU and process limits when the qualification flag is set. Existing output files are never overwritten. A malformed plan, changed release/code inputs, unavailable sampler, unexpected scientific outcome or divergent cold/warm/concurrent result hash fails the run; missing metrics never become zero. The final report is capped at 2 MiB and contains aggregate counts and hashes, not clinical records or measurement arrays.

For each workload, the script creates an empty parsed-component cache, measures one cold request, then 2–10 warm repetitions and four concurrent warm requests. The native worker path includes release revalidation and result hashing. Raw wall-time samples, warm medians, sampled per-phase process RSS, whole-cgroup memory, cache admission, backlog, implementation/lock/manifest hashes and runtime identities are retained. Initial all-member verification is measured separately. A cold parsed cache does **not** mean a cold filesystem cache: verification reads every member, and the benchmark never drops system page caches. Cache state is reset between workloads; the benchmark does not force garbage collection or trim Python/native allocators. Ordinary retained allocations remain visible across phases.

RSS samples use Linux `/proc/self/smaps_rollup`, which aggregates page-table memory across mappings. Sampling occurs about every 5 ms plus at each phase's start/end, so shorter peaks can be missed. Kernel reads and background sampling add measurement overhead; timings are native benchmark observations, not MCP, provider, model or production latency. Process lifetime high-water RSS is reported separately and is not attributed to an individual phase. Cgroup memory includes other charged memory such as filesystem pages and must not be presented as process RSS. These distinctions follow the [Linux kernel proc documentation](https://docs.kernel.org/filesystems/proc.html).

A separate controlled lifecycle check gates two actual workers while they hold clinical-cache leases, fills the four-task backlog, verifies rejection of a fifth task and cancels running/queued waiters. Running threads must retain their worker and workspace/payload admissions; queued cancellations must release their slots. It then releases the gate and verifies quiescent accounting. This deliberately injected wait has **no latency measurement**. Ordinary concurrent scientific requests are measured separately.

The benchmark does not prove clinical validity, per-base mutation callability, all-study readiness, worst-case allocator behavior or exact unsampled peaks. Review representative sources, assay coverage, licensing and workload feasibility independently. Use actual container/process limits for a hard memory ceiling; [cache admission](study-resources.md) alone is not an RSS limit. Qualification results and real public study data remain operator-owned; no clinical dataset is redistributed by this script.

## Synthetic population stress

`scripts/generate-study-resource-fixture.py --destination <new-directory>` streams an artificial release with 10,000 unique patients/samples, 1,000 matrix genes, discrete CNA calls, expression test values and explicit simulated mutation coverage. It computes every member checksum and records its own source hash. Supported dimensions are 4–10,000 samples and 2–1,000 matrix genes; an existing destination is never overwritten. The fixture is labeled synthetic and has no experimental, clinical or normalization meaning. Use it to exercise the interactive population ceiling and larger working sets alongside reviewed representative public studies. An explicit output/resource handoff remains a valid declared outcome; never change the expected outcome simply to hide a regression.

Each enabled manifest entry must declare reviewed `data_rights` covering `all_declared_files`, using `CC0-1.0` or `CC-BY-4.0` and a public HTTPS `evidence_url`; see the [immutable installer](study-resources.md#install-a-reviewed-immutable-release). The benchmark checks these rights before reading dataset members. Its native-only request validator uses the verified per-release permissions, not a broad provider-license override. This operator command enables no MCP integration and leaves every source hold intact. The report carries the reviewed permissions alongside the input hashes. Synthetic fixtures declare their synthetic provenance; real projected datasets must retain their original source measurements, units, biological identities and transformation provenance.
