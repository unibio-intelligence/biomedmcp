#!/usr/bin/env python3
"""Score recorded agent traces against fixed tasks. Does not fabricate model runs."""

import argparse
import json
from pathlib import Path

import jsonschema

from biomedmcp.contracts import BatchCall
from biomedmcp.public_catalog import ADAPTERS, schema

TASKS = [
    {"id": "gene-record", "question": "Retrieve the PCSK9 gene record.", "routes": ["get"]},
    {
        "id": "ambiguous-alias",
        "question": "Resolve LDL receptor before combining gene evidence.",
        "routes": ["resolve"],
    },
    {"id": "gtex-only", "question": "Retrieve LDLR expression using only GTEx.", "routes": ["get"]},
    {
        "id": "literature-dates",
        "question": "Find PubMed PCSK9 papers published since 2024-01-01.",
        "routes": ["literature_search"],
    },
    {"id": "article-direct", "question": "Read the full text for PMC123.", "routes": ["get"]},
    {"id": "trial-status", "question": "Find recruiting familial hypercholesterolemia trials.", "routes": ["trial_search"]},
    {
        "id": "exact-variant",
        "question": "Retrieve ClinVar evidence for GRCh38 chr1:55039974:G:T.",
        "routes": ["variant_evidence"],
    },
    {
        "id": "ambiguous-variant",
        "question": "Retrieve evidence for PCSK9 R46L; preserve allele ambiguity.",
        "routes": ["variant_evidence"],
    },
    {"id": "target-dossier", "question": "Assemble a target dossier for LDLR.", "routes": ["research"]},
    {
        "id": "study-frequency",
        "question": "Calculate TP53 mutation frequency in ubi_synthetic, using assay coverage.",
        "routes": ["study_analysis"],
    },
    {
        "id": "study-survival",
        "question": "Calculate overall survival by TP53 mutation in ubi_synthetic.",
        "routes": ["study_analysis"],
    },
    {
        "id": "source-failure",
        "question": "Find PCSK9 PubMed papers when the provider is unavailable; preserve the failure.",
        "routes": ["literature_search"],
    },
    {"id": "advanced-source", "question": "Retrieve GTEx tissue metadata.", "routes": ["query_source"]},
    {
        "id": "platform-handoff",
        "question": "Import this evidence into my private project and start a durable modeling run.",
        "routes": [],
    },
]


def score(traces):
    tasks = {task["id"]: task for task in TASKS}
    rows = []
    seen = set()
    for trace in traces:
        required = {"task_id", "model", "client_version", "attempt", "calls"}
        if required - trace.keys():
            raise ValueError("Trace must identify task, model, client version, attempt and calls")
        task = tasks[trace["task_id"]]
        key = (trace["task_id"], trace["model"], trace["client_version"], trace["attempt"])
        if key in seen:
            raise ValueError("Duplicate trace attempt")
        seen.add(key)
        errors = []
        scientific_calls = []
        calls = []
        for call in trace["calls"]:
            if call["tool"] != "batch":
                calls.append(call)
                continue
            try:
                arguments = call["arguments"]
                if (
                    set(arguments) - {"calls", "idempotency_key"}
                    or not 1 <= len(arguments.get("calls", [])) <= 10
                ):
                    raise ValueError("Invalid batch envelope")
                for inner in arguments["calls"]:
                    inner = BatchCall.model_validate(inner)
                    calls.append({"tool": inner.operation, "arguments": inner.arguments})
            except ValueError as exc:
                errors.append(str(exc).splitlines()[0][:200])
        for call in calls:
            name = call["tool"]
            if name in ADAPTERS:
                scientific_calls.append(name)
                try:
                    jsonschema.validate(call["arguments"], schema(name))
                    ADAPTERS[name].validate_python(call["arguments"])
                except (jsonschema.ValidationError, ValueError) as exc:
                    errors.append(str(exc).splitlines()[0][:200])
            elif name not in {"capabilities", "quota"}:
                errors.append("Unknown public tool: " + name)
        chosen = scientific_calls[0] if scientific_calls else None
        route_ok = (
            chosen in task["routes"]
            if task["routes"]
            else not scientific_calls and trace.get("platform_handoff") is True
        )
        # Human/scientific adjudication is separate from syntactic routing.
        judged = trace.get("adjudication", {})
        for name in ("task_success", "scientific_correct", "source_identity_safe"):
            if name in judged and not isinstance(judged[name], bool):
                raise ValueError("Adjudication values must be booleans")
        rows.append(
            {
                "task_id": task["id"],
                "model": trace["model"],
                "client_version": trace["client_version"],
                "attempt": trace["attempt"],
                "route_correct": route_ok,
                "schema_errors": errors,
                "call_count": len(trace["calls"]),
                "adjudication": judged,
                "measurements": {
                    k: trace[k]
                    for k in ("elapsed_ms", "input_tokens", "output_tokens", "provider_requests")
                    if k in trace
                },
            }
        )
    return {
        "kind": "recorded_agent_evaluation",
        "attempts": len(rows),
        "tasks_observed": sorted({row["task_id"] for row in rows}),
        "missing_tasks": sorted(set(tasks) - {row["task_id"] for row in rows}),
        "correct_routes": sum(row["route_correct"] for row in rows),
        "valid_schemas": sum(not row["schema_errors"] for row in rows),
        "scientifically_adjudicated": sum("scientific_correct" in row["adjudication"] for row in rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = (
        score([json.loads(line) for line in args.traces.read_text().splitlines() if line.strip()])
        if args.traces
        else {
            "status": "not_run",
            "tasks": TASKS,
            "instructions": "Run multiple held-out attempts with recorded model/client versions, then supply JSONL traces. Missing metrics and scientific adjudication remain missing.",
        }
    )
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
