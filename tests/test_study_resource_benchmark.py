"""Resource protocol correctness; unit samplers are explicitly not RSS evidence."""

import hashlib
import json
import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture
def profiler():
    return runpy.run_path(str(ROOT / "scripts/benchmark-study-resources.py"))


class UnitMemory:
    def read(self):
        return {"rss_bytes": 1000, "cgroup_memory_bytes": None}


def plan(**changes):
    row = {
        "id": "mutation",
        "operation": "query",
        "params": {"study": "ubi_synthetic", "gene": "TP53"},
        "expected": "success",
    }
    return [{**row, **changes}]


async def test_cold_warm_concurrent_and_cancelled_work_preserve_scientific_results(
    profiler, study, monkeypatch
):
    _, install = study
    install()
    from biomedmcp import studies

    original, checksums = studies._verify_studies, []

    def verify(*args):
        checksums.append(True)
        return original(*args)

    monkeypatch.setattr(studies, "_verify_studies", verify)
    report = await profiler["benchmark"](
        Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"]),
        Path(os.environ["UBI_PUBLIC_STUDY_DIR"]),
        plan(),
        repeats=2,
        reader=UnitMemory(),
    )
    record = report["workloads"][0]
    assert len(record["warm"]) == 2 and record["concurrent_warm"]["width"] == 4
    for phase in [record["cold"], *record["warm"], record["concurrent_warm"]]:
        assert phase["outcome"] == record["cold"]["outcome"]
        assert phase["outcome"]["status"] == "success" and phase["outcome"]["clinical_samples"] == 4
        assert phase["cache"]["pinned_entries"] == phase["cache"]["building"] == 0
        assert phase["memory"]["samples"] >= 2
    lifecycle = report["controlled_lifecycle"]
    assert lifecycle["two_workers_entered"] and lifecycle["fifth_task_rejected"]
    assert lifecycle["continuing_workers_after_cancellation"] == 2
    assert lifecycle["final_cache"]["accounted_bytes"] == lifecycle["final_cache"]["retained_bytes"]
    assert lifecycle["final_cache"]["pinned_entries"] == 0
    assert lifecycle["latency_measurement"] is False
    assert report["measurement"]["provider_requests"] == 0
    assert checksums == [True]
    json.dumps(report, allow_nan=False)


async def test_explicit_unavailable_outcome_does_not_become_empty_success(profiler, study):
    _, install = study
    install()
    report = await profiler["benchmark"](
        Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"]),
        Path(os.environ["UBI_PUBLIC_STUDY_DIR"]),
        plan(
            params={"study": "ubi_synthetic", "gene": "ABSENT", "type": "expression"},
            expected="study_gene_unavailable",
        ),
        repeats=2,
        reader=UnitMemory(),
    )
    assert report["controlled_lifecycle"] is None
    assert report["workloads"][0]["cold"]["outcome"]["status"] == "study_gene_unavailable"


@pytest.mark.source_permissions
async def test_reviewed_native_benchmark_preserves_per_release_server_gate(profiler, study):
    from biomedmcp import source_licensing
    from biomedmcp.extensions import ExtendedSources

    _, install = study
    install()
    assert source_licensing.availability("study")[0] is True
    assert ExtendedSources().availability("study")[0] is True
    report = await profiler["benchmark"](
        Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"]),
        Path(os.environ["UBI_PUBLIC_STUDY_DIR"]),
        plan(),
        repeats=2,
        reader=UnitMemory(),
    )
    assert report["data_permissions"]["ubi_synthetic"]["license"] == "CC0-1.0"
    assert report["provider_integrations_enabled"] is False
    assert source_licensing.availability("study")[0] is True


@pytest.mark.parametrize("license", [None, "CC-BY-NC-4.0", "unresolved"])
async def test_native_benchmark_refuses_unknown_or_restricted_data(profiler, study, license):
    _, install = study
    install()
    manifest = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    document = json.loads(manifest.read_text())
    document["studies"][0]["data_rights"]["license"] = license
    manifest.write_text(json.dumps(document))
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await profiler["benchmark"](
            manifest,
            Path(os.environ["UBI_PUBLIC_STUDY_DIR"]),
            plan(),
            repeats=2,
            reader=UnitMemory(),
        )
    assert caught.value.code == "source_license_unreleased"


async def test_wrong_scientific_outcome_cannot_be_reported_as_qualified(profiler, study):
    _, install = study
    install()
    with pytest.raises(ValueError, match="declared scientific outcome"):
        await profiler["benchmark"](
            Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"]),
            Path(os.environ["UBI_PUBLIC_STUDY_DIR"]),
            plan(expected="study_budget_exceeded"),
            repeats=2,
            reader=UnitMemory(),
        )


@pytest.mark.parametrize(
    "bad_plan",
    [
        [],
        plan() * 17,
        plan() * 2,
        plan(id="invalid id"),
        plan(operation="retired"),
        plan(operation="list"),
        plan(expected="invalid status"),
        plan(params={"gene": "x" * 41}),
        plan(params={"study": "ubi_synthetic", "gene": "TP53", "chart": True}),
        [{"id": "missing"}],
    ],
)
def test_workloads_are_bounded_and_preflighted(profiler, bad_plan):
    with pytest.raises(ValueError):
        profiler["validate_plan"](bad_plan)


