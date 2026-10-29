# Example investigations

Use these workflows to organize a research notebook and make its evidence gaps explicit. Calls are tested with synthetic provider responses; outputs and source availability vary. Check [source release eligibility](source-licenses.md) before execution; keys cannot enable unreleased integrations. Live coverage and scientific adjudication remain separate. Known identifiers can be used directly without mandatory discovery calls. For study examples install the [synthetic demo](studies.md) first.

## Which observations belong in an LDL-receptor evidence notebook?

```sh
UBI_PROFILE=local biomedmcp research '{"workflow":"target_dossier","focus":"LDLR","species":9606}'
UBI_PROFILE=local biomedmcp get '{"entity":"gene","id":"LDLR","species":9606,"sections":["expression"],"section_parameters":{"expression":{"query_type":"gene_tissue","tissue_id":"Liver"}}}'
UBI_PROFILE=local biomedmcp get '{"entity":"gene","id":"LDLR","species":9606,"sections":["eqtl"],"section_parameters":{"eqtl":{"tissue_id":"Liver"}}}'
```

Read the qualified gene/allele identity, expression units/tissue/release, association direction and each section's outcome. Inspect the separate expression/QTL schemas with capabilities for source=gtex. Distinguish posterior probabilities, p-values and standard errors, and paired values from unknown participant counts. Preserve prefilter source pointers, qualified intron joins, provenance, disagreements and recovery. Observational expression/QTL associations do not establish causal target validation; missing sections prevent a complete conclusion.

Keep the JSON results, evidence IDs, source releases and continuation actions with your answer. An error or partial result requires a qualified alternative, continuation or an explicit limitation.

## How can I keep a PCSK9 allele claim separate from gene-level evidence?

```sh
UBI_PROFILE=local biomedmcp variant_evidence '{"id":"PCSK9 R46L"}'
UBI_PROFILE=local biomedmcp relate '{"entity":"variant","id":"PCSK9 R46L","relation":"structure"}'
UBI_PROFILE=local biomedmcp relate '{"entity":"gene","id":"PCSK9","relation":"articles","species":9606}'
```

Confirm allele/transcript/build equivalence before combining assertions. Structural coverage is a sequence mapping, not proof of an experimental residue effect. Gene co-mention papers are discovery leads; inspect experiment/species/variant scope before citing support. Preserve source assertions independently.

Keep the JSON results, evidence IDs, source releases and continuation actions with your answer. An error or partial result requires a qualified alternative, continuation or an explicit limitation.

## Can I reproduce the analysis before using my own study?

```sh
UBI_PROFILE=local biomedmcp study_analysis '{"analysis":"gene_profile","study":"ubi_synthetic","gene":"TP53"}'
UBI_PROFILE=local biomedmcp study_analysis '{"analysis":"survival","study":"ubi_synthetic","gene":"TP53","endpoint":"os"}'
UBI_PROFILE=local biomedmcp study_analysis '{"analysis":"co_occurrence","study":"ubi_synthetic","genes":["TP53","KRAS"]}'
```

Report clinical-study samples separately from mutation-assayed samples, unique mutant samples and mutation events. Use the assay-evaluable denominator, preserve calculation inputs, exclusions and patient grouping, and distinguish missing measurement from measured negative. Inspect capabilities with source=study for the derived record schemas; preserve unavailable inference, source selectors and truncation/recovery. A request's species default does not establish study species or assembly. These synthetic results demonstrate mechanics only; they are not real clinical evidence or validated statistical conclusions for a real study.

Keep the JSON results, evidence IDs, source releases and continuation actions with your answer. An error or partial result requires a qualified alternative, continuation or an explicit limitation.
