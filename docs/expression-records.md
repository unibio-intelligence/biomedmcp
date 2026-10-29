# GTEx expression records

Call `capabilities` with `{"source":"gtex"}` to inspect the discriminated
`expression` field schema. Gene expression retrieval uses the existing `get`
tool, for example:

```json
{"entity":"gene","id":"ENSG00000169174.14","sections":["expression"],"sources":["gtex"],"source_versions":{"gtex":"gtex_v10"}}
```

`gene_median` returns `provider_median_expression` assertions. These are
provider-reported tissue medians; Ubi does not recompute a median or infer the
number of participants contributing to it. `gene_tissue`, with an explicit
tissue ID, returns `provider_expression_values` assertions. The supplied value
count identifies the length of that source record's complete acquired series.
It does not identify participants, an assay population, or missing measurements.
Both those denominators remain null. A reported zero remains a measurement.
Missing/malformed required measurements fail validation rather than becoming
zero. An empty provider record collection does not establish zero expression.

Records preserve the resolved versioned GENCODE gene, supported dataset and
its reference annotation/build context. Species is the human GTEx dataset
scope; no transcript is inferred. The tissue ID uses the GTEx tissue namespace.
The independent reported ontology code is retained without claiming a canonical
tissue-to-ontology equivalence. Provider gene symbols remain reported metadata;
joins use the resolved versioned gene identity. Subset metadata is retained.

Units remain exactly as reported under the
[GTEx API contract](https://gtexportal.org/api/v2/redoc). No transformation,
imputation, or normalization is performed here. Array positions do not provide
retained sample identifiers for joining measurements across genes or tissues.
Provider page totals count records, while `provided_value_count` counts a
series's supplied values. Neither quantity becomes a participant denominator.

Each record has a hash of its source fields before annotation and a locator
containing the endpoint, zero-based provider page, row index, measurement pointer
and units pointer. Production validators enforce gene/release consistency,
source hashes, pointers and value counts. The inspectable JSON Schema describes
fields and discriminators; it cannot express every arithmetic or hash equality.

The surrounding section's evidence IDs and receipt locate the acquired evidence
and bind the public request, participating sources, implementation, retrieval
time and delivered hashes. A dataset label does not prove immutable HTTP replay:
receipts remain time-dependent with exact reproduction unestablished. Follow
provider actions for later records. Use [evidence resources](evidence-resources.md)
to recover values omitted from the current acquired snapshot without another
provider call. Recover a complete record before recomputing its input hash or
validating its original supplied-value count; bounded views may omit values.

This family covers the two public gene expression sections. The separate
[QTL family](qtl-records.md) covers five public association/calculation assertions.
Other expression sources, GTEx comparisons, nested dossiers and other scientific
record families require their own contracts and qualification.
