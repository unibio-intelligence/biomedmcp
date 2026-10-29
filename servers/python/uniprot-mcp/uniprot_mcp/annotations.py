"""Bounded comparisons of UniProt records; no inferred homology or geometry."""

from hashlib import sha256
from itertools import combinations

from biomedmcp.errors import ResearchError

from .shapes import ACCESSION

EVOLUTION_FIELDS = {
    "similarity_annotations": "cc_similarity",
    "orthology_references": "xref_orthodb",
    "phylogeny_references": "xref_phylomedb",
}
COMPARISON_FIELDS = {
    "sequence": "sequence,length",
    "function": "cc_function",
    "structure": "xref_pdb",
}
METHODS = {
    "sequence": "Exact sequence string equality and residue count difference; no alignment, similarity score, or homology inference.",
    "function": "Exact shared FUNCTION statement text; missing or differently worded annotations do not establish functional divergence.",
    "structure": "Shared PDB cross-reference identifiers; these do not establish equivalent structures, chain mappings, or geometry.",
}


def preflight(operation, params):
    if operation not in {"analyze_evolution", "compare_proteins"}:
        return
    values = params.get("accessions") if operation == "compare_proteins" else [params.get("accession")]
    if (
        not isinstance(values, list)
        or not (2 <= len(values) <= 5 if operation == "compare_proteins" else len(values) == 1)
        or any(not isinstance(v, str) or not ACCESSION.fullmatch(v) for v in values)
        or len(set(values)) != len(values)
    ):
        raise ResearchError(
            "invalid_parameters", "Provide distinct canonical UniProt accessions (2–5 for comparison)."
        )


def identity(record, requested):
    return {
        "source": "uniprot",
        "requested_accession": requested,
        "primary_accession": record["primaryAccession"],
        "taxon_id": record.get("organism", {}).get("taxonId"),
        "source_release": record.get("source_release"),
        "url": f"https://www.uniprot.org/uniprotkb/{record['primaryAccession']}/entry",
    }


def statements(record, kind, *, prefix=""):
    return [
        {
            "value": text["value"],
            "evidences": text.get("evidences", []),
            "input_locator": f"{prefix}/comments/{i}/texts/{j}",
        }
        for i, comment in enumerate(record.get("comments", []))
        if comment["commentType"] == kind
        for j, text in enumerate(comment["texts"])
    ]


def references(record, database, *, prefix=""):
    return [
        {
            "database": database,
            "id": ref["id"],
            "properties": ref.get("properties", []),
            "input_locator": f"{prefix}/uniProtKBCrossReferences/{i}",
        }
        for i, ref in enumerate(record.get("uniProtKBCrossReferences", []))
        if ref["database"] == database
    ]


def evolution(record, requested, mode):
    annotations = (
        statements(record, "SIMILARITY")
        if mode == "similarity_annotations"
        else references(
            record, {"orthology_references": "OrthoDB", "phylogeny_references": "PhylomeDB"}[mode]
        )
    )
    outcome = "data" if annotations else "unavailable"
    return {
        **record,
        "accession": requested,
        "analysis_type": mode,
        "identity": identity(record, requested),
        "url": identity(record, requested)["url"],
        "annotations": annotations,
        "annotation_status": "reported" if annotations else "not_reported",
        "method": "UniProt SIMILARITY annotations or external database references; no inferred orthologs, paralogs, homolog set, or phylogenetic tree. External reference contents were not retrieved.",
        "section_outcomes": {
            "record": {"outcome": "data", "sources": ["uniprot"]},
            "annotations": {"outcome": outcome, "sources": ["uniprot"] if annotations else []},
        },
        "warnings": []
        if annotations
        else [
            "Requested annotations are not reported in this UniProt projection; relationship absence is unknown."
        ],
    }


def comparison(results, accessions, kind):
    summaries = []
    for i, peer in enumerate(results):
        if "data" not in peer:
            continue
        record = peer["data"]
        prefix = f"/results/{i}/data"
        summary = {
            "result_index": i,
            "identity": identity(record, peer["accession"]),
            "input_locator": prefix,
        }
        if kind == "sequence":
            raw = record["sequence"]["value"]
            summary.update(
                sequence_length=len(raw),
                length_unit="residues",
                sequence_sha256=sha256(raw.encode("ascii")).hexdigest(),
                contains_ambiguous_residues=bool(set(raw) & set("BXZJ")),
                sequence_input_locator=prefix + "/sequence/value",
                measurement_status="reported",
            )
        else:
            evidence = (
                statements(record, "FUNCTION", prefix=prefix)
                if kind == "function"
                else references(record, "PDB", prefix=prefix)
            )
            summary.update(
                annotations=evidence, measurement_status="reported" if evidence else "not_reported"
            )
        summaries.append(summary)

    pairs = []
    by_index = {summary["result_index"]: summary for summary in summaries}
    for left_index, right_index in combinations(range(len(results)), 2):
        left, right = by_index.get(left_index), by_index.get(right_index)
        available = (
            left is not None
            and right is not None
            and left["identity"]["primary_accession"] != right["identity"]["primary_accession"]
            and all(s["measurement_status"] == "reported" for s in (left, right))
        )
        pair = {
            "result_indices": [left_index, right_index],
            "status": "computed" if available else "unavailable",
            "input_locators": [f"/results/{left_index}/data", f"/results/{right_index}/data"]
            if available
            else [],
            "reason": None
            if available
            else "Distinct primary identities and reported measurements are required; failed peer evidence remains unavailable.",
        }
        if available and kind == "sequence":
            pair.update(
                exact_sequence_match=results[left_index]["data"]["sequence"]["value"]
                == results[right_index]["data"]["sequence"]["value"],
                residue_count_difference_left_minus_right=left["sequence_length"] - right["sequence_length"],
            )
        elif available:
            key = "value" if kind == "function" else "id"
            pair["shared_function_statement_texts" if kind == "function" else "shared_pdb_reference_ids"] = (
                sorted({v[key] for v in left["annotations"]} & {v[key] for v in right["annotations"]})
            )
        pairs.append(pair)
    complete = (
        len(summaries) == len(accessions)
        and len({s["identity"]["primary_accession"] for s in summaries}) == len(accessions)
        and all(s["measurement_status"] == "reported" for s in summaries)
    )
    releases = {s["identity"]["source_release"] for s in summaries}
    observed_release = next(iter(releases)) if len(releases) == 1 and None not in releases else None
    warnings = []
    if not complete:
        warnings.append(
            "Comparison is incomplete: failed peers, missing annotations, or aliases of one primary identity remain explicit; unknown measurements are not negative evidence."
        )
    if len(releases - {None}) > 1:
        warnings.append(
            "Input records were observed in different UniProt releases; per-record releases are retained."
        )
    return {
        "comparison_type": kind,
        "accessions": accessions,
        "results": results,
        "method": METHODS[kind],
        "summaries": summaries,
        "pairwise_comparisons": pairs,
        "source_release": observed_release,
        "warnings": warnings,
        "section_outcomes": {
            **{
                r["accession"]: {
                    "outcome": "data" if "data" in r else "unavailable",
                    "sources": ["uniprot"] if "data" in r else [],
                }
                for r in results
            },
            "comparison": {
                "outcome": "data" if complete else "unavailable",
                "sources": ["uniprot"] if complete else [],
            },
        },
    }
