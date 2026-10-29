# Open Targets retained adapter

Generated from biomedmcp.examples. From the public runtime root, refresh with uv run --frozen python scripts/catalog.py.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Retrieve human gene sections target_evidence, diseases and druggability through get. The public target_dossier composes those assertions with expression and literature under one qualified gene identity.

Declared advanced operations: `analyze_advanced`, `analyze_association`, `query_genetics`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Stable Ensembl gene identifiers are resolved before target acquisition. Keep the source association score, tractability modality and disease identifier attached to each assertion.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Association scores are not clinical risk probabilities, treatment effects or proof of causality. Tractability annotations do not establish safety or therapeutic efficacy. Distinct advanced association/genetics operations and nested response meanings require separate qualification.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Human ERBB2 target evidence and source disease associations

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "ERBB2",
    "species": 9606,
    "sections": [
      "target_evidence",
      "diseases",
      "druggability"
    ]
  }
}
```

## Bounded human ERBB2 target dossier

```json
{
  "tool": "research",
  "arguments": {
    "workflow": "target_dossier",
    "focus": "ERBB2",
    "species": 9606
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Open Targets Platform API](https://platform-docs.opentargets.org/data-access/graphql-api).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
