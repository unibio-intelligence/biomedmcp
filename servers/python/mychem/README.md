# MyChem.info retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Discover drug identities with search_records(entity=drug), then retrieve a provider-stable record using get_record(entity=drug). Inspect identifier mapping and reported ADMET annotation schemas through get_capabilities; chemical computations are not advertised.

Advanced operations: `get_admet_properties`, `map_identifiers`.

Run get_capabilities for this source to see its current parameters. Names can be ambiguous. Preserve the returned identifier and separate chemical structures, source assertions and clinical indications when joining records.

The examples are tested through MCP against mock responses; live results may differ. Reported source annotations do not establish comparable efficacy, safety or clinical suitability. Missing ADMET modalities are unavailable. This mixed annotation source is eligible under the source policy with SIDER and UMLS content excluded. Source-specific rights and attribution still apply; examples establish fixture routing, not live qualification.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Ezetimibe compound discovery

```json
{
  "tool": "search_records",
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
  "tool": "get_record",
  "arguments": {
    "entity": "drug",
    "id": "OLNTVTPDXPETLC-XPWALMASSA-N"
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [MyChem.info](https://mychem.info/).

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
