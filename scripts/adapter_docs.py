"""README text for the retained adapter packages under servers/python."""

import json

from biomedmcp.examples import by_id
from biomedmcp.native.catalog import ADVANCED

ADAPTER_READMES = {
    "clinical-trials-mcp": (
        "clinical-trials",
        (
            "trial-recruiting",
            "trial-phase",
            "trial-ezetimibe",
            "trial-record",
            "trial-contacts",
            "trial-location",
            "trial-completed",
            "trial-pediatric",
            "trial-statistics",
            "trial-comparison",
        ),
    ),
    "gtex": (
        "gtex",
        (
            "gene-expression",
            "gene-tissue",
            "gene-eqtl",
            "gene-sqtl",
            "gene-transcripts",
            "gene-exons",
            "gtex-tissues",
            "gtex-dataset",
            "gtex-service",
            "gtex-sample",
        ),
    ),
    "chembl-mcp": (
        "chembl",
        (
            "chembl-compounds",
            "chembl-compound",
            "chembl-targets",
            "chembl-bioactivities",
            "chembl-properties",
            "chembl-batch",
        ),
    ),
    "ncbi-mcp": (
        "ncbi",
        (
            "ncbi-genomes",
            "ncbi-assembly",
            "ncbi-annotation",
            "ncbi-taxonomy-search",
            "ncbi-lineage",
            "ncbi-organism",
            "ncbi-quality",
            "ncbi-sequence-report",
            "ncbi-stats",
            "ncbi-project",
            "ncbi-sample",
        ),
    ),
    "mygene": ("mygene", ("gene-search", "gene-record", "resolve-ldl-receptor", "resolve-mouse", "gene-map")),
    "mychem": ("mychem", ("drug-search", "drug-record")),
    "mydisease": ("mydisease", ("disease-search", "disease-record")),
    "uniprot-mcp": ("uniprot", ("protein-search", "protein-record")),
    "reactome-mcp": ("reactome", ("pathway-search", "pathway-record", "gene-pathways")),
    "opentargets": ("opentargets", ("gene-target-evidence", "target-dossier")),
    "protein-atlas-mcp": ("protein-atlas", ("gene-hpa",)),
    "openfda-mcp": ("openfda", ("drug-label", "drug-safety", "adverse-event-search")),
    "surechembl-mcp": ("surechembl", ("patent-search",)),
    "ensembl-mcp": ("ensembl", ("ensembl-assembly",)),
    "pdb-mcp": ("pdb", ("pdb-record",)),
    "bio-ontology-mcp": ("bio-ontology", ("bio-ontology-class",)),
    "antibody-registry": ("antibody-registry", ("antibody-record",)),
}

