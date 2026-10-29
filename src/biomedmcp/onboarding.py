"""Generated onboarding calls share the tested public example registry."""

import json

from .examples import by_id
from .source_policy import policy, source_names

INVESTIGATIONS = (
    {
        "id": "target",
        "question": "What evidence supports human ERBB2 as a research target?",
        "steps": ["target-dossier", "gene-tissue", "gene-eqtl"],
        "interpretation": "Read the qualified gene/allele identity, expression units/tissue/release, association direction and each section's outcome. Inspect the separate expression/QTL schemas with capabilities for source=gtex. Distinguish posterior probabilities, p-values and standard errors, and paired values from unknown participant counts. Preserve prefilter source pointers, qualified intron joins, provenance, disagreements and recovery. Observational expression/QTL associations do not establish causal target validation; missing sections prevent a complete conclusion.",
    },
    {
        "id": "variant",
        "question": "How is BRAF V600E contextualized by variant, structural and literature evidence?",
        "steps": ["variant-protein", "variant-structure", "gene-articles"],
        "interpretation": "Confirm allele/transcript/build equivalence before combining assertions. Structural coverage is a sequence mapping, not proof of an experimental residue effect. Gene co-mention papers are discovery leads; inspect experiment/species/variant scope before citing support. Preserve source assertions independently.",
    },
    {
        "id": "study",
        "question": "What does the installed synthetic TP53/KRAS cohort demonstrate?",
        "steps": ["study-profile", "study-survival", "study-cooccurrence"],
        "interpretation": "Report clinical-study samples separately from mutation-assayed samples, unique mutant samples and mutation events. Use the assay-evaluable denominator, preserve calculation inputs, exclusions and patient grouping, and distinguish missing measurement from measured negative. Inspect capabilities with source=study for the derived record schemas; preserve unavailable inference, source selectors and truncation/recovery. A request's species default does not establish study species or assembly. These synthetic results demonstrate mechanics only; they are not real clinical evidence or validated statistical conclusions for a real study.",
    },
)


def investigations_markdown():
    rows = [
        "# Example investigations",
        "",
        "Generated from the same immutable examples as tool descriptions. These are synthetic contract demonstrations. Check [source release eligibility](source-licenses.md) before execution; keys cannot enable unreleased integrations. Live coverage and scientific adjudication remain separate. Known identifiers can be used directly without mandatory discovery calls. For study examples install the [synthetic demo](studies.md) first.",
        "",
    ]
    for item in INVESTIGATIONS:
        rows += [f"## {item['question']}", "", "```sh"]
        for identifier in item["steps"]:
            entry = by_id(identifier)
            rows.append(
                f"UBI_PROFILE=local uv run --frozen biomedmcp {entry.operation} '{json.dumps(entry.arguments, separators=(',', ':'))}'"
            )
        rows += [
            "```",
            "",
            item["interpretation"],
            "",
            "Keep the JSON results, evidence IDs, source releases and continuation actions with your answer. An error or partial result requires a qualified alternative, continuation or an explicit limitation.",
            "",
        ]
    return "\n".join(rows)


def matrix_markdown():
    rows = [
        "# Source credentials and access",
        "",
        "Generated from current source policy. Set secrets in the server/operator environment or client secret storage; never pass them as scientific tool arguments. Hosted users ask the operator to configure source access. Restart processes after changing source credentials. Environment presence does not verify credentials, rights, live availability or scientific coverage.",
        "",
        "Local users may supply supported keys in their own process environment or client secret storage. Shared hosted per-user keys require a separately implemented platform secret boundary; never switch users by changing server-wide environment variables. `UBI_LICENSED_SOURCES` and keys cannot override an unreleased source. Review the [source license inventory](source-licenses.md); source eligibility and integration-code licensing are separate.",
        "",
        "| Source | Required environment | Optional environment | Source release / access policy |",
        "| --- | --- | --- | --- |",
    ]
    for name in source_names():
        value = policy(name)
        required = ", ".join(f"`{key}`" for key in value["required_environment"]) or "None"
        optional = ", ".join(f"`{key}`" for key in value["optional_environment"]) or "None"
        access = (
            value["license_review"]["release_status"]
            + "; "
            + value["access_policy"]
            + (f"; `UBI_LICENSED_SOURCES` includes `{name}`" if value["access_attestation"] else "")
        )
        if name == "depmap":
            access = (
                "Retained route unavailable; use a separately released qualified platform data capability"
            )
        rows.append(f"| `{name}` | {required} | {optional} | {access} |")
    rows += [
        "",
        'Use `biomedmcp diagnose \'{"source":"bio-ontology"}\'` to distinguish missing settings from import failure and qualification evidence. The [connection guide](connect.md) and [study guide](studies.md) provide recovery steps.',
        "",
    ]
    return "\n".join(rows)
