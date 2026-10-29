# Reactome retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use search(entity=pathway) for human pathway discovery, get(entity=pathway) for a stable Reactome pathway ID, and get(entity=gene, sections=[pathways]) for a qualified gene's source pathway memberships.

Declared advanced operations: `get_pathway_diagram`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Reactome stable IDs carry an organism prefix. The ordinary retained search currently uses Homo sapiens; it does not offer an arbitrary species filter. A pathway diagram has its distinct query_source operation.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Membership is a source annotation, not proof of pathway activity in a tissue or perturbation. Selected gene-membership list responses are validated; the full search/detail/diagram provider contracts and scientific coverage remain separately qualified work.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Human apoptosis pathway discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "pathway",
    "query": "apoptosis"
  }
}
```

## Reactome apoptosis pathway record

```json
{
  "tool": "get",
  "arguments": {
    "entity": "pathway",
    "id": "R-HSA-109581"
  }
}
```

## Pathway membership for a qualified human BRAF gene

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "BRAF",
    "species": 9606,
    "sections": [
      "pathways"
    ]
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Reactome Content Service](https://reactome.org/ContentService/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
