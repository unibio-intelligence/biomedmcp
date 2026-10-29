# Antibody Registry retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use query_source with query_antibody and query_type search or details. Detail lookup accepts a numeric registry ID, AB_ identifier or qualified RRID; search preserves bounded page, totalElements and next_page.

Declared advanced operations: `query_antibody`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Access follows the installed source-permission policy at both adapter and wire boundaries; no legacy environment attestation is required. Tests use synthetic website responses and exercise the shipped policy without that flag. Provider redirects retain requested and returned identities.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. The provider FAQ does not offer direct API access; the retained adapter reads website endpoints observed on 2026-10-09. These are not a supported stable API contract. Review current provider terms before enabling live access. Registry annotations do not establish binding, specificity, epitope validity or experimental suitability. Vendor/account/write URLs are not followed.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Antibody Registry annotations for an exact RRID

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "antibody-registry",
    "operation": "query_antibody",
    "params": {
      "query_type": "details",
      "query": "RRID:AB_3753073"
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [Antibody Registry access FAQ](https://www.antibodyregistry.org/faq).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
