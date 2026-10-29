import asyncio
import hashlib
import io
import json
import os
import threading
import time
from pathlib import Path

import pytest

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.study_workers import StudyWorkers


@pytest.mark.asyncio
async def test_slow_verification_is_shared_and_does_not_block_event_loop(study, monkeypatch):
    _, install = study
    install()
    from biomedmcp import studies

    studies._verified.clear()
    original = studies._verify_studies
    calls, ticks = [], []

    def slow(*args):
        calls.append(True)
        time.sleep(0.12)
        return original(*args)

    monkeypatch.setattr(studies, "_verify_studies", slow)
    service = ResearchService()
    started = time.monotonic()

    async def ticker():
        await asyncio.sleep(0.01)
        ticks.append(time.monotonic() - started)

    await asyncio.gather(service.capabilities(), ticker())
    result = await service.extensions.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53"})
    assert result["mutation_count"] == 2
    assert len(calls) == 1
    assert ticks[0] < 0.08


@pytest.mark.asyncio
async def test_discovery_and_first_analysis_share_whole_release_checksums(study, monkeypatch):
    directory, install = study
    install()
    from biomedmcp import studies

    studies._verified.clear()
    original, reads = Path.open, []

    def record(path, *args, **kwargs):
        if path.parent == directory:
            reads.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record)
    first, second = ResearchService(), ResearchService()
    await asyncio.gather(first.capabilities(), second.capabilities())
    unused = {
        "data_cna.txt",
        "data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt",
        "data_clinical_patient.txt",
    }
    assert all(reads.count(name) == 1 for name in unused)
    for service in (first, second):
        result = await service.extensions.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53"})
        assert result["mutation_count"] == 2
    assert all(reads.count(name) == 1 for name in unused)


@pytest.mark.asyncio
async def test_tampered_cached_study_never_returns_old_healthy_measurements(study):
    directory, install = study
    install()
    service = ResearchService()
    await service.extensions.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53"})
    path = directory / "data_mutations.txt"
    path.write_text(path.read_text() + "tampered\n")
    with pytest.raises(ResearchError) as caught:
        await service.extensions.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53"})
    assert caught.value.code == "study_version_changed"


def test_same_size_tampering_with_restored_mtime_is_reverified(study):
    directory, install = study
    analytics = install()
    path = directory / "data_mutations.txt"
    before = path.stat()
    original = path.read_text()
    altered = original.replace("TP53", "FAKE")
    assert altered != original and len(altered) == len(original)
    path.write_text(altered)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    from biomedmcp.studies import load_studies

    with pytest.raises(ResearchError) as caught:
        load_studies()
    assert caught.value.code == "study_version_changed"
    assert analytics.registry["ubi_synthetic"]["release"] == "synthetic-v1"


