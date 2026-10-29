"""Synthetic selected InterPro projection; never a biological measurement."""

from copy import deepcopy

IDENTITY = {"accession": "P15056", "length": 766, "species": 9606}


def entry(*, accession="IPR000719", kind="domain", fragments=None):
    return {
        "metadata": {
            "accession": accession,
            "name": "Synthetic entry",
            "type": kind,
            "source_database": "interpro",
            "integrated": None,
            "member_databases": {"pfam": {"PF00069": "Synthetic member"}},
            "go_terms": [
                {
                    "identifier": "GO:0005524",
                    "name": "Synthetic term",
                    "category": {"code": "F", "name": "molecular_function"},
                }
            ],
        },
        "proteins": [
            {
                "accession": "p15056",
                "protein_length": 766,
                "organism": "9606",
                "source_database": "reviewed",
                "in_alphafold": True,
                "entry_protein_locations": [
                    {
                        "fragments": fragments or [{"start": 457, "end": 717, "dc-status": "CONTINUOUS"}],
                        "representative": False,
                        "model": None,
                        "score": None,
                    }
                ],
            }
        ],
    }


def body(rows=None, *, count=None, after=None, limit=25):
    rows = [entry()] if rows is None else rows
    return {
        "count": len(rows) if count is None else count,
        "results": deepcopy(rows),
        "next": None
        if after is None
        else f"https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?page_size={limit}&cursor={after}",
        "previous": None,
    }


def response(value=None, *, status=200, release="110.0"):
    return {
        "status": status,
        "headers": {"interpro-version": release},
        "body": body() if value is None and status == 200 else deepcopy(value),
    }


def protein():
    from test_uniprot_responses import PROTEIN

    return deepcopy(PROTEIN) | {
        "sequence": {"value": "A" * 599 + "V" + "A" * 166, "length": 766, "molWeight": 80000},
        "uniProtKBCrossReferences": [
            {"database": "PDB", "id": "1ABC", "properties": [{"key": "Chains", "value": "A=500-700"}]}
        ],
    }
