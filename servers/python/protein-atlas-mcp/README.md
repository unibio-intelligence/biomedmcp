# Human Protein Atlas retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use get_record(entity=gene, sections=[hpa]) with an explicit human gene identity. The service resolves the gene to its Ensembl identifier before requesting the source XML annotations.

Advanced operations: `analyze_localization`, `compare_expression_profiles`.

Run get_capabilities for this source to see its current parameters. The public hpa section retains source annotations. Inspect get_capabilities for localization and expression-profile review schemas; antibody-information acquisition is unavailable.

The examples are tested through MCP against mock responses; live results may differ. Single-gene XML is checked for one matching Ensembl identity and required entry/schema/annotation version metadata before caching; this is not full XSD or assay validation. The source release, Ensembl/GENCODE annotation build and whole-document UTF-8 hash remain distinct. XML selectors are explicitly unapplied and comparisons retain successful peers with separate failures, without normalized measurements or derived reliability scores. Do not infer numeric units, assay coverage, tissue-specific negatives or validated specificity from missing annotations. Large compressible XML can be recovered through advertised bounded ranges within unchanged stored-snapshot and response ceilings; decoded size/structure, scope, expiry and storage limits still apply. Broader XML interpretation, TSV antibody acquisition and advanced scientific workflows remain unqualified.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human Protein Atlas source annotations for qualified LDLR

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "hpa"
    ]
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Human Protein Atlas data downloads and formats](https://www.proteinatlas.org/about/download).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