def test_same_size_tampering_with_unchanged_metadata_is_reverified(study, monkeypatch):
    directory, install = study
    install()
    path = directory / "data_mutations.txt"
    before = path.lstat()
    original_lstat = Path.lstat
    original = path.read_text()
    path.write_text(original.replace("TP53", "FAKE"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    def unchanged_metadata(candidate, *args, **kwargs):
        return before if candidate == path else original_lstat(candidate, *args, **kwargs)

    # Linux filesystems can give rapid writes the same ctime tick. Preserve the
    # entire metadata signature to qualify content verification independently.
    monkeypatch.setattr(Path, "lstat", unchanged_metadata)
    from biomedmcp.studies import load_studies

    with pytest.raises(ResearchError) as caught:
        load_studies()
    assert caught.value.code == "study_version_changed"


@pytest.mark.asyncio
async def test_cancelled_initialization_remains_unready_then_reuses_verified_release(study, monkeypatch):
    _, install = study
    install()
    from biomedmcp import studies, study_workers

    studies._verified.clear()
    original = studies._verify_studies
    entered, release = threading.Event(), threading.Event()
    calls = []
    workers = StudyWorkers(workers=2, max_pending=2)
    monkeypatch.setattr(study_workers, "study_workers", workers)

    def blocking(*args):
        calls.append(True)
        entered.set()
        release.wait(3)
        return original(*args)

    monkeypatch.setattr(studies, "_verify_studies", blocking)
    service = ResearchService()
    task = asyncio.create_task(service.extensions.initialize_studies())
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ResearchError) as unready:
            service.extensions.studies()
        assert unready.value.code == "study_not_ready"
        assert workers.pending == 1
        release.set()
        registry = await service.extensions.initialize_studies()
        assert "ubi_synthetic" in registry and len(calls) == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()


@pytest.mark.asyncio
async def test_changed_verified_coverage_invalidates_cached_scientific_result(study):
    _, install = study
    install()
    service = ResearchService()
    args = {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}
    first = await execute(service, "study_analysis", args, scope="public")
    assert first.sections["study"].data["mutation_count"] == 2
    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    manifest = json.loads(path.read_text())
    manifest["studies"][0]["mutation_coverage"]["samples"] = ["S1", "S3", "S4"]
    path.write_text(json.dumps(manifest))
    second = await execute(service, "study_analysis", args, scope="public")
    assert second.sections["study"].data["mutation_count"] == 1
    assert second.sections["study"].data["total_samples"] == 3
    assert second.provenance[0].evidence_id != first.provenance[0].evidence_id


@pytest.mark.asyncio
async def test_public_result_cache_cannot_hide_consumed_content_tampering(study, monkeypatch):
    directory, install = study
    install()
    service = ResearchService()
    args = {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}
    first = await execute(service, "study_analysis", args, scope="public")
    second = await execute(service, "study_analysis", args, scope="public")
    assert (
        first.sections["study"].data["mutation_count"] == second.sections["study"].data["mutation_count"] == 2
    )
    path = directory / "data_mutations.txt"
    before, original_lstat = path.lstat(), Path.lstat
    path.write_bytes(path.read_bytes().replace(b"TP53", b"FAKE"))

    def unchanged_metadata(candidate, *args, **kwargs):
        return before if candidate == path else original_lstat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unchanged_metadata)
    third = await execute(service, "study_analysis", args, scope="public")
    section = third.sections["study"]
    assert section.outcome == "error"
    assert section.error["code"] == "study_version_changed"
    assert section.data is None


def test_verified_registry_views_cannot_mutate_shared_snapshot(study):
    _, install = study
    analytics = install()
    analytics.registry["ubi_synthetic"]["release"] = "caller mutation"
    from biomedmcp.studies import load_studies

    assert load_studies()["ubi_synthetic"]["release"] == "synthetic-v1"


@pytest.mark.asyncio
async def test_cancelled_worker_retains_admission_until_thread_finishes():
    workers = StudyWorkers(workers=1, max_pending=1)
    entered, release = threading.Event(), threading.Event()

    def blocking():
        entered.set()
        release.wait(3)

    task = asyncio.create_task(workers.run(blocking))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert workers.pending == 1
        with pytest.raises(ResearchError) as caught:
            await workers.run(lambda: None)
        assert caught.value.code == "provider_busy"
        release.set()
        for _ in range(100):
            if workers.pending == 0:
                break
            await asyncio.sleep(0.005)
        assert workers.pending == 0
        assert await workers.run(lambda: "healthy") == "healthy"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()


def test_initial_verification_stops_a_member_that_grows_past_its_budget(tmp_path, monkeypatch):
    from biomedmcp import studies

    root = tmp_path / "studies"
    directory = root / "growing"
    directory.mkdir(parents=True)
    path = directory / "meta_study.txt"
    path.write_bytes(b"tiny")
    files = {path.name: hashlib.sha256(b"tiny").hexdigest()}
    entry = {
        "id": "growing",
        "enabled": True,
        "release": "synthetic",
        "source_url": "https://example.org/synthetic",
        "files": files,
        "sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"studies": [entry]}))
    monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", str(root))
    monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", str(manifest))
    monkeypatch.setattr(studies, "MAX_MEMBER_BYTES", 5)
    original, reads = Path.open, []

    class Growing(io.BytesIO):
        def read(self, size=-1):
            assert not reads, "Verifier kept reading after exceeding the member budget"
            reads.append(size)
            return b"growth"

    def opened(candidate, *args, **kwargs):
        return Growing() if candidate == path else original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(ResearchError, match="Invalid managed study member"):
        studies.load_studies()
    assert len(reads) == 1 and not studies._verification_pending
