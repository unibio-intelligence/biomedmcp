"""Selected current NCBI gene/virus report contracts, without permission grants."""

import hashlib
import json
import math
import re

from biomedmcp.errors import ResearchError
from biomedmcp.pagination import ProviderPage, numeric_total, page_payload

from .datasets import VALIDATORS, invalid_response

UINT64 = (1 << 64) - 1
VIRUS_ACCESSION = r"[A-Z][A-Z0-9_]*[0-9]+\.[0-9]+"
GENE = "/gene/id/{gene_ids}/dataset_report"
ORTHOLOG = "/gene/id/{gene_id}/orthologs"
VIRUS = "/virus/accession/{accessions}/dataset_report"


def positive(value):
    return type(value) is int and 1 <= value <= UINT64


def gene_number(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[1-9][0-9]{0,19}", value)) and int(value) <= UINT64


def ortholog_plans(arguments):
    targets = arguments.get("target_tax_ids")
    if (
        not positive(arguments.get("gene_id"))
        or not positive(arguments.get("source_tax_id"))
        or not isinstance(targets, list)
        or not 1 <= len(targets) <= 25
        or any(not positive(taxon) or taxon == arguments["source_tax_id"] for taxon in targets)
        or len(set(targets)) != len(targets)
        or type(arguments.get("max_results", 10)) is not int
        or not 1 <= arguments.get("max_results", 10) <= 25
        or arguments.get("page_token") is not None
        and (not isinstance(arguments["page_token"], str) or not 1 <= len(arguments["page_token"]) <= 8192)
    ):
        raise ResearchError(
            "invalid_parameters",
            "Use an exact positive GeneID/source taxon and 1–25 distinct positive target taxa, with a bounded page size/token.",
        )
    identifier = str(arguments["gene_id"])
    params = {
        "returned_content": "COMPLETE",
        "taxon_filter": [str(taxon) for taxon in targets],
        "page_size": arguments.get("max_results", 10),
    }
    if arguments.get("page_token"):
        params["page_token"] = arguments["page_token"]
    return (
        {
            "template": GENE,
            "endpoint": f"gene/id/{identifier}/dataset_report",
            "params": {"returned_content": "COMPLETE", "page_size": 2},
        },
        {"template": ORTHOLOG, "endpoint": f"gene/id/{identifier}/orthologs", "params": params},
    )


def virus_plan(arguments):
    accession = arguments.get("accession")
    if (
        not isinstance(accession, str)
        or not re.fullmatch(VIRUS_ACCESSION, accession)
        or arguments.get("tax_id") is not None
        and not positive(arguments["tax_id"])
    ):
        raise ResearchError(
            "invalid_parameters",
            "Use one exact versioned viral nucleotide accession and an optional positive viral taxon.",
        )
    return {
        "template": VIRUS,
        "endpoint": f"virus/accession/{accession}/dataset_report",
        "params": {"returned_content": "COMPLETE", "page_size": 2},
    }


def envelope(raw, plan):
    if not isinstance(raw, dict) or "error" in raw or "errors" in raw or raw.get("success") is False:
        invalid_response()
    stack = [(raw, 0)]
    inspected = 0
    while stack:
        node, depth = stack.pop()
        inspected += 1
        if depth > 24 or inspected > 100000 or isinstance(node, float) and not math.isfinite(node):
            invalid_response()
        if isinstance(node, dict):
            stack.extend((value, depth + 1) for value in node.values())
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in node)
    if not VALIDATORS[plan["template"]].is_valid(raw):
        invalid_response()
    rows = raw.get("reports", [])
    total = numeric_total(raw.get("total_count"))
    token = raw.get("next_page_token") or None
    if (
        len(rows) > plan["params"]["page_size"]
        or total is not None
        and total < len(rows)
        or not rows
        and total is None
        and token is None
        or not rows
        and total is not None
        and total > 0
        and not plan["params"].get("page_token")
        and token is None
        or token is not None
        and (not token.strip() or len(token) > 8192 or token == plan["params"].get("page_token"))
        or total is not None
        and total > len(rows)
        and not plan["params"].get("page_token")
        and token is None
        or any("error" in message for message in raw.get("messages", []))
    ):
        invalid_response()
    return rows, total, token


def groups(gene):
    output = set()
    for item in gene.get("gene_groups", []):
        if (
            not gene_number(item.get("id"))
            or not isinstance(item.get("method"), str)
            or not item["method"].strip()
        ):
            invalid_response()
        if item["method"] == "NCBI Ortholog":
            output.add(item["id"])
    return output


def gene_rows(rows):
    seen = set()
    for row in rows:
        if row.get("errors") or "error" in row:
            invalid_response()
        gene = row.get("gene")
        if (
            not isinstance(gene, dict)
            or not gene_number(gene.get("gene_id"))
            or not gene_number(gene.get("tax_id"))
            or not isinstance(gene.get("symbol"), str)
            or not gene["symbol"].strip()
            or len(gene["symbol"]) > 256
            or gene["gene_id"] in seen
        ):
            invalid_response()
        seen.add(gene["gene_id"])
        groups(gene)
        for name in ("transcript_count", "protein_count"):
            if name in gene and (type(gene[name]) is not int or gene[name] < 0):
                invalid_response()
        for name in ("ensembl_gene_ids", "swiss_prot_accessions"):
            if name in gene and any(not isinstance(value, str) or not value.strip() for value in gene[name]):
                invalid_response()
    return rows


