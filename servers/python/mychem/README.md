# MyChem.info retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Discover drug identities with search(entity=drug), then retrieve a provider-stable record using get(entity=drug). Inspect identifier mapping and reported ADMET annotation schemas through capabilities; chemical computations are not advertised.

Declared advanced operations: `get_admet_properties`, `map_identifiers`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Names can be ambiguous. Preserve the returned identifier and separate chemical structures, source assertions and clinical indications when joining records.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Reported source annotations do not establish comparable efficacy, safety or clinical suitability. Missing ADMET modalities are unavailable. This mixed annotation source is eligible under the source policy with SIDER and UMLS content excluded. Source-specific rights and attribution still apply; examples establish fixture routing, not live qualification.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Ezetimibe compound discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "drug",
    "query": "ezetimibe",
    "filters": {
      "source": "mychem"
    }
  }
}
```

## Ezetimibe record by provider-stable identifier

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "OLNTVTPDXPETLC-XPWALMASSA-N"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [MyChem.info](https://mychem.info/).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
