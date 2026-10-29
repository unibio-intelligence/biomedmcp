# UniProt retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use search(entity=protein) with an explicit taxonomy ID and get(entity=protein) with an exact UniProt accession. Sequences, features and cross-references belong to the returned record and projection.

Declared advanced operations: `analyze_evolution`, `compare_proteins`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Follow the public search cursor with unchanged filters. A known accession identifies a specific protein record; isoform sequence/feature coordinates must stay qualified to that isoform. Taxonomy acquisition belongs to the NCBI source route.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Selected response, accession, field projection and pagination contracts are fixture-qualified. Protein annotations and cross-references do not prove a variant mechanism or an experimental interaction. Distinct comparison/evolution operations require their own interpretation and broader qualification.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Human insulin protein discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "protein",
    "query": "insulin",
    "filters": {
      "species": 9606
    }
  }
}
```

## Human BRAF protein by UniProt accession

```json
{
  "tool": "get",
  "arguments": {
    "entity": "protein",
    "id": "P15056"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [UniProt REST API](https://www.uniprot.org/help/api_queries).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
