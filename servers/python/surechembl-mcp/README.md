# SureChEMBL retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

The ordinary public patent search acquires SureChEMBL patent-chemistry discovery records. Its distinct chemistry, structure-similarity and statistics operations use query_source.

Declared advanced operations: `analyze_patent_chemistry`, `get_patent_statistics`, `search_similar_structures`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Preserve provider patent and chemical identifiers. Public patent bibliographic retrieval uses the separate patents source and its qualified EPO access mode; a chemistry search record is not a complete patent document.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Chemical mentions do not establish claim scope, biological activity, novelty or freedom to operate. These mocked routes do not establish current SureChEMBL endpoint availability, source access or exhaustive patent coverage.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## SureChEMBL patent chemistry discovery for imatinib

```json
{
  "tool": "search",
  "arguments": {
    "entity": "patent",
    "query": "imatinib"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [SureChEMBL](https://www.surechembl.org/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
