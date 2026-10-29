"""Benchmark correctness/provenance contracts, without timing thresholds."""

import json
import runpy
from pathlib import Path

import pytest
from test_native_studies import request

from biomedmcp.errors import ResearchError

ROOT = Path(__file__).parents[1]
BASELINE = ROOT / "tests/fixtures/statistics/study-audited-0148.txt"


@pytest.fixture
def benchmark():
    return runpy.run_path(str(ROOT / "scripts/benchmark-study-algorithms.py"))


def test_offline_scaling_compares_actual_algorithms_and_preserves_reference_results(benchmark):
    report = benchmark["benchmark"](BASELINE, sizes=[16, 32], repeats=1)
    assert report["validation"]["fixed_logrank_cases"] == 11
    assert report["validation"]["duplicate_and_undeclared_samples_rejected"]
    assert report["workload"]["provider_requests"] == report["workload"]["provider_latency_ms"] == 0
    assert report["inputs_sha256"]["reviewed_study_source"] == benchmark["BASELINE_SHA256"]
    for name in ["mutation_membership", "logrank"]:
        rows = report[name]
        assert [row["n"] for row in rows] == [16, 32]
        assert rows[-1]["growth_from_previous"]["current"]["size_ratio"] == 2
        assert all(len(row[mode]["milliseconds"]) == 1 for row in rows for mode in ["reviewed", "current"])
    json.dumps(report, allow_nan=False)


def test_wrong_baseline_cannot_execute_source(benchmark, tmp_path):
    marker = tmp_path / "executed"
    source = tmp_path / "unknown.txt"
    source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    with pytest.raises(ValueError, match="exact reviewed"):
        benchmark["baseline_methods"](source)
    assert not marker.exists()


def test_changed_inputs_cannot_be_reported_as_qualified_measurements(benchmark, tmp_path, monkeypatch):
    source = tmp_path / "baseline.txt"
    source.write_bytes(BASELINE.read_bytes())
    function = benchmark["benchmark"]
    original = function.__globals__["measure"]

    def mutate(*args):
        source.write_bytes(BASELINE.read_bytes() + b"\n")
        return original(*args)

    monkeypatch.setitem(function.__globals__, "measure", mutate)
    with pytest.raises(ValueError, match="inputs changed"):
        function(source, sizes=[16, 32], repeats=1)


@pytest.mark.parametrize(
    "sizes,repeats",
    [([16], 1), ([32, 16], 1), ([16, 16], 1), ([0, 32], 1), ([16, 8193], 1), ([16, 32], 0), ([16, 32], 11)],
)
def test_benchmark_workload_is_bounded_before_execution(benchmark, sizes, repeats):
    with pytest.raises(ValueError, match="increasing sizes"):
        benchmark["benchmark"](BASELINE, sizes=sizes, repeats=repeats)


def test_existing_output_is_preserved(benchmark, tmp_path):
    output = tmp_path / "report.json"
    output.write_text("existing evidence")
    with pytest.raises(SystemExit):
        benchmark["main"](["--baseline", str(BASELINE), "--output", str(output)])
    assert output.read_text() == "existing evidence"


@pytest.mark.parametrize("change", ["duplicate", "undeclared"])
def test_actual_release_loading_rejects_invalid_sample_identity(study, change):
    directory, install = study
    if change == "duplicate":
        path = directory / "data_clinical_sample.txt"
        path.write_text(path.read_text().replace("P2\tS2", "P2\tS1"))
    else:
        path = directory / "data_mutations.txt"
        path.write_text(path.read_text().replace("S1", "UNDECLARED"))
    with pytest.raises(ResearchError) as caught:
        install().run("query", request(gene="TP53"))
    assert caught.value.code == "invalid_study"


def test_oversized_baseline_is_refused_before_parsing(benchmark, tmp_path):
    source = tmp_path / "oversized.txt"
    source.write_bytes(b" " * 128_001)
    with pytest.raises(ValueError, match="source budget"):
        benchmark["benchmark"](source, sizes=[16, 32], repeats=1)
