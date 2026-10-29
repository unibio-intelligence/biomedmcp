# CIViC evidence scope and continuation

Select `civic` on human gene/drug/disease `get` requests or `variant_evidence`.
The section accepts `limit` (1–25, default 10), an optional `collection`
(`evidenceItems` or `assertions`), and a signed `cursor` returned in an action.
A cursor requires the original collection and page limit. Execute the returned
action rather than constructing a provider cursor or changing the focus.

The request and selected response fields are checked against the dated official
[CIViC GraphQL schema](https://github.com/griffithlab/civic-v2/blob/0488d61aeb0a5c45d2a1a7edc114ac085942939f/client/src/app/generated/server.schema.json).
This snapshot qualifies those fields, not current production health. Required
connections, nested scientific fields, selected enums and paging metadata must
be present with valid types. Application errors or partial responses fail
safely and cannot become cached empty evidence. Explicit valid empty
connections are distinct from failed acquisition. Nullable citation, publication
year, disease and assertion level remain nullable.

CIViC's name filters select substring candidates. Coverage therefore reports
candidate totals separately from exact local matches. Variant retrieval accepts
one gene/protein molecular profile and excludes compound profiles or other
protein changes. It does not infer genomic allele/build/transcript equivalence
or clinical classification. Gene retrieval checks feature/known fusion-partner
identity and, when qualified, its Entrez identifier. Drug/disease retrieval
obtains an attributed name from the confirmed MyChem/MyDisease record; stable
identifiers never become name filters. Missing names fail identity qualification.
Exact canonical-name matching does not establish exhaustive synonym coverage.

Provider continuation survives a page with zero locally matched records. Each
collection has a separate executable follow-up action. Provider tokens remain
internal; signed cursors bind focus, species/build, collection, page size,
scientific revision and account scope. State expires after one hour and is
shared through Redis in distributed runtimes. Local cursors require the same
runtime cache and signing key. The 1000-candidate scan bound or unavailable
continuation storage leaves evidence explicitly partial. Source restrictions
also apply to naming/identity dependencies.

The offline tests exercise these selected contracts and actual MCP actions.
They do not establish exhaustive provider coverage, live client compatibility
or scientific/clinical correctness beyond the specified identity checks.
