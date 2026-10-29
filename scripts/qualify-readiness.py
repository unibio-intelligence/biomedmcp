#!/usr/bin/env python3
"""Bind passing offline inventory/endpoint JUnit cases to installed source code.

Executes the deterministic suite without provider traffic, then binds its evidence
to unchanged source/dependency/test inputs. Diagnosis rejects stale fingerprints.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from biomedmcp.adapters import PROVIDERS
from biomedmcp.diagnostics import import_probe
from biomedmcp.native import REVISION
from biomedmcp.native.catalog import ADVANCED
from biomedmcp.source_policy import policy, source_names

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_EVIDENCE = {
    "alphamissense": ["test_alphamissense"],
    "eve": ["test_eve"],
    "openalex": ["test_openalex"],
    "pmc": ["test_pmc_fulltext_fallback", "test_fulltext_range_contract"],
    "monarch": ["test_monarch_responses"],
    "ensembl": ["test_ensembl_contracts", "test_ensembl_genome_contracts"],
    "ols": ["test_ols_responses"],
    "gencc": ["test_gencc_responses"],
    "interpro": ["test_interpro_responses"],
    "complexportal": ["test_complexportal_responses"],
    "gwas": ["test_gwas_responses"],
    "europepmc": ["test_fulltext_range_contract", "test_typed_literature_records", "test_evidence_recovery",
                  "test_open_citation_graph"],
    "gtex": [
        "test_gtex_responses",
        "test_gtex_pagination",
        "test_gtex_reference_identity",
        "test_typed_expression_records",
        "test_typed_qtl_records",
    ],
    "chembl": ["test_chembl_properties"],
    "clinical-trials": ["test_clinical_trials_responses", "test_typed_trial_records"],
    "uniprot": ["test_uniprot_responses", "test_uniprot_annotations", "test_uniprot_unknown_positions"],
    "pdb": ["test_pdb_responses"],
    "surechembl": ["test_surechembl_metadata", "test_surechembl_search", "test_surechembl_annotations"],
    "mychem": ["test_biothings_responses"],
    "mydisease": ["test_biothings_responses"],
    "myvariant": ["test_myvariant_responses"],
    "civic": ["test_civic_responses"],
    "gnomad": ["test_gnomad_responses", "test_typed_population_records"],
    "ncbi": ["test_ncbi_datasets", "test_ncbi_gene_reports", "test_direct_clinvar"],
    "reactome": ["test_reactome_responses", "test_reactome_contracts"],
    "antibody-registry": ["test_repaired_adapters"],
    "bio-ontology": ["test_repaired_adapters"],
    "mygene": ["test_repaired_adapters", "test_qualified_gene_identity"],
    "protein-atlas": ["test_hpa_responses"],
    "string": ["test_string_network"],
    "clingen": ["test_clingen_responses", "test_typed_variant_assertions"],
    "opentargets": [
        "test_opentargets_responses",
        "test_opentargets_assessments",
        "test_opentargets_partial",
        "test_opentargets_workflows",
        "test_opentargets_variant_evidence",
        "test_opentargets_pair_evidence",
        "test_source_schemas",
    ],
    "study": [
        "test_study_metadata_contract",
        "test_native_studies",
        "test_study_missingness",
        "test_typed_study_records",
        "test_typed_mutation_profile",
        "test_typed_study_derivations",
        "test_study_initialization",
        "test_study_concurrent_recovery",
        "test_study_statistics_reference",
        "test_study_patient_inference",
        "test_study_statistics_boundaries",
        "test_study_algorithm_benchmark",
        "test_study_cache",
        "test_study_resources",
        "test_study_resource_benchmark",
    ],
}


def qualify(junit, *, probe=None):
    tree = ET.fromstring(junit)
    cases = list(tree.iter("testcase"))
    if not cases or any(
        any(child.tag in {"failure", "error", "skipped"} for child in case) for case in cases
    ):
        raise ValueError("Readiness qualification requires a passing, non-skipped deterministic suite")
    names = {case.get("name") for case in cases}
    for source in PROVIDERS:
        required = {f"test_each_retained_package_imports_offline[{source}]"}
        if source in ADVANCED:
            required.add(f"test_every_declared_retained_operation_exists_in_actual_catalog[{source}]")
        if not required <= names:
            raise ValueError("The required retained adapter inventory is missing")
    modules = {
        name: [case for case in cases if case.get("classname", "").split(".")[-1] == name]
        for group in ENDPOINT_EVIDENCE.values()
        for name in group
    }
    if any(not modules[name] for name in modules):
        raise ValueError("The declared endpoint evidence is missing")
    known = source_names()
    probe = probe or import_probe({name: policy(name)["module"] for name in known})
    entries = {}
    for source in sorted(set(PROVIDERS) | set(ENDPOINT_EVIDENCE)):
        imported = probe["sources"][source]
        if not imported["importable"]:
            raise ValueError("An adapter could not import during readiness qualification")
        evidence = ["tests/test_adapter_inventory.py"] if source in PROVIDERS else []
        endpoint_modules = ENDPOINT_EVIDENCE.get(source, [])
        evidence += [f"tests/{name}.py" for name in endpoint_modules]
        entries[source] = {
            "kind": "endpoint_contract" if endpoint_modules else "inventory",
            "implementation_sha256": imported["implementation_sha256"],
            "scope": (
                "Retained import/declared operation inventory"
                if source in PROVIDERS
                else "Checksummed public study fixtures"
                if source == "study"
                else "Native provider response contracts"
            )
            + (
                "; selected response/identity fixtures (not exhaustive provider qualification)"
                if endpoint_modules
                else "; provider response semantics not qualified by this inventory"
            ),
            "test_count": sum(len(modules[name]) for name in endpoint_modules)
            + (2 if source in ADVANCED and source in PROVIDERS else 1 if source in PROVIDERS else 0),
            "evidence": evidence,
            "evidence_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in evidence
            },
        }
    return {
        "schema_version": "1.0",
        "implementation": REVISION,
        "qualified_at": datetime.now(UTC).isoformat(),
        "junit_sha256": hashlib.sha256(junit).hexdigest(),
        "core_sha256": probe["core_sha256"],
        "dependencies": probe["dependencies"],
        "sources": entries,
        "interpretation": "Offline bounded inventory/endpoint fixtures only; no live-health or model/client readiness claim.",
    }


def test_inputs():
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "tests").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", type=Path, required=True)
    args = parser.parse_args()
    if args.junit.exists():
        raise ValueError("Choose a fresh JUnit output path; existing reports are not used as test proof")
    specifications = {name: policy(name)["module"] for name in source_names()}
    before = import_probe(specifications)
    inputs = test_inputs()
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--junitxml", str(args.junit.resolve())],
        cwd=ROOT,
        timeout=300,
        check=True,
    )
    after = import_probe(specifications)
    if before != after or inputs != test_inputs():
        raise ValueError("Code, dependency or test inputs changed during qualification")
    report = qualify(args.junit.read_bytes(), probe=after)
    report["test_inputs_sha256"] = inputs
    report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["runner"] = (
        "scripts/qualify-readiness.py executed the full deterministic suite with unchanged code/dependency/test inputs"
    )
    path = ROOT / "src/biomedmcp/offline-qualification.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"qualified_sources": len(report["sources"]), "live_qualified": False}))


if __name__ == "__main__":
    main()
