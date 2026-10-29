#!/usr/bin/env python3
"""Repeat native study resource measurements on operator-reviewed public releases."""

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import platform
import re
import resource
import statistics
import threading
import time
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

from biomedmcp import studies, study_workers
from biomedmcp.errors import ResearchError
from biomedmcp.extensions import MODELS, ExtendedSources
from biomedmcp.native import REVISION, study, study_statistics, study_storage
from biomedmcp.study_installation import require_data_rights
from biomedmcp.study_metadata import manifest_entries

ROOT = Path(__file__).resolve().parents[1]


class ReviewedStudyBenchmark(ExtendedSources):
    """Validate native benchmark requests against verified per-release data rights.

    This operator script serves no MCP requests and changes no source policy.
    General study/source integrations remain subject to their existing holds.
    """

    def availability(self, source):
        if source != "study" or not self._studies:
            return False, "Benchmark requires an installed reviewed study."
        for release in self._studies.values():
            require_data_rights(release)
        return True, None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bounded_read(path, limit=16_384):
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Measurement input exceeds its budget")
    return raw.decode()


class LinuxMemory:
    """Sample process page-table totals; never substitute missing metrics with zero."""

    def read(self):
        text = bounded_read(Path("/proc/self/smaps_rollup"))
        match = re.search(r"^Rss:\s+(\d+) kB$", text, re.MULTILINE)
        if match is None:
            raise ValueError("Linux process RSS measurement is unavailable")
        current = Path("/sys/fs/cgroup/memory.current")
        return {
            "rss_bytes": int(match[1]) * 1024,
            "cgroup_memory_bytes": int(bounded_read(current)) if current.is_file() else None,
        }


