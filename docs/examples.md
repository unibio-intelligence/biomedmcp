# Public call examples

Use these typed calls to inspect records or extend an evidence notebook. Calls are tested with synthetic provider responses; live results vary. Check [source release eligibility](source-licenses.md) before execution; unreleased integrations cannot be enabled by adding keys.

## Executable examples

These calls demonstrate routing against synthetic test fixtures; live access and evidence availability are not guaranteed.
Study examples require an installed verified study: ubi_synthetic is the deterministic fixture, not clinical evidence. Substitute an installed study ID from capabilities.
The cBioPortal example requires a real molecular-profile/sample-list pair for the intended population; study_mutations/study_all are fixture identifiers.
Full text requires an accessible PMC record and article-specific rights.

### Human BRCA1 gene discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "gene",
    "query": "BRCA1",
    "filters": {
      "species": 9606
    }
  }
}
```

### Human insulin protein discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "protein",
    "query": "insulin",
    "filters": {
      "species": 9606
    }
  }
}
```

### Ezetimibe compound discovery

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

### Human PCSK9 gene record

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "PCSK9",
    "species": 9606
  }
}
```

### Human LDLR median expression by tissue

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

### Full-text outline for a qualified PMID, when accessible

```json
{
  "tool": "get",
  "arguments": {
    "entity": "article",
    "id": "PMID:123",
    "sections": [
      "fulltext"
    ]
  }
}
```

### Human LDLR expression in liver tissue

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

### Human LDLR eQTL associations in liver tissue

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

### Ezetimibe record by provider-stable identifier

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "OLNTVTPDXPETLC-XPWALMASSA-N"
  }
}
```

### Melanoma record by MONDO identifier

```json
{
  "tool": "get",
  "arguments": {
    "entity": "disease",
    "id": "MONDO:0007750"
  }
}
```

### PCSK9 LDL cholesterol papers

```json
{
  "tool": "literature_search",
  "arguments": {
    "query": "PCSK9 LDL cholesterol"
  }
}
```

### PCSK9 papers since 2024

```json
{
  "tool": "literature_search",
  "arguments": {
    "query": "PCSK9",
    "filters": {
      "source": "pubmed",
      "date_from": "2024-01-01"
    }
  }
}
```

### Open-access familial hypercholesterolemia papers from Europe PMC

```json
{
  "tool": "literature_search",
  "arguments": {
    "query": "familial hypercholesterolemia",
    "filters": {
      "source": "europepmc",
      "open_access": true
    }
  }
}
```

### Recruiting familial hypercholesterolemia trials

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "familial hypercholesterolemia",
    "filters": {
      "status": "RECRUITING"
    }
  }
}
```

### Phase 3 breast-cancer trials

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "breast cancer",
    "filters": {
      "phase": "PHASE3"
    }
  }
}
```

### Ezetimibe trial discovery

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "ezetimibe"
  }
}
```

### PCSK9 R46L variant evidence

```json
{
  "tool": "variant_evidence",
  "arguments": {
    "id": "PCSK9 R46L"
  }
}
```

### GRCh38 PCSK9 variant coordinate evidence

```json
{
  "tool": "variant_evidence",
  "arguments": {
    "id": "chr1:55039974:G:T",
    "assembly": "grch38",
    "sections": [
      "clinvar",
      "population"
    ]
  }
}
```

### Variant evidence for rs11591147

```json
{
  "tool": "variant_evidence",
  "arguments": {
    "id": "rs11591147",
    "sections": [
      "clinvar",
      "population"
    ]
  }
}
```

### Variant evidence in an explicit cBioPortal cohort

```json
{
  "tool": "variant_evidence",
  "arguments": {
    "id": "PCSK9 R46L",
    "sections": [
      "cbioportal"
    ],
    "section_parameters": {
      "cbioportal": {
        "molecular_profile_id": "study_mutations",
        "sample_list_id": "study_all"
      }
    }
  }
}
```

### TP53 mutation frequency in the installed synthetic study

```json
{
  "tool": "study_analysis",
  "arguments": {
    "analysis": "gene_profile",
    "study": "ubi_synthetic",
    "gene": "TP53"
  }
}
```

### Overall survival by TP53 mutation in the installed synthetic study

```json
{
  "tool": "study_analysis",
  "arguments": {
    "analysis": "survival",
    "study": "ubi_synthetic",
    "gene": "TP53",
    "endpoint": "os"
  }
}
```

### TP53/KRAS co-occurrence in the installed synthetic study

```json
{
  "tool": "study_analysis",
  "arguments": {
    "analysis": "co_occurrence",
    "study": "ubi_synthetic",
    "genes": [
      "TP53",
      "KRAS"
    ]
  }
}
```

### Resolve the human LDL receptor gene alias

```json
{
  "tool": "resolve",
  "arguments": {
    "entity": "gene",
    "query": "LDL receptor",
    "species": 9606
  }
}
```

### Resolve rs11591147 before joining evidence

```json
{
  "tool": "resolve",
  "arguments": {
    "entity": "variant",
    "query": "rs11591147"
  }
}
```

### Resolve mouse Trp53 without changing species

```json
{
  "tool": "resolve",
  "arguments": {
    "entity": "gene",
    "query": "Trp53",
    "species": 10090
  }
}
```

### References of a known PubMed article

```json
{
  "tool": "relate",
  "arguments": {
    "entity": "article",
    "id": "PMID:123",
    "relation": "references"
  }
}
```

### PCSK9 R46L structural coverage

```json
{
  "tool": "relate",
  "arguments": {
    "entity": "variant",
    "id": "PCSK9 R46L",
    "relation": "structure"
  }
}
```

### Human PCSK9 article discovery with qualified identity

```json
{
  "tool": "relate",
  "arguments": {
    "entity": "gene",
    "id": "PCSK9",
    "relation": "articles",
    "species": 9606
  }
}
```

### Bounded human LDLR target dossier

```json
{
  "tool": "research",
  "arguments": {
    "workflow": "target_dossier",
    "focus": "LDLR",
    "species": 9606
  }
}
```

### Bounded ezetimibe drug review

```json
{
  "tool": "research",
  "arguments": {
    "workflow": "drug_review",
    "focus": "ezetimibe"
  }
}
```

### Bounded familial hypercholesterolemia disease landscape

```json
{
  "tool": "research",
  "arguments": {
    "workflow": "disease_landscape",
    "focus": "MONDO:0007750"
  }
}
```

### GTEx tissue metadata

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

### Human gene-set enrichment

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "enrichment",
    "operation": "gene_set",
    "params": {
      "genes": [
        "PCSK9",
        "KRAS",
        "TP53"
      ],
      "organism": "hsapiens"
    }
  }
}
```

