"""Configuration constants for GTEx API."""

# GTEx API Base URL
GTEX_API_BASE_URL = "https://gtexportal.org/api/v2"

# GTEx release defaults. The API metadata endpoint currently reports gtex_v10
# as the most complete Adult GTEx release, using GENCODE v39.
DEFAULT_DATASET_ID = "gtex_v10"
DATASET_GENCODE_VERSION = {
    "gtex_v7": "v19",
    "gtex_v8": "v26",
    "gtex_v10": "v39",
}
DEFAULT_GENCODE_VERSION = DATASET_GENCODE_VERSION[DEFAULT_DATASET_ID]

# API Endpoints
ENDPOINTS = {
    # Service Info
    "service_info": "/",
    # Expression
    "median_gene_expression": "/expression/medianGeneExpression",
    "gene_expression": "/expression/geneExpression",
    "top_expressed_genes": "/expression/topExpressedGene",
    "median_transcript_expression": "/expression/medianTranscriptExpression",
    "median_exon_expression": "/expression/medianExonExpression",
    "median_junction_expression": "/expression/medianJunctionExpression",
    # Association - Static
    "eqtl_genes": "/association/egene",
    "single_tissue_eqtl": "/association/singleTissueEqtl",
    "sqtl_genes": "/association/sgene",
    "single_tissue_sqtl": "/association/singleTissueSqtl",
    "metasoft": "/association/metasoft",
    "independent_eqtl": "/association/independentEqtl",
    "independent_sqtl": "/association/independentSqtl",
    # Association - Dynamic
    "dynamic_eqtl": "/association/dyneqtl",
    "dynamic_sqtl": "/association/dynsqtl",
    "dynamic_ieqtl": "/association/dynieqtl",
    "dynamic_isqtl": "/association/dynisqtl",
    # Reference
    "gene": "/reference/gene",
    "transcript": "/reference/transcript",
    "exon": "/reference/exon",
    "variant": "/dataset/variant",
    "tissue": "/dataset/tissueSiteDetail",
    # Dataset
    "dataset_info": "/metadata/dataset",
    "ld_variants": "/dataset/ldVariants",
    # Biobank
    "sample": "/dataset/sample",
}

# Request timeout (seconds)
REQUEST_TIMEOUT = 30.0

# Rate limiting - GTEx requires sequential queries, not parallel
RATE_LIMIT_DELAY = 0.5  # seconds between requests
