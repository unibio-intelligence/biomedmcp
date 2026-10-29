"""Explicit live probes with provider-free definition preflight.

Import never runs a probe. Reports retain status and hashes, not provider bodies
or exception messages. Healthy empty collections do not establish biological absence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import transport
from .contracts import ResearchResult
from .dispatch import execute, prepare
from .domain import ResearchService
from .errors import ResearchError
from .native import REVISION
from .public_catalog import ADAPTERS, native_request
from .runtime import digest


@dataclass(frozen=True)
class CanaryCase:
    name: str
    operation: str
    arguments: dict
    sources: tuple[str, ...]
    allow_empty: bool = False

    def request(self):
        # Fresh reads and independent copies preserve the declared request.
        return {**json.loads(json.dumps(self.arguments)), "freshness": "fresh"}


CASES = (
    CanaryCase("gene", "get", {"entity": "gene", "id": "BRAF"}, ("mygene",)),
    CanaryCase(
        "gtex-expression",
        "get",
        {
            "entity": "gene",
            "id": "BRAF",
            "sections": ["expression"],
            "source_versions": {"gtex": "gtex_v10"},
        },
        ("gtex",),
    ),
    CanaryCase(
        "gtex-eqtl",
        "get",
        {
            "entity": "gene",
            "id": "BRAF",
            "sections": ["eqtl"],
            "source_versions": {"gtex": "gtex_v10"},
            "section_parameters": {"eqtl": {"tissue_id": "Thyroid"}},
        },
        ("gtex",),
        allow_empty=True,
    ),
    CanaryCase(
        "gtex-sqtl",
        "get",
        {
            "entity": "gene",
            "id": "BRAF",
            "sections": ["sqtl"],
            "source_versions": {"gtex": "gtex_v10"},
            "section_parameters": {"sqtl": {"tissue_id": "Thyroid"}},
        },
        ("gtex",),
        allow_empty=True,
    ),
    CanaryCase(
        "opentargets",
        "get",
        {
            "entity": "gene",
            "id": "BRAF",
            "sections": ["target_evidence"],
        },
        ("mygene", "opentargets"),
    ),
    CanaryCase(
        "literature",
        "literature_search",
        {
            "query": "BRAF melanoma",
            "filters": {"source": "pubmed"},
            "limit": 3,
        },
        ("pubmed",),
        allow_empty=True,
    ),
    CanaryCase(
        "trials",
        "trial_search",
        {
            "query": "melanoma",
            "filters": {"source": "clinical-trials", "status": "RECRUITING"},
            "limit": 3,
        },
        ("clinical-trials",),
        allow_empty=True,
    ),
    CanaryCase(
        "genbank",
        "query_source",
        {
            "source": "ncbi-records",
            "operation": "get",
            "params": {"database": "genbank", "accession": "NM_004333.6"},
        },
        ("ncbi-records",),
    ),
    CanaryCase(
        "protein",
        "get",
        {
            "entity": "protein",
            "id": "P15056",
            "sections": ["domains"],
        },
        ("interpro", "uniprot"),
    ),
    CanaryCase(
        "variant",
        "variant_evidence",
        {
            "id": "chr7:140753336:A:T",
            "assembly": "grch38",
            "sections": ["clinvar", "population"],
        },
        ("gnomad", "ncbi"),
    ),
)
REQUIRED_CASES = frozenset(case.name for case in CASES)
CONFIG_CODES = {"source_unavailable", "adapter_not_installed", "source_not_configured"}
PROVIDER_CODES = {
    "source_unavailable",
    "source_timeout",
    "source_rate_limited",
    "source_authentication_failed",
    "source_access_denied",
    "source_not_found",
    "invalid_source_response",
    "upstream_error",
    "response_too_large",
}
RUNTIME_CODES = {
    "operation_timeout",
    "cache_unavailable",
    "cache_invalid_data",
    "provider_budget_unavailable",
    "provider_busy",
}


def failure(exc, *, preflight=False):
    # Known codes only: neither messages nor arbitrary exception/code strings.
    code = exc.code if isinstance(exc, ResearchError) else "unexpected_error"
    if preflight:
        category = "missing_configuration" if code in CONFIG_CODES else "invalid_probe"
    elif code in PROVIDER_CODES:
        category = "provider_failure"
    else:
        category = "runtime_failure"
    known = CONFIG_CODES | PROVIDER_CODES | RUNTIME_CODES
    return {
        "classification": category,
        "passed": False,
        "error_code": code if code in known else "invalid_probe" if preflight else "unexpected_error",
    }


async def validate_case(service, case):
    """Check public ownership, scientific plan and adapter schemas without reads."""
    model = ADAPTERS[case.operation].validate_python(case.request())
    operation, model = native_request(case.operation, model)
    if operation == "get":
        plan = service._get_plan(model)
        sources = {owner for owner, _ in plan.values()} | {
            dependency for _, dependencies in plan.values() for dependency in dependencies
        }
        sections = set(plan)
    elif operation == "search":
        _, selected = service._search_plan(model)
        sources, sections = set(selected), set(selected)
    elif operation == "query_source":
        service._source_route(model.source, model.operation, model.params)
        sources = sections = {model.source}
    else:
        raise ResearchError("invalid_probe", "Canaries must be bounded evidence retrievals.")
    if not case.name or len(case.sources) != len(set(case.sources)) or set(case.sources) != sources:
        raise ResearchError("invalid_probe", "Declared sources differ from the scientific plan.")
    missing = sorted(source for source in sources if not service.source_availability(source)[0])
    if missing:
        return {"classification": "missing_configuration", "passed": False, "missing_sources": missing}
    await prepare(service, case.operation, case.request(), scope="qualification")
    return {
        "classification": "valid_probe",
        "planned_sources": sorted(sources),
        "expected_sections": sorted(sections),
    }


def observation(case, result, expected_sections):
    """Successful peers cannot hide a failed, ambiguous or missing section."""
    result = ResearchResult.model_validate(result)
    section_outcomes = {
        name: result.sections[name].outcome for name in expected_sections if name in result.sections
    }
    codes = sorted(
        {
            section.error.get("code")
            if section.error.get("code") in PROVIDER_CODES | RUNTIME_CODES
            else "unexpected_error"
            for section in result.sections.values()
            if section.error
        }
    )
    participating = {proof.source for proof in result.provenance} | {
        source for proof in result.provenance for source in proof.sources
    }
    complete = set(expected_sections) <= set(result.sections) and set(case.sources) <= participating
    # Empty is healthy only when a source explicitly supplied an empty
    # collection. A missing body/collection is still a qualification failure.
    explicit_empty = all(
        section.data == []
        or isinstance(section.data, dict)
        and any(
            isinstance(section.data.get(key), list) and not section.data[key]
            for key in ("articles", "results", "hits", "studies", "items", "records", "data")
        )
        for section in result.sections.values()
        if section.outcome == "empty"
    )
    healthy = result.outcome in {"data", "empty"} and all(
        section.outcome in {"data", "empty"} and not section.error for section in result.sections.values()
    )
    if not healthy:
        classification = (
            "ambiguous_identity"
            if result.outcome == "ambiguous" or "ambiguous" in section_outcomes.values()
            else ("runtime_failure" if any(code in RUNTIME_CODES for code in codes) else "provider_failure")
        )
    elif not complete or not explicit_empty:
        classification = "invalid_result"
    else:
        classification = "healthy_empty" if result.outcome == "empty" else "healthy_data"
    empty_sections = any(section.outcome == "empty" for section in result.sections.values())
    passed = (
        healthy
        and complete
        and explicit_empty
        and (case.allow_empty or not empty_sections and result.outcome == "data")
    )
    return {
        "classification": classification,
        "passed": passed,
        "outcome": result.outcome,
        "record_count": len(result.records),
        "section_outcomes": section_outcomes,
        "error_codes": codes,
        "participating_sources": sorted(set(case.sources) & participating),
        "result_sha256": digest(result.model_dump(mode="json")),
        "evidence": [
            {"source": proof.source, "provenance_sha256": digest(proof.model_dump(mode="json"))}
            for proof in result.provenance
            if proof.source in case.sources
        ],
        "has_continuation": bool(result.next_cursor),
        "truncated": result.truncated,
    }


async def run(*, service=None, cases=CASES, validation_only=False):
    """Preflight the whole suite before I/O, then qualify every required probe."""
    service = service or ResearchService()
    rows, plans = [], []
    names = [case.name for case in cases]
    for case in cases:
        row = {
            "case": case.name,
            "operation": case.operation,
            "arguments": case.request(),
            "required": True,
            "allow_empty": case.allow_empty,
            "declared_sources": list(case.sources),
        }
        try:
            plan = await validate_case(service, case)
            if names.count(case.name) != 1 or case.name not in REQUIRED_CASES:
                raise ResearchError("invalid_probe", "Duplicate or unknown canary definition.")
        except Exception as exc:  # noqa: BLE001 -- never retain exception text
            plan = failure(exc, preflight=True)
        row["preflight"] = plan
        rows.append(row)
        plans.append(plan)
    missing = sorted(REQUIRED_CASES - set(names))
    definitions_valid = not missing and all(plan["classification"] == "valid_probe" for plan in plans)
    if not validation_only:
        for case, row, plan in zip(cases, rows, plans, strict=True):
            if plan["classification"] != "valid_probe":
                row["observation"] = {**plan, "executed": False}
                continue
            started = time.perf_counter()
            try:
                result = await execute(service, case.operation, case.request(), scope="qualification")
                value = observation(case, result, plan["expected_sections"])
            except Exception as exc:  # noqa: BLE001 -- report failure without raw text
                value = failure(exc)
            row["observation"] = {
                **value,
                "executed": True,
                "seconds": round(time.perf_counter() - started, 3),
            }
    qualified = (
        not validation_only and definitions_valid and all(row["observation"]["passed"] for row in rows)
    )
    return {
        "report_version": "1.0",
        "implementation": REVISION,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "mode": "definitions_only" if validation_only else "live",
        "definitions_valid": definitions_valid,
        "qualified": qualified,
        "missing_required_cases": missing,
        "cases": rows,
        "definitions_sha256": digest(
            [
                {
                    key: row[key]
                    for key in (
                        "case",
                        "operation",
                        "arguments",
                        "required",
                        "allow_empty",
                        "declared_sources",
                    )
                }
                for row in rows
            ]
        ),
        "interpretation": "Point-in-time probes; not scientific absence, model accuracy or a performance claim.",
    }


def exit_code(report):
    if report["mode"] == "definitions_only":
        return 0 if report["definitions_valid"] else 1
    return 0 if report["qualified"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Check definitions without provider reads; does not qualify live health.",
    )
    args = parser.parse_args(argv)

    async def managed_run():
        transport.configure()
        try:
            return await run(validation_only=args.validate_only)
        finally:
            await transport.shutdown()

    report = asyncio.run(managed_run())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        "definitions valid"
        if args.validate_only and report["definitions_valid"]
        else "qualified"
        if report["qualified"]
        else "qualification failed"
    )
    return exit_code(report)
