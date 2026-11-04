# UniProt retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use search_records(entity=protein) with an explicit taxonomy ID and get_record(entity=protein) with an exact UniProt accession. Sequences, features and cross-references belong to the returned record and projection.

Advanced operations: `analyze_evolution`, `compare_proteins`.

Run get_capabilities for this source to see its current parameters. Follow the public search cursor with unchanged filters. A known accession identifies a specific protein record; isoform sequence/feature coordinates must stay qualified to that isoform. Taxonomy acquisition belongs to the NCBI source route.

The examples are tested through MCP against mock responses; live results may differ. Selected response, accession, field projection and pagination contracts are fixture-qualified. Protein annotations and cross-references do not prove a variant mechanism or an experimental interaction. Distinct comparison/evolution operations require their own interpretation and broader qualification.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human insulin protein discovery

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "protein",
    "query": "insulin",
    "filters": {
      "species": 9606
    }
  }
}
```

## Human PCSK9 protein by UniProt accession

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "protein",
    "id": "Q8NBP7"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [UniProt REST API](https://www.uniprot.org/help/api_queries).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
