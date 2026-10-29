"""Public study resource/lifecycle outcomes, independently of cache internals."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_native_studies import request

from biomedmcp.errors import ResearchError
from biomedmcp.native.study_storage import MIB, StudyCache
from biomedmcp.study_workers import StudyWorkers


def test_verified_mutation_profile_parses_only_its_required_modalities(study, monkeypatch):
    _, install = study
    analytics = install()
    original = analytics.table
    reads = []

    def record(directory, name, *args, **kwargs):
        reads.append(name)
        return original(directory, name, *args, **kwargs)

    monkeypatch.setattr(analytics, "table", record)
    result = analytics.run("query", request(gene="TP53"))
    assert result["mutation_count"] == 2
    assert set(reads) == {"data_clinical_sample.txt", "data_mutations.txt"}


def test_mutation_analysis_does_not_open_unused_assays_even_for_verification(study, monkeypatch):
    directory, install = study
    analytics = install()
    analytics.cache = StudyCache()
    original, reads = Path.open, []

    def record(path, *args, **kwargs):
        if path.parent == directory:
            reads.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record)
    cold = analytics.run("query", request(gene="TP53"))
    warm = analytics.run("query", request(gene="TP53"))
    assert cold == warm and cold["mutation_count"] == 2
    assert set(reads) == {"data_clinical_sample.txt", "data_mutations.txt"}


@pytest.mark.parametrize(
    "filename,arguments,old,new",
    [
        ("data_mutations.txt", {"gene": "TP53"}, b"TP53", b"FAKE"),
        ("data_cna.txt", {"gene": "ERBB2", "type": "cna"}, b"ERBB2", b"FAKE2"),
        (
            "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt",
            {"gene": "ERBB2", "type": "expression"},
            b"ERBB2",
            b"FAKE2",
        ),
        ("data_clinical_sample.txt", {"gene": "TP53"}, b"S1", b"X1"),
    ],
)
def test_cached_consumed_member_tampering_with_unchanged_metadata_fails_closed(
    study, monkeypatch, filename, arguments, old, new
):
    directory, install = study
    analytics = install()
    analytics.run("query", request(**arguments))
    path = directory / filename
    before, original_lstat = path.lstat(), Path.lstat
    original = path.read_bytes()
    altered = original.replace(old, new)
    assert altered != original and len(altered) == len(original)
    path.write_bytes(altered)

    def unchanged_metadata(candidate, *args, **kwargs):
        return before if candidate == path else original_lstat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unchanged_metadata)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(**arguments))
    assert caught.value.code == "study_version_changed"
    assert analytics.cache.snapshot()["pinned_entries"] == 0


def test_warm_member_checksums_are_not_serialized_by_registry_lock(study, monkeypatch):
    _, install = study
    analytics = install()
    analytics.run("query", request(gene="TP53"))
    from biomedmcp.native import study as native_study

    original = native_study.verify_study_member
    barrier = threading.Barrier(2, timeout=2)
    local = threading.local()

    def simultaneous(path, expected):
        if not getattr(local, "entered", False):
            local.entered = True
            barrier.wait()
        return original(path, expected)

    monkeypatch.setattr(native_study, "verify_study_member", simultaneous)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(analytics.run, "query", request(gene="TP53"))
        right = pool.submit(analytics.run, "query", request(gene="KRAS"))
        assert left.result()["mutation_count"] == 2
        assert right.result()["mutation_count"] == 1


def test_unused_changed_assay_still_invalidates_installed_release(study):
    directory, install = study
    analytics = install()
    analytics.run("query", request(gene="TP53"))
    path = directory / "data_cna.txt"
    path.write_bytes(path.read_bytes().replace(b"ERBB2", b"FAKE2"))
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_version_changed"


def test_cached_reads_can_enter_analysis_concurrently(study, monkeypatch):
    _, install = study
    analytics = install()
    analytics.run("query", request(gene="TP53"))
    original = analytics._run
    both, release = threading.Event(), threading.Event()
    entered = []
    lock = threading.Lock()

    def blocked(*args, **kwargs):
        with lock:
            entered.append(True)
            if len(entered) == 2:
                both.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(analytics, "_run", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(analytics.run, "query", request(gene="TP53"))
        right = pool.submit(analytics.run, "query", request(gene="KRAS"))
        try:
            concurrent = both.wait(0.5)
        finally:
            release.set()
        assert left.result()["mutation_count"] == 2
        assert right.result()["mutation_count"] == 1
    assert concurrent


def test_separate_service_instances_share_verified_tables(study, monkeypatch):
    _, install = study
    first = install()
    cache = first.cache = StudyCache()
    expected = first.run("query", request(gene="TP53"))
    second = install()
    second.cache = cache

    def forbidden(*args, **kwargs):
        raise AssertionError("A verified cached table must not be parsed again")

    monkeypatch.setattr(second, "table", forbidden)
    assert second.run("query", request(gene="TP53")) == expected


def test_patient_table_is_only_required_for_survival(study, monkeypatch):
    _, install = study
    analytics = install()
    analytics.cache = StudyCache()
    original, reads = analytics.table, []

    def record(directory, name, **kwargs):
        reads.append(name)
        return original(directory, name, **kwargs)

    monkeypatch.setattr(analytics, "table", record)
    analytics.run("compare", request(gene="TP53", target="ERBB2", type="expression"))
    assert "data_clinical_patient.txt" not in reads
    analytics.run("survival", request(gene="TP53"))
    assert reads.count("data_clinical_patient.txt") == 1


def test_matrix_cache_retains_index_and_requested_row_not_unused_values(study):
    directory, install = study
    path = directory / "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt"
    path.write_text(
        "Hugo_Symbol\tS1\tS2\tS3\tS4\tannotation\n"
        + "ERBB2\t1\t2\t3\t4\tsmall\n"
        + "".join(f"G{i}\t1\t2\t3\t4\t{'x' * 100_000}\n" for i in range(40))
    )
    analytics = install()
    analytics.cache = StudyCache()
    result = analytics.run("query", request(gene="ERBB2", type="expression"))
    assert result["values"] == {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
    state = analytics.cache.snapshot()
    assert state["retained_bytes"] < path.stat().st_size / 4
    assert state["pinned_entries"] == state["building"] == 0
    assert state["accounted_bytes"] == state["retained_bytes"]


def test_gene_named_index_does_not_collide_with_matrix_locator_cache(study):
    directory, install = study
    path = directory / "data_cna.txt"
    path.write_text(path.read_text().replace("ERBB2", "index"))
    result = install().run("query", request(gene="index", type="cna"))
    assert result["values"]["S1"] == 2


def test_returned_records_cannot_mutate_shared_cache(study):
    directory, install = study
    (directory / "data_sv.txt").write_text("Site1_Hugo_Symbol\tSite2_Hugo_Symbol\tSample_Id\nALK\tEML4\tS1\n")
    analytics = install()
    first = analytics.run("query", request(gene="ALK", type="sv"))
    assert first["records"]
    first["records"][0]["Site1_Hugo_Symbol"] = "FORGED"
    first["release"]["release"] = "FORGED"
    second = analytics.run("query", request(gene="ALK", type="sv"))
    assert second["records"][0]["Site1_Hugo_Symbol"] != "FORGED"
    assert second["release"]["release"] == "synthetic-v1"


def test_tampering_between_verification_and_parsing_cannot_poison_cache(study, monkeypatch):
    directory, install = study
    analytics = install()
    analytics.cache = StudyCache()
    path = directory / "data_mutations.txt"
    original_bytes, table = path.read_bytes(), analytics.table

    def tamper(directory, name, **kwargs):
        if name == "data_mutations.txt":
            path.write_bytes(original_bytes.replace(b"TP53", b"FAKE"))
        return table(directory, name, **kwargs)

    monkeypatch.setattr(analytics, "table", tamper)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_version_changed"
    assert analytics.cache.snapshot()["building"] == 0
    path.write_bytes(original_bytes)
    monkeypatch.setattr(analytics, "table", table)
    assert analytics.run("query", request(gene="TP53"))["mutation_count"] == 2


def test_release_change_during_analysis_never_returns_healthy_result(study, monkeypatch):
    directory, install = study
    analytics = install()
    original = analytics._run

    def tamper(*args):
        result = original(*args)
        path = directory / "data_mutations.txt"
        path.write_bytes(path.read_bytes().replace(b"TP53", b"FAKE"))
        return result

    monkeypatch.setattr(analytics, "_run", tamper)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_version_changed"
    assert analytics.cache.snapshot()["pinned_entries"] == 0


def test_release_metadata_is_local_to_each_concurrent_analysis(study, monkeypatch):
    _, install = study
    analytics = install()
    original, entered, release = analytics._run, threading.Event(), threading.Event()

    def block(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(analytics, "_run", block)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(analytics.run, "query", request(gene="TP53"))
        try:
            assert entered.wait(1)
            analytics.registry = {"ubi_synthetic": {"release": "other concurrent view"}}
        finally:
            release.set()
        result = task.result()
    assert result["release"]["release"] == "synthetic-v1"


@pytest.mark.parametrize(
    "table,contents",
    [
        ("data_mutations.txt", "Hugo_Symbol\tTumor_Sample_Barcode\nTP53\n"),
        ("data_mutations.txt", "Hugo_Symbol\tHugo_Symbol\tTumor_Sample_Barcode\nTP53\tTP53\tS1\n"),
        ("data_cna.txt", 'Hugo_Symbol\tS1\n"ERBB2\npart"\t2\n'),
        ("data_cna.txt", "Hugo_Symbol\tS1\nERBB2\t2\textra\n"),
        ("data_cna.txt", "Hugo_Symbol\tS1\tS1\nERBB2\t2\t2\n"),
    ],
)
def test_malformed_installed_tables_fail_closed(study, table, contents):
    directory, install = study
    (directory / table).write_text(contents)
    analytics = install()
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="ERBB2", type="cna") if table == "data_cna.txt" else request())
    assert caught.value.code == "invalid_study"


def test_payload_admission_failure_releases_analysis_and_builder_reservations(study):
    _, install = study
    analytics = install()
    # Analysis + parser exactly fill the budget; no retained row can fit.
    analytics.cache = StudyCache(budget=64 * MIB)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_budget_exceeded"
    state = analytics.cache.snapshot()
    assert state["accounted_bytes"] == state["building"] == state["pinned_entries"] == 0
    assert state["peak_accounted_bytes"] <= state["budget_bytes"]


async def test_cancelled_analysis_retains_payload_and_worker_admission_until_it_finishes(study, monkeypatch):
    _, install = study
    analytics = install()
    analytics.cache = StudyCache()
    original, entered, release = analytics.table, threading.Event(), threading.Event()
    workers = StudyWorkers(workers=1, max_pending=1)

    def block(directory, name, **kwargs):
        if name == "data_mutations.txt":
            entered.set()
            assert release.wait(3)
        return original(directory, name, **kwargs)

    monkeypatch.setattr(analytics, "table", block)
    task = asyncio.create_task(workers.run(analytics.run, "query", request(gene="TP53")))
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state = analytics.cache.snapshot()
        assert state["building"] == state["pinned_entries"] == 1
        assert state["accounted_bytes"] > 64 * MIB
        assert workers.pending == 1
        with pytest.raises(ResearchError) as caught:
            await workers.run(analytics.run, "query", request(gene="KRAS"))
        assert caught.value.code == "provider_busy"
        release.set()
        for _ in range(200):
            if workers.pending == 0:
                break
            await asyncio.sleep(0.005)
        assert workers.pending == 0
        state = analytics.cache.snapshot()
        assert state["building"] == state["pinned_entries"] == 0
        assert state["accounted_bytes"] == state["retained_bytes"]
        assert (await workers.run(analytics.run, "query", request(gene="TP53")))["mutation_count"] == 2
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()


async def test_cancelled_queued_study_releases_queue_slot_without_parsing(study):
    _, install = study
    analytics = install()
    analytics.cache = StudyCache()
    workers = StudyWorkers(workers=1, max_pending=2)
    entered, release = threading.Event(), threading.Event()

    def block():
        entered.set()
        assert release.wait(3)

    running = asyncio.create_task(workers.run(block))
    queued = None
    try:
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        queued = asyncio.create_task(workers.run(analytics.run, "query", request(gene="TP53")))
        await asyncio.sleep(0)
        assert workers.pending == 2
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert workers.pending == 1
        assert analytics.cache.snapshot()["accounted_bytes"] == 0
    finally:
        release.set()
        await asyncio.gather(*([running, queued] if queued else [running]), return_exceptions=True)
        workers.close()


def test_oversized_record_is_rejected_before_csv_decoding(study, monkeypatch):
    directory, install = study
    from biomedmcp.native import study_storage

    (directory / "data_mutations.txt").write_text(
        "Hugo_Symbol\tTumor_Sample_Barcode\nTP53\t" + "x" * 200 + "\n"
    )
    analytics = install()
    monkeypatch.setattr(study_storage, "MAX_LINE", 100)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_budget_exceeded"


def test_clinical_population_exceeding_workspace_bound_is_handed_off(study, monkeypatch):
    _, install = study
    from biomedmcp.native import study_storage

    analytics = install()
    analytics.cache = StudyCache()
    monkeypatch.setattr(study_storage, "MAX_SAMPLES", 3)
    with pytest.raises(ResearchError) as caught:
        analytics.run("query", request(gene="TP53"))
    assert caught.value.code == "study_budget_exceeded"
    assert analytics.cache.snapshot()["accounted_bytes"] == 0


def test_large_result_is_unavailable_instead_of_claiming_empty_success(study, monkeypatch):
    _, install = study
    import biomedmcp.native.study as native_study

    analytics = install()
    analytics.cache = StudyCache()
    monkeypatch.setattr(native_study, "MAX_RESULT_BYTES", 100)
    with pytest.raises(ResearchError) as caught:
        analytics.run("cohort", request(gene="TP53"))
    assert caught.value.code == "study_budget_exceeded"
    state = analytics.cache.snapshot()
    assert state["pinned_entries"] == state["building"] == 0
