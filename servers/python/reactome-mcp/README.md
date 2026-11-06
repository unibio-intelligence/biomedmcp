# Reactome retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use search_records(entity=pathway) for human pathway discovery, get_record(entity=pathway) for a stable Reactome pathway ID, and get_record(entity=gene, sections=[pathways]) for a qualified gene's source pathway memberships.

Advanced operations: `get_pathway_diagram`.

Run get_capabilities for this source to see its current parameters. Reactome stable IDs carry an organism prefix. The ordinary retained search currently uses Homo sapiens; it does not offer an arbitrary species filter. A pathway diagram has its distinct query_source operation.

The examples are tested through MCP against mock responses; live results may differ. Membership is a source annotation, not proof of pathway activity in a tissue or perturbation. Selected gene-membership list responses are validated; the full search/detail/diagram provider contracts and scientific coverage remain separately qualified work.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human apoptosis pathway discovery

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "pathway",
    "query": "apoptosis"
  }
}
```

## Reactome apoptosis pathway record

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "pathway",
    "id": "R-HSA-109581"
  }
}
```

## Pathway membership for a qualified human PCSK9 gene

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "gene",
    "id": "PCSK9",
    "species": 9606,
    "sections": [
      "pathways"
    ]
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Reactome Content Service](https://reactome.org/ContentService/).

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
