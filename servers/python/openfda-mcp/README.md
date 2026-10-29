# openFDA retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use get(entity=drug) with explicit label or safety sections and search(entity=adverse-event) for reported drug events. Recall acquisition is the distinct advanced operation.

Declared advanced operations: `search_recalls`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Preserve each submitted source record and its provenance. Name-based discovery can require identity review before combining labels or reports.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Spontaneous reports have no exposure denominator and do not establish event incidence or drug causality. Submitted labels and recall records do not establish individual clinical suitability; optional missing fields remain unknown. The examples qualify routing, not complete provider response semantics.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Submitted imatinib labeling records

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "imatinib",
    "sections": [
      "label"
    ]
  }
}
```

## Reported imatinib adverse-event records

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "imatinib",
    "sections": [
      "safety"
    ]
  }
}
```

## Imatinib reported adverse-event discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "adverse-event",
    "query": "imatinib"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [openFDA API documentation](https://open.fda.gov/apis/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
