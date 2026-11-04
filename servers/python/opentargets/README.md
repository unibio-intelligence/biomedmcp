# Open Targets retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Retrieve human gene sections target_evidence, diseases and druggability through get. The public target_dossier composes those assertions with expression and literature under one qualified gene identity.

Advanced operations: `analyze_advanced`, `analyze_association`, `query_genetics`.

Run get_capabilities for this source to see its current parameters. Stable Ensembl gene identifiers are resolved before target acquisition. Keep the source association score, tractability modality and disease identifier attached to each assertion.

The examples are tested through MCP against mock responses; live results may differ. Association scores are not clinical risk probabilities, treatment effects or proof of causality. Tractability annotations do not establish safety or therapeutic efficacy. Distinct advanced association/genetics operations and nested response meanings require separate qualification.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human LDLR target evidence and source disease associations

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "target_evidence",
      "diseases",
      "druggability"
    ]
  }
}
```

## Bounded human LDLR target dossier

```json
{
  "tool": "build_dossier",
  "arguments": {
    "workflow": "target_dossier",
    "focus": "LDLR",
    "species": 9606
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Open Targets Platform API](https://platform-docs.opentargets.org/data-access/graphql-api).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
