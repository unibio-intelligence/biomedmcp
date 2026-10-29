# ClinGen identities, assertions and references

Use `get` for a species-qualified gene with `sections: ["clingen"]`, or
`query_source` with `source: "clingen"` and one of `normalize`, `assertions`,
`specifications` or `linked_data`. These operations provide different kinds of
evidence; the `record_type` and request identity identify their meaning.

Gene autocomplete records are matched by the qualified HGNC identifier, keeping
reported aliases. They establish indexed identity, not gene-disease validity.
Allele Registry normalization preserves canonical CA nucleotide and PA protein
identifiers, including leading zeros, and their reported HGVS representations.
A protein allele does not establish a unique genomic allele. No independent
cross-build conversion or clinical classification is performed here.

Expert Repository assertions retain their allele identity, panel, document
version, classification and reported retraction independently. Conflicting
assertions are not collapsed into a new classification. The current request
selects the first page of up to 25 assertions; coverage explicitly says this is
not exhaustive. Low-detail CSpec records are specification references rather
than extracted criteria or applied classifications. LDH records preserve their
link type, entity type, source identifiers and any reported source version. A
link does not establish identity equivalence or a measured frequency.

Null/object/error payloads, missing collection/status fields, inconsistent
identity and malformed nested records fail before caching or evidence issuance.
An explicit empty successful collection is valid for the request, with an
absence caveat. An unsuccessful provider status is an error even when data are
present. Failure cannot establish biological absence. Subsequent requests retry
failed acquisition; successful cached results retain their evidence identity.
Source rendering timestamps and document versions are retained where reported,
but the live provider release is unpinned.

Returned evidence beyond the display bound carries precise omission metadata
and bounded recovery resources. Use the supplied URI to retrieve omitted
returned records with the same evidence IDs and no additional provider request.
Recovery cannot retrieve records the provider did not return.

Primary contracts: [Allele Registry](https://reg.clinicalgenome.org/docs/cg-car/),
[Expert Repository](https://erepo.clinicalgenome.org/docs/cg-erepo/) and
[Linked Data Hub](https://ldh.clinicalgenome.org/ldh/ui/api-docs).
The [offline regressions](../tests/test_clingen_responses.py) cover selected
response shapes, aliases and namespaces, conflicting assertions, retries,
cache provenance and actual MCP resource recovery. These checks do not prove
current live health, complete provider coverage or model scientific correctness.
