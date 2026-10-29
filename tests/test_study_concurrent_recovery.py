"""Actual caller regressions for concurrent study reads and evidence recovery."""

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from fastmcp import Client

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.runtime import digest
from biomedmcp.study_workers import StudyWorkers


def changed_coverage():
    path = Path(os.environ["UBI_PUBLIC_STUDY_MANIFEST"])
    value = json.loads(path.read_text())
    value["studies"][0]["mutation_coverage"]["samples"] = ["S1", "S3", "S4"]
    path.write_text(json.dumps(value))


async def entered(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.005)


async def test_verified_release_remains_readable_during_refresh(study, monkeypatch):
    _, install = study
    install()
    service = ResearchService()
    registry = await service.extensions.initialize_studies()
    from biomedmcp import studies, study_workers

    original = studies.study_registry
    started, release = threading.Event(), threading.Event()
    workers = StudyWorkers(workers=1, max_pending=1)
    monkeypatch.setattr(study_workers, "study_workers", workers)

    def blocking():
        started.set()
        assert release.wait(3)
        return original()

    monkeypatch.setattr(studies, "study_registry", blocking)
    task = asyncio.create_task(service.extensions.initialize_studies())
    try:
        await entered(started)
        assert service.extensions.studies() == registry
        release.set()
        assert await task == registry
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()


async def test_cancelled_warm_refresh_keeps_verified_view_then_rechecks(study, monkeypatch):
    _, install = study
    install()
    service = ResearchService()
    registry = await service.extensions.initialize_studies()
    from biomedmcp import studies, study_workers

    original = studies.load_studies
    started, release = threading.Event(), threading.Event()
    workers = StudyWorkers(workers=1, max_pending=2)
    monkeypatch.setattr(study_workers, "study_workers", workers)

    def blocking():
        started.set()
        assert release.wait(3)
        return original()

    monkeypatch.setattr(studies, "load_studies", blocking)
    task = asyncio.create_task(service.extensions.initialize_studies(recheck=True))
    try:
        await entered(started)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.extensions.studies() == registry
        release.set()
        assert await service.extensions.initialize_studies() == registry
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()


@pytest.mark.parametrize("warm", [False, True])
async def test_failed_verification_never_exposes_a_healthy_previous_registry(study, warm):
    directory, install = study
    install()
    service = ResearchService()
    if warm:
        await service.extensions.initialize_studies()
    path = directory / "data_mutations.txt"
    path.write_text(path.read_text().replace("TP53", "FAKE"))
    with pytest.raises(ResearchError) as invalid:
        await service.extensions.initialize_studies(recheck=True)
    assert invalid.value.code == "study_version_changed"
    with pytest.raises(ResearchError) as unready:
        service.extensions.studies()
    assert unready.value.code == "study_not_ready"


@pytest.mark.parametrize("warm", [False, True])
async def test_actual_mcp_concurrent_get_profile_and_cohort_preserve_science(study, monkeypatch, warm):
    _, install = study
    install()
    monkeypatch.setenv("UBI_PROFILE", "local")
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        if warm:
            await client.call_tool("capabilities", {"source": "study"})
        values = await asyncio.gather(
            client.call_tool("get", {"entity": "study", "id": "ubi_synthetic", "sources": ["study"]}),
            client.call_tool(
                "study_analysis", {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}
            ),
            client.call_tool(
                "study_analysis", {"analysis": "mutation_cohort", "study": "ubi_synthetic", "gene": "TP53"}
            ),
        )
        record, profile, cohort = [value.structured_content for value in values]
        assert record["outcome"] == profile["outcome"] == cohort["outcome"] == "data"
        assert record["sections"]["record"]["data"]["release"] == "synthetic-v1"
        measured = profile["sections"]["study"]["data"]
        assert measured["total_samples"] == 4 and measured["unique_samples"] == 2
        assert measured["mutation_count"] == 2 and measured["frequency"] == 0.5
        assert cohort["sections"]["study"]["data"]["mutant_samples"] == ["S1", "S2"]
        assert all(value["provenance"][0]["source"] == "study" for value in [record, profile, cohort])


