# Reproduce study algorithm scaling

The offline profiler compares the exact reviewed sample-membership and log-rank algorithms with the current implementation. It generates deterministic synthetic data across increasing sizes, records raw elapsed times, adjacent growth ratios and empirical exponents, and checks scientific agreement before reporting timings. Timing thresholds are not CI assertions. These results describe algorithms on the recorded hardware, not production speedups or endpoint latency.

The [reviewed source fixture](../tests/fixtures/statistics/study-audited-0148.txt) is the byte-identical public study source at review revision `0148aea1a9ce75db2876468f815fb81db6ba10c1`, SHA-256 `02d81eb34883fb878e6fae6b2ccb4dc6f1f657128188a0c5a9070cb6e866f90d`. The profiler refuses other reference bytes and oversized inputs. It extracts the log-rank function and sample-ID construction/duplicate/mutation-validation statements from the AST. It never executes the full obsolete module or its analytics class. The current membership statements come from actual current source; log-rank calls the actual current function. The archived fixture does not provide service operations.

Run from the public root with a fresh output:

```sh
uv run --frozen python scripts/benchmark-study-algorithms.py \
  --baseline tests/fixtures/statistics/study-audited-0148.txt \
  --output /tmp/study-algorithm-measurement.json \
  --sizes 128 256 512 1024 2048 4096 --repeats 5
```

The default six sizes contain equally sized survival groups, deterministic integer times with ties, events and censoring. Each workload reports the number of events, censored observations and distinct event times. Membership workloads use four mutation records per declared sample, with uniformly repeated declared identifiers. Both modes include construction of the identifier list, duplicate validation and membership rejection. The current implementation retains one sample-ID set for both duplicate validation and mutation membership. Log-rank maintains grouped events/censoring and decreasing risk sets, avoiding a scan of all observations at every event time.

Eleven independently specified log-rank cases, including empty groups, no events, zero variance and tied censoring, must preserve the reviewed statistic and probability at relative `1e-10`/absolute `1e-12` tolerances. Each timed workload also checks agreement. Duplicate sample IDs and undeclared mutation barcodes must remain rejected. The separate [statistical reference suite](statistical-methods.md) checks the current algorithms against independently generated R results. The profiler binds source, runner and reference hashes and refuses input changes during measurement. Existing output is never overwritten.

One untimed call per size/mode warms imports and identifier hashing; each reported sample times one complete algorithm invocation. The report contains median/min/max and all raw samples, not request percentiles. It records Python/SciPy versions, architecture, CPU identity, affinity and available cgroup limits. Review the full size curve; small-call noise, fixed import/dispatch costs and host contention can distort a single growth ratio. Five sequential samples are observations, not a statistical confidence interval or an SLO.

For controlled Linux reproduction, build the independently qualified test image and execute the same command in a network-disabled, read-only container, with a writable output mount and explicit CPU/memory limits. The test image includes the archived fixture and profiler; the runtime image does not include test fixtures. Retain the exact image identity with each measurement report.

Release verification/hashing, file parsing, modality loading, cache synchronization, result serialization, provider latency and client/model tasks are excluded. This does not qualify resident memory, continuing timed-out workers, aggregate cache budgets or representative real-study latency. Those study-resource requirements remain separate; see [installation and interpretation](studies.md).