### Bounded versioned GenBank sequence region

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ncbi-records",
    "operation": "get",
    "params": {
      "database": "genbank",
      "accession": "NM_174936.4",
      "sequence": true,
      "start": 1,
      "stop": 100
    }
  }
}
```

### Batch a human gene record read

```json
{
  "tool": "batch",
  "arguments": {
    "calls": [
      {
        "operation": "get",
        "arguments": {
          "entity": "gene",
          "id": "PCSK9",
          "species": 9606
        }
      }
    ]
  }
}
```

### Batch trial discovery

```json
{
  "tool": "batch",
  "arguments": {
    "calls": [
      {
        "operation": "trial_search",
        "arguments": {
          "query": "familial hypercholesterolemia"
        }
      }
    ]
  }
}
```

### Batch human gene alias resolution

```json
{
  "tool": "batch",
  "arguments": {
    "calls": [
      {
        "operation": "resolve",
        "arguments": {
          "query": "LDL receptor",
          "entity": "gene",
          "species": 9606
        }
      }
    ]
  }
}
```

### Inspect configured capabilities

```json
{
  "tool": "capabilities",
  "arguments": {}
}
```

### Inspect the advanced GTEx schema

```json
{
  "tool": "capabilities",
  "arguments": {
    "source": "gtex"
  }
}
```

### Inspect variant evidence sections

```json
{
  "tool": "capabilities",
  "arguments": {
    "entity": "variant"
  }
}
```

### Read the current account quota

```json
{
  "tool": "quota",
  "arguments": {}
}
```

### ChEMBL aspirin compound discovery

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "chembl",
    "operation": "search_compounds",
    "params": {
      "query": "aspirin",
      "search_type": "name",
      "limit": 10
    }
  }
}
```

### ChEMBL aspirin compound record

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "chembl",
    "operation": "get_compound_details",
    "params": {
      "chembl_id": "CHEMBL25"
    }
  }
}
```

### Human kinase targets in ChEMBL

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "chembl",
    "operation": "search_targets",
    "params": {
      "query": "kinase",
      "organism": "Homo sapiens",
      "limit": 10
    }
  }
}
```

### ChEMBL IC50 measurements for a target, in nM

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "chembl",
    "operation": "search_bioactivities",
    "params": {
      "target_chembl_id": "CHEMBL2095173",
      "activity_type": "IC50",
      "units": "nM",
      "limit": 10
    }
  }
}
```

### Physicochemical rule-of-five assessment for aspirin

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "chembl",
    "operation": "analyze_compound_properties",
    "params": {
      "chembl_id": "CHEMBL25",
      "property_type": "drug_likeness"
    }
  }
}
```

### Batch three distinct ChEMBL compound records

```json
{
  "tool": "batch",
  "arguments": {
    "calls": [
      {
        "operation": "query_source",
        "arguments": {
          "source": "chembl",
          "operation": "get_compound_details",
          "params": {
            "chembl_id": "CHEMBL25"
          }
        }
      },
      {
        "operation": "query_source",
        "arguments": {
          "source": "chembl",
          "operation": "get_compound_details",
          "params": {
            "chembl_id": "CHEMBL521"
          }
        }
      },
      {
        "operation": "query_source",
        "arguments": {
          "source": "chembl",
          "operation": "get_compound_details",
          "params": {
            "chembl_id": "CHEMBL192"
          }
        }
      }
    ]
  }
}
```