async def test_acquisition_rejects_a_release_change_without_mixing_cache_identity(study, monkeypatch):
    _, install = study
    install()
    service = ResearchService()
    registry = await service.extensions.initialize_studies()
    started, release = asyncio.Event(), asyncio.Event()
    original = service.providers.record
    acquired, keys = [], []

    async def blocking(*args, **kwargs):
        started.set()
        await release.wait()
        acquired.append(service.extensions.studies())
        return await original(*args, **kwargs)

    invoke = service.runtime.invoke

    async def recording(source, key, *args, **kwargs):
        if source == "study":
            keys.append(key)
        return await invoke(source, key, *args, **kwargs)

    monkeypatch.setattr(service.providers, "record", blocking)
    monkeypatch.setattr(service.runtime, "invoke", recording)
    task = asyncio.create_task(
        execute(service, "get", {"entity": "study", "id": "ubi_synthetic"}, scope="public")
    )
    try:
        async with asyncio.timeout(3):
            await started.wait()
        changed_coverage()
        replacement = await service.extensions.initialize_studies()
        assert replacement != registry
        release.set()
        result = await task
        assert acquired == [registry]
        assert keys[0]["study_registry"] == digest(registry)
        assert result.sections["record"].outcome == "error"
        assert result.sections["record"].error["code"] == "study_version_changed"
        assert result.sections["record"].data is None and not result.provenance
        cache_key = digest({"source": "study", "params": keys[0], "scope": "public"})
        assert await service.runtime.cache.get(cache_key) is None
        assert service.extensions.studies() == replacement
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_analysis_rejects_a_change_between_admission_and_worker_start(study, monkeypatch):
    _, install = study
    install()
    from biomedmcp.native.study import StudyAnalytics

    service = ResearchService()
    registry = await service.extensions.initialize_studies()
    started, release = threading.Event(), threading.Event()
    original = StudyAnalytics.run
    admitted = []

    def blocking(self, operation, request, *, registry=None):
        admitted.append(registry)
        started.set()
        assert release.wait(3)
        return original(self, operation, request, registry=registry)

    monkeypatch.setattr(StudyAnalytics, "run", blocking)
    task = asyncio.create_task(
        execute(
            service,
            "study_analysis",
            {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"},
            scope="public",
        )
    )
    try:
        await entered(started)
        changed_coverage()
        replacement = await service.extensions.initialize_studies()
        assert replacement != registry
        release.set()
        result = await task
        assert admitted == [registry]
        assert result.sections["study"].outcome == "error"
        assert result.sections["study"].error["code"] == "study_version_changed"
        assert result.sections["study"].data is None and not result.provenance
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_failed_refresh_does_not_erase_an_inflight_verified_context(study, monkeypatch):
    _, install = study
    install()
    service = ResearchService()
    registry = await service.extensions.initialize_studies()
    from biomedmcp import studies

    started, release = asyncio.Event(), asyncio.Event()
    original = service.providers.record

    async def blocking(*args, **kwargs):
        started.set()
        await release.wait()
        assert service.extensions.studies() == registry
        return await original(*args, **kwargs)

    def failed():
        raise ResearchError("study_version_changed", "Synthetic verification failure.")

    monkeypatch.setattr(service.providers, "record", blocking)
    task = asyncio.create_task(
        execute(service, "get", {"entity": "study", "id": "ubi_synthetic"}, scope="public")
    )
    try:
        async with asyncio.timeout(3):
            await started.wait()
        monkeypatch.setattr(studies, "load_studies", failed)
        with pytest.raises(ResearchError, match="Synthetic verification failure"):
            await service.extensions.initialize_studies(recheck=True)
        with pytest.raises(ResearchError) as unready:
            service.extensions.studies()
        assert unready.value.code == "study_not_ready"
        release.set()
        result = await task
        assert result.sections["record"].outcome == "data"
        # The request's ContextVar must not leak back into the caller.
        with pytest.raises(ResearchError):
            service.extensions.studies()
        assert await service.extensions.initialize_studies() == registry
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_mutation_profile_snapshot_recovers_original_class_counts(study, monkeypatch):
    _, install = study
    install()
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        result = await client.call_tool(
            "study_analysis", {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}
        )
        section = result.structured_content["sections"]["study"]
        assert section["outcome"] == "data"
        assert section["recovery"]["snapshot_status"] == "available"
        root = json.loads((await client.read_resource(section["recovery"]["uri"]))[0].text)
        classes = next(item["uri"] for item in root["children"] if item["field"] == "top_variant_classes")
        recovered = json.loads((await client.read_resource(classes))[0].text)
        assert recovered["value"] == section["data"]["top_variant_classes"]
        assert sum(count for _, count in recovered["value"]) == section["data"]["mutation_count"] == 2
        assert root["evidence_ids"] == section["evidence_ids"]
