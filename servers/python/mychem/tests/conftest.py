# tests/conftest.py
"""Shared test fixtures and configuration."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import os
from datetime import datetime, timedelta

# Add the src directory to Python path for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mychem_mcp.client import MyChemClient, CacheEntry


@pytest.fixture
def mock_client():
    """Create a mock MyChem client."""
    client = MagicMock(spec=MyChemClient)
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def real_client():
    """Create a real client instance for testing caching."""
    return MyChemClient(cache_enabled=True, cache_ttl=60)


@pytest.fixture
def sample_chemical_hit():
    """Sample chemical hit from query results."""
    return {
        "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "_score": 22.757837,
        "pubchem": {
            "cid": 2244,
            "smiles": {"canonical": "CC(=O)OC1=CC=CC=C1C(=O)O"}
        },
        "chembl": {
            "molecule_chembl_id": "CHEMBL25"
        },
        "drugbank": {
            "id": "DB00945",
            "name": "Aspirin"
        },
        "name": "Aspirin"
    }


@pytest.fixture
def sample_chemical_annotation():
    """Sample full chemical annotation."""
    return {
        "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "pubchem": {
            "cid": 2244,
            "molecular_formula": "C9H8O4",
            "molecular_weight": 180.16,
            "smiles": {
                "canonical": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "isomeric": "CC(=O)OC1=CC=CC=C1C(=O)O"
            },
            "inchi": "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)",
            "inchikey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        },
        "chembl": {
            "molecule_chembl_id": "CHEMBL25",
            "molecule_type": "Small molecule",
            "max_phase": 4
        },
        "drugbank": {
            "id": "DB00945",
            "name": "Aspirin",
            "groups": ["approved", "vet_approved"],
            "categories": ["Anti-Inflammatory Agents", "Platelet Aggregation Inhibitors"]
        }
    }


@pytest.fixture
def sample_batch_results():
    """Sample batch query results."""
    return [
        {
            "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "_score": 22.757837,
            "query": "aspirin",
            "found": True,
            "pubchem": {"cid": 2244},
            "name": "Aspirin"
        },
        {
            "_id": "HEFNNWSXXWATRW-UHFFFAOYSA-N",
            "_score": 22.757837,
            "query": "ibuprofen",
            "found": True,
            "pubchem": {"cid": 3672},
            "name": "Ibuprofen"
        },
        {
            "query": "INVALID_CHEMICAL",
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
            "total": 150000000
        },
        "src": {
            "chembl": {
                "version": "33",
                "stats": {"total": 2300000}
            },
            "drugbank": {
                "version": "5.1.10",
                "stats": {"total": 15000}
            },
            "pubchem": {
                "version": "2024.01.01",
                "stats": {"total": 110000000}
            }
        }
    }


@pytest.fixture
def sample_drug_interactions():
    """Sample drug interaction data."""
    return {
        "drugbank": {
            "drug_interactions": [
                {
                    "name": "Warfarin",
                    "drugbank-id": "DB00682",
                    "description": "The risk or severity of bleeding can be increased when Aspirin is combined with Warfarin."
                },
                {
                    "name": "Methotrexate",
                    "drugbank-id": "DB00563",
                    "description": "The excretion of Methotrexate can be decreased when combined with Aspirin."
                }
            ]
        }
    }


@pytest.fixture
def sample_structure_data():
    """Sample chemical structure data."""
    return {
        "_id": "RYYVLZVUVIJVGH-UHFFFAOYSA-N",
        "pubchem": {
            "smiles": {
                "canonical": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
                "isomeric": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
            },
            "inchi": "InChI=1S/C8H10N4O2/c1-10-4-9-6-5(10)7(13)12(3)8(14)11(6)2/h4H,1-3H3",
            "inchikey": "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
        },
        "chembl": {
            "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
            "inchi": "InChI=1S/C8H10N4O2/c1-10-4-9-6-5(10)7(13)12(3)8(14)11(6)2/h4H,1-3H3",
            "inchikey": "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
        }
    }


@pytest.fixture
def sample_admet_data():
    """Sample ADMET properties data."""
    return {
        "chembl": {
            "absorption": {
                "bioavailability": "High",
                "caco2_permeability": "Positive"
            },
            "distribution": {
                "vd": "0.15 L/kg",
                "protein_binding": "99%"
            },
            "metabolism": {
                "cyp_substrate": ["CYP2C9", "CYP3A4"],
                "cyp_inhibitor": ["CYP2C19"]
            },
            "excretion": {
                "half_life": "15-20 min",
                "clearance": "High"
            },
            "toxicity": {
                "ld50": "200 mg/kg (oral, rat)",
                "class": "Category 3"
            }
        },
        "drugbank": {
            "absorption": "Absorption is generally rapid and complete following oral administration.",
            "metabolism": "Aspirin is rapidly hydrolyzed in the plasma to salicylic acid.",
            "toxicity": "The toxic dose of aspirin is generally considered greater than 150 mg per kg of body mass."
        },
        "pubchem": {
            "molecular_weight": 180.16,
            "logp": 1.2,
            "tpsa": 63.6
        }
    }


@pytest.fixture
def sample_clinical_trials():
    """Sample clinical trials data."""
    return {
        "drugbank": {
            "clinical_trials": [
                {
                    "nct_id": "NCT01234567",
                    "title": "Aspirin for Primary Prevention of Cardiovascular Events",
                    "phase": "Phase 3",
                    "status": "Completed"
                },
                {
                    "nct_id": "NCT02345678",
                    "title": "Low-Dose Aspirin in Cancer Prevention",
                    "phase": "Phase 2",
                    "status": "Active"
                }
            ]
        }
    }


@pytest.fixture
def sample_patent_data():
    """Sample patent data."""
    return {
        "pharmgkb": {
            "patent": ["US1234567", "EP9876543"]
        },
        "drugbank": {
            "patents": [
                {
                    "number": "US6737045",
                    "country": "United States",
                    "approved": "2004-05-18",
                    "expires": "2024-05-18"
                }
            ]
        }
    }


@pytest.fixture
def sample_fda_approval():
    """Sample FDA approval data."""
    return {
        "drugbank": {
            "fda_approval": "1950-06-12",
            "fda_label": "https://www.accessdata.fda.gov/drugsatfda_docs/label/aspirin.pdf"
        },
        "chembl": {
            "max_phase": 4
        }
    }


@pytest.fixture
def sample_fields_metadata():
    """Sample available fields metadata."""
    return {
        "pubchem.cid": {
            "type": "integer",
            "description": "PubChem Compound ID"
        },
        "chembl.molecule_chembl_id": {
            "type": "string",
            "description": "ChEMBL molecule ID"
        },
        "drugbank.id": {
            "type": "string",
            "description": "DrugBank ID"
        },
        "pubchem.smiles.canonical": {
            "type": "string",
            "description": "Canonical SMILES representation"
        },
        "chembl.max_phase": {
            "type": "integer",
            "description": "Maximum phase of drug development"
        }
    }


@pytest.fixture
def sample_mapping_results():
    """Sample identifier mapping results."""
    return [
        {
            "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "found": True,
            "query": "aspirin",
            "pubchem": {"cid": 2244},
            "chembl": {"molecule_chembl_id": "CHEMBL25"},
            "drugbank": {"id": "DB00945"}
        }
    ]


@pytest.fixture
def sample_bioactivity_data():
    """Sample bioactivity data."""
    return {
        "chembl": {
            "activities": [
                {
                    "assay_chembl_id": "CHEMBL123456",
                    "target_pref_name": "Cyclooxygenase-2",
                    "target_type": "SINGLE PROTEIN",
                    "standard_type": "IC50",
                    "standard_value": "50",
                    "standard_units": "nM",
                    "standard_relation": "=",
                    "activity_comment": "Active"
                }
            ]
        },
        "pubchem": {
            "bioassays": [
                {
                    "aid": 504466,
                    "name": "COX-2 Inhibition Assay",
                    "activity_outcome": "Active",
                    "assay_type": "Confirmatory"
                }
            ]
        }
    }


@pytest.fixture
def sample_pathway_data():
    """Sample pathway association data."""
    return {
        "pharmgkb": {
            "pathways": [
                {
                    "id": "PA165111376",
                    "name": "Aspirin Pathway, Pharmacodynamics"
                }
            ]
        },
        "drugbank": {
            "pathways": [
                {
                    "name": "Arachidonic Acid Metabolism",
                    "category": "Metabolic"
                }
            ],
            "enzymes": [
                {
                    "name": "Prostaglandin G/H synthase 1",
                    "gene_name": "PTGS1",
                    "actions": ["inhibitor"]
                }
            ]
        }
    }


@pytest.fixture
def sample_disease_data():
    """Sample disease association data."""
    return {
        "drugbank": {
            "indication": "For the temporary relief of minor aches and pains.",
            "categories": ["Analgesics", "Anti-Inflammatory Agents"]
        },
        "chembl": {
            "indication_class": ["Analgesic", "Antipyretic", "Anti-inflammatory"]
        },
        "pharmgkb": {
            "diseases": [
                {
                    "id": "PA443440",
                    "name": "Pain"
                }
            ]
        }
    }


@pytest.fixture
def sample_structure_properties():
    """Sample structure properties data."""
    return {
        "pubchem": {
            "molecular_formula": "C9H8O4",
            "molecular_weight": 180.16,
            "xlogp": 1.2,
            "tpsa": 63.6,
            "complexity": 212,
            "h_bond_acceptor_count": 4,
            "h_bond_donor_count": 1,
            "rotatable_bond_count": 3,
            "heavy_atom_count": 13,
            "atom_stereo_count": 0
        },
        "chembl": {
            "ro3_pass": "Y",
            "num_ro5_violations": 0,
            "qed_weighted": 0.55,
            "aromatic_rings": 1
        }
    }