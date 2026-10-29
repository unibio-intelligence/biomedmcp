# Ensembl retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Distinct sequence, assembly, regulation, evolution, coordinate and variant operations use query_source. The example retrieves assembly metadata for the explicit homo_sapiens provider selector.

Declared advanced operations: `analyze_evolution`, `analyze_variants`, `get_genome_info`, `get_regulatory_elements`, `get_sequences`, `map_coordinates`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Current assembly metadata is time-dependent. Preserve assembly/version and sequence identifiers supplied by the provider; do not silently treat current server data as a requested historical release or infer coordinate conversions.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Offline contracts validate genome metadata, qualified sequence identities, species-qualified homology and gene-tree member routes, regional feature lists, VEP identifier results and assembly mappings before evidence and caching. Protein retrieval retains all returned translations; FASTA is derived from validated JSON. Null batch lookups are unavailable, not negative evidence. These are minimum acquisition checks, not full scientific annotation validation. Homology is a provider inference; its cdna selector uses coding-DNA alignments. Mappings can cover only part of the requested region. Current lookup versions are checked when explicitly requested; they do not request a historical release. Translation lookup can omit assembly metadata. Sequence query echoes and Ensembl namespaces qualify source attribution but do not independently establish every transcript/translation's membership or functional equivalence. Live health and comprehensive biological interpretation remain unqualified.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Current Ensembl human assembly metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ensembl",
    "operation": "get_genome_info",
    "params": {
      "info_type": "assembly",
      "species": "homo_sapiens"
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Ensembl assembly API](https://rest.ensembl.org/documentation/info/assembly_info).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
