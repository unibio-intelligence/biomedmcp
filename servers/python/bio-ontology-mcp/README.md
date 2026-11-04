# BioOntology retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

The BioPortal source exposes ontology discovery, class pages, exact class information and mapping assertions through query_source. Ordinary phenotype term discovery uses the public phenotype route.

Advanced operations: `get_class_info`, `get_mappings`, `get_ontology_classes`, `search_ontologies`.

Run get_capabilities for this source to see its current parameters. Configure BIOONTOLOGY_API_KEY outside tool arguments. The adapter uses the Authorization header. Preserve ontology acronym, exact class URI, mapping source/process and provider continuation; missing process attribution remains explicit.

The examples are tested through MCP against mock responses; live results may differ. Mapping assertions do not imply biological equivalence. The class example uses one exact GO URI and a synthetic credential only in offline tests; it does not establish live credential validity, ontology release pinning or comprehensive coverage.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

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
