# gnomAD population and constraint evidence

`variant_evidence` population retrieval uses one GRCh38 allele and the
`gnomad_r4` browser dataset selector. The response must agree on variant ID,
reference genome, chromosome, position and both alleles. MyVariant-derived
SNV mappings require one explicit GRCh38 coordinate annotation; this service
does not perform a lift-over. Gene constraint uses one qualified Ensembl gene
ID and checks the returned gene ID, symbol, reference genome and available
NCBI ID. Nonhuman, ambiguous or missing identity mappings stop acquisition.

For an explicit GRCh38 single-nucleotide variant, request only `population`
with `sources: ["gnomad"]`, for example
`variant_evidence(id="chr1:55039974:G:T", assembly="grch38", sections=["population"], sources=["gnomad"])`.
The provider confirms the supplied coordinates and alleles; no MyVariant
annotation is acquired. rsIDs, indels and other assemblies still need their
separately qualified identity/normalization dependencies.

The [source policy](source-licenses.md) covers only the fixed primary-data
projections under the [official CC0 policy](https://gnomad.broadinstitute.org/policies).
Imported predictors such as SpliceAI are excluded. Extra response annotations
fail validation. Gene constraint still requires its separately reviewed gene
identity dependency; gnomAD permission cannot enable a held identity provider.

Selected requests validate against the dated official
[gnomAD GraphQL schema source](https://github.com/broadinstitute/gnomad-browser/tree/1975cd49436290ac47f7a28fa2747266c8f6f7aa/graphql-api/src/graphql/types).
Required selected fields must be present, including those with explicit null
values. GraphQL application errors, malformed scientific fields or impossible
counts fail safely and cannot enter the healthy-result cache.

Allele count (AC) and allele number (AN) are distinct measurements. Frequency
is AC/AN only when both are known and AN is positive. AC=0 with AN>0 is
measured zero; missing counts, AN=0, missing modalities or no indexed variant
record cannot establish population absence. Unknown measurements produce
partial section status and retain successful peer evidence. Ancestry rows keep
their own denominators and source IDs; rows can overlap and are not summed.
Exome and genome counts are also not added. Joint counts are supplied by the
provider, preserving its treatment of overlapping samples. Filtering flags
remain attached to the relevant modality.

Blank population identifiers remain blank with `id_status: "missing"` and
make that modality partial. Counts and source row pointers are retained;
no ancestry or cohort label is inferred. Multiple unnamed rows are kept as
separate source rows, and are not summed.
Repeated nonempty source IDs retain every row with `id_status: "ambiguous"`
and partial modality status. Row pointers distinguish the original measurements;
the service neither merges them nor infers which cohorts they represent.

Constraint pLI is a probability, LOEUF is a nonnegative observed/expected
upper bound, and signed z-scores may be negative. Unknown metrics and missing
transcript attribution remain explicit. The preferred constraint transcript is
inferred from the dated provider annotation policy: MANE Select when available,
otherwise the canonical transcript. Returned MANE/RefSeq versions are preserved;
missing versions are not invented. The response labels this association as an
inference because the constraint record has no explicit transcript field.
Unavailable metrics do not prove lack of constraint, and neither population nor
constraint data establish clinical pathogenicity.

`gnomad_r4` is a mutable browser selector rather than an exact release pin.
Population output labels it as `dataset_selector`, reports `release: null`,
and labels exact reproduction as unavailable from that alias. The gene API
does not expose an exact constraint-release selector; its release also stays
null. Provenance preserves retrieval time and content hashes without inventing
a source version. The official [changelog](https://gnomad.broadinstitute.org/news/changelog/)
documents updates within version families.

The checked-in official SDL/resolver fixture retains its upstream MIT license.
Offline tests cover the selected fields, identity and denominator semantics,
HTTP failures, and actual MCP cache/composition behavior. They do not qualify
all gnomAD fields, live provider health, real client/model performance or
clinical interpretation.
