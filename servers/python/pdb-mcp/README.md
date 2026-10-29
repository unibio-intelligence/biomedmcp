# RCSB PDB retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use query_source for structure discovery, exact entry metadata, coordinate downloads and quality annotations. The example requests JSON entry metadata for the exact four-character PDB identifier 4HHB.

Declared advanced operations: `download_structure`, `get_structure_info`, `get_structure_quality`, `search_structures`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Entry metadata and coordinate files are different acquisitions. Preserve model, chain, assembly and experimental method when interpreting coordinates; do not assume a default biological assembly or protein isoform.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Structure identity and coverage do not establish a variant effect, ligand affinity or comparable experimental quality. The example qualifies metadata routing; broader entry, coordinate and quality contracts remain unqualified.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

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

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
