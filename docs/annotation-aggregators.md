# Annotation aggregators

MyChem and MyDisease combine upstream annotations with different permissions.
Check their release status in [source licenses](source-licenses.md); a personal API
key does not override a source license. This guide does not grant permission to
redistribute their data.

Acquisition validates query envelopes, annotation identities, bulk matches and
explicit `notfound` records before caching. Provider HTTP bodies and exception
strings are excluded from errors. Invalid cached envelopes are evicted and fail
without becoming empty scientific results.

Bulk identifier mapping uses the documented form-encoded `q`/`scopes` request.
Every requested identifier requires a source outcome; unknown response queries and
contradictory missingness fail. All matching records remain candidates. Duplicate
inputs are reported separately from unique inputs. Missing target annotations are
null. Use ordinary search for names. Literal mapping inputs cannot contain the
provider's batch separators. Source candidates still require independent verification
of identity, namespace and species before they are joined with scientific evidence.

The MyChem adapter no longer advertises chemical conversion, structural similarity,
substructure matching or a similarity matrix, because the former methods did
not perform those computations. Existing drug structure retrieval preserves source
representations. Cheminformatics computation requires a separately
qualified workflow with licensed data and an explicit algorithm.

`get_admet_properties` returns reported source annotations, with unavailable
modalities marked explicitly. Physicochemical properties are not predictions of absorption, distribution,
metabolism, excretion and toxicity (ADMET).
`get_gene_disease_evidence` replaces the former score operation and retains source
assertions without an added confidence value, causality claim or aggregate score.
Symbol matches do not establish a gene's species or namespace.

Phenotype similarity is Jaccard or Dice **annotation-set overlap** for exact Human Phenotype Ontology (HPO)
identifiers, within a single 100-record source window. It exposes the numerator,
denominator, source total, omitted windows and unavailable annotations. It is not a
clinical similarity or diagnosis, and its result remains partial. Phenotype
frequency preserves all exact HPO matches and the source's raw frequency values or
HPO frequency terms; it does not silently convert them to percentages or negative
measurements.

Minimum acquisition checks follow the primary
[MyChem query contract](https://docs.mychem.info/en/latest/doc/chem_query_service.html),
[MyChem annotation contract](https://docs.mychem.info/en/latest/doc/chem_annotation_service.html),
[MyDisease query contract](https://docs.mydisease.info/en/latest/doc/disease_query_service.html)
and [MyDisease annotation contract](https://docs.mydisease.info/en/latest/doc/disease_annotation_service.html).
Fixtures are synthetic and establish selected contracts, not live provider health,
exhaustive upstream semantics, scientific completeness or model task success.
