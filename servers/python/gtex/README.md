# GTEx retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Human gene expression, eQTL/sQTL evidence and transcript/exon annotations use the canonical get tool with explicit gene sections. Metadata and public sample records use query_source. Gene identity is qualified against the selected dataset's GENCODE release; stable identifiers are not treated as symbols.

Declared advanced operations: `get_metadata`, `get_sample`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Supported release pins are gtex_v8 and gtex_v10. Use source_versions for gene sections and dataset_id for advanced metadata/sample calls. Tissue IDs come from get_metadata(info_type=tissues). Follow next_actions to resume a zero-based provider page with the same qualified gene, tissue, release and filter. Requested limits are capped at 25 records per acquired page to fit the public row budget; later records remain reachable. At most three wholly filtered windows are scanned per call. Provider totals describe raw source records, not the count passing a local p-value filter.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Static QTL filters use measured pValue; METASOFT uses metaP. The service does not send an unsupported pValueThreshold query parameter. A dynamic calculation is retained even when nonsignificant, with an explicit threshold assessment. Dynamic sQTL requires phenotype_id from a validated gene/tissue/variant intron association; an unqualified intron cannot become negative evidence. Donor arrays and standard errors belong to a single QTL measurement record. Offline tests cover dated request and response schemas, exact identity, bounded pagination, filters and actual MCP examples. Transcript and exon sections acquire records for a parent gene, qualified under the selected GENCODE version and genome build; transcript/exon IDs alone are not parent-gene selectors. Exon records preserve their parent transcript and exon ordinal rather than deduplicating shared exons across transcripts. QTL variants are qualified against the selected cohort before joins: rsIDs use snpId and require one complete, unambiguous reference mapping; explicit coordinate variants require the GRCh38 _b38 suffix and matching position/alleles. An unavailable or ambiguous cohort variant stops the join rather than becoming negative QTL evidence. Recovery actions preserve the qualified coordinate identity. Internal gene/variant annotation and top-gene operations are not separate public routes. This adapter does not offer transcript, exon or junction expression tools. Large nested donor arrays can be truncated by the public evidence budget; follow advertised recovery ranges, subject to snapshot storage and response limits. Dataset/source access and scientific suitability require live qualification.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Human LDLR median expression by tissue

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "expression"
    ]
  }
}
```

## Human LDLR expression in liver tissue

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "expression"
    ],
    "section_parameters": {
      "expression": {
        "query_type": "gene_tissue",
        "tissue_id": "Liver"
      }
    }
  }
}
```

## Human LDLR eQTL associations in liver tissue

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "eqtl"
    ],
    "section_parameters": {
      "eqtl": {
        "tissue_id": "Liver"
      }
    }
  }
}
```

## Human LDLR sQTL associations in liver tissue

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "sqtl"
    ],
    "sources": [
      "gtex"
    ],
    "source_versions": {
      "gtex": "gtex_v10"
    },
    "section_parameters": {
      "sqtl": {
        "tissue_id": "Liver",
        "p_value_threshold": 0.05,
        "limit": 10,
        "page": 0
      }
    }
  }
}
```

## Release-qualified human gene transcript annotations

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "transcripts"
    ],
    "sources": [
      "gtex"
    ],
    "source_versions": {
      "gtex": "gtex_v10"
    },
    "section_parameters": {
      "transcripts": {
        "limit": 10,
        "page": 0
      }
    }
  }
}
```

## Transcript-associated exons of a release-qualified human gene

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "LDLR",
    "species": 9606,
    "sections": [
      "exons"
    ],
    "sources": [
      "gtex"
    ],
    "source_versions": {
      "gtex": "gtex_v10"
    },
    "section_parameters": {
      "exons": {
        "limit": 10,
        "page": 0
      }
    }
  }
}
```

## GTEx tissue metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "gtex",
    "operation": "get_metadata",
    "params": {
      "info_type": "tissues",
      "dataset_id": "gtex_v10"
    }
  }
}
```

## GTEx V10 release metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "gtex",
    "operation": "get_metadata",
    "params": {
      "info_type": "dataset",
      "dataset_id": "gtex_v10"
    }
  }
}
```

## GTEx API service metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "gtex",
    "operation": "get_metadata",
    "params": {
      "info_type": "service"
    }
  }
}
```

## Metadata for an exact public GTEx sample

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "gtex",
    "operation": "get_sample",
    "params": {
      "sample_id": "GTEX-1117F-0003-SM-58Q7G",
      "dataset_id": "gtex_v10",
      "limit": 10
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [GTEx Portal API contract](https://gtexportal.org/api/v2/openapi.json). Packaged contracts.json identifies the dated official document hash and the response schemas used for validation.

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
