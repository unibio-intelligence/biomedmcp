# MyDisease.info retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use search_records(entity=disease) for discovery and get_record(entity=disease) with the returned qualified disease identifier. Gene and phenotype enrichment use explicit sections on the public disease record.

Advanced operations: `get_gene_disease_evidence`, `get_phenotype_frequency`, `get_phenotype_similarity`, `map_disease_ids`.

Run get_capabilities for this source to see its current parameters. Keep identifier namespaces and candidate distinctions; a shared label is not proof that two disease concepts are equivalent.

The examples are tested through MCP against mock responses; live results may differ. Aggregated disease annotations do not establish prevalence, prognosis or a diagnostic decision. Distinct phenotype/identifier comparison methods require separate scientific qualification. Missing annotations remain unknown.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Melanoma disease identity discovery

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "disease",
    "query": "familial hypercholesterolemia"
  }
}
```

## Melanoma record by MONDO identifier

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "disease",
    "id": "MONDO:0007750"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [MyDisease.info](https://mydisease.info/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