def environment(require_limits):
    limits = {}
    for name in ("cpu.max", "memory.max", "pids.max", "memory.events"):
        path = Path("/sys/fs/cgroup") / name
        limits[name] = bounded_read(path).strip() if path.is_file() else None
    if require_limits:
        if limits["memory.max"] != "536870912" or limits["pids.max"] != "64":
            raise ValueError("Qualification requires observed 512 MiB memory and 64-process cgroup limits")
        cpu = limits["cpu.max"].split() if limits["cpu.max"] else []
        if len(cpu) != 2 or cpu[0] == "max" or int(cpu[0]) / int(cpu[1]) != 1:
            raise ValueError("Qualification requires an observed one-CPU quota")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "scipy": version("scipy"),
        "cgroup": limits,
        "blas_threads": {
            name: os.getenv(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


class Sampler:
    def __init__(self, cache, workers, reader):
        self.cache, self.workers, self.reader = cache, workers, reader
        self.stop = threading.Event()
        self.samples = self.rss_peak = self.admission_peak = self.pending_peak = 0
        self.cgroup_peak = None
        self.failed = False

    def capture(self):
        try:
            memory = self.reader.read()
            self.rss_peak = max(self.rss_peak, memory["rss_bytes"])
            if memory["cgroup_memory_bytes"] is not None:
                self.cgroup_peak = max(self.cgroup_peak or 0, memory["cgroup_memory_bytes"])
            self.admission_peak = max(self.admission_peak, self.cache.snapshot()["accounted_bytes"])
            with self.workers.lock:
                self.pending_peak = max(self.pending_peak, self.workers.pending)
            self.samples += 1
        except (OSError, ValueError, KeyError, TypeError):
            self.failed = True

    def poll(self):
        while not self.stop.wait(0.005):
            self.capture()

    def __enter__(self):
        self.capture()
        if self.failed:
            raise ValueError("Resource sampling failed before the request")
        self.thread = threading.Thread(target=self.poll, name="ubi-rss-sampler", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        self.capture()
        if self.failed:
            raise ValueError("Resource sampling failed during the request")
        high_water = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.lifetime_rss = high_water if platform.system() == "Darwin" else high_water * 1024

    def report(self):
        return {
            "samples": self.samples,
            "sampled_rss_peak_bytes": self.rss_peak,
            "sampled_cgroup_memory_peak_bytes": self.cgroup_peak,
            "sampled_admission_peak_bytes": self.admission_peak,
            "sampled_pending_peak": self.pending_peak,
            "process_lifetime_high_water_rss_bytes": self.lifetime_rss,
            "sampling_interval_seconds": 0.005,
        }


def validate_plan(plan):
    if not isinstance(plan, list) or not 1 <= len(plan) <= 16:
        raise ValueError("Use 1–16 explicit study workloads")
    names = set()
    for row in plan:
        if not isinstance(row, dict) or set(row) != {"id", "operation", "params", "expected"}:
            raise ValueError("Every workload requires id, operation, params and expected")
        if (
            not isinstance(row["id"], str)
            or not re.fullmatch(r"[a-z0-9_-]{1,40}", row["id"])
            or row["id"] in names
        ):
            raise ValueError("Workload identifiers must be distinct and bounded")
        names.add(row["id"])
        if row["operation"] not in MODELS["study"] or row["operation"] == "list":
            raise ValueError("Use supported scientific study operations")
        if not isinstance(row["expected"], str) or not re.fullmatch(r"[a-z_]{1,80}", row["expected"]):
            raise ValueError("Expected outcomes must be success or a declared error code")
        MODELS["study"][row["operation"]].model_validate(row["params"])
        if row["params"].get("chart"):
            raise ValueError("Native resource workloads do not include chart rendering")
    return plan


def inputs(manifest, root):
    modules = (study, study_storage, study_statistics, studies, study_workers)
    return {
        "manifest_sha256": sha(bounded_read(manifest, 1_000_000).encode()),
        "release_metadata_sha256": sha(json.dumps(studies.release_fingerprint(manifest, root)).encode()),
        "implementation_sha256": {
            "src/" + module.__name__.replace(".", "/") + ".py": sha(
                Path(inspect.getfile(module)).read_bytes()
            )
            for module in modules
        },
        "request_contract_sha256": sha(Path(inspect.getfile(ExtendedSources)).read_bytes()),
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "lock_sha256": sha((ROOT / "uv.lock").read_bytes()),
    }


def outcome(function, operation, request):
    try:
        result = function(operation, request)
        raw = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return {
            "status": "success",
            "result_sha256": sha(raw),
            "serialized_bytes": len(raw),
            "clinical_samples": result.get("clinical_samples"),
            "total_samples": result.get("total_samples"),
        }
    except ResearchError as exc:
        return {"status": exc.code, "result_sha256": None, "serialized_bytes": None}


async def measured(analytics, workers, reader, operation, request, width=1):
    with Sampler(analytics.cache, workers, reader) as sampler:
        started = time.perf_counter_ns()
        results = await asyncio.gather(
            *[workers.run(outcome, analytics.run, operation, request) for _ in range(width)]
        )
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
    if len({json.dumps(row, sort_keys=True) for row in results}) != 1:
        raise ValueError("Concurrent scientific results diverged")
    state = analytics.cache.snapshot()
    if state["building"] or state["pinned_entries"] or state["accounted_bytes"] != state["retained_bytes"]:
        raise ValueError("Study reservations or leases survived completed work")
    if state["peak_accounted_bytes"] > state["budget_bytes"] or sampler.pending_peak > workers.max_pending:
        raise ValueError("Study admission exceeded its declared resource bounds")
    return {
        "milliseconds": elapsed,
        "width": width,
        "outcome": results[0],
        "memory": sampler.report(),
        "cache": state,
    }


async def wait_until(predicate, seconds=5):
    end = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= end:
            raise ValueError("Controlled lifecycle did not reach its required state")
        await asyncio.sleep(0.002)


async def lifecycle(analytics, workers, operation, request):
    """Injected gate verifies real leases/admission; never report its duration as latency."""
    original, release, entered = analytics._run, threading.Event(), []
    lock = threading.Lock()
    tasks = []

    def gated(*args):
        view = analytics.load(request.study)
        view["samples"]
        with lock:
            entered.append(True)
        if not release.wait(10):
            raise ValueError("Controlled lifecycle gate expired")
        return original(*args)

    analytics._run = gated
    try:
        tasks = [
            asyncio.create_task(workers.run(outcome, analytics.run, operation, request)) for _ in range(4)
        ]
        await wait_until(lambda: len(entered) == 2 and workers.pending == 4)
        try:
            await workers.run(lambda: None)
        except ResearchError as exc:
            if exc.code != "provider_busy":
                raise ValueError("Backlog admission returned the wrong error") from None
        else:
            raise ValueError("A fifth continuing task was admitted")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await wait_until(lambda: workers.pending == 2)
        retained = analytics.cache.snapshot()
        if (
            retained["pinned_entries"] < 1
            or retained["accounted_bytes"]
            < retained["retained_bytes"] + 2 * study_storage.ANALYSIS_RESERVATION
        ):
            raise ValueError("Cancellation released live study memory admission")
        release.set()
        await wait_until(lambda: workers.pending == 0)
        final = analytics.cache.snapshot()
        if (
            final["pinned_entries"]
            or final["building"]
            or final["accounted_bytes"] != final["retained_bytes"]
        ):
            raise ValueError("Controlled lifecycle retained finished-work reservations")
        return {
            "controlled_gate": True,
            "latency_measurement": False,
            "two_workers_entered": len(entered) == 2,
            "maximum_running_and_queued": 4,
            "fifth_task_rejected": True,
            "after_waiter_cancellation": retained,
            "continuing_workers_after_cancellation": 2,
            "final_cache": final,
        }
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        workers.close()
        analytics._run = original


@contextmanager
def configuration(manifest, root):
    values = {"UBI_PUBLIC_STUDY_MANIFEST": str(manifest), "UBI_PUBLIC_STUDY_DIR": str(root)}
    before = {key: os.getenv(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def benchmark(manifest, root, plan, *, repeats=5, require_limits=False, reader=None):
    validate_plan(plan)
    if not isinstance(repeats, int) or not 2 <= repeats <= 10:
        raise ValueError("Use 2–10 warm repetitions")
    enabled = [
        entry
        for entry in manifest_entries(bounded_read(manifest, 1_000_000).encode())
        if entry.get("enabled")
    ]
    if not enabled:
        raise ValueError("Benchmark requires an enabled reviewed release")
    for entry in enabled:
        require_data_rights(entry)
    reader = reader or LinuxMemory()
    hardware = environment(require_limits)
    with configuration(manifest, root):
        before = inputs(manifest, root)
        # A standalone benchmark owns this registry view; force the initial
        # all-member checksum pass even if called after a local installation.
        with studies._verification_lock:
            studies._verified.pop((str(manifest.resolve()), str(root.resolve())), None)
        workers, cache = study_workers.StudyWorkers(), study_storage.StudyCache()
        try:
            with Sampler(cache, workers, reader) as sampler:
                started = time.perf_counter_ns()
                registry = await workers.run(studies.load_studies)
                verification_ms = (time.perf_counter_ns() - started) / 1_000_000
            validator = ReviewedStudyBenchmark()
            validator._studies = registry
            analytics = study.StudyAnalytics(registry=registry, cache=cache)
            records = []
            for row in plan:
                request = validator.validate("study", row["operation"], row["params"])
                analytics.cache = study_storage.StudyCache()
                cold = await measured(analytics, workers, reader, row["operation"], request)
                warm = [
                    await measured(analytics, workers, reader, row["operation"], request)
                    for _ in range(repeats)
                ]
                concurrent = await measured(analytics, workers, reader, row["operation"], request, width=4)
                phases = [cold, *warm, concurrent]
                if any(phase["outcome"]["status"] != row["expected"] for phase in phases):
                    raise ValueError("Workload did not produce its declared scientific outcome")
                if any(phase["outcome"] != cold["outcome"] for phase in phases):
                    raise ValueError("Cold, warm and concurrent scientific results diverged")
                records.append(
                    {
                        "workload": row,
                        "cold": cold,
                        "warm": warm,
                        "concurrent_warm": concurrent,
                        "warm_median_ms": statistics.median(phase["milliseconds"] for phase in warm),
                    }
                )
            eligible = next((row for row in plan if row["expected"] == "success"), None)
            controlled = None
            if eligible is not None:
                request = validator.validate("study", eligible["operation"], eligible["params"])
                controlled = await lifecycle(analytics, workers, eligible["operation"], request)
            if inputs(manifest, root) != before:
                raise ValueError("Study or implementation inputs changed during measurement")
            return {
                "schema_version": 1,
                "scientific_revision": REVISION,
                "inputs": before,
                "plan_sha256": sha(json.dumps(plan, sort_keys=True).encode()),
                "data_permissions": {name: release["data_rights"] for name, release in registry.items()},
                "provider_integrations_enabled": False,
                "hardware": hardware,
                "initial_verification": {"milliseconds": verification_ms, "memory": sampler.report()},
                "workloads": records,
                "controlled_lifecycle": controlled,
                "measurement": {
                    "scope": "Native study queries in the actual bounded executor, including release revalidation; no MCP/network/model latency",
                    "rss_source": "/proc/self/smaps_rollup Rss; phase samples plus start/end snapshots; short peaks may be missed",
                    "cgroup_memory": "Whole cgroup charge, including filesystem pages; distinct from process RSS",
                    "cold": "Empty parsed-component cache; filesystem cache is not reset and verification reads every approved member",
                    "warm": "Shared parsed components/indexes; the native service still revalidates release metadata",
                    "instrumentation": "RSS/cache/admission sampling and output hashing overhead included; no timing CI thresholds",
                    "cleanup": "No forced garbage collection or allocator trimming; ordinary interpreter cleanup and retained allocations remain observable",
                    "scientific_limit": "Stable result hashes and declared outcomes do not establish clinical correctness or assay callability",
                    "provider_requests": 0,
                },
            }
        finally:
            workers.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--require-container-limits", action="store_true")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Choose a fresh output path; existing evidence is never overwritten")
    try:
        plan = json.loads(bounded_read(args.plan, 65_536))
        report = asyncio.run(
            benchmark(
                args.manifest.resolve(),
                args.root.resolve(),
                plan,
                repeats=args.repeats,
                require_limits=args.require_container_limits,
            )
        )
        raw = json.dumps(report, indent=2, allow_nan=False).encode() + b"\n"
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Report exceeds its output budget")
        with args.output.open("xb") as handle:
            handle.write(raw)
    except (OSError, ValueError, KeyError, TypeError, ResearchError):
        parser.error("Resource measurement failed; inspect the reviewed inputs and runtime configuration")
    print(
        json.dumps(
            {"workloads": len(report["workloads"]), "provider_requests": 0, "output": str(args.output)}
        )
    )


if __name__ == "__main__":
    main()
