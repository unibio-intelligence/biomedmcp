# UniProt response qualification

Protein search and accession retrieval validate JSON before evidence extraction.
A search must contain an explicit `results` list; an empty list is a valid
zero-match response. Direct retrieval requires a canonical primary accession,
matching the requested primary or a documented secondary accession. An inactive
entry is a retrieval failure, and an isoform request never becomes a keyword
search for its parent protein.

Compact projections may omit optional annotations. Present sequence, organism,
protein name, gene, feature and cross-reference fields are checked for their
minimum documented shapes. Full sequence requests require a nonempty amino-acid
sequence; reported length must agree with it. Unknown feature coordinates remain
unknown. These checks do not infer absent annotations, homology, phylogeny,
functional equivalence or experimental validation.

`include_features` requests the 36 explicit feature columns in the dated UniProt
field configuration. The former `ft_*` selector is rejected by the provider.
Each JSON projection retains accession identity. Full cross-reference metadata
uses a bounded full JSON entry instead of the unsupported `xref_*` selector.

Use `capabilities(source="uniprot")` to discover the current advanced operations.
`analyze_evolution` now offers `similarity_annotations`, `orthology_references`
and `phylogeny_references`. Each selects its own UniProt projection: SIMILARITY
texts, OrthoDB identifiers or PhylomeDB identifiers. Missing annotations retain
the protein record with partial status and `not_reported`; they do not establish
absence of evolutionary relationships. These are annotations and external
reference identifiers, with input locators, rather than computed relationships
or a phylogenetic tree. External database contents are not fetched. Organism
filters belong to protein search; the removed `target_organism` argument never
filtered an exact accession GET.

`compare_proteins` accepts two to five distinct canonical accessions. Sequence
comparison reports exact string equality, sequence SHA-256, lengths in residues,
and count difference (left minus right). Function comparison reports exact shared
FUNCTION statement text; structure comparison reports shared PDB reference IDs.
The result states its method and retains per-record species, primary identity,
requested aliases, source release and JSON input locators. These methods do not
compute an alignment, infer functional equivalence or establish structural
geometry. Ambiguous sequence symbols remain explicit. Different annotations do
not establish biological divergence.

Every requested pair has a status. Missing annotations, failed retrievals and
different accessions resolving to one primary identity make the affected pair
unavailable, with the successful source records retained. Partial comparisons
cannot become healthy-result cache entries. The next call can retry retrieval.
Invalid source shapes and transport failures carry safe error codes without raw
response or exception text. FUNCTION/SIMILARITY text and evidence shapes are
validated before extraction; valid ECO-only evidence remains supported.

Exact-entry responses retain the observed `x-uniprot-release` header. The source
body cannot supply or overwrite that release. Mixed observed releases remain
per-record with a warning; no aggregate release is invented when a header is
missing or inputs disagree. An observed release is not a reproducible replay pin.
Source53 invalidates older cached science and continuations.

The source53 additions in `tests/test_uniprot_annotations.py` and the earlier
`tests/test_uniprot_responses.py` pass native and Docker contract qualification.
The synthetic fixture contains an explicit SIMILARITY annotation where a healthy
annotation result is asserted. Its dated field fixture records the source URL, hash and
immutable official model references. Taxonomy, non-JSON exports and all nested
comment types remain outside these selected contracts. Actual client/model task
success and broad current provider health require separate evaluation.

[Source permissions](source-licenses.md) permit UniProt record content under
CC BY 4.0. Referencing an external identifier does not grant access to or a
license for the external database's full contents.

Primary contracts: [UniProt query and projection documentation](https://www.uniprot.org/help/api_queries),
[return fields](https://www.uniprot.org/help/return_fields),
[field configuration](https://rest.uniprot.org/configure/uniprotkb/result-fields),
and [official JSON domain-model parser](https://github.com/ebi-uniprot/uniprot-core/tree/f2e1f8f6c537d80d5501bb0af04fb47a91bf8296/json-parser/src/test/java/org/uniprot/core/json/parser/uniprot).
