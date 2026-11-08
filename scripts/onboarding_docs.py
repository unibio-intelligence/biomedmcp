"""Generated onboarding calls share the tested public example registry."""

import json

from biomedmcp.examples import by_id
from biomedmcp.source_policy import policy, source_names

INVESTIGATIONS = (
    {
        "id": "target",
        "question": "Which observations belong in an LDL-receptor evidence notebook?",
        "steps": ["target-dossier", "gene-tissue", "gene-eqtl"],
        "interpretation": "Check the gene and allele identity, the expression units, tissue and release, the direction of each association, and whether each section succeeded. Keep posterior probabilities, p-values and standard errors apart, and do not assume a participant count that is not reported. Run get_capabilities for source=gtex to see the expression and QTL record fields. Expression and QTL associations are observational: they do not validate a target. If a section is missing, the conclusion is incomplete.",
    },
    {
        "id": "variant",
        "question": "How can I keep a PCSK9 allele claim separate from gene-level evidence?",
        "steps": ["variant-protein", "variant-structure", "gene-articles"],
        "interpretation": "Before combining results, confirm they refer to the same allele, transcript and genome build. A structure covering the residue is a sequence mapping, not evidence of an experimental effect. Papers that mention the gene are leads: check the experiment, species and variant before citing them. Keep each source's claims separate.",
    },
    {
        "id": "study",
        "question": "Can I reproduce the analysis before using my own study?",
        "steps": ["study-profile", "study-survival", "study-cooccurrence"],
        "interpretation": "Count study samples, mutation-tested samples, mutated samples and mutation events separately. Use the tested samples as the denominator, keep the inputs, exclusions and patient grouping, and do not count a missing measurement as a negative result. Run get_capabilities for source=study to see the record fields. The request's default species does not tell you the study's species or genome assembly. The demo data is synthetic: it shows how the tools work, not real clinical findings.",
    },
)


def investigations_markdown():
    rows = [
        "# Example investigations",
        "",
        "Each workflow answers one research question in a few calls and explains how to read the results. The calls are tested against mock responses, so live results may differ. If you already know an identifier, use it directly. Some sources are not released, and a key cannot turn them on; see [source release eligibility](source-licenses.md). For the study example, install the [synthetic demo](studies.md) first.",
        "",
    ]
    for item in INVESTIGATIONS:
        rows += [f"## {item['question']}", "", "```sh"]
        for identifier in item["steps"]:
            entry = by_id(identifier)
            rows.append(
                f"UBI_PROFILE=local biomedmcp {entry.operation} '{json.dumps(entry.arguments, separators=(',', ':'))}'"
            )
        rows += [
            "```",
            "",
            item["interpretation"],
            "",
            "Save the JSON results, evidence IDs and source releases with your answer. If a call fails or returns partial results, continue it, try another source, or state the gap.",
            "",
        ]
    return "\n".join(rows)


def matrix_markdown():
    rows = [
        "# Source credentials and access",
        "",
        "Most sources need no key. For those that do, set the key as an environment variable where the server runs, or in your client's secret storage, then restart the server. Never put keys in tool arguments. On a hosted server, ask whoever runs it to set up keys. Setting a variable does not check that the key works, that you have rights to the data, or that the source is reachable.",
        "",
        "Per-user keys on a shared hosted server need secret storage that this package does not provide; never switch users by changing server-wide environment variables. A source marked **Not released** stays off even with a key or `UBI_LICENSED_SOURCES`. Available sources still have data terms; check them in the [source license inventory](source-licenses.md) before reusing data.",
        "",
        "| Source | Required environment | Optional environment | Status |",
        "| --- | --- | --- | --- |",
    ]
    for name in source_names():
        value = policy(name)
        required = ", ".join(f"`{key}`" for key in value["required_environment"]) or "None"
        optional = ", ".join(f"`{key}`" for key in value["optional_environment"]) or "None"
        if name == "depmap":
            status = "Not available in this release"
        elif value["license_review"]["release_status"] != "eligible":
            status = "Not released"
        elif name == "study":
            status = "Available after you install a checksummed study release"
        elif value["required_environment"]:
            status = "Available with your provider key"
        else:
            status = "Available"
        rows.append(f"| `{name}` | {required} | {optional} | {status} |")
    rows += [
        "",
        'To check a source\'s setup, run `biomedmcp diagnose \'{"source":"bio-ontology"}\'`. It tells you whether a setting is missing or the source failed to load. For fixes, see the [connection guide](connect.md) and [study guide](studies.md).',
        "",
    ]
    return "\n".join(rows)