ADAPTER_DOCUMENTATION = {
    "clinical-trials-mcp": (
        "ClinicalTrials.gov",
        "Use search_trials for trial discovery, get_record(entity=trial) for known NCT records and explicit submitted protocol sections, and query_source for the two distinct comparison/statistics operations. The public surface keeps its compact tool interface; the eight retained implementation helpers are not separately mounted public aliases.",
        "Queries use the documented Essie syntax for location, sponsor, dates, posted results or age eligibility when an ordinary trial filter is insufficient. Follow the signed search_trials cursor; query_source statistics uses its generated next_actions to retrieve another provider window with unchanged filters. Counts in separate windows are not cumulative. Identifier-only queries cannot be combined with filters because the provider ignores those filters; use get for known NCT records. To discover trials sharing a reference trial's conditions, retrieve that record first and search its actual submitted condition terms; co-condition discovery is not a validated similarity score.",
        "The adapter validates dated OpenAPI request/response schemas, exact or explicitly aliased NCT identity, nested protocol/results fields, counts and continuation before extracting evidence. Missing optional protocol modules are unavailable, not measured negative evidence. Statistics count unique study memberships per label in one bounded provider-returned window, with acquired/grouped/missing denominators and explicit completeness. A trial can have several phase or condition labels; their sum may exceed the study denominator. The window is not a representative population sample. Comparisons preserve successful peers and safe failures, retain ACTUAL versus ESTIMATED enrollment, and mark missing fields unavailable. Missing enrollment counts are unavailable; counts without an actual/estimated classification remain partial. Registry protocol endpoints and posted results do not establish comparable treatment effects, individual eligibility, current site recruitment or clinical suitability. Large nested records can be truncated; follow advertised recovery ranges for acquired data. Real agent/client and full provider qualification remain open. No claim of complete inherited functionality is made.",
        "[ClinicalTrials.gov REST API and dated OpenAPI](https://clinicaltrials.gov/api/oas/v2), [study data structure](https://clinicaltrials.gov/data-api/about-api/study-data-structure), [complex search syntax](https://clinicaltrials.gov/find-studies/constructing-complex-search-queries). Packaged contracts.json records the official source hash/date and selected endpoint schemas.",
    ),
    "gtex": (
        "GTEx",
        "Human gene expression, eQTL/sQTL evidence and transcript/exon annotations use the canonical get tool with explicit gene sections. Metadata and public sample records use query_source. Gene identity is qualified against the selected dataset's GENCODE release; stable identifiers are not treated as symbols.",
        "Supported release pins are gtex_v8 and gtex_v10. Use source_versions for gene sections and dataset_id for advanced metadata/sample calls. Tissue IDs come from get_metadata(info_type=tissues). Follow next_actions to resume a zero-based provider page with the same qualified gene, tissue, release and filter. Requested limits are capped at 25 records per acquired page to fit the public row budget; later records remain reachable. At most three wholly filtered windows are scanned per call. Provider totals describe raw source records, not the count passing a local p-value filter.",
        "Static QTL filters use measured pValue; METASOFT uses metaP. The service does not send an unsupported pValueThreshold query parameter. A dynamic calculation is retained even when nonsignificant, with an explicit threshold assessment. Dynamic sQTL requires phenotype_id from a validated gene/tissue/variant intron association; an unqualified intron cannot become negative evidence. Donor arrays and standard errors belong to a single QTL measurement record. Offline tests cover dated request and response schemas, exact identity, bounded pagination, filters and actual MCP examples. Transcript and exon sections acquire records for a parent gene, qualified under the selected GENCODE version and genome build; transcript/exon IDs alone are not parent-gene selectors. Exon records preserve their parent transcript and exon ordinal rather than deduplicating shared exons across transcripts. QTL variants are qualified against the selected cohort before joins: rsIDs use snpId and require one complete, unambiguous reference mapping; explicit coordinate variants require the GRCh38 _b38 suffix and matching position/alleles. An unavailable or ambiguous cohort variant stops the join rather than becoming negative QTL evidence. Recovery actions preserve the qualified coordinate identity. Internal gene/variant annotation and top-gene operations are not separate public routes. This adapter does not offer transcript, exon or junction expression tools. Large nested donor arrays can be truncated by the public evidence budget; follow advertised recovery ranges, subject to snapshot storage and response limits. Dataset/source access and scientific suitability require live qualification.",
        "[GTEx Portal API contract](https://gtexportal.org/api/v2/openapi.json). Packaged contracts.json identifies the dated official document hash and the response schemas used for validation.",
    ),
    "chembl-mcp": (
        "ChEMBL",
        "ChEMBL acquisition retains compound structures, target identity and assay measurements. Ordinary drug identity uses search_records/get_record with MyChem; these ChEMBL operations have distinct scientific semantics.",
        "A batch uses the public batch tool and repeats canonical query_source calls; it does not expose the retained batch_compound_lookup alias.",
        "Bioactivities retain assay identity, relation, units and target; values from different assays are not automatically comparable. Rule-of-five checks describe physicochemical heuristics and do not establish efficacy, safety, ADMET or clinical suitability.",
        "[ChEMBL REST API](https://www.ebi.ac.uk/chembl/api/data/docs), [aspirin record](https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL25.json).",
    ),
    "ncbi-mcp": (
        "NCBI Datasets",
        "Assembly discovery and exact assembly/annotation retrieval use NCBI Datasets v2 documented report routes. Assembly identity includes its accession version and organism TaxID; annotation-release metadata is retained when supplied. Full metadata does not download genome sequences.",
        "For genome discovery, query selects one taxon; with tax_id or organism, query becomes search text within that taxon. Assembly discovery without a taxon selects an assembly name or exact accession. Use complete_genome for the complete-assembly level. Annotation regions use provider-native coordinates with no inferred offset conversion. Follow next_actions with their unchanged filters and page_token, including an empty final provider window.",
        "The offline qualification covers assembly/taxonomy discovery, exact assembly and annotation retrieval, taxonomy lineage/names/available genomes, assembly statistics/quality/sequence reports and BioProject/BioSample assembly associations. Project/sample lookup acquires genome assembly associations; it does not promise a universal repository search. CheckM values retain percentage units, marker set and version; annotation BUSCO retains raw provider scores, lineage and version without a percent conversion. Missing requested measurements are unavailable and make the public result partial; a measured zero remains data. The CheckM contamination estimate does not establish comprehensive contamination screening. Taxonomy classification names cover selected ranks, while ancestor TaxIDs retain the separate lineage. Secondary report failures preserve successful taxonomy evidence and are not cached as healthy results. Follow generated actions to resume separate genome/name report windows. Selected source56 contracts add exact-GeneID/taxon ortholog-group assertions and versioned viral nucleotide metadata. Orthology is a provider inference with no computed similarity percentage or functional equivalence; raw continuation survives exact-taxon filtering. Unsupported comparison, phylogenetic tree and global-statistics declarations, a first-hit gene lookup and unqualified search modes are retired; taxonomy lineage or assembly statistics do not establish synteny, orthology or phylogenetic inference. Sequence records use the canonical ncbi-records/Ensembl routes; standalone retained BLAST is not a public route. No assertion of complete inherited functionality or live client performance is supported. Large records can be explicitly truncated by the public result budget; use any advertised recovery ranges for acquired data, subject to their scope, expiry and storage limits.",
        "[NCBI Datasets REST API and dated OpenAPI](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/rest-api/), [NCBI annotation BUSCO policy](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/data-processing/policies-annotation/quality/busco/). The packaged contracts.json retains twelve selected qualified paths and their referenced schemas, with the source snapshot SHA-256 and retrieval date.",
    ),
}

