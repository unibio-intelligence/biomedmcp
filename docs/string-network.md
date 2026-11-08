# STRING functional networks

Use `get_record` with a species-qualified gene identifier and `sections: ["interactions"]`.
Gene identity is qualified before acquisition; the canonical gene symbol and
requested species are retained in the result. The STRING (Search Tool for the Retrieval of
Interacting Genes/Proteins) `network` request
explicitly selects a functional network with up to ten added neighbors.

Each edge retains the provider's protein identifiers, preferred names, taxon,
combined confidence score and any reported channel scores. Edges can connect
two neighbors rather than the queried gene. Protein identifiers and preferred
names are not assertions of equivalent gene identity. Functional associations
do not establish physical binding or causality, and confidence scores are not
effect sizes or experimental measurements. An omitted channel score remains
unreported; it is never replaced with zero.

Null, object or error payloads, missing edge identity, wrong species and invalid
scores fail the interaction section with `invalid_source_response`. A malformed
edge invalidates the complete collection, including edges beyond the displayed
row bound. Other successful sections are still returned. Failed responses are
not cached, so the next request contacts STRING again.

An empty network means STRING returned no edges for this request, not that no
association exists. The STRING release is not pinned. If more than 25 edges are
returned, the rest are listed as omitted; use the recovery URI to fetch them
without a new STRING request.

These semantics follow the [STRING API contract](https://string-db.org/help/api/).
The [offline regression tests](../tests/unit/sources/test_string_network.py) exercise selected
response shapes, qualified human/mouse requests, partial results, retries,
cache provenance and recovery through the actual MCP client boundary.
