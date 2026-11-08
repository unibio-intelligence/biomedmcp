# NCBI Datasets retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

Assembly discovery and exact assembly/annotation retrieval use NCBI Datasets v2 documented report routes. Assembly identity includes its accession version and organism TaxID; annotation-release metadata is retained when supplied. Full metadata does not download genome sequences.

Advanced operations: `find_orthologs`, `get_assembly_data`, `get_genome_data`, `get_taxonomy_data`, `get_virus_info`, `search_ncbi_data`, `search_project_sample`.

Run get_capabilities for this source to see its current parameters. For genome discovery, query selects one taxon; with tax_id or organism, query becomes search text within that taxon. Assembly discovery without a taxon selects an assembly name or exact accession. Use complete_genome for the complete-assembly level. Annotation regions use provider-native coordinates with no inferred offset conversion. Follow next_actions with their unchanged filters and page_token, including an empty final provider window.

The examples are tested through MCP against mock responses; live results may differ. The offline qualification covers assembly/taxonomy discovery, exact assembly and annotation retrieval, taxonomy lineage/names/available genomes, assembly statistics/quality/sequence reports and BioProject/BioSample assembly associations. Project/sample lookup acquires genome assembly associations; it does not promise a universal repository search. CheckM values retain percentage units, marker set and version; annotation Benchmarking Universal Single-Copy Orthologs (BUSCO) values retain raw provider scores, lineage and version without a percent conversion. Missing requested measurements are unavailable and make the public result partial; a measured zero remains data. The CheckM contamination estimate does not establish comprehensive contamination screening. Taxonomy classification names cover selected ranks, while ancestor TaxIDs retain the separate lineage. Secondary report failures preserve successful taxonomy evidence and are not cached as healthy results. Follow generated actions to resume separate genome/name report windows. Selected contracts add exact-GeneID/taxon ortholog-group assertions and versioned viral nucleotide metadata. Orthology is a provider inference with no computed similarity percentage or functional equivalence; raw continuation survives exact-taxon filtering. Unsupported comparison, phylogenetic tree and global-statistics declarations, a first-hit gene lookup and unqualified search modes are retired; taxonomy lineage or assembly statistics do not establish synteny, orthology or phylogenetic inference. Sequence records use the canonical ncbi-records/Ensembl routes; standalone retained BLAST is not a public route. Complete inherited functionality and live client performance are not established. Large records can be explicitly truncated by the public result budget; use any advertised recovery ranges for acquired data, subject to their scope, expiry and storage limits.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

## Human RefSeq chromosome-level assembly discovery

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "search_ncbi_data",
    "params": {
      "query": "Homo sapiens",
      "data_type": "genomes",
      "assembly_source": "refseq",
      "assembly_level": "chromosome",
      "max_results": 10
    }
  }
}
```

## Exact GRCh38.p14 assembly and annotation-release metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_genome_data",
    "params": {
      "accession": "GCF_000001405.40",
      "info_type": "full"
    }
  }
}
```

## BRCA1 annotation on the exact GRCh38.p14 assembly

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_genome_data",
    "params": {
      "accession": "GCF_000001405.40",
      "info_type": "annotation",
      "symbols": [
        "BRCA1"
      ],
      "gene_types": [
        "protein-coding"
      ],
      "page_size": 10
    }
  }
}
```

## Human taxonomy discovery at species rank

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "search_ncbi_data",
    "params": {
      "query": "Homo sapiens",
      "data_type": "taxonomy",
      "rank": "species",
      "max_results": 10
    }
  }
}
```

## Human ancestor TaxIDs and named-rank classification

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_taxonomy_data",
    "params": {
      "tax_id": 9606,
      "info_type": "lineage"
    }
  }
}
```

## Human taxonomy, provider names and available assembly page

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_taxonomy_data",
    "params": {
      "tax_id": 9606,
      "info_type": "organism",
      "include_synonyms": true,
      "genome_page_size": 10
    }
  }
}
```

## E. coli MG1655 assembly quality with explicit missing measurements

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_assembly_data",
    "params": {
      "assembly_accession": "GCF_000005845.2",
      "report_type": "quality"
    }
  }
}
```

## GRCh38.p14 sequence metadata with lengths and accessions

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_assembly_data",
    "params": {
      "assembly_accession": "GCF_000001405.40",
      "report_type": "sequence_report",
      "page_size": 10
    }
  }
}
```

## GRCh38.p14 provider assembly statistics

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "get_assembly_data",
    "params": {
      "assembly_accession": "GCF_000001405.40",
      "report_type": "stats"
    }
  }
}
```

## Human-reference BioProject assembly associations

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "search_project_sample",
    "params": {
      "accession": "PRJNA31257",
      "search_type": "bioproject",
      "max_results": 10
    }
  }
}
```

## E. coli MG1655 BioSample assembly associations

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi",
    "operation": "search_project_sample",
    "params": {
      "accession": "SAMN02604091",
      "search_type": "biosample",
      "max_results": 10
    }
  }
}
```

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [NCBI Datasets REST API and dated OpenAPI](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/rest-api/), [NCBI annotation BUSCO policy](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/data-processing/policies-annotation/quality/busco/). The packaged contracts.json retains twelve selected qualified paths and their referenced schemas, with the source snapshot SHA-256 and retrieval date.

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