ADAPTER_DOCUMENTATION.update(
    {
        "mygene": (
            "MyGene.info",
            "Use search and resolve for gene discovery and get for known genes. Keep one explicit taxonomy ID through follow-up enrichment. map_gene_ids is the distinct batch mapping operation for up to 25 inputs in one declared namespace and species.",
            "Resolve ambiguity before joining evidence. Mapping accepts symbol, entrezgene or ensembl.gene and retains each input's qualified candidates; it does not choose a species from the spelling of a symbol.",
            "Mapping failures, wrong-species rows and absent provider responses are not evidence of absence. Provider annotation coverage and ontology assertions require source-specific interpretation. The former standalone 1,000-gene batch and export helpers are not public routes.",
            "[MyGene.info query and batch API](https://docs.mygene.info/en/latest/doc/query_service.html).",
        ),
        "mychem": (
            "MyChem.info",
            "Discover drug identities with search_records(entity=drug), then retrieve a provider-stable record using get_record(entity=drug). Inspect identifier mapping and reported ADMET annotation schemas through get_capabilities; chemical computations are not advertised.",
            "Names can be ambiguous. Preserve the returned identifier and separate chemical structures, source assertions and clinical indications when joining records.",
            "Reported source annotations do not establish comparable efficacy, safety or clinical suitability. Missing ADMET modalities are unavailable. This mixed annotation source is eligible under the source policy with SIDER and UMLS content excluded. Source-specific rights and attribution still apply; examples establish fixture routing, not live qualification.",
            "[MyChem.info](https://mychem.info/).",
        ),
        "mydisease": (
            "MyDisease.info",
            "Use search_records(entity=disease) for discovery and get_record(entity=disease) with the returned qualified disease identifier. Gene and phenotype enrichment use explicit sections on the public disease record.",
            "Keep identifier namespaces and candidate distinctions; a shared label is not proof that two disease concepts are equivalent.",
            "Aggregated disease annotations do not establish prevalence, prognosis or a diagnostic decision. Distinct phenotype/identifier comparison methods require separate scientific qualification. Missing annotations remain unknown.",
            "[MyDisease.info](https://mydisease.info/).",
        ),
        "uniprot-mcp": (
            "UniProt",
            "Use search_records(entity=protein) with an explicit taxonomy ID and get_record(entity=protein) with an exact UniProt accession. Sequences, features and cross-references belong to the returned record and projection.",
            "Follow the public search cursor with unchanged filters. A known accession identifies a specific protein record; isoform sequence/feature coordinates must stay qualified to that isoform. Taxonomy acquisition belongs to the NCBI source route.",
            "Selected response, accession, field projection and pagination contracts are fixture-qualified. Protein annotations and cross-references do not prove a variant mechanism or an experimental interaction. Distinct comparison/evolution operations require their own interpretation and broader qualification.",
            "[UniProt REST API](https://www.uniprot.org/help/api_queries).",
        ),
        "reactome-mcp": (
            "Reactome",
            "Use search_records(entity=pathway) for human pathway discovery, get_record(entity=pathway) for a stable Reactome pathway ID, and get_record(entity=gene, sections=[pathways]) for a qualified gene's source pathway memberships.",
            "Reactome stable IDs carry an organism prefix. The ordinary retained search currently uses Homo sapiens; it does not offer an arbitrary species filter. A pathway diagram has its distinct query_source operation.",
            "Membership is a source annotation, not proof of pathway activity in a tissue or perturbation. Selected gene-membership list responses are validated; the full search/detail/diagram provider contracts and scientific coverage remain separately qualified work.",
            "[Reactome Content Service](https://reactome.org/ContentService/).",
        ),
        "opentargets": (
            "Open Targets",
            "Retrieve human gene sections target_evidence, diseases and druggability through get. The public target_dossier composes those assertions with expression and literature under one qualified gene identity.",
            "Stable Ensembl gene identifiers are resolved before target acquisition. Keep the source association score, tractability modality and disease identifier attached to each assertion.",
            "Association scores are not clinical risk probabilities, treatment effects or proof of causality. Tractability annotations do not establish safety or therapeutic efficacy. Distinct advanced association/genetics operations and nested response meanings require separate qualification.",
            "[Open Targets Platform API](https://platform-docs.opentargets.org/data-access/graphql-api).",
        ),
        "protein-atlas-mcp": (
            "Human Protein Atlas",
            "Use get_record(entity=gene, sections=[hpa]) with an explicit human gene identity. The service resolves the gene to its Ensembl identifier before requesting the source XML annotations.",
            "The public hpa section retains source annotations. Inspect get_capabilities for localization and expression-profile review schemas; antibody-information acquisition is unavailable.",
            "Single-gene XML is checked for one matching Ensembl identity and required entry/schema/annotation version metadata before caching; this is not full XSD or assay validation. The source release, Ensembl/GENCODE annotation build and whole-document UTF-8 hash remain distinct. XML selectors are explicitly unapplied and comparisons retain successful peers with separate failures, without normalized measurements or derived reliability scores. Do not infer numeric units, assay coverage, tissue-specific negatives or validated specificity from missing annotations. Large compressible XML can be recovered through advertised bounded ranges within unchanged stored-snapshot and response ceilings; decoded size/structure, scope, expiry and storage limits still apply. Broader XML interpretation, TSV antibody acquisition and advanced scientific workflows remain unqualified.",
            "[Human Protein Atlas data downloads and formats](https://www.proteinatlas.org/about/download).",
        ),
        "openfda-mcp": (
            "openFDA",
            "Use get_record(entity=drug) with explicit label or safety sections and search_records(entity=adverse_event) for reported drug events. Recall acquisition is the distinct advanced operation.",
            "Preserve each submitted source record and its provenance. Name-based discovery can require identity review before combining labels or reports.",
            "Spontaneous reports have no exposure denominator and do not establish event incidence or drug causality. Submitted labels and recall records do not establish individual clinical suitability; optional missing fields remain unknown. The examples qualify routing, not complete provider response semantics.",
            "[openFDA API documentation](https://open.fda.gov/apis/).",
        ),
        "surechembl-mcp": (
            "SureChEMBL",
            "The ordinary public patent search acquires SureChEMBL patent-chemistry discovery records. Its distinct chemistry, structure-similarity and statistics operations use query_source.",
            "Preserve provider patent and chemical identifiers. Public patent bibliographic retrieval uses the separate patents source and its qualified EPO access mode; a chemistry search record is not a complete patent document.",
            "Chemical mentions do not establish claim scope, biological activity, novelty or freedom to operate. These mocked routes do not establish current SureChEMBL endpoint availability, source access or exhaustive patent coverage.",
            "[SureChEMBL](https://www.surechembl.org/).",
        ),
        "ensembl-mcp": (
            "Ensembl",
            "Distinct sequence, assembly, regulation, evolution, coordinate and variant operations use query_source. The example retrieves assembly metadata for the explicit homo_sapiens provider selector.",
            "Current assembly metadata is time-dependent. Preserve assembly/version and sequence identifiers supplied by the provider; do not silently treat current server data as a requested historical release or infer coordinate conversions.",
            "Offline contracts validate genome metadata, qualified sequence identities, species-qualified homology and gene-tree member routes, regional feature lists, VEP identifier results and assembly mappings before evidence and caching. Protein retrieval retains all returned translations; FASTA is derived from validated JSON. Null batch lookups are unavailable, not negative evidence. These are minimum acquisition checks, not full scientific annotation validation. Homology is a provider inference; its cdna selector uses coding-DNA alignments. Mappings can cover only part of the requested region. Current lookup versions are checked when explicitly requested; they do not request a historical release. Translation lookup can omit assembly metadata. Sequence query echoes and Ensembl namespaces qualify source attribution but do not independently establish every transcript/translation's membership or functional equivalence. Live health and comprehensive biological interpretation remain unqualified.",
            "[Ensembl assembly API](https://rest.ensembl.org/documentation/info/assembly_info).",
        ),
        "pdb-mcp": (
            "RCSB PDB",
            "Use query_source for structure discovery, exact entry metadata, coordinate downloads and quality annotations. The example requests JSON entry metadata for the exact four-character PDB identifier 4HHB.",
            "Entry metadata and coordinate files are different acquisitions. Preserve model, chain, assembly and experimental method when interpreting coordinates; do not assume a default biological assembly or protein isoform.",
            "Structure identity and coverage do not establish a variant effect, ligand affinity or comparable experimental quality. The example qualifies metadata routing; broader entry, coordinate and quality contracts remain unqualified.",
            "[RCSB PDB Data API](https://data.rcsb.org/).",
        ),
        "bio-ontology-mcp": (
            "BioOntology",
            "The BioPortal source exposes ontology discovery, class pages, exact class information and mapping assertions through query_source. Ordinary phenotype term discovery uses the public phenotype route.",
            "Configure BIOONTOLOGY_API_KEY outside tool arguments. The adapter uses the Authorization header. Preserve ontology acronym, exact class URI, mapping source/process and provider continuation; missing process attribution remains explicit.",
            "Mapping assertions do not imply biological equivalence. The class example uses one exact GO URI and a synthetic credential only in offline tests; it does not establish live credential validity, ontology release pinning or comprehensive coverage.",
            "[BioOntology REST API](https://data.bioontology.org/documentation).",
        ),
        "antibody-registry": (
            "Antibody Registry",
            "Use query_source with query_antibody and query_type search or details. Detail lookup accepts a numeric registry ID, AB_ identifier or qualified RRID; search preserves bounded page, totalElements and next_page.",
            "Access follows the installed source-permission policy at both adapter and wire boundaries; no legacy environment attestation is required. Tests use synthetic website responses and exercise the shipped policy without that flag. Provider redirects retain requested and returned identities.",
            "The provider FAQ does not offer direct API access; the retained adapter reads website endpoints observed on 2026-10-09. These are not a supported stable API contract. Review current provider terms before enabling live access. Registry annotations do not establish binding, specificity, epitope validity or experimental suitability. Vendor/account/write URLs are not followed.",
            "[Antibody Registry access FAQ](https://www.antibodyregistry.org/faq).",
        ),
    }
)


