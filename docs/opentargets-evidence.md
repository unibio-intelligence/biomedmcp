# Open Targets acquisition and target evidence

Use `get` for a qualified human gene with `target_evidence`, `diseases` or
`druggability` or `genetics` sections. One qualified gene identity supplies the exact Ensembl
selector; the returned target identifier and approved symbol must agree with
that identity before composition or caching.

The client validates selected fields against a dated snapshot of the provider's
[GraphQL API](https://platform-docs.opentargets.org/data-access/graphql-api).
Missing fields differ from explicitly nullable measurements. Objects, arrays,
enums, booleans, finite numeric values and integer counts retain their declared
types. Association/component scores must be within the source's 0–1 range;
collection counts cannot be smaller than returned rows. Unexpected unqueried
fields and partial GraphQL errors fail acquisition rather than becoming empty
evidence. Aliases, fragments, conditional fields and merged selections retain
their GraphQL meaning. Single-entity requests verify the source identifier even
when the original query did not select it.

An explicit empty association collection is a valid indexed result for this
request, with an absence caveat. A null entity or malformed response is an error
with no scientific evidence ID. Other successful gene sections survive it.
Failed results retry on the next request; successful cache results retain their
evidence identity. More returned records than the display bound produce exact
omission locators and scoped recovery resources. Recovery returns already
acquired evidence with the same IDs and no additional provider request.

An optional acquisition failure preserves an independently acquired primary
target, drug or disease record and successful peer sections. Inspect
`section_outcomes`: failed sections have `outcome="error"`, a safe structured
error and a null value. They never become empty association, indication or
clinical-candidate collections. Nullable source fields and explicitly empty
collections keep their distinct source meanings. Primary acquisition failures
stop composition before optional queries and cannot establish an identity.
Expected provider failures are sanitized before adapter logging; cancellation
still propagates.

Disease associations retain their records, provider total and first-page
coverage. A limited first page is not exhaustive. Tractability flags and safety
liabilities remain source annotations; they do not establish physical binding,
causality, clinical efficacy or the absence of risk. Nullable expression values
stay unreported rather than becoming zero. The dated schema snapshot is an API
structure contract, not a data release pin; live results remain time-dependent.

The current provider schema omits ProbeMiner scores and TEP records. Chemical
probe responses retain the separately reported `probesDrugsScore` without
renaming it as ProbeMiner evidence. TEP requests report source unavailability
before outbound access.

For a source assessment, inspect `capabilities` and use `query_source` with
`source="opentargets"`, `operation="analyze_advanced"` and
`params={"analysis_type":"validate","entity_ids":["ENSG00000169174"]}`.
The assessment retains clinical candidate records and reports annotation counts
with methods and input pointers. It computes no aggregate validation score,
safety score or efficacy recommendation. Its generation timestamp is distinct
from the source's release date.

Failed clinical-candidate acquisition leaves counts and coverage null with an
unavailable status. Successful annotation counts identify their inputs and the
exact Boolean-positive predicate. An association analysis preserves an acquired
aggregate association if evidence acquisition fails, and preserves acquired
evidence if the aggregate query fails. Failed evidence acquisition leaves its
counts and biomarker coverage unavailable. If both acquisitions fail, the
request issues no scientific evidence ID. These nested partial assessments
retry on a later request rather than entering the healthy cache.

Pair-specific `analyze_association` requests query the exact target–disease pair.
Use a disease identifier returned by current source evidence; a null source
entity fails rather than triggering a guessed replacement. An unindexed
association has an unreported score, not a synthesized zero. Overall and
datatype-specific association scores retain their separate meanings. Biomarker
output contains reported `biomarkerList` annotations linked to displayed
evidence records, with an explicit coverage limit.

Evidence pages retain provider totals, acquired and filtered counts. Follow the
returned `continuation` action unchanged, including `evidence_cursor`. Filtering
an entire page does not remove its provider continuation. A final continuation
page is not claimed to be the complete result of earlier pages.

Target comparisons accept 2–10 distinct human Ensembl identifiers and closed
comparison aspects. Requested disease associations are actually acquired,
limited to each target's first ten records. A failed peer retains successful
targets and marks the result partial; partial results are not cached as healthy
evidence. If all targets fail, no scientific evidence identifier is minted.

Gene `genetics` retains acquired study-locus records, nullable study/variant
metadata, separately reported GWAS/QTL types, fine-mapping method and source
p-value mantissa/exponent. The provider's
[target-to-credible-set relation](https://github.com/opentargets/platform-api/blob/master/app/models/gql/Objects.scala)
is a source linkage; it does not establish a causal gene assignment or imply
that `study.target` matches the requested gene. Sample/case/control counts
retain their study-level denominator; unreported counts remain null.

Use `section_parameters={"genetics":{"limit":10,"page":0}}` to bound a gene
window. Follow its canonical `get` continuation unchanged. It preserves the
original selector, species and source policy while advancing the locus page.
Coverage describes the current window. It does not summarize earlier pages.

For disease study discovery, use `query_source` with
`operation="query_genetics"`, `query_type="study"` and one indexed `disease_id`.
`include_credible_sets=true` acquires the first ten loci for each returned study.
`continuation` advances the study list; `credible_set_continuations` separately
advances each incomplete locus window using an exact `study_id`. A failed locus
request retains independently acquired study metadata, reports a null section
with a safe error and retries on the next request. Variant functional annotations
are acquired only when `include_functional_consequences=true`.

`analyze_advanced` with `analysis_type="similar"` accepts exactly one human
Ensembl target and `pathways`, `go_terms`, `diseases` or `interactions` as the
criterion. Candidate discovery uses at most 100 labels from the source's
[PubMed word-embedding model](https://github.com/opentargets/platform-api/blob/master/app/models/gql/Objects.scala).
The reported annotation Jaccard is computed from acquired unique identifiers:
intersection divided by union. Model scores remain separate discovery inputs.
`threshold` filters the Jaccard score; `limit` bounds displayed matches. Full
acquired comparisons and input pointers remain available for evidence recovery.
An empty union or unavailable candidate annotations has an unreported score,
not zero. Interaction overlap uses explicitly human, resolved Ensembl partners.
Disease and interaction annotations are limited to each target's first 100 rows.
This bounded candidate window cannot establish a global similarity ranking,
biological absence, binding or clinical similarity.

`analysis_type="prioritize"` requires one indexed disease and 0–10 distinct
human Ensembl targets. An empty target array discovers within the first 100
direct associations. Ranking uses only the separately reported
`genetic_association` component. Overall and somatic-mutation scores cannot
replace an unreported genetic score. Requested IDs, unindexed IDs, raw acquired
records, missing scores and candidate-window coverage remain visible.
`analyze_association` discovery consumes `min_score` for that genetic component.
It supports the `genetic_evidence` strategy; unqualified clinical, safety and
novelty rankings are rejected before acquisition. Source
[association scores](https://platform-docs.opentargets.org/associations) are
evidence heuristics, not causal confidence or therapeutic recommendations.

For variant source evidence, use `query_source` with `operation="query_genetics"`,
`query_type="variant"`, an exact source `variant_id`, `include_evidences=true`
and a bounded `limit`. Follow the returned `next_actions` entry unchanged.
Its `evidence_cursor` is a service-signed, account-scoped continuation. Provider
tokens stay in expiring runtime state and cannot be submitted directly. The
action binds every original selector and flag, page size and implementation
revision. State loss, expiry, tampering or a changed account/request fail before
provider access. Local CLI processes and distributed replicas need their
configured shared cursor state and signing key.

An empty nonterminal evidence window keeps its continuation. Source cycles,
1,000 acquired rows or 64 windows stop with explicit partial coverage and retain
acquired records. A failed optional evidence request preserves the independently
acquired primary variant and retries on a later request. Beta confidence bounds,
odds-ratio bounds, scores and p-value components remain separate reported source
measurements; unreported values remain null. No standard error or confidence
level is inferred from an interval. Zero-valued source measurements remain
reported zeros. Probability validation uses the value represented by the source
mantissa and exponent without imposing an undocumented normalization.

Variant evidence uses the source's exact variant relation. The selected evidence
projection does not independently qualify a genome build or allele for each
record. Coverage applies to the current window; a terminal page cannot summarize
earlier pages. Source data remain unpinned, and empty windows cannot establish
biological absence.

The [selected offline regressions](../tests/test_opentargets_responses.py)
and [assessment regressions](../tests/test_opentargets_assessments.py), alongside
[partial acquisition regressions](../tests/test_opentargets_partial.py), exercise
acquisition types, scientific counts/scores, qualified identity, selected
assessment/comparison semantics, cache/retry, actual MCP continuation and
recovery. These checks do not qualify all advanced composition or derived
analyses, current live health, model scientific correctness or clinical target
validation.

Variant credible-set windows also expose an executable `query_source` next action.
They page independently from evidence: their actions clear the evidence cursor and
disable evidence acquisition, preserving the original variant and locus page size.
The requested variant may be a locus member rather than its lead variant; each
returned lead variant retains its own reported coordinates and alleles. Nullable
study denominators, effects and fine-mapping measurements stay nullable. These
source records do not establish a causal variant or independently qualify the
requested variant's genome build. Display omissions can be recovered through
evidence resources without contacting the provider again. Local CLI continuation
uses the same private state directory across invocations.

For target-disease pair evidence, call `query_source` with
`operation="analyze_association"`, an exact human target `source_id` and disease
`target_id`. Follow the top-level `next_actions` entry unchanged. Its signed
`evidence_cursor` binds both identities, every original filter, biomarker flag,
page size, account and implementation revision. Raw provider tokens stay in
expiring private runtime state and are never returned in nested scientific data
or evidence resources. Target validation (`analyze_advanced`, `analysis_type="validate"`)
returns a separately executable canonical pair action using the actual pair
parameters; it does not require rerunning the full target report.

Empty or entirely filtered windows preserve continuation. Missing first-window
continuation, source token cycles, 1,000 acquired rows or 64 windows report partial
coverage and retain independently acquired association/evidence records. Failed
peer requests retry uncached. Missing cursor storage retains current evidence,
and expiry/state loss or changed request/account fails before provider access.
Source totals and returned counts remain window-specific; source scores are
reported evidence heuristics, not causal or clinical validation. Display omissions
are recoverable without new provider calls. Local CLI processes share their
configured private state directory; hosted replicas share their configured state
and signing key. This qualifies selected offline contracts only, not current
provider health, model task success or complete scientific workflow coverage.
