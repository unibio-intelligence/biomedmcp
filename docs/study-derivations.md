# Derived study records

Use `capabilities({"source":"study"})` to inspect `record_schemas.study_derived`. Its `record_type` discriminator covers the eight derived families below. Mutation gene profiles and expression/CNA gene measurements retain their separate schemas. These are installed, checksummed public releases; use the Ubi platform for private data or larger computation.

| Public analysis | Record type | Interpretation |
| --- | --- | --- |
| `mutation_cohort` | `study_mutation_cohort` | Distinct assayed sample IDs partitioned by any mutation in the requested gene. |
| `top_mutated` | `study_mutation_ranking` | Distinct mutated samples divided by declared assay samples; observed mutated genes only. `total_mutated_genes` and `ranking_truncated` describe the displayed window. Unlisted genes are not a complete negative inventory. |
| `filter_cohort` | `study_filtered_cohort` | Clinical selection and missing measurements have separate exclusion counts. Only samples evaluable for every requested measurement enter the denominator. A measured zero-result cohort differs from unavailable measurements. |
| `survival` | `study_survival` | Each patient is counted once. Endpoint exclusions, risk sets, event/censor counts, pointwise uncertainty and log-rank availability remain explicit. Follow-up does not establish exposure timing. |
| `compare`, mutations | `study_mutation_association` | Fisher exact uses unmodified patient counts. Observed and conditional odds ratios differ; infinite/undefined estimates retain explicit statuses and null finite-value slots. Effect-only pseudocounts do not alter Fisher counts. |
| `compare`, expression | `study_expression_comparison` | Finite eligible biopsy measurements become one median per patient. Sample and patient missingness differ. Rank-test probability and Welch uncertainty for the mean difference are distinct quantities; neither implies a causal effect. |
| `co_occurrence` | `study_co_occurrence` | All requested unordered pairs remain in the hypothesis family, including unavailable tests. Shared genes/patients create dependence. Mutation in different biopsies of a patient is not cell-level co-occurrence. |
| `gene_profile`, structural variants | `study_structural_variants` | Source table rows and distinct reported sample IDs are separate units. No assay denominator, genome build or allele normalization is inferred. An installed empty source table reports zero rows with coverage still undeclared. An absent table is unavailable. |

Every derived record carries its release identity, method, analysis unit and actual consumed file hashes. `input_locators.selection` identifies mutation genes, measurement gene rows, or patient endpoint columns according to its role; null means the whole source table. Mutation calculations also locate declared assay coverage in the hashed release metadata. Gene, sample and patient namespaces are scoped to that verified study release. Do not join them across releases or infer species/build from a caller default.

The runtime validates count partitions, finite probabilities/measurements, uncertainty availability, source selectors, units and calculation identities before evidence bounds are applied. JSON Schema describes field shapes; these arithmetic and identity checks are additional runtime guarantees. This preserves the independently qualified statistical methods; it does not independently establish scientific validity of a real study or its observational design.

Delivered sections may contain bounded arrays or omitted fields. Inspect section truncation/recovery metadata and use the supplied resource links and `next_uri` continuation to retrieve supporting ranges with the same evidence IDs. Displayed IDs or curve points are not an exhaustive population when truncation is reported. The outer receipt binds the final delivered view; recovered evidence retains its original snapshot identity. Resource availability, expiry and payload limits remain explicit.

Missing patient outcome files cannot produce a zero-event survival analysis. Present files with missing endpoint values retain excluded-patient reasons and unavailable inference. NaN and infinity are rejected as expression-filter thresholds before analysis. Valid finite extreme thresholds still produce measured cohorts with explicit denominators.