def row_proof(row, locator, url):
    return {
        "record_sha256": hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest(),
        "locator": locator,
        "url": url,
        "source_release": None,
        "time_dependent": True,
    }


def source_identity(raw, arguments, plan):
    rows, total, token = envelope(raw, plan)
    gene_rows(rows)
    if len(rows) != 1 or total not in {None, 1} or token is not None:
        raise ResearchError(
            "unresolved_identity", "The exact source GeneID did not yield one complete identity record."
        )
    gene = rows[0]["gene"]
    if gene["gene_id"] != str(arguments["gene_id"]) or gene["tax_id"] != str(arguments["source_tax_id"]):
        invalid_response()
    return rows[0]


def ortholog_report(raw, identity, arguments, plan, *, base_url):
    rows, total, token = envelope(raw, plan)
    gene_rows(rows)
    source = identity["gene"]
    source_groups = groups(source)
    source_proof = row_proof(
        identity, "/reports/0", base_url + f"/gene/id/{arguments['gene_id']}/dataset_report"
    )
    retained, assertions, candidates = [], [], []
    filtering = {"source_gene": 0, "other_taxon": 0}
    for index, row in enumerate(rows):
        gene = row["gene"]
        if gene["gene_id"] == source["gene_id"]:
            if gene["tax_id"] != source["tax_id"] or groups(gene) != source_groups:
                invalid_response()
            filtering["source_gene"] += 1
            continue
        if int(gene["tax_id"]) not in arguments["target_tax_ids"]:
            filtering["other_taxon"] += 1
            candidates.append(
                {
                    "record": row,
                    "reason": "outside_exact_target_taxa",
                    "provenance": row_proof(row, f"/reports/{index}", base_url + "/" + plan["endpoint"]),
                }
            )
            continue
        retained.append(row)
        shared = source_groups & groups(gene)
        if not shared:
            candidates.append(
                {
                    "record": row,
                    "reason": "shared_reported_ortholog_group_unavailable",
                    "provenance": row_proof(row, f"/reports/{index}", base_url + "/" + plan["endpoint"]),
                }
            )
            continue
        assertions.append(
            {
                "source_gene_id": source["gene_id"],
                "source_tax_id": source["tax_id"],
                "target_gene_id": gene["gene_id"],
                "target_tax_id": gene["tax_id"],
                "assertion_type": "provider_inferred_orthology",
                "method": "NCBI Ortholog",
                "group_ids": sorted(shared),
                "sequence_identity_percent": None,
                "functional_equivalence": None,
                "inputs": [
                    source_proof,
                    row_proof(row, f"/reports/{index}", base_url + "/" + plan["endpoint"]),
                ],
            }
        )
    result = page_payload(
        retained,
        raw_count=len(rows),
        filtered_count=sum(filtering.values()),
        filtering=filtering,
        total=total,
        continuation=token,
        exhausted=token is None,
    )
    result["pagination"] = ProviderPage.model_validate(result["_provider_page"]).public_metadata()
    result.update(
        source_gene=identity,
        source_provenance=source_proof,
        relationship_assertions=assertions,
        unqualified_candidates=candidates,
        source_window_records=rows,
        exact_target_tax_ids=arguments["target_tax_ids"],
        provider_messages=raw.get("messages", []),
        status="partial",
        section_outcomes={"orthology": {"outcome": "partial"}},
        warnings=[
            "NCBI orthology is an inferred annotation; no sequence percentage, functional equivalence or experimental relationship is established.",
            "Only this provider window is assessed; source totals include filtered records and unassessed windows.",
            "Missing gene-group annotations and no retained records do not establish absence. Gene/group metadata is mutable and unpinned.",
        ],
        url=base_url + "/" + plan["endpoint"],
    )
    return result


def virus_report(raw, arguments, plan, *, base_url):
    rows, total, token = envelope(raw, plan)
    if len(rows) > 1 or total not in {None, 0, 1} or token is not None:
        invalid_response()
    for row in rows:
        taxon = row.get("virus", {})
        if (
            row.get("accession") != arguments["accession"]
            or not positive(taxon.get("tax_id"))
            or arguments.get("tax_id") is not None
            and taxon["tax_id"] != arguments["tax_id"]
            or not isinstance(taxon.get("organism_name") or taxon.get("sci_name"), str)
            or not (taxon.get("organism_name") or taxon.get("sci_name")).strip()
        ):
            invalid_response()
        for name in ("length", "protein_count", "gene_count", "mature_peptide_count"):
            if name in row and (type(row[name]) is not int or row[name] < (1 if name == "length" else 0)):
                invalid_response()
    result = page_payload(rows, raw_count=len(rows), total=total, exhausted=True)
    result["pagination"] = ProviderPage.model_validate(result["_provider_page"]).public_metadata()
    result.update(
        accession=arguments["accession"],
        records_provenance=[
            row_proof(row, f"/reports/{index}", base_url + "/" + plan["endpoint"])
            for index, row in enumerate(rows)
        ],
        reported_counts=[
            {
                name: row.get(name)
                for name in ("length", "protein_count", "gene_count", "mature_peptide_count")
            }
            for row in rows
        ],
        warnings=[
            "Reported record/annotation counts are not measurements of infection, expression, pathogenicity or transmission.",
            "The nucleotide accession is versioned; metadata is mutable and no database release is pinned. No sequences are downloaded.",
        ],
        url=base_url + "/" + plan["endpoint"],
    )
    return result
