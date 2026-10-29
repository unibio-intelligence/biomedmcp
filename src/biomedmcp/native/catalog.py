"""Ubi owns this catalog. Source adapters are implementation details, not MCP mounts.

A section is a projection/enrichment of an entity. A relation traverses identities.
The advanced registry contains operations with additional scientific semantics.
"""

SEARCH_SOURCES = {
    "gene": ["mygene"],
    "variant": ["myvariant"],
    "article": ["pubmed", "europepmc", "pubtator", "litsense2"],
    "author": ["openalex"],
    "trial": ["clinical-trials", "nci"],
    "drug": ["mychem"],
    "disease": ["mydisease"],
    "phenotype": ["ols"],
    "protein": ["uniprot"],
    "pathway": ["reactome"],
    "pgx": ["cpic"],
    "gwas": ["gwas"],
    "diagnostic": ["gtr", "fda-devices"],
    "adverse-event": ["openfda"],
    "study": ["study"],
    "patent": ["surechembl"],
    "sequence": ["ncbi-records"],
}
RECORD_OWNER = {entity: sources[0] for entity, sources in SEARCH_SOURCES.items()}
SECTIONS = {
    "gene": {
        **dict.fromkeys(["ontology", "go"], "mygene"),
        "pathways": "reactome",
        "protein": "uniprot",
        "expression": "gtex",
        "eqtl": "gtex",
        "sqtl": "gtex",
        "transcripts": "gtex",
        "exons": "gtex",
        "target_evidence": "opentargets",
        "diseases": "opentargets",
        "druggability": "opentargets",
        "genetics": "opentargets",
        "hpa": "protein-atlas",
        "interactions": "string",
        "civic": "civic",
        "clingen": "clingen",
        "gencc": "gencc",
        "constraint": "gnomad",
        "disgenet": "disgenet",
        "funding": "nih-reporter",
        "diagnostics": "gtr",
    },
    "variant": {
        **dict.fromkeys(["conservation", "cosmic", "cgi"], "myvariant"),
        "predictions": "alphamissense",
        "eve": "eve",
        "clinvar": "ncbi",
        "population": "gnomad",
        "civic": "civic",
        "cbioportal": "cbioportal",
        "gwas": "gwas",
    },
    "article": {
        "annotations": "pubtator",
        "fulltext": "europepmc",
        "assets": "europepmc",
        "indexing": "pubmed",
    },
    "trial": dict.fromkeys(
        ["eligibility", "contacts", "locations", "outcomes", "arms", "references"], "clinical-trials"
    ),
    "drug": {
        "label": "openfda",
        "regulatory": "openfda",
        "safety": "openfda",
        "shortage": "openfda",
        "targets": "mychem",
        "indications": "mychem",
        "interactions": "mychem",
        "civic": "civic",
        "approvals": "orange-book",
    },
    "disease": {
        **dict.fromkeys(["genes", "phenotypes", "models"], "monarch"),
        **dict.fromkeys(["variants", "prevalence", "survival", "clinical_features"], "mydisease"),
        "pathways": "reactome",
        "diagnostics": "gtr",
        "funding": "nih-reporter",
        "civic": "civic",
        "disgenet": "disgenet",
    },
    "diagnostic": dict.fromkeys(["genes", "conditions", "methods"], "gtr") | {"regulatory": "fda-devices"},
    "pgx": dict.fromkeys(
        ["interactions", "recommendations", "frequencies", "guidelines", "annotations"], "cpic"
    ),
    "pathway": dict.fromkeys(["genes", "events"], "reactome"),
    "protein": {
        "domains": "interpro",
        "interactions": "string",
        "complexes": "complexportal",
        "structures": "uniprot",
    },
    "adverse-event": dict.fromkeys(["reactions", "outcomes", "concomitant", "guidance"], "openfda"),
    "patent": dict.fromkeys(["biblio", "family", "claims", "citations"], "patents"),
    "study": {},
    "sequence": {},
    "phenotype": {},
    "author": {},
    "gwas": {},
}
# No section aliases: callers get route guidance rather than a second execution path.
ALIASES = {
    "variant": {"predict": "predictions", "population-details": "population"},
    "gene": {"ontology": "go"},
}
SECTIONS["gene"].pop("ontology")
RELATIONS = {
    "gene": ["articles", "trials"],
    "drug": ["articles", "trials"],
    "disease": ["articles", "trials"],
    "variant": ["articles", "structure"],
    "article": ["citations", "references", "recommendations", "authors", "entities"],
    "author": ["articles"],
}
ADVANCED = {
    "gtex": {"get_metadata", "get_sample"},
    "uniprot": {"compare_proteins", "get_taxonomy_info", "analyze_evolution"},
    "ensembl": {
        "get_sequences",
        "analyze_evolution",
        "get_regulatory_elements",
        "get_genome_info",
        "map_coordinates",
    },
    "chembl": {
        "search_compounds",
        "get_compound_details",
        "search_targets",
        "get_target_details",
        "search_bioactivities",
        "get_assay_details",
        "compare_compound_activities",
        "analyze_compound_properties",
        "advanced_property_search",
    },
    "mychem": {
        "get_admet_properties",
        "map_identifiers",
    },
    "mygene": {"map_gene_ids", "compare_genes"},
    "mydisease": {
        "get_phenotype_similarity",
        "get_gene_disease_evidence",
        "get_phenotype_frequency",
        "map_disease_ids",
    },
    "clinical-trials": {"get_trial_statistics", "compare_trials"},
    "dailymed": {"get_drug_label_sections"},
    "opentargets": {"search_drugs", "analyze_advanced", "analyze_association"},
    "protein-atlas": {"compare_expression_profiles", "analyze_localization", "get_antibody_info"},
    "reactome": {"get_pathway_diagram"},
    "surechembl": {"analyze_patent_chemistry", "search_similar_structures", "get_patent_statistics"},
    "pdb": {
        "search_structures",
        "get_structure_details",
        "analyze_structure",
        "get_ligand_info",
        "compare_structures",
    },
    "omnipath": {"get_interactions", "get_annotations", "get_complexes", "get_intercell"},
    "antibody-registry": {"query_antibody"},
    "bio-ontology": {"search_ontologies", "get_ontology_classes", "get_class_info", "get_mappings"},
    "ncbi-records": {"search", "get", "links"},
    "enrichment": {"gene_set"},
    "patents": {"search"},
    "study": {"query", "cohort", "survival", "compare", "co_occurrence", "filter", "top_mutated"},
    "clingen": {"normalize", "assertions", "specifications"},
}
# These source operations carry distinct acquisition parameters. Their common
# entity equivalents are deliberately removed; source guidance spells this out.
SEARCH_SOURCES["sequence"] = []
RECORD_OWNER.pop("sequence")
SECTIONS.pop("sequence")
# GenBank/GEO/SRA use one typed source route including regions and cross-links.

