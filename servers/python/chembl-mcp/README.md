# ChEMBL retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

ChEMBL acquisition retains compound structures, target identity and assay measurements. Ordinary drug identity uses the public search/get routes with MyChem; these ChEMBL operations have distinct scientific semantics.

Declared advanced operations: `advanced_property_search`, `analyze_compound_properties`, `compare_compound_activities`, `get_assay_details`, `get_compound_details`, `get_target_details`, `search_bioactivities`, `search_compounds`, `search_targets`.

Inspect capabilities for this source to obtain the exact current parameter schemas. A batch uses the public batch tool and repeats canonical query_source calls; it does not expose the retained batch_compound_lookup alias.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. Bioactivities retain assay identity, relation, units and target; values from different assays are not automatically comparable. Rule-of-five checks describe physicochemical heuristics and do not establish efficacy, safety, ADMET or clinical suitability.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## ChEMBL aspirin compound discovery

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

## ChEMBL aspirin compound record

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

## Human kinase targets in ChEMBL

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

## ChEMBL IC50 measurements for a target, in nM

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

## Physicochemical rule-of-five assessment for aspirin

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

## Batch three distinct ChEMBL compound records

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

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [ChEMBL REST API](https://www.ebi.ac.uk/chembl/api/data/docs), [aspirin record](https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL25.json).

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
