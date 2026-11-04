# openFDA retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use get_record(entity=drug) with explicit label or safety sections and search_records(entity=adverse_event) for reported drug events. Recall acquisition is the distinct advanced operation.

Advanced operations: `search_recalls`.

Run get_capabilities for this source to see its current parameters. Preserve each submitted source record and its provenance. Name-based discovery can require identity review before combining labels or reports.

The examples are tested through MCP against mock responses; live results may differ. Spontaneous reports have no exposure denominator and do not establish event incidence or drug causality. Submitted labels and recall records do not establish individual clinical suitability; optional missing fields remain unknown. The examples qualify routing, not complete provider response semantics.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Submitted ezetimibe labeling records

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "drug",
    "id": "ezetimibe",
    "sections": [
      "label"
    ]
  }
}
```

## Reported ezetimibe adverse-event records

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "drug",
    "id": "ezetimibe",
    "sections": [
      "safety"
    ]
  }
}
```

## Ezetimibe reported adverse-event discovery

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "adverse_event",
    "query": "ezetimibe"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [openFDA API documentation](https://open.fda.gov/apis/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
