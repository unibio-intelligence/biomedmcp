# Source credentials and access

Generated from current source policy. Set secrets in the server/operator environment or client secret storage; never pass them as scientific tool arguments. Hosted users ask the operator to configure source access. Restart processes after changing source credentials. Environment presence does not verify credentials, rights, live availability or scientific coverage.

Local users may supply supported keys in their own process environment or client secret storage. Shared hosted per-user keys require a separately implemented platform secret boundary; never switch users by changing server-wide environment variables. `UBI_LICENSED_SOURCES` and keys cannot override an unreleased source. Review the [source license inventory](source-licenses.md); source eligibility and integration-code licensing are separate.

| Source | Required environment | Optional environment | Source release / access policy |
| --- | --- | --- | --- |
| `alphamissense` | None | None | eligible; No access credential required by this implementation; review source terms |
| `antibody-registry` | None | None | eligible; No access credential required by this implementation; review source terms |
| `bio-ontology` | `BIOONTOLOGY_API_KEY` | None | eligible; Provider credentials required; review account/access terms |
| `cancerhotspots` | None | None | eligible; No access credential required by this implementation; review source terms |
| `cbioportal` | None | None | eligible; No access credential required by this implementation; review source terms |
| `chembl` | None | None | eligible; No access credential required by this implementation; review source terms |
| `civic` | None | None | eligible; No access credential required by this implementation; review source terms |
| `clingen` | None | None | eligible; No access credential required by this implementation; review source terms |
| `clinical-trials` | None | None | eligible; No access credential required by this implementation; review source terms |
| `complexportal` | None | None | eligible; No access credential required by this implementation; review source terms |
| `cpic` | None | None | eligible; No access credential required by this implementation; review source terms |
| `dailymed` | None | None | eligible; No access credential required by this implementation; review source terms |
| `depmap` | None | None | Retained route unavailable; use a separately released qualified platform data capability |
| `disgenet` | `DISGENET_API_KEY` | None | unreleased; Explicitly qualified licensed/access mode required; `UBI_LICENSED_SOURCES` includes `disgenet` |
| `ema` | None | None | eligible; No access credential required by this implementation; review source terms |
| `enrichment` | None | None | eligible; No access credential required by this implementation; review source terms |
| `ensembl` | None | None | eligible; No access credential required by this implementation; review source terms |
| `europepmc` | None | None | eligible; No access credential required by this implementation; review source terms |
| `eve` | None | None | eligible; No access credential required by this implementation; review source terms |
| `fda-devices` | None | None | eligible; No access credential required by this implementation; review source terms |
| `gencc` | None | None | eligible; No access credential required by this implementation; review source terms |
| `gnomad` | None | None | eligible; No access credential required by this implementation; review source terms |
| `gtex` | None | None | eligible; No access credential required by this implementation; review source terms |
| `gtr` | None | `NCBI_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `gwas` | None | None | eligible; No access credential required by this implementation; review source terms |
| `interpro` | None | None | eligible; No access credential required by this implementation; review source terms |
| `litsense2` | None | None | eligible; No access credential required by this implementation; review source terms |
| `monarch` | None | None | eligible; No access credential required by this implementation; review source terms |
| `mychem` | None | None | eligible; No access credential required by this implementation; review source terms |
| `mydisease` | None | None | eligible; No access credential required by this implementation; review source terms |
| `mygene` | None | None | eligible; No access credential required by this implementation; review source terms |
| `myvariant` | None | None | unreleased; No access credential required by this implementation; review source terms |
| `ncbi` | None | `NCBI_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `ncbi-records` | None | `NCBI_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `nci` | `NCI_API_KEY` | None | eligible; Provider credentials required; review account/access terms |
| `nih-reporter` | None | None | eligible; No access credential required by this implementation; review source terms |
| `ols` | None | None | eligible; No access credential required by this implementation; review source terms |
| `omnipath` | None | None | eligible; No access credential required by this implementation; review source terms |
| `oncokb` | `ONCOKB_TOKEN` | None | unreleased; Explicitly qualified licensed/access mode required; `UBI_LICENSED_SOURCES` includes `oncokb` |
| `openalex` | None | `OPENALEX_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `openfda` | None | `OPENFDA_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `opentargets` | None | None | eligible; No access credential required by this implementation; review source terms |
| `orange-book` | None | None | eligible; No access credential required by this implementation; review source terms |
| `orcid` | None | None | eligible; No access credential required by this implementation; review source terms |
| `patents` | `EPO_OPS_CONSUMER_KEY`, `EPO_OPS_CONSUMER_SECRET` | None | unreleased; Account terms require operator review |
| `pdb` | None | None | eligible; No access credential required by this implementation; review source terms |
| `pmc` | None | `NCBI_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `protein-atlas` | None | None | eligible; No access credential required by this implementation; review source terms |
| `pubmed` | None | `NCBI_API_KEY` | eligible; No access credential required by this implementation; review source terms |
| `pubtator` | None | None | eligible; No access credential required by this implementation; review source terms |
| `reactome` | None | None | eligible; No access credential required by this implementation; review source terms |
| `string` | None | None | eligible; No access credential required by this implementation; review source terms |
| `study` | `UBI_PUBLIC_STUDY_DIR`, `UBI_PUBLIC_STUDY_MANIFEST` | None | eligible; Checksummed public release required |
| `surechembl` | None | None | eligible; No access credential required by this implementation; review source terms |
| `uniprot` | None | None | eligible; No access credential required by this implementation; review source terms |
| `who` | None | None | eligible; No access credential required by this implementation; review source terms |
| `who-ivd` | None | None | eligible; No access credential required by this implementation; review source terms |

Use `biomedmcp diagnose '{"source":"bio-ontology"}'` to distinguish missing settings from import failure and qualification evidence. The [connection guide](connect.md) and [study guide](studies.md) provide recovery steps.
