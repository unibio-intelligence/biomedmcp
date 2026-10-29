"""Read-only readiness distinguishes evidence from configuration and health."""

import json
import runpy
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastmcp import Client

from biomedmcp import cli
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.native import REVISION

SENTINEL = "diagnosis-credential-sentinel"


@pytest.mark.asyncio
async def test_cli_diagnosis_never_opens_cursor_state_or_provider_http(monkeypatch, tmp_path):
    from biomedmcp import transport
    from biomedmcp.local_state import LocalState

    async def forbidden(*args, **kwargs):
        pytest.fail("Read-only diagnosis opened state or provider HTTP")

    monkeypatch.setattr(LocalState, "open", forbidden)
    monkeypatch.setattr(transport.AsyncClient, "request", forbidden)
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", SENTINEL)
    monkeypatch.setenv("UBI_LOCAL_STATE_DIR", str(tmp_path / "state"))
    value = await cli.execute("diagnose", {"source": "bio-ontology"})
    row = value["diagnosis"][0]
    assert row["configured"] and row["importable"]
    assert row["health"] == "not_probed"
    assert "contract_tested" in row and "recently_live_qualified" in row
    assert not (tmp_path / "state").exists()
    assert SENTINEL not in json.dumps(value)


@pytest.mark.asyncio
async def test_unconfigured_source_can_still_be_importable(monkeypatch):
    monkeypatch.delenv("BIOONTOLOGY_API_KEY", raising=False)
    value = await cli.execute("diagnose", {"source": "bio-ontology"})
    row = value["diagnosis"][0]
    assert row["configured"] is False and row["importable"] is True
    assert row["recently_live_qualified"] is False
    assert row["recovery"] and "BIOONTOLOGY_API_KEY" in json.dumps(row)


@pytest.mark.asyncio
async def test_mcp_diagnosis_keeps_thirteen_tools_and_never_contacts_sources(monkeypatch):
    from biomedmcp import transport

    async def forbidden(*args, **kwargs):
        pytest.fail("Diagnosis contacted a provider")

    monkeypatch.setattr(transport.AsyncClient, "request", forbidden)
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        assert len(await client.list_tools()) == 13
        result = await client.call_tool("capabilities", {"source": "gtex", "diagnose": True})
    row = result.structured_content["diagnosis"][0]
    assert row["source"] == "gtex" and row["health"] == "not_probed"


@pytest.mark.asyncio
async def test_uninstalled_studies_have_a_safe_recovery(monkeypatch, tmp_path):
    monkeypatch.delenv("UBI_PUBLIC_STUDY_MANIFEST", raising=False)
    # An explicitly empty installation replaces the bundled synthetic demo.
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"studies": []}')
    root = tmp_path / "studies"
    root.mkdir()
    monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", str(manifest))
    monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", str(root))
    value = await cli.execute("diagnose", {"source": "study"})
    row = value["diagnosis"][0]
    assert not row["configured"] and row["studies"] == []
    assert "checksummed" in row["recovery"]


def test_readiness_evidence_paths_are_publishable_and_resolve():
    root = Path(__file__).parents[1]
    report = json.loads((root / "docs/capability-readiness.json").read_text())
    for key in ("source_schemas", "architecture", "live_observations"):
        assert (root / "docs" / report[key]).is_file(), key
    for row in report["rows"]:
        for evidence in row["evidence"]:
            if evidence.startswith(("tests/", "docs/")):
                assert (root / evidence).is_file(), evidence


@pytest.mark.asyncio
async def test_unknown_diagnostic_source_fails_before_probe(monkeypatch):
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await cli.execute("diagnose", {"source": SENTINEL})
    assert caught.value.code == "unknown_source" and SENTINEL not in str(caught.value)


def test_missing_and_stale_offline_receipts_do_not_claim_contract_success():
    from biomedmcp.diagnostics import offline_evidence

    probe = {
        "dependencies": {"fastmcp": "4.0.3"},
        "core_sha256": "core",
        "sources": {"gtex": {"implementation_sha256": "gtex", "importable": True}},
    }
    receipt = {
        "implementation": REVISION,
        "dependencies": probe["dependencies"],
        "core_sha256": "core",
        "qualified_at": "2026-10-09T00:00:00+00:00",
        "sources": {
            "gtex": {
                "implementation_sha256": "gtex",
                "scope": "Selected GTEx fixtures",
                "kind": "endpoint_contract",
                "test_count": 1,
                "evidence": ["tests/test_gtex_responses.py"],
            }
        },
    }
    assert offline_evidence(probe, "gtex", receipt)["status"] == "passed"
    for key in ("implementation", "dependencies", "core_sha256"):
        changed = deepcopy(receipt)
        changed[key] = "stale"
        assert offline_evidence(probe, "gtex", changed)["status"] == "stale"
    changed = deepcopy(receipt)
    changed["sources"]["gtex"]["implementation_sha256"] = "stale"
    assert offline_evidence(probe, "gtex", changed)["status"] == "stale"
    receipt["sources"].clear()
    assert offline_evidence(probe, "gtex", receipt)["status"] == "not_recorded"


