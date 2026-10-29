# ClinicalTrials.gov retained adapter

Examples use the public BioMedMCP tools and their typed JSON arguments.

Use the biomedmcp server and its canonical tools. Retained adapters are implementation packages; their internal tools are not separate public MCP mounts.

Use trial_search for trial discovery, get(entity=trial) for known NCT records and explicit submitted protocol sections, and query_source for the two distinct comparison/statistics operations. The public surface keeps its compact tool interface; the eight retained implementation helpers are not separately mounted public aliases.

Declared advanced operations: `compare_trials`, `get_trial_statistics`.

Inspect capabilities for this source to obtain the exact current parameter schemas. Queries use the documented Essie syntax for location, sponsor, dates, posted results or age eligibility when an ordinary trial filter is insufficient. Follow the signed trial_search cursor; query_source statistics uses its generated next_actions to retrieve another provider window with unchanged filters. Counts in separate windows are not cumulative. Identifier-only queries cannot be combined with filters because the provider ignores those filters; use get for known NCT records. To discover trials sharing a reference trial's conditions, retrieve that record first and search its actual submitted condition terms; co-condition discovery is not a validated similarity score.

These examples pass schemas and preflight and execute through MCP against mocked provider responses. They do not establish live source health or comprehensive scientific qualification. The adapter validates dated OpenAPI request/response schemas, exact or explicitly aliased NCT identity, nested protocol/results fields, counts and continuation before extracting evidence. Missing optional protocol modules are unavailable, not measured negative evidence. Statistics count unique study memberships per label in one bounded provider-returned window, with acquired/grouped/missing denominators and explicit completeness. A trial can have several phase or condition labels; their sum may exceed the study denominator. The window is not a representative population sample. Comparisons preserve successful peers and safe failures, retain ACTUAL versus ESTIMATED enrollment, and mark missing fields unavailable. Missing enrollment counts are unavailable; counts without an actual/estimated classification remain partial. Registry protocol endpoints and posted results do not establish comparable treatment effects, individual eligibility, current site recruitment or clinical suitability. Large nested records can be truncated; follow advertised recovery ranges for acquired data. Real agent/client and full provider qualification remain open. No claim of complete inherited functionality is made.

Follow advertised provider continuation for further acquisition. If the result advertises an evidence recovery URI, use its bounded ranges to read acquired data omitted from the preview; see [evidence recovery](../../../docs/evidence-resources.md). Snapshot scope, expiry and source rights still apply.

## Recruiting familial hypercholesterolemia trials

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

## Phase 3 breast-cancer trials

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

## Ezetimibe trial discovery

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "ezetimibe"
  }
}
```

## A known trial's protocol and posted results

```json
{
  "tool": "get",
  "arguments": {
    "entity": "trial",
    "id": "NCT04368728"
  }
}
```

## A known trial's submitted contacts and sites

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

## Melanoma trials listing a Boston site

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

## Completed COVID-19 trials with posted results

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

## Leukemia trial discovery with child eligibility

```json
{
  "tool": "trial_search",
  "arguments": {
    "query": "leukemia AND AREA[StdAge]CHILD"
  }
}
```

## Phase memberships in one bounded lung-cancer trial window

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

## Separate phase, status and enrollment assertions for two trials

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

See the [public runtime README](../../../README.md) for installation, source configuration and testing.

Provider contracts: [ClinicalTrials.gov REST API and dated OpenAPI](https://clinicaltrials.gov/api/oas/v2), [study data structure](https://clinicaltrials.gov/data-api/about-api/study-data-structure), [complex search syntax](https://clinicaltrials.gov/find-studies/constructing-complex-search-queries). Packaged contracts.json records the official source hash/date and selected endpoint schemas.

Licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).
