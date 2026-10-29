# Protein complex membership

Use the existing `get` tool with a canonical UniProt accession, an explicit species and the `complexes` section:

```json
{"entity":"protein","id":"P15056","species":9606,"sections":["complexes"],"sources":["complexportal","uniprot"],"section_parameters":{"complexes":{"limit":25}}}
```

Complex Portal is an eligible CC0 source in the [source license inventory](source-licenses.md). The UniProt dependency independently checks one exact accession, taxon, sequence and length before interpreting source matches. Name and isoform requests fail before acquisition; resolve an exact canonical identity first. Nonhuman requests retain the supplied species throughout the request and returned actions.

The [search service](https://www.ebi.ac.uk/intact/complex-ws/search/) discovers free-text matches. Descriptions can mention proteins that are not complex participants. A returned `complex_membership` record requires the exact requested accession in a protein participant and matching complex/participant taxa. Unknown species and isoform-only candidates remain explicitly unqualified; they are not exact canonical membership. Other organisms and description-only hits are filtered, with separate counts.

A source annotation is not a measurement. `predicted_by_source` retains the source's flag; a false value does not prove experimental binding, a direct interaction, affinity, expression, function or therapeutic effect. `experimental_binding` explicitly reports that search summaries do not assess this. Stoichiometry remains nullable source text (`stoichiometry_raw`), without deriving numerical subunit counts. Full participant features, binding regions and publication support require separately qualified detail retrieval. The selected projection does not claim them.

Each selected record retains its CPX identity, canonical source URL, source-row SHA-256 and field locators in the acquired `/elements` array. A matching participant has its own locator. Section provenance supplies the service evidence identity, participating sources and retrieval time. Source URLs and prose are evidence data; only service-issued `next_actions` are executable requests. The [output contract](output-contracts.md) defines receipts and recovery.

Complex Portal search has no pinned release identifier in the consumed response. `source_release` stays null, and coverage reports `time_dependent: true`. The source query total counts discovery hits, not qualified memberships. An empty window means no qualified membership in that acquired window; it does not establish biological absence. Missing, malformed, failed or unresolved responses are structured failures or partial evidence, never healthy empty results.

Provider `first` is a raw offset; `number` is a window size. Windows contain at most 25 source hits. Filtering and duplicate suppression preserve continuation to later source windows. Execute the complete returned `get` action, retaining identity, species, freshness, source dependencies and limit. Cursors bind these fields, account scope and implementation revision, expire after one hour, and require stored state. Local CLI state survives process restarts; distributed workers share Redis state. Expired or invalid state requires restarting the original request. Changing the source total or independent sequence fingerprint during continuation also requires restarting.

The service acquires at most 1,000 source candidates across a continuation. Reaching this bound or losing continuation storage keeps acquired evidence and reports the unassessed remainder. Continuation windows remain partial evidence even when their accessible source window is exhausted. Deduplication and a stable total do not prove stable provider ordering or release alignment: live additions, removals and reordering can still affect a time-dependent search.
