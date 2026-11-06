# SureChEMBL retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

The ordinary public patent search acquires SureChEMBL patent-chemistry discovery records. Its distinct chemistry, structure-similarity and statistics operations use query_source.

Advanced operations: `analyze_patent_chemistry`, `get_patent_statistics`, `search_similar_structures`.

Run get_capabilities for this source to see its current parameters. Preserve provider patent and chemical identifiers. Public patent bibliographic retrieval uses the separate patents source and its qualified EPO access mode; a chemistry search record is not a complete patent document.

The examples are tested through MCP against mock responses; live results may differ. Chemical mentions do not establish claim scope, biological activity, novelty or freedom to operate. These mocked routes do not establish current SureChEMBL endpoint availability, source access or exhaustive patent coverage.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## SureChEMBL patent chemistry discovery for ezetimibe

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "patent",
    "query": "ezetimibe"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [SureChEMBL](https://www.surechembl.org/).

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
