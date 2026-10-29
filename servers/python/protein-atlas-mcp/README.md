# Human Protein Atlas retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use get(entity=gene, sections=[hpa]) with an explicit human gene identity. The service resolves the gene to its Ensembl identifier before requesting the source XML annotations.

Declared advanced operations: `analyze_localization`, `compare_expression_profiles`.

Inspect capabilities for this source to obtain the exact current parameter schemas. The public hpa section retains source annotations. Inspect capabilities for localization and expression-profile review schemas; antibody-information acquisition is unavailable.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Single-gene XML is checked for one matching Ensembl identity and required entry/schema/annotation version metadata before caching; this is not full XSD or assay validation. The source release, Ensembl/GENCODE annotation build and whole-document UTF-8 hash remain distinct. XML selectors are explicitly unapplied and comparisons retain successful peers with separate failures, without normalized measurements or derived reliability scores. Do not infer numeric units, assay coverage, tissue-specific negatives or validated specificity from missing annotations. Large compressible XML can be recovered through advertised bounded ranges within unchanged stored-snapshot and response ceilings; decoded size/structure, scope, expiry and storage limits still apply. Broader XML interpretation, TSV antibody acquisition and advanced scientific workflows remain unqualified.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Human Protein Atlas source annotations for qualified LDLR

```json
{
  "tool": "get",
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
