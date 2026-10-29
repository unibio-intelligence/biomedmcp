# tests/conftest.py
"""Shared test fixtures and configuration."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from mygene_mcp.client import MyGeneClient


@pytest.fixture
def mock_client():
    """Create a mock MyGene client."""
    client = MagicMock(spec=MyGeneClient)
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def sample_gene_hit():
    """Sample gene hit from query results."""
    return {
        "_id": "1017",
        "_score": 22.757837,
        "entrezgene": 1017,
        "name": "cyclin dependent kinase 2",
        "symbol": "CDK2",
        "taxid": 9606
    }


@pytest.fixture
def sample_gene_annotation():
    """Sample full gene annotation."""
    return {
        "_id": "1017",
        "entrezgene": 1017,
        "name": "cyclin dependent kinase 2",
        "symbol": "CDK2",
        "taxid": 9606,
        "type_of_gene": "protein-coding",
        "genomic_pos": {
            "chr": "12",
            "start": 55966769,
            "end": 55972784,
            "strand": 1
        },
        "refseq": {
            "genomic": ["NC_000012.12"],
            "rna": ["NM_001798.5", "NM_052827.4"],
            "protein": ["NP_001789.2", "NP_439892.2"]
        },
        "ensembl": {
            "gene": "ENSG00000123374",
            "transcript": ["ENST00000266970", "ENST00000354056"],
            "protein": ["ENSP00000266970", "ENSP00000346022"]
        }
    }


@pytest.fixture
def sample_batch_results():
    """Sample batch query results."""
    return [
        {
            "_id": "1017",
            "_score": 22.757837,
            "entrezgene": 1017,
            "name": "cyclin dependent kinase 2",
            "query": "CDK2",
            "symbol": "CDK2",
            "taxid": 9606,
            "found": True
        },
        {
            "_id": "7157",
            "_score": 22.757837,
            "entrezgene": 7157,
            "name": "tumor protein p53",
            "query": "TP53",
            "symbol": "TP53",
            "taxid": 9606,
            "found": True
        },
        {
            "query": "INVALID_GENE",
            "found": False
        }
    ]


@pytest.fixture
def sample_metadata():
    """Sample metadata response."""
    return {
        "app_revision": "abcd1234",
        "available_fields": ["entrezgene", "symbol", "name", "taxid"],
        "build_date": "2024-01-01",
        "build_version": "20240101",
        "genome_assembly": {
            "human": "GRCh38",
            "mouse": "GRCm39"
        },
        "stats": {
            "total": 20000000,
            "human": 40000,
            "mouse": 35000
        }
    }


@pytest.fixture
def sample_species_facets():
    """Sample species facets response."""
    return {
        "total": 100,
        "hits": [],
        "facets": {
            "taxid": {
                "terms": [
                    {"term": 9606, "count": 40000},
                    {"term": 10090, "count": 35000},
                    {"term": 10116, "count": 25000},
                    {"term": 7227, "count": 15000},
                    {"term": 6239, "count": 10000}
                ]
            }
        }
    }


@pytest.fixture
def sample_expression_data():
    """Sample expression data."""
    return {
        "hpa": {
            "tissue": [
                {"name": "brain", "level": "high"},
                {"name": "liver", "level": "medium"},
                {"name": "kidney", "level": "low"}
            ],
            "subcellular_location": ["nucleus", "cytoplasm"],
            "rna_tissue_specificity": {
                "specificity": "tissue enhanced",
                "distribution": "detected in all"
            }
        },
        "gtex": {
            "brain": 45.2,
            "liver": 23.8,
            "kidney": 12.5
        },
        "biogps": {
            "104": 1234.5,
            "105": 2345.6
        }
    }


@pytest.fixture
def sample_pathway_data():
    """Sample pathway data."""
    return {
        "kegg": [
            {"id": "hsa04110", "name": "Cell cycle"},
            {"id": "hsa04115", "name": "p53 signaling pathway"}
        ],
        "reactome": [
            {"id": "R-HSA-69278", "name": "Cell Cycle, Mitotic"},
            {"id": "R-HSA-69620", "name": "Cell Cycle Checkpoints"}
        ],
        "wikipathways": [
            {"id": "WP179", "name": "Cell cycle"}
        ]
    }


@pytest.fixture
def sample_go_data():
    """Sample GO annotation data."""
    return {
        "BP": [
            {
                "id": "GO:0006468",
                "term": "protein phosphorylation",
                "evidence": "IDA",
                "qualifier": [""],
                "pubmed": [12345678, 23456789]
            },
            {
                "id": "GO:0007049",
                "term": "cell cycle",
                "evidence": "TAS",
                "qualifier": [""]
            }
        ],
        "MF": [
            {
                "id": "GO:0004672",
                "term": "protein kinase activity",
                "evidence": "IDA",
                "qualifier": ["enables"]
            }
        ],
        "CC": [
            {
                "id": "GO:0005634",
                "term": "nucleus",
                "evidence": "IDA",
                "qualifier": ["located_in"]
            }
        ]
    }


@pytest.fixture
def sample_disease_data():
    """Sample disease association data."""
    return {
        "disgenet": {
            "diseases": [
                {
                    "disease_id": "C0006142",
                    "disease_name": "Breast Cancer",
                    "score": 0.9,
                    "source": "BEFREE",
                    "pmid": [12345678]
                },
                {
                    "disease_id": "C0029925",
                    "disease_name": "Ovarian Cancer",
                    "score": 0.85,
                    "source": "CURATED"
                }
            ]
        },
        "clinvar": {
            "rcv": [
                {
                    "accession": {"accession": "RCV000048420"},
                    "conditions": {
                        "name": "Hereditary breast and ovarian cancer syndrome",
                        "identifiers": [{"db": "MedGen", "value": "C2676676"}]
                    },
                    "clinical_significance": "Pathogenic",
                    "last_evaluated": "2023-06-01"
                }
            ]
        },
        "omim": {
            "omim_id": "114480",
            "name": "BREAST CANCER 1 GENE",
            "inheritance": "Autosomal dominant"
        }
    }


@pytest.fixture
def sample_chemical_data():
    """Sample chemical/drug interaction data."""
    return {
        "pharmgkb": {
            "chemical": [
                {
                    "name": "tamoxifen",
                    "id": "PA451581",
                    "type": "substrate"
                },
                {
                    "name": "paclitaxel",
                    "id": "PA450761",
                    "type": "substrate"
                }
            ]
        },
        "chembl": {
            "target_component": [
                {
                    "target_chembl_id": "CHEMBL1824",
                    "component_type": "PROTEIN",
                    "accession": "P11511"
                }
            ]
        },
        "drugbank": [
            {
                "id": "DB00675",
                "name": "tamoxifen",
                "groups": ["approved", "investigational"]
            }
        ]
    }


@pytest.fixture
def sample_variant_data():
    """Sample variant data."""
    return {
        "clinvar": {
            "rcv": [
                {
                    "accession": {"accession": "RCV000048420"},
                    "title": "NM_007294.3(BRCA1):c.5266dup (p.Gln1756fs)",
                    "clinical_significance": "Pathogenic",
                    "last_evaluated": "2023-06-01",
                    "review_status": "reviewed by expert panel",
                    "conditions": {
                        "name": "Hereditary breast and ovarian cancer syndrome"
                    },
                    "measure_set": {
                        "measure": {
                            "type": "Duplication",
                            "name": "c.5266dup"
                        }
                    }
                }
            ]
        },
        "snpeff": {
            "ann": [
                {
                    "effect": "frameshift_variant",
                    "putative_impact": "HIGH",
                    "gene_name": "BRCA1",
                    "feature_type": "transcript"
                }
            ]
        }
    }


@pytest.fixture
def sample_homology_data():
    """Sample homology data."""
    return {
        "homologene": {
            "id": 5276,
            "genes": [
                [9606, 672],    # Human BRCA1
                [10090, 12189], # Mouse Brca1
                [10116, 497672] # Rat Brca1
            ]
        },
        "ensembl": {
            "homologene": [
                {
                    "id": "ENSMUSG00000017146",
                    "species": "mouse",
                    "type": "ortholog_one2one"
                }
            ]
        },
        "pantherdb": {
            "ortholog": [
                {
                    "id": "PTHR13763:SF184",
                    "species": "MOUSE"
                }
            ]
        }
    }