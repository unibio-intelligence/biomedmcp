# Example investigations

Each workflow answers one research question in a few calls and explains how to read the results. The calls are tested against mock responses, so live results may differ. If you already know an identifier, use it directly. Some sources are not released, and a key cannot turn them on; see [source release eligibility](source-licenses.md). For the study example, install the [synthetic demo](studies.md) first.

## Which observations belong in an LDL-receptor evidence notebook?

```sh
UBI_PROFILE=local biomedmcp build_dossier '{"workflow":"target_dossier","focus":"LDLR","species":9606}'
UBI_PROFILE=local biomedmcp get_record '{"entity":"gene","id":"LDLR","species":9606,"sections":["expression"],"section_parameters":{"expression":{"query_type":"gene_tissue","tissue_id":"Liver"}}}'
UBI_PROFILE=local biomedmcp get_record '{"entity":"gene","id":"LDLR","species":9606,"sections":["eqtl"],"section_parameters":{"eqtl":{"tissue_id":"Liver"}}}'
```

Check the gene and allele identity, the expression units, tissue and release, the direction of each association, and whether each section succeeded. Keep posterior probabilities, p-values and standard errors apart, and do not assume a participant count that is not reported. Run get_capabilities for source=gtex to see the expression and QTL record fields. Expression and QTL associations are observational: they do not validate a target. If a section is missing, the conclusion is incomplete.

Save the JSON results, evidence IDs and source releases with your answer. If a call fails or returns partial results, continue it, try another source, or state the gap.

## How can I keep a PCSK9 allele claim separate from gene-level evidence?

```sh
UBI_PROFILE=local biomedmcp get_variant_evidence '{"id":"PCSK9 R46L"}'
UBI_PROFILE=local biomedmcp find_related '{"entity":"variant","id":"PCSK9 R46L","relation":"structure"}'
UBI_PROFILE=local biomedmcp find_related '{"entity":"gene","id":"PCSK9","relation":"articles","species":9606}'
```

Before combining results, confirm they refer to the same allele, transcript and genome build. A structure covering the residue is a sequence mapping, not evidence of an experimental effect. Papers that mention the gene are leads: check the experiment, species and variant before citing them. Keep each source's claims separate.

Save the JSON results, evidence IDs and source releases with your answer. If a call fails or returns partial results, continue it, try another source, or state the gap.

## Can I reproduce the analysis before using my own study?

```sh
UBI_PROFILE=local biomedmcp analyze_study '{"analysis":"gene_profile","study":"ubi_synthetic","gene":"TP53"}'
UBI_PROFILE=local biomedmcp analyze_study '{"analysis":"survival","study":"ubi_synthetic","gene":"TP53","endpoint":"os"}'
UBI_PROFILE=local biomedmcp analyze_study '{"analysis":"co_occurrence","study":"ubi_synthetic","genes":["TP53","KRAS"]}'
```

Count study samples, mutation-tested samples, mutated samples and mutation events separately. Use the tested samples as the denominator, keep the inputs, exclusions and patient grouping, and do not count a missing measurement as a negative result. Run get_capabilities for source=study to see the record fields. The request's default species does not tell you the study's species or genome assembly. The demo data is synthetic: it shows how the tools work, not real clinical findings.

Save the JSON results, evidence IDs and source releases with your answer. If a call fails or returns partial results, continue it, try another source, or state the gap.