SEARCH_SOURCES["drug"] = ["mychem", "ema", "who"]
SEARCH_SOURCES["diagnostic"].append("who-ivd")
SECTION_ALTERNATIVES = {
    "article": {"fulltext": ["europepmc", "pmc"], "assets": ["europepmc", "pmc"]},
    "drug": {
        "regulatory": ["openfda", "ema", "who"],
        "safety": ["openfda", "ema"],
        "shortage": ["openfda", "ema"],
    },
}

SECTIONS["pgx"].pop("annotations")
ALIASES["pgx"] = {"annotations": "interactions"}

ADVANCED["orange-book"] = {
    "get_therapeutic_equivalence",
    "search_generic_equivalents",
    "get_patent_info",
    "get_exclusivity_info",
}
ADVANCED["ncbi"] = {
    "search_ncbi_data",
    "get_genome_data",
    "get_taxonomy_data",
    "get_assembly_data",
    "get_virus_info",
    "find_orthologs",
    "search_project_sample",
}
ADVANCED["omnipath"] = {
    "get_interactions",
    "get_enzyme_substrate",
    "get_ligand_receptor",
    "get_tf_targets",
    "get_mirna_targets",
    "get_complexes",
    "get_annotations",
}
ADVANCED["pdb"] = {"search_structures", "get_structure_info", "download_structure", "get_structure_quality"}
ADVANCED["opentargets"] = {"analyze_advanced", "analyze_association"}
ADVANCED["clingen"].add("linked_data")
SECTIONS["variant"].update(oncokb="oncokb", hotspots="cancerhotspots")

ADVANCED["uniprot"].discard("get_taxonomy_info")  # Taxonomy belongs to the NCBI advanced route.
ADVANCED["protein-atlas"].discard("get_antibody_info")  # No qualified antibody identity/validation API.

RECORD_OWNER["patent"] = "patents"

ADVANCED["openfda"] = {"search_recalls"}
ADVANCED["opentargets"].add("query_genetics")
ADVANCED["ensembl"].add("analyze_variants")

# Shared identity dependencies for planning, ownership metadata and source restrictions.
SECTION_DEPENDENCIES = {
    ("gene", section): {"mygene"}
    for section, source in SECTIONS["gene"].items()
    if source not in {"mygene", "gtex"}
}
SECTION_DEPENDENCIES[("protein", "domains")] = {"uniprot"}
SECTION_DEPENDENCIES[("protein", "complexes")] = {"uniprot"}
SECTION_DEPENDENCIES[("drug", "civic")] = {"mychem"}
SECTION_DEPENDENCIES[("disease", "civic")] = {"mydisease"}
SECTION_DEPENDENCIES[("disease", "pathways")] = {"mydisease"}
for _section in ("record", *SECTIONS["variant"]):
    _dependencies = set()
    if _section not in {"record", "clinvar", "predictions", "eve", "civic", "gwas", "oncokb", "hotspots"}:
        _dependencies.add("myvariant")
    if _section == "cbioportal":
        _dependencies.add("mygene")
    SECTION_DEPENDENCIES[("variant", _section)] = _dependencies

SECTION_DEPENDENCIES[("variant", "eve")] = {"uniprot"}
