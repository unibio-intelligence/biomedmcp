# NCBI ortholog and virus reports

The NCBI integration remains **held** under the source permission policy. This guide
explains selected fixture-qualified contracts, not a grant to retrieve or reuse
contributed records. An API key does not resolve their underlying permissions.

`query_source(source="ncbi", operation="find_orthologs")` selects one numeric
`gene_id`, its exact `source_tax_id`, 1–25 distinct `target_tax_ids`, a bounded
`max_results` and an optional provider `page_token`. It independently checks the
source GeneID and taxon through the current gene dataset-report endpoint. It then
requests the documented ortholog-report page. Every row is validated before exact
target-taxon selection; omitted source/other-taxon rows remain in acquired evidence,
and their filtering never removes provider continuation.

A qualified relationship assertion requires an explicitly shared gene-group ID
with reported method `NCBI Ortholog`. Missing, differing or other-method groups
remain unqualified candidates. All source matches remain independent, including
multiple target genes in one species. There is no best-hit collapse, sequence
similarity percentage, inferred functional equivalence or experimental claim. The
result remains partial: it assesses one mutable provider window, with unknown
source release and no global absence claim. Input hashes and JSON report locators
support each relationship assertion. Follow the generated action with its original
GeneID, source/target taxa and page size to acquire the next window.

`get_virus_info` requires a versioned viral nucleotide accession and optionally an
exact viral taxon. It retrieves the current virus **metadata report**, retaining
reported annotation/collection fields and count zeroes; missing count fields remain
null. It does not download nucleotide or protein sequences. Annotation counts and
collection metadata do not establish infection, expression, pathogenicity or
transmission. The nucleotide accession is versioned, while its metadata remains
mutable and is not an immutable database-release snapshot.

The former genome-comparison, phylogenetic-tree and global database-statistics
operations used routes absent from the current provider specification and are no
longer advertised. The private SDK's first-hit gene lookup is also removed. Generic
NCBI search supports its qualified assembly/taxonomy modes only. Ordinary gene
search/get retain their canonical owner and permission checks; this change does not
introduce a second common lookup route. Actual alignment/tree computation requires
its own qualified workflow and appropriate modeling owner.

The packaged `contracts.json` retains twelve selected REST paths and referenced
schemas, bound to the exact current
[official OpenAPI specification](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/rest-api/).
The [gene report schema](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/data-reports/gene/)
explains reported gene groups. All new biological fixtures are synthetic. These
checks do not establish live health, exhaustive source meaning, licensed scientific
content, sequence-based evolutionary inference or current model task performance.