@pytest.mark.parametrize("repeats", [0, 1, 11])
async def test_repetition_bounds_precede_study_reads(profiler, repeats, tmp_path):
    with pytest.raises(ValueError, match="2–10"):
        await profiler["benchmark"](
            tmp_path / "missing", tmp_path, plan(), repeats=repeats, reader=UnitMemory()
        )


def test_missing_rss_never_becomes_zero(profiler, monkeypatch):
    function = profiler["bounded_read"]
    monkeypatch.setitem(function.__globals__, "bounded_read", lambda path, limit=16_384: "No Rss field\n")
    with pytest.raises(ValueError, match="unavailable"):
        profiler["LinuxMemory"]().read()


def test_sampler_failure_cannot_produce_a_measurement(profiler):
    class BrokenMemory:
        def read(self):
            raise OSError("synthetic unavailable measurement")

    from biomedmcp.native.study_storage import StudyCache
    from biomedmcp.study_workers import StudyWorkers

    workers = StudyWorkers()
    try:
        with (
            pytest.raises(ValueError, match="sampling failed"),
            profiler["Sampler"](StudyCache(), workers, BrokenMemory()),
        ):
            pass
    finally:
        workers.close()


def test_existing_report_is_never_overwritten(profiler, tmp_path):
    output = tmp_path / "report.json"
    output.write_text("existing evidence")
    with pytest.raises(SystemExit):
        profiler["main"](
            ["--manifest", "absent", "--root", "absent", "--plan", "absent", "--output", str(output)]
        )
    assert output.read_text() == "existing evidence"


async def test_changed_manifest_cannot_bind_a_successful_resource_report(profiler, study, monkeypatch):
    _, install = study
    install()
    manifest = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    function = profiler["benchmark"]
    original = function.__globals__["lifecycle"]

    async def change(*args):
        result = await original(*args)
        manifest.write_text(manifest.read_text() + "\n")
        return result

    monkeypatch.setitem(function.__globals__, "lifecycle", change)
    with pytest.raises(ValueError, match="inputs changed"):
        await function(
            manifest, Path(os.environ["UBI_PUBLIC_STUDY_DIR"]), plan(), repeats=2, reader=UnitMemory()
        )


@pytest.mark.parametrize("samples,genes", [(3, 2), (10_001, 2), (4, 1), (4, 1001)])
def test_stress_generator_rejects_unbounded_dimensions_before_writing(tmp_path, samples, genes):
    generator = runpy.run_path(str(ROOT / "scripts/generate-study-resource-fixture.py"))
    destination = tmp_path / "fixture"
    with pytest.raises(ValueError):
        generator["generate"](destination, samples=samples, genes=genes)
    assert not destination.exists()


def test_stress_fixture_is_synthetic_checksums_exact_and_existing_files_preserved(tmp_path, monkeypatch):
    generator = runpy.run_path(str(ROOT / "scripts/generate-study-resource-fixture.py"))
    destination = tmp_path / "fixture"
    result = generator["generate"](destination, samples=20, genes=4)
    manifest = destination / "manifest.json"
    entry = json.loads(manifest.read_text())["studies"][0]
    assert entry["fixture"]["kind"] == "synthetic" and entry["fixture"]["samples"] == 20
    for filename, expected in entry["files"].items():
        assert (
            hashlib.sha256((destination / "studies" / result["study"] / filename).read_bytes()).hexdigest()
            == expected
        )
    with pytest.raises(FileExistsError):
        generator["generate"](destination, samples=20, genes=4)
    monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", str(manifest))
    monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", str(destination / "studies"))
    from biomedmcp.extensions import StudyRequest
    from biomedmcp.native.study import StudyAnalytics

    analytics = StudyAnalytics()
    query = analytics.run("query", StudyRequest(study=result["study"], gene="TP53"))
    assert query["total_samples"] == 20 and query["mutation_count"] == 4


def test_inputs_bind_installed_module_bytes_outside_checkout(profiler, study, monkeypatch, tmp_path):
    _, install = study
    install()
    function = profiler["inputs"]
    globals_ = function.__globals__
    inspect = globals_["inspect"]
    original = inspect.getfile
    relocated = {}
    for name in ("studies", "study_workers", "study", "study_statistics", "study_storage"):
        module = globals_[name]
        path = tmp_path / "site-packages" / (module.__name__.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(original(module)).read_bytes())
        relocated[module.__name__] = path
    manifest = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    root = Path(os.environ["UBI_PUBLIC_STUDY_DIR"])
    before = function(manifest, root)
    monkeypatch.setattr(
        inspect, "getfile", lambda module: str(relocated.get(module.__name__) or original(module))
    )
    assert function(manifest, root) == before
    changed = relocated[globals_["study"].__name__]
    changed.write_bytes(changed.read_bytes() + b"\n# synthetic installed-module change\n")
    after = function(manifest, root)
    assert after["implementation_sha256"] != before["implementation_sha256"]
