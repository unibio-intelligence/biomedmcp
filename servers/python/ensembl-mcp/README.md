# Ensembl retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Distinct sequence, assembly, regulation, evolution, coordinate and variant operations use query_source. The example retrieves assembly metadata for the explicit homo_sapiens provider selector.

Advanced operations: `analyze_evolution`, `analyze_variants`, `get_genome_info`, `get_regulatory_elements`, `get_sequences`, `map_coordinates`.

Run get_capabilities for this source to see its current parameters. Current assembly metadata is time-dependent. Preserve assembly/version and sequence identifiers supplied by the provider; do not silently treat current server data as a requested historical release or infer coordinate conversions.

The examples are tested through MCP against mock responses; live results may differ. Offline contracts validate genome metadata, qualified sequence identities, species-qualified homology and gene-tree member routes, regional feature lists, VEP identifier results and assembly mappings before evidence and caching. Protein retrieval retains all returned translations; FASTA is derived from validated JSON. Null batch lookups are unavailable, not negative evidence. These are minimum acquisition checks, not full scientific annotation validation. Homology is a provider inference; its cdna selector uses coding-DNA alignments. Mappings can cover only part of the requested region. Current lookup versions are checked when explicitly requested; they do not request a historical release. Translation lookup can omit assembly metadata. Sequence query echoes and Ensembl namespaces qualify source attribution but do not independently establish every transcript/translation's membership or functional equivalence. Live health and comprehensive biological interpretation remain unqualified.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

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

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
