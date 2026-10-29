# Variant population measurements

Call `capabilities` with `{"source":"gnomad"}` to inspect the
`variant_population` field schema. Retrieve measurements through
`variant_evidence`, for example:

```json
{"id":"chr1:55039974:G:T","assembly":"grch38","sections":["population"]}
```

The population section identifies one human GRCh38 chromosome, position,
reference and alternate allele. It performs no implicit lift-over and does not
infer a transcript or clinical classification. Exome, genome and joint
measurements remain independent. Joint counts come from the provider; do not
sum the other modalities or ancestry groups.

Each frequency has unit `proportion`, denominator unit `observed alleles`,
the retained AC and AN inputs, and the explicit method `AC / AN` when AC is
supplied and AN is positive. AC=0 with AN>0 is measured zero. A missing AC,
missing AN or AN=0 leaves frequency null with its own missingness reason.
An unindexed variant or missing modality remains unavailable. Allele numbers
describe source measurement coverage, not participants or a disease cohort.
Source quality filters and ancestry identifiers remain provider assertions.

`source_record_sha256` hashes the selected, validated GraphQL variant node
before derived fields are added; `source_record_locator` is `/data/variant`.
Each frequency's two JSON pointers identify that node's AC and AN fields,
including the exact modality and ancestry array index. Production validation
enforces these pointers, input hash, identity, arithmetic, subset counts and
section outcomes together. The inspectable JSON Schema describes fields;
it does not express all arithmetic and cross-field equalities.

The surrounding section's evidence IDs locate acquired evidence and its
receipt, which binds the public request, participating sources, implementation,
retrieval time and delivered result hashes. `gnomad_r4` is a mutable selector;
the exact source release is unknown, and live repetition is time-dependent.
Do not treat the selected-node hash as a release pin. Bounded results may omit
ancestry rows; use the receipt's evidence resources to recover the same acquired
snapshot without another provider request. See [evidence recovery](evidence-resources.md).

This family covers direct gnomAD population retrieval. Other variant assertions,
gene constraint, provider expression and study-summary families require their
own scientific contracts and qualification.
