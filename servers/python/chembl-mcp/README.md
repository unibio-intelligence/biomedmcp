# ChEMBL retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.

ChEMBL acquisition retains compound structures, target identity and assay measurements. Ordinary drug identity uses search_records/get_record with MyChem; these ChEMBL operations have distinct scientific semantics.

Advanced operations: `advanced_property_search`, `analyze_compound_properties`, `compare_compound_activities`, `get_assay_details`, `get_compound_details`, `get_target_details`, `search_bioactivities`, `search_compounds`, `search_targets`.

Run get_capabilities for this source to see its current parameters. A batch uses the public batch tool and repeats canonical query_source calls; it does not expose the retained batch_compound_lookup alias.

The examples are tested through MCP against mock responses; live results may differ. Bioactivities retain assay identity, relation, units and target; values from different assays are not automatically comparable. Rule-of-five checks describe physicochemical heuristics and do not establish efficacy, safety, absorption, distribution, metabolism, excretion and toxicity (ADMET) properties or clinical suitability.

To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.

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
  "tool": "run_batch",
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

Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
