# BioOntology retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

The BioPortal source exposes ontology discovery, class pages, exact class information and mapping assertions through query_source. Ordinary phenotype term discovery uses the public phenotype route.

Declared advanced operations: `get_class_info`, `get_mappings`, `get_ontology_classes`, `search_ontologies`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Configure BIOONTOLOGY_API_KEY outside tool arguments. The adapter uses the Authorization header. Preserve ontology acronym, exact class URI, mapping source/process and provider continuation; missing process attribution remains explicit.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Mapping assertions do not imply biological equivalence. The class example uses one exact GO URI and a synthetic credential only in offline tests; it does not establish live credential validity, ontology release pinning or comprehensive coverage.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## BioPortal Gene Ontology class by its exact URI

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "bio-ontology",
    "operation": "get_class_info",
    "params": {
      "ontology": "GO",
      "class_id": "http://purl.obolibrary.org/obo/GO_0006915"
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [BioOntology REST API](https://data.bioontology.org/documentation).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
