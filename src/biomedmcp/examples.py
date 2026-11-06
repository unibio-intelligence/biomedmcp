"""Executable public examples, shared by descriptions, guide and documentation.

Argument JSON keeps registry entries immutable; callers receive private dictionaries.
These are routing examples, not live-provider or scientific-result guarantees.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    id: str
    label: str
    operation: str
    arguments_json: str

    @property
    def arguments(self):
        return json.loads(self.arguments_json)


def example(identifier, label, operation, arguments):
    return Example(identifier, label, operation, json.dumps(arguments, separators=(",", ":")))


EXAMPLES = (
    example(
        "gene-search",
        "Human BRCA1 gene discovery",
        "search_records",
        {"entity": "gene", "query": "BRCA1", "filters": {"species": 9606}},
    ),
    example(
        "protein-search",
        "Human insulin protein discovery",
        "search_records",
        {"entity": "protein", "query": "insulin", "filters": {"species": 9606}},
    ),
    example(
        "drug-search",
        "Ezetimibe compound discovery",
        "search_records",
        {"entity": "drug", "query": "ezetimibe", "filters": {"source": "mychem"}},
    ),
    example(
        "gene-record", "Human PCSK9 gene record", "get_record", {"entity": "gene", "id": "PCSK9", "species": 9606}
    ),
    example(
        "gene-expression",
        "Human LDLR median expression by tissue",
        "get_record",
        {"entity": "gene", "id": "LDLR", "species": 9606, "sections": ["expression"]},
    ),
    example(
        "article-fulltext",
        "Full-text outline for a qualified PMID, when accessible",
        "get_record",
        {"entity": "article", "id": "PMID:123", "sections": ["fulltext"]},
    ),
    example(
        "gene-tissue",
        "Human LDLR expression in liver tissue",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["expression"],
            "section_parameters": {
                "expression": {"query_type": "gene_tissue", "tissue_id": "Liver"}
            },
        },
    ),
    example(
        "gene-eqtl",
        "Human LDLR eQTL associations in liver tissue",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["eqtl"],
            "section_parameters": {"eqtl": {"tissue_id": "Liver"}},
        },
    ),
    example(
        "drug-record",
        "Ezetimibe record by provider-stable identifier",
        "get_record",
        {"entity": "drug", "id": "OLNTVTPDXPETLC-XPWALMASSA-N"},
    ),
    example(
        "disease-record",
        "Melanoma record by MONDO identifier",
        "get_record",
        {"entity": "disease", "id": "MONDO:0007750"},
    ),
    example("literature-lipids", "PCSK9 LDL cholesterol papers", "search_literature", {"query": "PCSK9 LDL cholesterol"}),
    example(
        "literature-date",
        "PCSK9 papers since 2024",
        "search_literature",
        {"query": "PCSK9", "filters": {"source": "pubmed", "date_from": "2024-01-01"}},
    ),
    example(
        "literature-open",
        "Open-access familial hypercholesterolemia papers from Europe PMC",
        "search_literature",
        {"query": "familial hypercholesterolemia", "filters": {"source": "europepmc", "open_access": True}},
    ),
    example(
        "trial-recruiting",
        "Recruiting familial hypercholesterolemia trials",
        "search_trials",
        {"query": "familial hypercholesterolemia", "filters": {"status": "RECRUITING"}},
    ),
    example(
        "trial-phase",
        "Phase 3 breast-cancer trials",
        "search_trials",
        {"query": "breast cancer", "filters": {"phase": "PHASE3"}},
    ),
    example("trial-ezetimibe", "Ezetimibe trial discovery", "search_trials", {"query": "ezetimibe"}),
    example("variant-protein", "PCSK9 R46L variant evidence", "get_variant_evidence", {"id": "PCSK9 R46L"}),
    example(
        "variant-coordinate",
        "GRCh38 PCSK9 variant coordinate evidence",
        "get_variant_evidence",
        {"id": "chr1:55039974:G:T", "assembly": "grch38", "sections": ["clinvar", "population"]},
    ),
    example(
        "variant-rsid",
        "Variant evidence for rs11591147",
        "get_variant_evidence",
        {"id": "rs11591147", "sections": ["clinvar", "population"]},
    ),
    example(
        "variant-cohort",
        "Variant evidence in an explicit cBioPortal cohort",
        "get_variant_evidence",
        {
            "id": "PCSK9 R46L",
            "sections": ["cbioportal"],
            "section_parameters": {
                "cbioportal": {"molecular_profile_id": "study_mutations", "sample_list_id": "study_all"}
            },
        },
    ),
    example(
        "study-profile",
        "TP53 mutation frequency in the installed synthetic study",
        "analyze_study",
        {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"},
    ),
    example(
        "study-survival",
        "Overall survival by TP53 mutation in the installed synthetic study",
        "analyze_study",
        {"analysis": "survival", "study": "ubi_synthetic", "gene": "TP53", "endpoint": "os"},
    ),
    example(
        "study-cooccurrence",
        "TP53/KRAS co-occurrence in the installed synthetic study",
        "analyze_study",
        {"analysis": "co_occurrence", "study": "ubi_synthetic", "genes": ["TP53", "KRAS"]},
    ),
    example(
        "resolve-ldl-receptor",
        "Resolve the human LDL receptor gene alias",
        "resolve_entity",
        {"entity": "gene", "query": "LDL receptor", "species": 9606},
    ),
    example(
        "resolve-variant",
        "Resolve rs11591147 before joining evidence",
        "resolve_entity",
        {"entity": "variant", "query": "rs11591147"},
    ),
    example(
        "resolve-mouse",
        "Resolve mouse Trp53 without changing species",
        "resolve_entity",
        {"entity": "gene", "query": "Trp53", "species": 10090},
    ),
    example(
        "article-references",
        "References of a known PubMed article",
        "find_related",
        {"entity": "article", "id": "PMID:123", "relation": "references"},
    ),
    example(
        "variant-structure",
        "PCSK9 R46L structural coverage",
        "find_related",
        {"entity": "variant", "id": "PCSK9 R46L", "relation": "structure"},
    ),
    example(
        "gene-articles",
        "Human PCSK9 article discovery with qualified identity",
        "find_related",
        {"entity": "gene", "id": "PCSK9", "relation": "articles", "species": 9606},
    ),
    example(
        "target-dossier",
        "Bounded human LDLR target dossier",
        "build_dossier",
        {
            "workflow": "target_dossier",
            "focus": "LDLR",
            "species": 9606,
        },
    ),
    example(
        "drug-dossier",
        "Bounded ezetimibe drug review",
        "build_dossier",
        {"workflow": "drug_review", "focus": "ezetimibe"},
    ),
    example(
        "disease-dossier",
        "Bounded familial hypercholesterolemia disease landscape",
        "build_dossier",
        {"workflow": "disease_landscape", "focus": "MONDO:0007750"},
    ),
    example(
        "gtex-tissues",
        "GTEx tissue metadata",
        "query_source",
        {
            "source": "gtex",
            "operation": "get_metadata",
            "params": {"info_type": "tissues", "dataset_id": "gtex_v10"},
        },
    ),
    example(
        "enrichment",
        "Human gene-set enrichment",
        "query_source",
        {
            "source": "enrichment",
            "operation": "gene_set",
            "params": {"genes": ["PCSK9", "KRAS", "TP53"], "organism": "hsapiens"},
        },
    ),
    example(
        "genbank-region",
        "Bounded versioned GenBank sequence region",
        "query_source",
        {
            "source": "ncbi-records",
            "operation": "get",
            "params": {
                "database": "genbank",
                "accession": "NM_174936.4",
                "sequence": True,
                "start": 1,
                "stop": 100,
            },
        },
    ),
    example(
        "batch-gene",
        "Batch a human gene record read",
        "run_batch",
        {"calls": [{"operation": "get_record", "arguments": {"entity": "gene", "id": "PCSK9", "species": 9606}}]},
    ),
    example(
        "batch-trial",
        "Batch trial discovery",
        "run_batch",
        {"calls": [{"operation": "search_trials", "arguments": {"query": "familial hypercholesterolemia"}}]},
    ),
    example(
        "batch-resolve",
        "Batch human gene alias resolution",
        "run_batch",
        {
            "calls": [
                {"operation": "resolve_entity", "arguments": {"query": "LDL receptor", "entity": "gene", "species": 9606}}
            ]
        },
    ),
    example("capabilities-all", "Inspect configured capabilities", "get_capabilities", {}),
    example("capabilities-gtex", "Inspect the advanced GTEx schema", "get_capabilities", {"source": "gtex"}),
    example(
        "capabilities-variant", "Inspect variant evidence sections", "get_capabilities", {"entity": "variant"}
    ),
    example("quota", "Read the current account quota", "get_quota", {}),
    example(
        "chembl-compounds",
        "ChEMBL aspirin compound discovery",
        "query_source",
        {
            "source": "chembl",
            "operation": "search_compounds",
            "params": {"query": "aspirin", "search_type": "name", "limit": 10},
        },
    ),
    example(
        "chembl-compound",
        "ChEMBL aspirin compound record",
        "query_source",
        {"source": "chembl", "operation": "get_compound_details", "params": {"chembl_id": "CHEMBL25"}},
    ),
    example(
        "chembl-targets",
        "Human kinase targets in ChEMBL",
        "query_source",
        {
            "source": "chembl",
            "operation": "search_targets",
            "params": {"query": "kinase", "organism": "Homo sapiens", "limit": 10},
        },
    ),
    example(
        "chembl-bioactivities",
        "ChEMBL IC50 measurements for a target, in nM",
        "query_source",
        {
            "source": "chembl",
            "operation": "search_bioactivities",
            "params": {
                "target_chembl_id": "CHEMBL2095173",
                "activity_type": "IC50",
                "units": "nM",
                "limit": 10,
            },
        },
    ),
    example(
        "chembl-properties",
        "Physicochemical rule-of-five assessment for aspirin",
        "query_source",
        {
            "source": "chembl",
            "operation": "analyze_compound_properties",
            "params": {"chembl_id": "CHEMBL25", "property_type": "drug_likeness"},
        },
    ),
    example(
        "chembl-batch",
        "Batch three distinct ChEMBL compound records",
        "run_batch",
        {
            "calls": [
                {
                    "operation": "query_source",
                    "arguments": {
                        "source": "chembl",
                        "operation": "get_compound_details",
                        "params": {"chembl_id": identifier},
                    },
                }
                for identifier in ("CHEMBL25", "CHEMBL521", "CHEMBL192")
            ]
        },
    ),
    example(
        "ncbi-genomes",
        "Human RefSeq chromosome-level assembly discovery",
        "query_source",
        {
            "source": "ncbi",
            "operation": "search_ncbi_data",
            "params": {
                "query": "Homo sapiens",
                "data_type": "genomes",
                "assembly_source": "refseq",
                "assembly_level": "chromosome",
                "max_results": 10,
            },
        },
    ),
    example(
        "ncbi-assembly",
        "Exact GRCh38.p14 assembly and annotation-release metadata",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_genome_data",
            "params": {"accession": "GCF_000001405.40", "info_type": "full"},
        },
    ),
    example(
        "ncbi-annotation",
        "BRCA1 annotation on the exact GRCh38.p14 assembly",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_genome_data",
            "params": {
                "accession": "GCF_000001405.40",
                "info_type": "annotation",
                "symbols": ["BRCA1"],
                "gene_types": ["protein-coding"],
                "page_size": 10,
            },
        },
    ),
    example(
        "ncbi-taxonomy-search",
        "Human taxonomy discovery at species rank",
        "query_source",
        {
            "source": "ncbi",
            "operation": "search_ncbi_data",
            "params": {
                "query": "Homo sapiens",
                "data_type": "taxonomy",
                "rank": "species",
                "max_results": 10,
            },
        },
    ),
    example(
        "ncbi-lineage",
        "Human ancestor TaxIDs and named-rank classification",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_taxonomy_data",
            "params": {"tax_id": 9606, "info_type": "lineage"},
        },
    ),
    example(
        "ncbi-organism",
        "Human taxonomy, provider names and available assembly page",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_taxonomy_data",
            "params": {
                "tax_id": 9606,
                "info_type": "organism",
                "include_synonyms": True,
                "genome_page_size": 10,
            },
        },
    ),
    example(
        "ncbi-quality",
        "E. coli MG1655 assembly quality with explicit missing measurements",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_assembly_data",
            "params": {"assembly_accession": "GCF_000005845.2", "report_type": "quality"},
        },
    ),
    example(
        "ncbi-sequence-report",
        "GRCh38.p14 sequence metadata with lengths and accessions",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_assembly_data",
            "params": {
                "assembly_accession": "GCF_000001405.40",
                "report_type": "sequence_report",
                "page_size": 10,
            },
        },
    ),
    example(
        "ncbi-stats",
        "GRCh38.p14 provider assembly statistics",
        "query_source",
        {
            "source": "ncbi",
            "operation": "get_assembly_data",
            "params": {"assembly_accession": "GCF_000001405.40", "report_type": "stats"},
        },
    ),
    example(
        "ncbi-project",
        "Human-reference BioProject assembly associations",
        "query_source",
        {
            "source": "ncbi",
            "operation": "search_project_sample",
            "params": {"accession": "PRJNA31257", "search_type": "bioproject", "max_results": 10},
        },
    ),
    example(
        "ncbi-sample",
        "E. coli MG1655 BioSample assembly associations",
        "query_source",
        {
            "source": "ncbi",
            "operation": "search_project_sample",
            "params": {"accession": "SAMN02604091", "search_type": "biosample", "max_results": 10},
        },
    ),
)

# Each migrated retained README is generated from these same executable cases.
EXAMPLES += (
    example(
        "gene-sqtl",
        "Human LDLR sQTL associations in liver tissue",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["sqtl"],
            "sources": ["gtex"],
            "source_versions": {"gtex": "gtex_v10"},
            "section_parameters": {
                "sqtl": {
                    "tissue_id": "Liver",
                    "p_value_threshold": 0.05,
                    "limit": 10,
                    "page": 0,
                }
            },
        },
    ),
    example(
        "gtex-dataset",
        "GTEx V10 release metadata",
        "query_source",
        {
            "source": "gtex",
            "operation": "get_metadata",
            "params": {"info_type": "dataset", "dataset_id": "gtex_v10"},
        },
    ),
    example(
        "gtex-service",
        "GTEx API service metadata",
        "query_source",
        {"source": "gtex", "operation": "get_metadata", "params": {"info_type": "service"}},
    ),
    example(
        "gtex-sample",
        "Metadata for an exact public GTEx sample",
        "query_source",
        {
            "source": "gtex",
            "operation": "get_sample",
            "params": {"sample_id": "GTEX-1117F-0003-SM-58Q7G", "dataset_id": "gtex_v10", "limit": 10},
        },
    ),
    example(
        "gene-transcripts",
        "Release-qualified human gene transcript annotations",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["transcripts"],
            "sources": ["gtex"],
            "source_versions": {"gtex": "gtex_v10"},
            "section_parameters": {"transcripts": {"limit": 10, "page": 0}},
        },
    ),
    example(
        "gene-exons",
        "Transcript-associated exons of a release-qualified human gene",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["exons"],
            "sources": ["gtex"],
            "source_versions": {"gtex": "gtex_v10"},
            "section_parameters": {"exons": {"limit": 10, "page": 0}},
        },
    ),
)

EXAMPLES += (
    example(
        "trial-record",
        "A known trial's protocol and posted results",
        "get_record",
        {"entity": "trial", "id": "NCT04368728"},
    ),
    example(
        "trial-contacts",
        "A known trial's submitted contacts and sites",
        "get_record",
        {"entity": "trial", "id": "NCT04368728", "sections": ["contacts", "locations"]},
    ),
    example(
        "trial-location",
        "Melanoma trials listing a Boston site",
        "search_trials",
        {"query": "familial hypercholesterolemia AND AREA[LocationCity]Boston", "filters": {"status": "RECRUITING"}},
    ),
    example(
        "trial-completed",
        "Completed COVID-19 trials with posted results",
        "search_trials",
        {"query": "COVID-19 AND AREA[HasResults]true", "filters": {"status": "COMPLETED"}},
    ),
    example(
        "trial-pediatric",
        "Leukemia trial discovery with child eligibility",
        "search_trials",
        {"query": "leukemia AND AREA[StdAge]CHILD"},
    ),
    example(
        "trial-statistics",
        "Phase memberships in one bounded lung-cancer trial window",
        "query_source",
        {
            "source": "clinical-trials",
            "operation": "get_trial_statistics",
            "params": {"condition": "lung cancer", "group_by": "phase", "page_size": 25},
        },
    ),
    example(
        "trial-comparison",
        "Separate phase, status and enrollment assertions for two trials",
        "query_source",
        {
            "source": "clinical-trials",
            "operation": "compare_trials",
            "params": {
                "nct_ids": ["NCT04368728", "NCT04280705"],
                "comparison_fields": ["phase", "status", "enrollment"],
            },
        },
    ),
)

EXAMPLES += (
    example(
        "gene-map",
        "Map two human gene symbols to qualified stable identities",
        "query_source",
        {
            "source": "mygene",
            "operation": "map_gene_ids",
            "params": {"gene_ids": ["PCSK9", "LDLR"], "input_namespace": "symbol", "species": 9606},
        },
    ),
    example(
        "disease-search",
        "Melanoma disease identity discovery",
        "search_records",
        {"entity": "disease", "query": "familial hypercholesterolemia"},
    ),
    example(
        "protein-record",
        "Human PCSK9 protein by UniProt accession",
        "get_record",
        {"entity": "protein", "id": "Q8NBP7"},
    ),
    example(
        "pathway-search",
        "Human apoptosis pathway discovery",
        "search_records",
        {"entity": "pathway", "query": "apoptosis"},
    ),
    example(
        "pathway-record",
        "Reactome apoptosis pathway record",
        "get_record",
        {"entity": "pathway", "id": "R-HSA-109581"},
    ),
    example(
        "gene-pathways",
        "Pathway membership for a qualified human PCSK9 gene",
        "get_record",
        {"entity": "gene", "id": "PCSK9", "species": 9606, "sections": ["pathways"]},
    ),
    example(
        "gene-target-evidence",
        "Human LDLR target evidence and source disease associations",
        "get_record",
        {
            "entity": "gene",
            "id": "LDLR",
            "species": 9606,
            "sections": ["target_evidence", "diseases", "druggability"],
        },
    ),
    example(
        "gene-hpa",
        "Human Protein Atlas source annotations for qualified LDLR",
        "get_record",
        {"entity": "gene", "id": "LDLR", "species": 9606, "sections": ["hpa"]},
    ),
    example(
        "drug-label",
        "Submitted ezetimibe labeling records",
        "get_record",
        {"entity": "drug", "id": "ezetimibe", "sections": ["label"]},
    ),
    example(
        "drug-safety",
        "Reported ezetimibe adverse-event records",
        "get_record",
        {"entity": "drug", "id": "ezetimibe", "sections": ["safety"]},
    ),
    example(
        "adverse-event-search",
        "Ezetimibe reported adverse-event discovery",
        "search_records",
        {"entity": "adverse_event", "query": "ezetimibe"},
    ),
    example(
        "patent-search",
        "SureChEMBL patent chemistry discovery for ezetimibe",
        "search_records",
        {"entity": "patent", "query": "ezetimibe"},
    ),
    example(
        "ensembl-assembly",
        "Current Ensembl human assembly metadata",
        "query_source",
        {
            "source": "ensembl",
            "operation": "get_genome_info",
            "params": {"info_type": "assembly", "species": "homo_sapiens"},
        },
    ),
    example(
        "pdb-record",
        "RCSB entry metadata for hemoglobin structure 4HHB",
        "query_source",
        {"source": "pdb", "operation": "get_structure_info", "params": {"pdb_id": "4HHB", "format": "json"}},
    ),
    example(
        "bio-ontology-class",
        "BioPortal Gene Ontology class by its exact URI",
        "query_source",
        {
            "source": "bio-ontology",
            "operation": "get_class_info",
            "params": {"ontology": "GO", "class_id": "http://purl.obolibrary.org/obo/GO_0006915"},
        },
    ),
    example(
        "antibody-record",
        "Antibody Registry annotations for an exact RRID",
        "query_source",
        {
            "source": "antibody-registry",
            "operation": "query_antibody",
            "params": {"query_type": "details", "query": "RRID:AB_3753073"},
        },
    ),
)

def for_operation(operation):
    return tuple(item for item in EXAMPLES if item.operation == operation)


def by_id(identifier):
    return next(item for item in EXAMPLES if item.id == identifier)


def description(base, operation):
    # One full call keeps discovery compact; all calls remain in the guide.
    return base + " e.g. " + for_operation(operation)[0].arguments_json


def guide_examples():
    lines = [
        "## Executable examples",
        "",
        "These calls demonstrate routing against synthetic test fixtures; live access and evidence availability are not guaranteed.",
        "Study examples require an installed verified study: ubi_synthetic is the deterministic fixture, not clinical evidence. Substitute an installed study ID from get_capabilities.",
        "The cBioPortal example requires a real molecular-profile/sample-list pair for the intended population; study_mutations/study_all are fixture identifiers.",
        "Full text requires an accessible PMC record and article-specific rights.",
        "",
    ]
    for item in EXAMPLES:
        lines.extend(
            [
                "### " + item.label,
                "",
                "```json",
                json.dumps({"tool": item.operation, "arguments": item.arguments}, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def readme_examples():
    names = {"literature-date", "gene-expression", "variant-protein"}
    return "\n".join(
        "UBI_PROFILE=local biomedmcp " + item.operation + " '" + item.arguments_json + "'"
        for item in EXAMPLES
        if item.id in names
    )
