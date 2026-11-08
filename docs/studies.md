# Install and diagnose public studies

Study analysis reads reviewed, versioned public study releases installed on the server with checksums. It does not download studies or copy private data. The server operator installs studies; diagnosis and analysis only read the installed files.

## Synthetic local demo

The public export includes a small synthetic fixture so a clean installation can exercise study workflows without network or credentials:

```sh
demo_home="$(mktemp -d)"
uv run --frozen python scripts/install-demo-study.py --destination "$demo_home/install"
export UBI_PUBLIC_STUDY_DIR="$demo_home/install/studies"
export UBI_PUBLIC_STUDY_MANIFEST="$demo_home/install/manifest.json"
export UBI_LOCAL_STATE_DIR="$demo_home/state"
uv run --frozen biomedmcp diagnose '{"source":"study"}'
UBI_PROFILE=local uv run --frozen biomedmcp analyze_study '{"analysis":"gene_profile","study":"ubi_synthetic","gene":"TP53"}'
```

The installer copies only the supplied synthetic files to a new destination and computes their manifest checksums. It refuses to overwrite an existing destination. Mutation coverage includes the four declared samples. The [study investigation](investigations.md) adds survival and co-occurrence examples. The results are synthetic, not clinical evidence.

## Real public releases

Choose and review a public release with source access/redistribution terms, attribution, units and known assay coverage. The create-only installer accepts CC0-1.0, CC-BY-4.0, CC-BY-SA-3.0/4.0 and ODbL-1.0 in `data_rights`, with an HTTPS evidence URL and `scope: all_declared_files`. Preserve the upstream data license and share-alike obligations separately from Apache-2.0 integration code. Place it under `<study-root>/<study-id>` and supply `UBI_PUBLIC_STUDY_DIR` and `UBI_PUBLIC_STUDY_MANIFEST` in the server environment. On a hosted server, the operator must install the release. The manifest's `studies` list contains one entry per release with `id`, `enabled`, `release`, `source_url`, `files` and `sha256`.

`files` maps every relative member filename to its approved SHA-256. `sha256` is the SHA-256 of the file mapping encoded as sorted compact JSON (`sort_keys=True`, `separators=(",", ":")`). Verification rejects undeclared/linked files, missing members, wrong checksums and release changes. Review the source's approved checksums before installing; recomputing a new manifest does not validate the scientific contents of a changed real release.

Native tables use tab-delimited cBioPortal-style fields. Clinical sample/patient tables retain `SAMPLE_ID`/`PATIENT_ID` relationships and declared survival endpoint fields. Supported assay filenames are `data_mutations.txt`, `data_cna.txt`, `data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt` and `data_sv.txt`; absent modalities remain unavailable. See the supplied [fixture files](../tests/fixtures/studies/ubi_synthetic) and [study tests](../tests/unit/studies/test_native_studies.py) for concrete field examples. Assay declarations can supply reviewed units under `assays.<kind>.units`; amplification and deletion filtering requires discrete copy-number alteration (CNA) calls. Expression defaults to the named z-score format, not raw counts or transcripts per million (TPM).

For mutation analyses, declare actual assay-evaluable samples and gene coverage under `mutation_coverage.samples` and `mutation_coverage.genes`. Use explicit sample/gene lists; `genes: "all"` applies only when the release actually assays all requested genes. Mutation-event presence alone cannot establish a measured negative in other samples. CNA/expression denominators use finite values per gene; absent/all-missing genes and excluded measurements are reported distinctly. Clinical filters and patient grouping can further reduce the analytic population.

Run `biomedmcp diagnose '{"source":"study"}'` to recheck every release member's checksum and assay metadata without analysis or provider reads. Then call `analyze_study` with the installed `study` identifier and an explicit analysis. Setting the directory does not by itself verify the release. Normal discovery and analysis share initial verification; each analysis independently checksums its consumed files, even when parsed data are cached. Manifest and inventory changes trigger revalidation. Unused files with undetectable metadata changes are rechecked by diagnosis or when consumed; mount reviewed installations read-only. See [statistical methods and interpretation](statistical-methods.md) for patient aggregation, missingness, effects, uncertainty and independent synthetic reference qualification. The [offline algorithm profiler](development/study-algorithm-benchmark.md) measures synthetic membership/log-rank scaling separately from parsing and request latency. The [study resource policy](study-resources.md) describes lazy parsing, shared indexes, aggregate admission and cancellation. Performance and statistics have not yet been validated on real studies; the [README](../README.md) lists current limits.

## Inspect measurement records as an agent

Call `get_capabilities` with `{"source":"study"}` to inspect `record_schemas.study_measurements`. `analyze_study` with `analysis: "gene_profile"` and `type: "expression"` or `"cna"` returns this record family in the study section. The source schema describes the retained finite values, sample counts, measurement coverage and checksummed input locators. Production validation also enforces their cross-field relationships: measured and missing counts partition the eligible sample population, value counts agree with the retained values, and coverage, units and gene matrix identity agree with the verified release.
`total_samples`, `evaluable_samples` and `measured_samples` count finite measured samples for this family. `eligible_samples` includes samples whose gene measurement is missing, and `clinical_samples` describes the installed clinical population. A measured zero remains a measured value. Values retain release units without normalization or imputation; `units_basis` distinguishes a manifest declaration from the named managed file format. `input_locators` identify the clinical population table and the gene row's assay file with their SHA-256 hashes. Gene identity is scoped to that release; the family does not infer species, assembly or transcript from a row label.
Other study analyses retain their distinct denominators and methods; they do not use this measurement discriminator. Inspect omission metadata and recovery actions when a delivered record is bounded. A recovered result refers to the same acquired snapshot. Receipt hashes identify the result and request; they do not establish biological validity or licensing.
