# Public alternatives to held source projections

Core ClinVar assertions use NCBI directly. They do not request MyVariant's mixed
annotation bundle, dbNSFP, CADD, COSMIC or SNPedia fields. The
[ClinVar data-use policy](https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/)
describes copying with attribution and the public E-utilities interface.
Preserve the accession version and independent germline, clinical-impact and
oncogenicity classifications. NIH does not independently verify submitted
assertions; missing classifications are unknown.

```json
{"tool":"variant_evidence","arguments":{"id":"BRAF V600E","sections":["clinvar"]}}
```

An explicit allele is preferable when an rsID or protein change maps to multiple
alleles. Discovery is bounded to 25 ClinVar candidates; mismatched or ambiguous
identities produce an error rather than substituted evidence. Coordinates check
chromosome, assembly, position, reference and alternate using one allele's SPDI
and assembly-specific location. A coordinate lookup fails closed if the summary
only supplies allele bases qualified for another assembly; use an exact
transcript HGVS or an allele in the qualified assembly. Indels require qualified HGVS rather than
unnormalized coordinates.

```json
{"tool":"variant_evidence","arguments":{"id":"chr7:140753336:A:T","assembly":"grch38","sections":["clinvar","population","civic"]}}
```

Population and CIViC remain separate sources with their own identity and
availability checks. Protein identifiers may still need a held aggregator for
population resolution. ClinVar does not unlock other mixed annotation fields.

Article citations and references use
[Europe PMC's public REST service](https://europepmc.org/RestfulWebService)
for PMID, PMCID and exact DOI inputs. The bounded bibliography includes
identifiers, titles, authors, publication dates and journal facts. It excludes
publisher abstracts/full text, citation contexts and recommendation scores.
Europe PMC and contributor terms remain attached; this is not a blanket
permissive license for all Europe PMC content.

```json
{"tool":"relate","arguments":{"entity":"article","id":"29846123","relation":"citations","limit":10}}
```

The response reports source total, returned count and whether more indexed
edges exist. It returns the first bounded window, up to 25 items, not an
exhaustive graph. Unlinked bibliography entries remain unresolved references,
without invented article identifiers. Missing source links do not establish
that no citation exists; citations do not establish scientific agreement.

Author search and records now use [OpenAlex](https://help.openalex.org/api/), with
source-qualified `openalex:A…` identifiers. Author `articles` relations return the
first bounded work window; name matches are candidates, not verified people.
Article `recommendations` accepts PMID, PMCID, DOI or `openalex:W…` and projects
OpenAlex's `related_works` metadata in source order. These are topic-based discovery
suggestions, not summaries or scientific support.
PMCID inputs first require an exact Europe PMC identity and a confirmed DOI/PMID bridge; both source notices are retained.
Bibliographic OpenAlex metadata is CC0; abstracts, full text and content downloads are not
part of this projection. Basic calls need no key. An optional operator
`OPENALEX_API_KEY` is read only at the wire boundary and improves provider capacity;
it is never a tool parameter. No paid plan, account creation or full-text download
is initiated. Shared research limits, cache and provider pacing still apply.

```json
{"tool":"search","arguments":{"entity":"author","query":"Jennifer Doudna","filters":{"source":"openalex"},"limit":3}}
{"tool":"relate","arguments":{"entity":"author","id":"openalex:A5023888391","relation":"articles","limit":3}}
{"tool":"relate","arguments":{"entity":"article","id":"10.7717/peerj.4375","relation":"recommendations","limit":3}}
```

Drug `label` reads return SPL identifiers, version/effective date, product metadata,
manufacturer-submitted label prose (including indications, warnings and dosage),
and an official label link. The initial view selects one matching SPL record,
with explicit coverage rather than an all-manufacturer/latest-label claim.
Text is preserved before caching and can be recovered
through bounded evidence resources. HTML tables, images and attachment downloads
are outside this projection. A listing does not establish FDA approval, current
distributed labeling or individual clinical suitability. Preserve source notices.

`variant_evidence` with `sections=["predictions"]` now returns **AlphaMissense**
precomputed predictions under CC BY 4.0. Gene/protein-change inputs use an exact
reviewed human UniProt sequence matched to the official AlphaFold DB score file;
the response retains the sequence version and score-file hash. Genomic, rsID and
accession HGVS inputs use Ensembl VEP's AlphaMissense projection, preserving each
allele/transcript context and the observed Ensembl service release. An rsID can
identify several alternate alleles. No mean or maximum is substituted for these
contexts. The exact AlphaMissense dataset release is not reported by VEP; that
limit remains explicit. Scores are research predictions, not clinical diagnoses
or patient-risk estimates. Non-missense or unavailable predictions stay explicit.
Restricted mixed aggregator bundles and other algorithms remain outside this route.

```json
{"tool":"variant_evidence","arguments":{"id":"BRAF V600E","sections":["predictions"]}}
{"tool":"variant_evidence","arguments":{"id":"chr7:140753336:A:T","assembly":"grch38","sections":["predictions"]}}
```

Semantic Scholar acquisition, TLDR sections, source discovery and credentials have
been removed. Use the released literature sources and OpenAlex author/work routes.
See `capabilities` for coverage and [connection instructions](connect.md).

## Additional predictor scores

Request `variant_evidence` with `sections: ["eve"]` and a gene/protein substitution such as `BRAF V600E` for original EVE ASM scores. The [EVE publisher licenses all site data under MIT](https://evemodel.org/download/bulk); returned evidence includes its full copyright/permission notice, uncertainty, source 75%-retained classification, canonical protein identity and artifact hash. Coverage depends on EVE's supplied proteins and positions; genomic mapping is not inferred. AlphaMissense remains available through `sections: ["predictions"]`. Scores from these distinct models are not combined.

Credential-free public predictor results can be reused across anonymous requests to the same server resource for one day. Personal-key results, signed-in/private data, saved-evidence grants and other operations keep their own scopes. Explicit `fresh` acquisition bypasses the result cache; upstream latency can vary.
