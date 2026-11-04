# Source credentials and access

Most sources need no key. For those that do, set the key as an environment variable where the server runs, or in your client's secret storage, then restart the server. Never put keys in tool arguments. On a hosted server, ask whoever runs it to set up keys. Setting a variable does not check that the key works, that you have rights to the data, or that the source is reachable.

Per-user keys on a shared hosted server need secret storage that this package does not provide; never switch users by changing server-wide environment variables. A source marked **Not released** stays off even with a key or `UBI_LICENSED_SOURCES`. Available sources still have data terms; check them in the [source license inventory](source-licenses.md) before reusing data.

| Source | Required environment | Optional environment | Status |
| --- | --- | --- | --- |
| `alphamissense` | None | None | Available |
| `antibody-registry` | None | None | Available |
| `bio-ontology` | `BIOONTOLOGY_API_KEY` | None | Available with your provider key |
| `cancerhotspots` | None | None | Available |
| `cbioportal` | None | None | Available |
| `chembl` | None | None | Available |
| `civic` | None | None | Available |
| `clingen` | None | None | Available |
| `clinical-trials` | None | None | Available |
| `complexportal` | None | None | Available |
| `cpic` | None | None | Available |
| `dailymed` | None | None | Available |
| `depmap` | None | None | Not available in this release |
| `disgenet` | `DISGENET_API_KEY` | None | Not released |
| `ema` | None | None | Available |
| `enrichment` | None | None | Available |
| `ensembl` | None | None | Available |
| `europepmc` | None | None | Available |
| `eve` | None | None | Available |
| `fda-devices` | None | None | Available |
| `gencc` | None | None | Available |
| `gnomad` | None | None | Available |
| `gtex` | None | None | Available |
| `gtr` | None | `NCBI_API_KEY` | Available |
| `gwas` | None | None | Available |
| `interpro` | None | None | Available |
| `litsense2` | None | None | Available |
| `monarch` | None | None | Available |
| `mychem` | None | None | Available |
| `mydisease` | None | None | Available |
| `mygene` | None | None | Available |
| `myvariant` | None | None | Not released |
| `ncbi` | None | `NCBI_API_KEY` | Available |
| `ncbi-records` | None | `NCBI_API_KEY` | Available |
| `nci` | `NCI_API_KEY` | None | Available with your provider key |
| `nih-reporter` | None | None | Available |
| `ols` | None | None | Available |
| `omnipath` | None | None | Available |
| `oncokb` | `ONCOKB_TOKEN` | None | Not released |
| `openalex` | None | `OPENALEX_API_KEY` | Available |
| `openfda` | None | `OPENFDA_API_KEY` | Available |
| `opentargets` | None | None | Available |
| `orange-book` | None | None | Available |
| `orcid` | None | None | Available |
| `patents` | `EPO_OPS_CONSUMER_KEY`, `EPO_OPS_CONSUMER_SECRET` | None | Not released |
| `pdb` | None | None | Available |
| `pmc` | None | `NCBI_API_KEY` | Available |
| `protein-atlas` | None | None | Available |
| `pubmed` | None | `NCBI_API_KEY` | Available |
| `pubtator` | None | None | Available |
| `reactome` | None | None | Available |
| `string` | None | None | Available |
| `study` | `UBI_PUBLIC_STUDY_DIR`, `UBI_PUBLIC_STUDY_MANIFEST` | None | Available after you install a checksummed study release |
| `surechembl` | None | None | Available |
| `uniprot` | None | None | Available |
| `who` | None | None | Available |
| `who-ivd` | None | None | Available |

To check a source's setup, run `biomedmcp diagnose '{"source":"bio-ontology"}'`. It tells you whether a setting is missing or the source failed to load. For fixes, see the [connection guide](connect.md) and [study guide](studies.md).
