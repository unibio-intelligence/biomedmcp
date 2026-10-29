#!/usr/bin/env python3
"""Offline synthetic scaling of actual reviewed/current study algorithms."""

import argparse
import ast
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
import platform
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from biomedmcp.errors import ResearchError
from biomedmcp.native import REVISION
from biomedmcp.native.study import StudyAnalytics
from biomedmcp.native.study_statistics import logrank
from biomedmcp.native.study_storage import validate_mutation_samples, validate_sample_ids

BASELINE_SHA256 = "02d81eb34883fb878e6fae6b2ccb4dc6f1f657128188a0c5a9070cb6e866f90d"
ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def selected_methods(source):
    """Execute only the selected function/validation AST, never the source module."""
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "logrank"]
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StudyAnalytics"]
    if len(classes) != 1:
        raise ValueError("Expected exactly one study class")
    load = next(node for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name == "load")
    statements = list(ast.walk(load))
    parts = []
    for name in ["ids", "sample_ids"]:
        matches = [
            node
            for node in statements
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        ]
        if len(matches) > 1 or (name == "ids" and not matches):
            raise ValueError("Unsupported sample validation assignment")
        parts += matches
    duplicates = [
        node
        for node in statements
        if isinstance(node, ast.If) and ast.unparse(node.test).startswith("len(ids) !=")
    ]
    membership = [
        node
        for node in statements
        if isinstance(node, ast.If)
        and ast.unparse(node.test).startswith("any(")
        and "Tumor_Sample_Barcode" in ast.unparse(node.test)
    ]
    if len(duplicates) != 1 or len(membership) != 1:
        raise ValueError("Unsupported mutation validation expression")
    parts += duplicates + membership
    text = (
        "def membership(samples, mutations):\n    data = {'mutations': mutations}\n"
        + "\n".join("    " + line for node in parts for line in ast.unparse(node).splitlines())
        + "\n"
    )
    namespace = {"ResearchError": ResearchError}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<reviewed-logrank>", "exec"), namespace)  # noqa: S102 -- exact hash-pinned reviewed reference; never execute its module.
    exec(compile(text, "<selected-mutation-validation>", "exec"), namespace)  # noqa: S102 -- selected source validation AST; current source is the already-imported application.
    return namespace.get("logrank"), namespace["membership"], text


def baseline_methods(path):
    if path.stat().st_size > 128_000:
        raise ValueError("Reviewed baseline exceeds its source budget")
    source = path.read_bytes()
    if sha(source) != BASELINE_SHA256:
        raise ValueError("Baseline must match the exact reviewed source SHA-256")
    original_logrank, membership, text = selected_methods(source.decode())
    if original_logrank is None:
        raise ValueError("Reviewed log-rank function is missing")
    return original_logrank, membership, text


