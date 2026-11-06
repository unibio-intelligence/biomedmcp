# MyGene.info retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Use search and resolve for gene discovery and get for known genes. Keep one explicit taxonomy ID through follow-up enrichment. map_gene_ids is the distinct batch mapping operation for up to 25 inputs in one declared namespace and species.

Advanced operations: `compare_genes`, `map_gene_ids`.

Run get_capabilities for this source to see its current parameters. Resolve ambiguity before joining evidence. Mapping accepts symbol, entrezgene or ensembl.gene and retains each input's qualified candidates; it does not choose a species from the spelling of a symbol.

The examples are tested through MCP against mock responses; live results may differ. Mapping failures, wrong-species rows and absent provider responses are not evidence of absence. Provider annotation coverage and ontology assertions require source-specific interpretation. The former standalone 1,000-gene batch and export helpers are not public routes.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human BRCA1 gene discovery

```json
{
  "tool": "search_records",
  "arguments": {
    "entity": "gene",
    "query": "BRCA1",
    "filters": {
      "species": 9606
    }
  }
}
```

## Human PCSK9 gene record

```json
{
  "tool": "get_record",
  "arguments": {
    "entity": "gene",
    "id": "PCSK9",
    "species": 9606
  }
}
```

## Resolve the human LDL receptor gene alias

```json
{
  "tool": "resolve_entity",
  "arguments": {
    "entity": "gene",
    "query": "LDL receptor",
    "species": 9606
  }
}
```

## Resolve mouse Trp53 without changing species

```json
{
  "tool": "resolve_entity",
  "arguments": {
    "entity": "gene",
    "query": "Trp53",
    "species": 10090
  }
}
```

## Map two human gene symbols to qualified stable identities

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "mygene",
    "operation": "map_gene_ids",
    "params": {
      "gene_ids": [
        "PCSK9",
        "LDLR"
      ],
      "input_namespace": "symbol",
      "species": 9606
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [MyGene.info query and batch API](https://docs.mygene.info/en/latest/doc/query_service.html).

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
