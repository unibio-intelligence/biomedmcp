"""Read-only diagnosis. Evidence states never become provider-health claims."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from .errors import ResearchError
from .native import REVISION
from .source_policy import policy, recovery, source_names
from .study_workers import study_workers


def import_probe(specifications):
    try:
        process = subprocess.run(
            [sys.executable, "-m", "biomedmcp.diagnosis_probe"],
            input=json.dumps(specifications),
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return json.loads(process.stdout)
    except (subprocess.SubprocessError, ValueError, OSError):
        raise ResearchError(
            "diagnosis_unavailable", "The isolated import diagnosis could not complete.", retryable=True
        ) from None


def offline_evidence(probe, source, evidence=None):
    if evidence is None:
        path = files("biomedmcp").joinpath("offline-qualification.json")
        try:
            evidence = json.loads(path.read_text())
        except (OSError, ValueError):
            return {"status": "not_recorded", "scope": None}
    if not isinstance(evidence, dict) or not isinstance(evidence.get("sources"), dict):
        return {"status": "invalid_receipt", "scope": None}
    entry = evidence.get("sources", {}).get(source)
    if entry is None:
        return {"status": "not_recorded", "scope": None}
    if (
        not isinstance(entry, dict)
        or entry.get("kind") not in {"endpoint_contract", "inventory"}
        or not isinstance(entry.get("scope"), str)
        or not isinstance(entry.get("test_count"), int)
        or isinstance(entry.get("test_count"), bool)
        or entry["test_count"] < 1
        or not isinstance(entry.get("evidence"), list)
        or not all(isinstance(path, str) for path in entry["evidence"])
        or not isinstance(evidence.get("qualified_at"), str)
    ):
        return {"status": "invalid_receipt", "scope": None}
    if (
        evidence.get("implementation") != REVISION
        or evidence.get("dependencies") != probe["dependencies"]
        or evidence.get("core_sha256") != probe.get("core_sha256")
        or entry.get("implementation_sha256") != probe["sources"][source].get("implementation_sha256")
    ):
        return {"status": "stale", "scope": entry.get("scope")}
    return {
        "status": "passed" if entry.get("kind") == "endpoint_contract" else "inventory_only",
        "scope": entry["scope"],
        "qualified_at": evidence["qualified_at"],
        "test_count": entry["test_count"],
        "evidence": entry["evidence"],
    }


def live_evidence(source, report=None, *, now=None):
    if report is None:
        path = os.getenv("UBI_PUBLIC_LIVE_QUALIFICATION")
        if not path:
            return {"status": "not_recorded"}
        try:
            with Path(path).open("rb") as stream:
                raw = stream.read(1_000_001)
            if len(raw) > 1_000_000:
                return {"status": "invalid_receipt"}
            report = json.loads(raw)
        except (OSError, ValueError):
            return {"status": "invalid_receipt"}
    if not isinstance(report, dict):
        return {"status": "invalid_receipt"}
    try:
        retrieved = datetime.fromisoformat(report["retrieved_at"])
        age = ((now or datetime.now(UTC)) - retrieved).total_seconds()
    except (KeyError, ValueError, TypeError):
        return {"status": "invalid_receipt"}
    if not 0 <= age <= 86400:
        return {"status": "stale"}
    if (
        report.get("mode") != "live"
        or report.get("implementation") != REVISION
        or report.get("definitions_valid") is not True
    ):
        return {"status": "unqualified"}
    from .canary import CASES
    from .runtime import digest

    expected = [
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
    cases = report.get("cases")
    if (
        not isinstance(cases, list)
        or len(cases) != len(expected)
        or any(not isinstance(row, dict) for row in cases)
    ):
        return {"status": "invalid_receipt"}
    actual = [{key: row.get(key) for key in expected[0]} for row in cases]
    if actual != expected or report.get("definitions_sha256") != digest(expected):
        return {"status": "definition_mismatch"}
    # Reports are operator-supplied observations, not a new probe or independent
    # verification of current provider health. Never expose arguments or bodies.
    rows = [row for row in cases if source in row.get("declared_sources", [])]
    if not rows:
        return {"status": "not_recorded"}
    passed = all(
        isinstance(row.get("observation"), dict)
        and row.get("observation", {}).get("executed") is True
        and row["observation"].get("passed") is True
        and row["observation"].get("classification") in {"healthy_data", "healthy_empty"}
        and (row["allow_empty"] or row["observation"].get("classification") != "healthy_empty")
        and row["observation"].get("error_codes") == []
        and isinstance(row["observation"].get("participating_sources"), list)
        and source in row["observation"].get("participating_sources", [])
        for row in rows
    )
    return {
        "status": "passed" if passed else "failed",
        "retrieved_at": retrieved.isoformat(),
        "scope": "Operator-supplied point-in-time canary receipt; current health is not probed.",
    }


async def diagnose(service, *, source=None):
    known = source_names()
    if source is not None and source not in known:
        raise ResearchError("unknown_source", "Unknown diagnostic source; inspect capabilities.")
    selected = [source] if source else known
    probe = await study_workers.run(import_probe, {name: policy(name)["module"] for name in selected})
    rows = []
    for name in selected:
        settings = policy(name)
        configured, reason = service.source_availability(name)
        row = {
            "source": name,
            "configured": configured,
            "reason": reason,
            "health": "not_probed",
            "importable": probe["sources"][name]["importable"],
            "contract_tested": offline_evidence(probe, name),
            "live_qualification": live_evidence(name),
            "requirements": {key: value for key, value in settings.items() if key != "module"},
        }
        row["recently_live_qualified"] = row["live_qualification"]["status"] == "passed"
        if name == "study":
            row["studies"] = []
        if name == "study" and configured:
            try:
                registry = await service.extensions.initialize_studies(recheck=True)
                configured = row["configured"] = bool(registry)
                row["reason"] = None if configured else "No verified public study release is installed."
                row["studies"] = [
                    {
                        "id": item["id"],
                        "release": item["release"],
                        "sha256": item["sha256"],
                        "assays": item["assays"],
                    }
                    for item in registry.values()
                ]
            except (ResearchError, OSError):
                configured = row["configured"] = False
                row["reason"] = "Public study verification failed; check the reviewed release and checksums."
        row["recovery"] = recovery(name, configured=configured, importable=row["importable"])
        rows.append(row)
    return {
        "implementation": REVISION,
        "diagnosis": rows,
        "interpretation": "Read-only configuration/import/evidence diagnosis; no provider reads or live-health probe.",
    }