### Human RefSeq chromosome-level assembly discovery

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

### Exact GRCh38.p14 assembly and annotation-release metadata

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

### BRCA1 annotation on the exact GRCh38.p14 assembly

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

### Human taxonomy discovery at species rank

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

### Human ancestor TaxIDs and named-rank classification

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

### Human taxonomy, provider names and available assembly page

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

### E. coli MG1655 assembly quality with explicit missing measurements

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

### GRCh38.p14 sequence metadata with lengths and accessions

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

### GRCh38.p14 provider assembly statistics

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

### Human-reference BioProject assembly associations

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

### E. coli MG1655 BioSample assembly associations

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

### Human LDLR sQTL associations in liver tissue

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

### GTEx V10 release metadata

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

### GTEx API service metadata

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

### Metadata for an exact public GTEx sample

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

### Release-qualified human gene transcript annotations

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

### Transcript-associated exons of a release-qualified human gene

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

### A known trial's protocol and posted results

```json
{
  "tool": "get",
  "arguments": {
    "entity": "trial",
    "id": "NCT04368728"
  }
}
```

### A known trial's submitted contacts and sites

```json
{
  "tool": "get",
  "arguments": {
    "entity": "trial",
    "id": "NCT04368728",
    "sections": [
      "contacts",
      "locations"
    ]
  }
}
```

### Melanoma trials listing a Boston site

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "familial hypercholesterolemia AND AREA[LocationCity]Boston",
    "filters": {
      "status": "RECRUITING"
    }
  }
}
```

### Completed COVID-19 trials with posted results

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "COVID-19 AND AREA[HasResults]true",
    "filters": {
      "status": "COMPLETED"
    }
  }
}
```

### Leukemia trial discovery with child eligibility

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "leukemia AND AREA[StdAge]CHILD"
  }
}
```

### Phase memberships in one bounded lung-cancer trial window

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "clinical-trials",
    "operation": "get_trial_statistics",
    "params": {
      "condition": "lung cancer",
      "group_by": "phase",
      "page_size": 25
    }
  }
}
```

### Separate phase, status and enrollment assertions for two trials

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "clinical-trials",
    "operation": "compare_trials",
    "params": {
      "nct_ids": [
        "NCT04368728",
        "NCT04280705"
      ],
      "comparison_fields": [
        "phase",
        "status",
        "enrollment"
      ]
    }
  }
}
```

### Map two human gene symbols to qualified stable identities

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

### Melanoma disease identity discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "disease",
    "query": "familial hypercholesterolemia"
  }
}
```

### Human PCSK9 protein by UniProt accession

```json
{
  "tool": "get",
  "arguments": {
    "entity": "protein",
    "id": "Q8NBP7"
  }
}
```

### Human apoptosis pathway discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "pathway",
    "query": "apoptosis"
  }
}
```

### Reactome apoptosis pathway record

```json
{
  "tool": "get",
  "arguments": {
    "entity": "pathway",
    "id": "R-HSA-109581"
  }
}
```

### Pathway membership for a qualified human PCSK9 gene

```json
{
  "tool": "get",
  "arguments": {
    "entity": "gene",
    "id": "PCSK9",
    "species": 9606,
    "sections": [
      "pathways"
    ]
  }
}
```

### Human LDLR target evidence and source disease associations

```json
{
  "tool": "get",
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

### Human Protein Atlas source annotations for qualified LDLR

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

### Submitted ezetimibe labeling records

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "ezetimibe",
    "sections": [
      "label"
    ]
  }
}
```

### Reported ezetimibe adverse-event records

```json
{
  "tool": "get",
  "arguments": {
    "entity": "drug",
    "id": "ezetimibe",
    "sections": [
      "safety"
    ]
  }
}
```

### Ezetimibe reported adverse-event discovery

```json
{
  "tool": "search",
  "arguments": {
    "entity": "adverse-event",
    "query": "ezetimibe"
  }
}
```

### SureChEMBL patent chemistry discovery for ezetimibe

```json
{
  "tool": "search",
  "arguments": {
    "entity": "patent",
    "query": "ezetimibe"
  }
}
```

### Current Ensembl human assembly metadata

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "ensembl",
    "operation": "get_genome_info",
    "params": {
      "info_type": "assembly",
      "species": "homo_sapiens"
    }
  }
}
```

### RCSB entry metadata for hemoglobin structure 4HHB

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "pdb",
    "operation": "get_structure_info",
    "params": {
      "pdb_id": "4HHB",
      "format": "json"
    }
  }
}
```

### BioPortal Gene Ontology class by its exact URI

```json
{
  "tool": "query_source",
  "arguments": {
    "source": "bio-ontology",
    "operation": "get_class_info",
    "params": {
      "ontology": "GO",
      "class_id": "http://purl.obolibrary.org/obo/GO_0006915"
    }
  }
}
```

### Antibody Registry annotations for an exact RRID

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