def hardware():
    result = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
    }
    if hasattr(os, "sched_getaffinity"):
        result["cpu_affinity"] = sorted(os.sched_getaffinity(0))
    if platform.system() == "Darwin":
        for name in ["hw.model", "machdep.cpu.brand_string", "hw.memsize"]:
            value = subprocess.run(
                ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip()
            result[name] = value
    for name in ["cpu.max", "memory.max"]:
        path = Path("/sys/fs/cgroup") / name
        if path.is_file():
            result[name] = path.read_text().strip()
    if Path("/proc/cpuinfo").is_file():
        result["cpuinfo_identity"] = [
            line
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.split(":")[0].strip() in {"model name", "CPU implementer", "CPU architecture", "CPU part"}
        ][:8]
    return result


def measure(function, arguments, repeats):
    function(*arguments)  # Warm imports/dispatch separately from timed calls.
    samples = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        function(*arguments)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "milliseconds": samples,
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def agreement(before, after):
    for field in ["statistic", "p_value"]:
        if before[field] is None or after[field] is None:
            if before[field] is not after[field]:
                raise ValueError("Unavailable log-rank result changed")
        elif not math.isclose(before[field], after[field], rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("Log-rank scientific result changed")


def scaling(rows):
    for previous, current in pairwise(rows):
        ratio = current["n"] / previous["n"]
        current["growth_from_previous"] = {
            name: {
                "time_ratio": current[name]["median_ms"] / previous[name]["median_ms"],
                "size_ratio": ratio,
                "empirical_exponent": math.log(current[name]["median_ms"] / previous[name]["median_ms"])
                / math.log(ratio),
            }
            for name in ["reviewed", "current"]
        }


def benchmark(baseline, *, sizes=(128, 256, 512, 1024, 2048, 4096), repeats=5):
    if (
        not 1 <= repeats <= 10
        or len(sizes) < 2
        or len(sizes) > 8
        or any(not isinstance(n, int) or not 16 <= n <= 8192 for n in sizes)
        or any(right <= left for left, right in pairwise(sizes))
    ):
        raise ValueError("Use 2–8 increasing sizes in 16–8192 and 1–10 repeats")
    if baseline.stat().st_size > 128_000:
        raise ValueError("Reviewed baseline exceeds its source budget")
    paths = {
        "reviewed_study_source": baseline,
        "current_study_source": Path(inspect.getfile(StudyAnalytics)),
        "current_storage_source": Path(inspect.getfile(validate_sample_ids)),
        "current_statistics_source": Path(inspect.getfile(logrank)),
        "benchmark_runner": Path(__file__),
        "reference_inputs": ROOT / "tests/fixtures/statistics/r-cases.json",
    }
    fingerprints = {name: sha(path.read_bytes()) for name, path in paths.items()}
    original_logrank, original_membership, before_text = baseline_methods(baseline)

    def current_membership(samples, mutations):
        validate_mutation_samples(mutations, validate_sample_ids(samples))

    after_text = inspect.getsource(validate_sample_ids) + inspect.getsource(validate_mutation_samples)
    cases = json.loads((ROOT / "tests/fixtures/statistics/r-cases.json").read_text())["logrank"]
    for case in cases:
        agreement(original_logrank(case["left"], case["right"]), logrank(case["left"], case["right"]))
    for function in [original_membership, current_membership]:
        for samples, mutations, expected in [
            ([{"SAMPLE_ID": "S1"}, {"SAMPLE_ID": "S1"}], [], "invalid_study"),
            ([{"SAMPLE_ID": "S1"}], [{"Tumor_Sample_Barcode": "S2"}], "invalid_study"),
        ]:
            try:
                function(samples, mutations)
            except ResearchError as error:
                if error.code != expected:
                    raise ValueError("Validation error changed") from None
            else:
                raise ValueError("Invalid sample membership was accepted")
    logrank_rows, membership_rows = [], []
    for n in sizes:
        rng = random.Random(19009 + n)
        observations = [(rng.randrange(n // 2), rng.random() < 0.7) for _ in range(n)]
        groups = observations[::2], observations[1::2]
        before, after = original_logrank(*groups), logrank(*groups)
        agreement(before, after)
        logrank_rows.append(
            {
                "n": n,
                "patients_per_group": [len(group) for group in groups],
                "unique_event_times": len({time for time, event in observations if event}),
                "events": sum(event for _, event in observations),
                "censored": sum(not event for _, event in observations),
                "observations_sha256": sha(json.dumps(observations, separators=(",", ":")).encode()),
                "result": {key: after[key] for key in ["statistic", "p_value"]},
                "reviewed": measure(original_logrank, groups, repeats),
                "current": measure(logrank, groups, repeats),
            }
        )
        samples = [{"SAMPLE_ID": f"S{index:06d}"} for index in range(n)]
        mutations = [{"Tumor_Sample_Barcode": samples[index % n]["SAMPLE_ID"]} for index in range(4 * n)]
        original_membership(samples, mutations)
        current_membership(samples, mutations)
        membership_rows.append(
            {
                "n": n,
                "mutations": len(mutations),
                "fixture_sha256": sha(json.dumps([samples, mutations], separators=(",", ":")).encode()),
                "includes_id_construction_and_duplicate_validation": True,
                "reviewed": measure(original_membership, (samples, mutations), repeats),
                "current": measure(current_membership, (samples, mutations), repeats),
            }
        )
    scaling(logrank_rows)
    scaling(membership_rows)
    if fingerprints != {name: sha(path.read_bytes()) for name, path in paths.items()}:
        raise ValueError("Benchmark inputs changed during measurement")
    return {
        "schema_version": 1,
        "measured_at": datetime.now(UTC).isoformat(),
        "implementation": REVISION,
        "hardware": hardware(),
        "software": {"python": platform.python_version(), "scipy": importlib.metadata.version("scipy")},
        "inputs_sha256": fingerprints,
        "validation": {
            "fixed_logrank_cases": len(cases),
            "scientific_tolerance": {"relative": 1e-10, "absolute": 1e-12},
            "duplicate_and_undeclared_samples_rejected": True,
        },
        "workload": {
            "kind": "deterministic synthetic algorithm scaling",
            "sizes": sizes,
            "repeats": repeats,
            "seed": "19009 + n",
            "provider_requests": 0,
            "provider_latency_ms": 0,
            "warmup_calls_per_size_and_mode": 1,
        },
        "mutation_validation_fragments": {"reviewed": before_text, "current": after_text},
        "logrank": logrank_rows,
        "mutation_membership": membership_rows,
        "limitations": [
            "Sequential synthetic algorithm timings exclude release verification, table parsing, cache locking, provider/network latency and client/model tasks.",
            "Samples are elapsed algorithm times, not endpoint request latency percentiles; empirical exponents are observations and no timing threshold is a CI test.",
            "No representative real-study RSS, aggregate memory bound or production speedup is established; R18 resource qualification remains separate.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--sizes", type=int, nargs="+", default=[128, 256, 512, 1024, 2048, 4096])
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Choose a fresh output; existing measurements are not overwritten")
    report = benchmark(args.baseline, sizes=args.sizes, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "validation": report["validation"],
                "largest_size": report["logrank"][-1]["n"],
                "logrank_medians_ms": {
                    name: report["logrank"][-1][name]["median_ms"] for name in ["reviewed", "current"]
                },
                "membership_medians_ms": {
                    name: report["mutation_membership"][-1][name]["median_ms"]
                    for name in ["reviewed", "current"]
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
