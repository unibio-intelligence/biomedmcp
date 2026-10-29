#!/usr/bin/env python3
"""Stream a bounded synthetic resource fixture; never copy clinical data."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def generate(destination, *, samples=10_000, genes=1000):
    if not isinstance(samples, int) or not 4 <= samples <= 10_000:
        raise ValueError("Use 4–10,000 synthetic samples")
    if not isinstance(genes, int) or not 2 <= genes <= 1000:
        raise ValueError("Use 2–1,000 synthetic matrix genes")
    destination.mkdir()
    directory = destination / "studies" / "ubi_resource_synthetic"
    directory.mkdir(parents=True)
    sample_ids = [f"S{i:05d}" for i in range(samples)]
    with (directory / "data_clinical_sample.txt").open("x") as handle:
        handle.write("PATIENT_ID\tSAMPLE_ID\tCANCER_TYPE\n")
        for i, sample in enumerate(sample_ids):
            handle.write(f"P{i:05d}\t{sample}\tSYNTHETIC\n")
    with (directory / "data_clinical_patient.txt").open("x") as handle:
        handle.write("PATIENT_ID\tOS_MONTHS\tOS_STATUS\n")
        for i in range(samples):
            handle.write(f"P{i:05d}\t{i + 1}\t{int(i % 3 != 0)}\n")
    with (directory / "data_mutations.txt").open("x") as handle:
        handle.write("Hugo_Symbol\tTumor_Sample_Barcode\tVariant_Classification\n")
        for i, sample in enumerate(sample_ids):
            for gene, period in [("TP53", 5), ("ERBB2", 7)]:
                if i % period == 0:
                    handle.write(f"{gene}\t{sample}\tMissense_Mutation\n")
    names = ["TP53", "ERBB2", *(f"SYN{i:04d}" for i in range(genes - 2))]
    for filename, expression in [
        ("data_cna.txt", False),
        ("data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt", True),
    ]:
        with (directory / filename).open("x") as handle:
            handle.write("Hugo_Symbol\t" + "\t".join(sample_ids) + "\n")
            for j, gene in enumerate(names):
                values = (
                    str(((i + j) % 11 - 5) / 2) if expression else str((i + j) % 5 - 2)
                    for i in range(samples)
                )
                handle.write(gene + "\t" + "\t".join(values) + "\n")
    files = {path.name: digest(path) for path in directory.iterdir()}
    entry = {
        "id": "ubi_resource_synthetic",
        "enabled": True,
        "release": "synthetic-resource-v1",
        "source_url": "https://example.org/synthetic-resource-fixture",
        "data_rights": {
            "license": "CC0-1.0",
            "evidence_url": "https://example.org/synthetic-resource-fixture",
            "scope": "all_declared_files",
        },
        "files": files,
        "sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "mutation_coverage": {"samples": sample_ids, "genes": "all"},
        "assays": {"expression": {"units": "z_score"}},
        "fixture": {
            "kind": "synthetic",
            "samples": samples,
            "matrix_genes": genes,
            "generator_sha256": digest(Path(__file__)),
            "description": "Artificial identifiers and values; simulated complete mutation assay with two altered genes. No clinical validity or normalization claim.",
        },
    }
    (destination / "manifest.json").write_text(json.dumps({"studies": [entry]}, indent=2) + "\n")
    return {"study": entry["id"], "samples": samples, "matrix_genes": genes, "files_sha256": files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--genes", type=int, default=1000)
    args = parser.parse_args(argv)
    try:
        result = generate(args.destination, samples=args.samples, genes=args.genes)
    except (OSError, ValueError):
        parser.error("Fixture generation failed; use a fresh directory and supported dimensions")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
