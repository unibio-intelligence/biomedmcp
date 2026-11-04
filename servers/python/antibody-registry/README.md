# Antibody Registry retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use query_source with query_antibody and query_type search or details. Detail lookup accepts a numeric registry ID, AB_ identifier or qualified RRID; search preserves bounded page, totalElements and next_page.

Advanced operations: `query_antibody`.

Run get_capabilities for this source to see its current parameters. Access follows the installed source-permission policy at both adapter and wire boundaries; no legacy environment attestation is required. Tests use synthetic website responses and exercise the shipped policy without that flag. Provider redirects retain requested and returned identities.

The examples are tested through MCP against mock responses; live results may differ. The provider FAQ does not offer direct API access; the retained adapter reads website endpoints observed on 2026-10-09. These are not a supported stable API contract. Review current provider terms before enabling live access. Registry annotations do not establish binding, specificity, epitope validity or experimental suitability. Vendor/account/write URLs are not followed.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

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
