# MyDisease.info retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use search(entity=disease) for discovery and get(entity=disease) with the returned qualified disease identifier. Gene and phenotype enrichment use explicit sections on the public disease record.

Declared advanced operations: `get_gene_disease_evidence`, `get_phenotype_frequency`, `get_phenotype_similarity`, `map_disease_ids`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Keep identifier namespaces and candidate distinctions; a shared label is not proof that two disease concepts are equivalent.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Aggregated disease annotations do not establish prevalence, prognosis or a diagnostic decision. Distinct phenotype/identifier comparison methods require separate scientific qualification. Missing annotations remain unknown.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Melanoma disease identity discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "disease",
    "query": "melanoma"
  }
}
```

## Melanoma record by MONDO identifier

```json
{
  "tool": "get",
  "arguments": {
    "entity": "disease",
    "id": "MONDO:0005105"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [MyDisease.info](https://mydisease.info/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
