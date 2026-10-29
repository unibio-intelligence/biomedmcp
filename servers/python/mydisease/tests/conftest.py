"""Shared test fixtures and configuration."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import os
from datetime import datetime, timedelta

# Add the src directory to Python path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mydisease_mcp.client import MyDiseaseClient, CacheEntry


@pytest.fixture
def mock_client():
    """Create a mock MyDisease client."""
    client = MagicMock(spec=MyDiseaseClient)
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def real_client():
    """Create a real client instance for testing caching."""
    return MyDiseaseClient(cache_enabled=True, cache_ttl=60)


@pytest.fixture
def sample_disease_hit():
    """Sample disease hit from query results."""
    return {
        "_id": "MONDO:0007739",
        "_score": 22.757837,
        "name": "Huntington disease",
        "mondo": {
            "mondo": "MONDO:0007739",
            "label": "Huntington disease"
        },
        "omim": "143100",
        "orphanet": {
            "id": "ORPHA:399"
        }
    }


@pytest.fixture
def sample_disease_annotation():
    """Sample full disease annotation."""
    return {
        "_id": "MONDO:0007739",
        "name": "Huntington disease",
        "mondo": {
            "mondo": "MONDO:0007739",
            "label": "Huntington disease",
            "definition": "A neurodegenerative disorder characterized by progressive motor dysfunction..."
        },
        "omim": "143100",
        "orphanet": {
            "id": "ORPHA:399",
            "prevalence": {
                "prevalence_class": "1-9 / 100 000"
            }
        },
        "gene": [
            {
                "symbol": "HTT",
                "id": "3064"
            }
        ],
        "inheritance": {
            "inheritance_type": "Autosomal dominant"
        }
    }


@pytest.fixture
def sample_batch_results():
    """Sample batch query results."""
    return [
        {
            "_id": "MONDO:0007739",
            "_score": 22.757837,
            "query": "143100",
            "found": True,
            "name": "Huntington disease"
        },
        {
            "_id": "MONDO:0011122",
            "_score": 22.757837,
            "query": "ORPHA:15",
            "found": True,
            "name": "Achondroplasia"
        },
        {
            "query": "INVALID_DISEASE",
            "found": False
        }
    ]


@pytest.fixture
def sample_metadata():
    """Sample metadata response."""
    return {
        "app_revision": "abcd1234",
        "build_date": "2024-01-01",
        "build_version": "20240101",
        "stats": {
            "total": 30000
        },
        "src": {
            "omim": {
                "version": "2024-01-01",
                "stats": {"total": 10000}
            },
            "orphanet": {
                "version": "4.1.7",
                "stats": {"total": 7000}
            },
            "disgenet": {
                "version": "7.0",
                "stats": {"total": 25000}
            }
        }
    }


@pytest.fixture
def sample_gene_association():
    """Sample gene-disease association data."""
    return {
        "gene": [
            {
                "symbol": "BRCA1",
                "id": "672",
                "name": "breast cancer 1"
            }
        ],
        "causal_gene": [
            {
                "symbol": "BRCA1",
                "relationship": "causal"
            }
        ],
        "disgenet": {
            "gene": [
                {
                    "gene_name": "BRCA1",
                    "gene_id": 672,
                    "score": 0.9
                }
            ]
        }
    }


@pytest.fixture
def sample_variant_data():
    """Sample variant data."""
    return {
        "clinvar": {
            "variant": [
                {
                    "rsid": "rs104894090",
                    "hgvs": "NM_000352.4:c.1187G>A",
                    "gene": "ABCC8",
                    "clinical_significance": "Pathogenic",
                    "review_status": "criteria provided, multiple submitters, no conflicts"
                }
            ]
        }
    }


@pytest.fixture
def sample_phenotype_data():
    """Sample phenotype data."""
    return {
        "phenotype_related_to_disease": [
            {
                "hpo_id": "HP:0001250",
                "hpo_phenotype": "Seizures",
                "frequency": "Very frequent (99-80%)",
                "source": "ORPHANET"
            },
            {
                "hpo_id": "HP:0001252",
                "hpo_phenotype": "Muscular hypotonia",
                "frequency": "Frequent (79-30%)",
                "source": "ORPHANET"
            }
        ]
    }


@pytest.fixture
def sample_clinical_data():
    """Sample clinical data."""
    return {
        "diagnostic_criteria": "Clinical diagnosis based on...",
        "treatment": [
            {
                "name": "Symptomatic treatment",
                "description": "Management of symptoms"
            }
        ],
        "prognosis": "Variable depending on severity"
    }


@pytest.fixture
def sample_gwas_data():
    """Sample GWAS data."""
    return {
        "gwas_catalog": [
            {
                "rsid": "rs12345678",
                "p_value": "1.2e-10",
                "risk_allele": "A",
                "odds_ratio": 1.25,
                "trait": "Type 2 diabetes",
                "pubmed_id": "30297969",
                "sample_size": "50000",
                "ancestry": "European"
            }
        ]
    }


@pytest.fixture
def sample_pathway_data():
    """Sample pathway data."""
    return {
        "kegg_pathway": [
            {
                "id": "hsa04110",
                "name": "Cell cycle",
                "genes": ["TP53", "CDK1", "CDK2"]
            }
        ],
        "reactome_pathway": [
            {
                "id": "R-HSA-109582",
                "name": "Hemostasis"
            }
        ]
    }


@pytest.fixture
def sample_drug_data():
    """Sample drug data."""
    return {
        "drug": [
            {
                "name": "Riluzole",
                "drugbank_id": "DB00740",
                "status": "approved",
                "indication": "Treatment of amyotrophic lateral sclerosis"
            }
        ]
    }


@pytest.fixture
def sample_epidemiology_data():
    """Sample epidemiology data."""
    return {
        "prevalence": {
            "value": "1-9 / 100 000",
            "geographic": "Worldwide",
            "source": "ORPHANET"
        },
        "incidence": {
            "value": "0.38 per 100,000",
            "year": "2020",
            "region": "Europe"
        },
        "age_of_onset": ["Adult", "Elderly"]
    }


@pytest.fixture
def sample_ontology_data():
    """Sample ontology data."""
    return {
        "mondo": {
            "mondo": "MONDO:0007739",
            "label": "Huntington disease",
            "parents": [
                {
                    "id": "MONDO:0000001",
                    "label": "disease or disorder"
                }
            ],
            "children": []
        },
        "disease_ontology": {
            "doid": "DOID:12858",
            "name": "Huntington's disease"
        }
    }


@pytest.fixture
def sample_fields_metadata():
    """Sample available fields metadata."""
    return {
        "mondo.mondo": {
            "type": "string",
            "description": "MONDO disease ID"
        },
        "omim": {
            "type": "string",
            "description": "OMIM number"
        },
        "orphanet.id": {
            "type": "string",
            "description": "Orphanet ID"
        },
        "gene.symbol": {
            "type": "string",
            "description": "Gene symbol"
        },
        "prevalence": {
            "type": "object",
            "description": "Disease prevalence information"
        }
    }


@pytest.fixture
def sample_mapping_results():
    """Sample identifier mapping results."""
    return [
        {
            "_id": "MONDO:0007739",
            "found": True,
            "query": "143100",
            "mondo": {"mondo": "MONDO:0007739"},
            "orphanet": {"id": "ORPHA:399"},
            "name": "Huntington disease"
        }
    ]