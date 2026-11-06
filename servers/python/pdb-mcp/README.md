# RCSB PDB retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use query_source for structure discovery, exact entry metadata, coordinate downloads and quality annotations. The example requests JSON entry metadata for the exact four-character PDB identifier 4HHB.

Advanced operations: `download_structure`, `get_structure_info`, `get_structure_quality`, `search_structures`.

Run get_capabilities for this source to see its current parameters. Entry metadata and coordinate files are different acquisitions. Preserve model, chain, assembly and experimental method when interpreting coordinates; do not assume a default biological assembly or protein isoform.

The examples are tested through MCP against mock responses; live results may differ. Structure identity and coverage do not establish a variant effect, ligand affinity or comparable experimental quality. The example qualifies metadata routing; broader entry, coordinate and quality contracts remain unqualified.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## RCSB entry metadata for hemoglobin structure 4HHB

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "pdb",
    "operation": "get_structure_info",
    "params": {
      "pdb_id": "4HHB",
      "format": "json"
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [RCSB PDB Data API](https://data.rcsb.org/).

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