def live_receipt():
    from biomedmcp.canary import CASES
    from biomedmcp.runtime import digest

    cases = [
        {
            "case": case.name,
            "operation": case.operation,
            "arguments": case.request(),
            "required": True,
            "allow_empty": case.allow_empty,
            "declared_sources": list(case.sources),
        }
        for case in CASES
    ]
    result = {
        "mode": "live",
        "implementation": REVISION,
        "definitions_valid": True,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "definitions_sha256": digest(cases),
        "qualified": True,
        "cases": cases,
    }
    for row in result["cases"]:
        row["observation"] = {
            "executed": True,
            "passed": True,
            "error_codes": [],
            "classification": "healthy_data",
            "participating_sources": row["declared_sources"],
        }
    return result


@pytest.mark.parametrize(
    "change,status",
    [
        ("mode", "unqualified"),
        ("implementation", "unqualified"),
        ("timestamp", "stale"),
        ("future", "stale"),
        ("definitions", "definition_mismatch"),
        ("missing_case", "invalid_receipt"),
        ("arguments", "definition_mismatch"),
        ("failed", "failed"),
        ("not_executed", "failed"),
    ],
)
def test_live_receipts_require_current_definitions_recent_time_and_actual_success(change, status):
    from biomedmcp.diagnostics import live_evidence

    receipt = live_receipt()
    assert live_evidence("gtex", receipt)["status"] == "passed"
    if change == "mode":
        receipt["mode"] = "definitions_only"
    if change == "implementation":
        receipt["implementation"] = "retired"
    if change == "timestamp":
        receipt["retrieved_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    if change == "future":
        receipt["retrieved_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    if change == "definitions":
        receipt["definitions_sha256"] = SENTINEL
    if change == "missing_case":
        receipt["cases"].pop()
    if change == "arguments":
        receipt["cases"][0]["arguments"] = {"secret": SENTINEL}
    if change in {"failed", "not_executed"}:
        row = next(row for row in receipt["cases"] if "gtex" in row["declared_sources"])
        row["observation"]["passed" if change == "failed" else "executed"] = False
    value = live_evidence("gtex", receipt)
    assert value["status"] == status and SENTINEL not in json.dumps(value)


@pytest.mark.parametrize("value", [None, [], {}, {"retrieved_at": SENTINEL}, {"retrieved_at": "2026-10-09"}])
def test_malformed_receipts_are_safe(value, monkeypatch):
    from biomedmcp.diagnostics import live_evidence

    monkeypatch.delenv("UBI_PUBLIC_LIVE_QUALIFICATION", raising=False)
    result = live_evidence("gtex", value)
    assert result["status"] in {"not_recorded", "invalid_receipt"}
    assert SENTINEL not in json.dumps(result)


@pytest.mark.asyncio
async def test_configured_broken_import_is_separate_from_configuration(monkeypatch):
    import biomedmcp.diagnostics as diagnosis

    monkeypatch.setattr(
        diagnosis,
        "import_probe",
        lambda specifications: {
            "sources": {
                name: {"importable": False, "code": "adapter_import_failed"} for name in specifications
            },
            "dependencies": {},
            "core_sha256": "broken",
        },
    )
    result = await cli.execute("diagnose", {"source": "gtex"})
    row = result["diagnosis"][0]
    assert row["configured"] and row["importable"] is False
    assert row["health"] == "not_probed" and not row["recently_live_qualified"]


@pytest.mark.asyncio
async def test_tampered_study_diagnosis_reports_unavailable_without_paths(study):
    directory, install = study
    install()
    (directory / "data_cna.txt").write_text(SENTINEL)
    result = await cli.execute("diagnose", {"source": "study"})
    row = result["diagnosis"][0]
    assert row["configured"] is False and row["studies"] == []
    assert str(directory) not in json.dumps(row) and SENTINEL not in json.dumps(row)


@pytest.mark.asyncio
async def test_explicit_diagnosis_rechecks_unused_bytes_with_unchanged_metadata(study, monkeypatch):
    directory, install = study
    install()
    service = ResearchService()
    await service.extensions.call("study", "query", {"study": "ubi_synthetic", "gene": "TP53"})
    path = directory / "data_cna.txt"
    before, original_lstat = path.lstat(), Path.lstat
    path.write_bytes(path.read_bytes().replace(b"ERBB2", b"FAKE2"))

    def unchanged_metadata(candidate, *args, **kwargs):
        return before if candidate == path else original_lstat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", unchanged_metadata)
    from biomedmcp.diagnostics import diagnose
    from biomedmcp.errors import ResearchError

    result = await diagnose(service, source="study")
    assert not result["diagnosis"][0]["configured"]
    with pytest.raises(ResearchError, match="verification has not completed"):
        service.extensions.studies()


def test_synthetic_demo_installs_and_verifies_without_overwriting(tmp_path, monkeypatch):
    root = Path(__file__).parents[1]
    install = runpy.run_path(str(root / "scripts/install-demo-study.py"))["install"]
    result = install(tmp_path / "demo")
    monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", result["study_root"])
    monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", result["manifest"])
    from biomedmcp.studies import load_studies

    registry = load_studies()
    assert registry["ubi_synthetic"]["release"] == "synthetic-v1"
    assert registry["ubi_synthetic"]["assays"]["cna"]["available"]
    with pytest.raises(ValueError, match="never overwrites"):
        install(tmp_path / "demo")


def test_actual_demo_cli_subprocess_reports_measured_mutation_denominator(tmp_path):
    import os

    from synthetic_permissions import BOOTSTRAP as PERMISSION_BOOTSTRAP

    root = Path(__file__).parents[1]
    install = runpy.run_path(str(root / "scripts/install-demo-study.py"))["install"]
    result = install(tmp_path / "demo")
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            PERMISSION_BOOTSTRAP + "from biomedmcp.cli import main; main()",
            "study_analysis",
            '{"analysis":"gene_profile","study":"ubi_synthetic","gene":"TP53"}',
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
        env={
            **os.environ,
            "UBI_PUBLIC_STUDY_DIR": result["study_root"],
            "UBI_PUBLIC_STUDY_MANIFEST": result["manifest"],
            "UBI_LOCAL_STATE_DIR": str(tmp_path / "state"),
            "UBI_PROFILE": "local",
        },
    )
    assert process.returncode == 0, process.stderr
    value = json.loads(process.stdout)
    assert value["outcome"] == "data" and value["provenance"][0]["source"] == "study"
    measured = value["sections"]["study"]["data"]
    assert measured["denominator"] == "declared mutation-assayed samples"
    assert measured["total_samples"] == 4 and measured["unique_samples"] == 2
    assert measured["frequency"] == 0.5


def test_generated_onboarding_guides_agree_with_shared_examples_and_source_policy():
    from biomedmcp.onboarding import investigations_markdown, matrix_markdown

    root = Path(__file__).parents[1]
    assert (root / "docs/investigations.md").read_text() == investigations_markdown()
    assert (root / "docs/source-access.md").read_text() == matrix_markdown()


@pytest.mark.parametrize("entry", [[], "invalid", {}, {"kind": "inventory", "test_count": True}])
def test_malformed_offline_source_entries_fail_safely(entry):
    from biomedmcp.diagnostics import offline_evidence

    value = offline_evidence({}, "gtex", {"sources": {"gtex": entry}})
    assert value["status"] == "invalid_receipt"


def test_inventory_evidence_does_not_claim_scientific_contract_qualification():
    from biomedmcp.diagnostics import offline_evidence

    probe = {"core_sha256": "core", "dependencies": {}, "sources": {"gtex": {"implementation_sha256": "pkg"}}}
    receipt = {
        "implementation": REVISION,
        "core_sha256": "core",
        "dependencies": {},
        "qualified_at": "date",
        "sources": {
            "gtex": {
                "kind": "inventory",
                "scope": "import only",
                "test_count": 1,
                "implementation_sha256": "pkg",
                "evidence": ["tests/test_adapter_inventory.py"],
            }
        },
    }
    assert offline_evidence(probe, "gtex", receipt)["status"] == "inventory_only"


def test_malformed_participation_cannot_qualify_a_live_source():
    from biomedmcp.diagnostics import live_evidence

    receipt = live_receipt()
    for row in receipt["cases"]:
        row["observation"]["participating_sources"] = None
    assert live_evidence("gtex", receipt)["status"] == "failed"


def test_isolated_import_probe_blocks_network_and_suppresses_raw_import_logs(tmp_path, monkeypatch):
    from biomedmcp.diagnostics import import_probe

    (tmp_path / "diagnosis_network_fixture.py").write_text(
        f"import socket\nprint({SENTINEL!r})\nsocket.create_connection(('127.0.0.1', 1))\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    result = import_probe({"fixture": "diagnosis_network_fixture"})
    assert result["sources"]["fixture"] == {"importable": False, "code": "adapter_import_failed"}
    assert SENTINEL not in json.dumps(result)
    assert not (tmp_path / "__pycache__").exists()


def test_readiness_qualifier_rejects_failed_skipped_and_incomplete_evidence():
    root = Path(__file__).parents[1]
    qualify = runpy.run_path(str(root / "scripts/qualify-readiness.py"))["qualify"]
    for xml in (
        b"<testsuite/>",
        b"<testsuite><testcase name='case'><failure/></testcase></testsuite>",
        b"<testsuite><testcase name='case'><skipped/></testcase></testsuite>",
        b"<testsuite><testcase name='case'/></testsuite>",
    ):
        with pytest.raises(ValueError):
            qualify(xml, probe={})


def test_onboarding_links_resolve_inside_the_public_distribution():
    import re
    from urllib.parse import unquote, urlsplit

    root = Path(__file__).parents[1].resolve()
    names = [
        "README.md",
        *[
            f"docs/{name}.md"
            for name in (
                "connect",
                "studies",
                "investigations",
                "source-access",
                "live-qualification",
                "native-python-architecture",
            )
        ],
    ]
    for name in names:
        path = root / name
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            target = urlsplit(link.strip("<>"))
            if target.scheme or not target.path:
                continue
            destination = (path.parent / unquote(target.path)).resolve()
            assert destination.is_relative_to(root) and destination.exists(), (name, link)