def adapter_readme(package):
    source, identifiers = ADAPTER_READMES[package]
    name, introduction, usage, limitations, references = ADAPTER_DOCUMENTATION[package]
    lines = [
        "# " + name + " retained adapter",
        "",
        "Examples use the public BioMedMCP tools and their typed JSON arguments.",
        "",
        "Connect to the biomedmcp server and use its tools. This package runs inside that server; it is not a separate MCP server.",
        "",
        introduction,
        "",
        "Advanced operations: "
        + ", ".join("`" + operation + "`" for operation in sorted(ADVANCED[source]))
        + ".",
        "",
        "Run get_capabilities for this source to see its current parameters. " + usage,
        "",
        "The examples are tested through MCP against mock responses; live results may differ. "
        + limitations,
        "",
        "To get more results, follow the continuation in the response. If a result includes an evidence recovery URI, use it to read data left out of the preview; see [evidence recovery](../../../docs/evidence-resources.md). Recovered data expires and is subject to the source's terms.",
        "",
    ]
    for identifier in identifiers:
        item = by_id(identifier)
        lines.extend(
            [
                "## " + item.label,
                "",
                "```json",
                json.dumps({"tool": item.operation, "arguments": item.arguments}, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "See the [public runtime README](../../../README.md) for installation, source configuration and testing.",
            "",
            "Provider contracts: " + references,
            "",
            "Licensed under [Apache-2.0](../../../LICENSE). Provider data has its own [terms](../../../docs/source-licenses.md).",
            "",
        ]
    )
    return "\n".join(lines)
