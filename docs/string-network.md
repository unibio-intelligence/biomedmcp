# STRING functional networks

Use `get` with a species-qualified gene identifier and `sections: ["interactions"]`.
Gene identity is qualified before acquisition; the canonical gene symbol and
requested species are retained in the result. The STRING `network` request
explicitly selects a functional network with up to ten added neighbors.

Each edge retains the provider's protein identifiers, preferred names, taxon,
combined confidence score and any reported channel scores. Edges can connect
two neighbors rather than the queried gene. Protein identifiers and preferred
names are not assertions of equivalent gene identity. Functional associations
do not establish physical binding or causality, and confidence scores are not
effect sizes or experimental measurements. An omitted channel score remains
unreported; it is never replaced with zero.

Null/object/error payloads, missing edge identity, wrong species and invalid
scores fail the interaction section with `invalid_source_response`. A malformed
edge invalidates the complete collection, including edges beyond the displayed
row bound. A failed section has no scientific evidence ID and does not prevent
other successful sections from being returned. Failed responses are retried on
a subsequent request rather than cached as successful empty results.

An explicit empty collection is a valid empty network for this request, not
evidence that a biological association is absent. The live provider release is
unpinned. More than 25 returned edges trigger precise omission metadata and
bounded evidence resources; use the supplied recovery URI to retrieve the
omitted edges with the same evidence identifiers and no new provider request.

These semantics follow the [STRING API contract](https://string-db.org/help/api/).
The [offline regressions](../tests/test_string_network.py) exercise selected
response shapes, qualified human/mouse requests, partial results, retries,
cache provenance and recovery through the actual MCP client boundary. They do
not establish current live provider health or real model task correctness.
