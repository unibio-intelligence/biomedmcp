"""Synthetic search summaries; no experimental measurement or complex release."""

from copy import deepcopy

from interpro_helpers import protein

from biomedmcp.native.complexportal import protein_identity

IDENTITY = protein_identity(protein(), "P15056", 9606)


def complex_row(*, complex_id="CPX-1", identifier="P15056", taxon=9606, participant_taxon=9606):
    return {
        "complexAC": complex_id,
        "complexName": "Synthetic complex",
        "description": "Description mentions P15056; this alone does not establish membership.",
        "organismName": None if taxon is None else f"Synthetic organism; {taxon}",
        "predictedComplex": False,
        "interactors": [
            {
                "identifier": identifier,
                "interactorType": "protein",
                "organismName": None
                if participant_taxon is None
                else f"Synthetic organism; {participant_taxon}",
                "stochiometry": "minValue: 1, maxValue: 1",
            }
        ],
    }


def body(rows=None, *, total=None):
    rows = [complex_row()] if rows is None else rows
    return {
        "size": len(rows),
        "totalNumberOfResults": len(rows) if total is None else total,
        "elements": deepcopy(rows),
        "facets": None,
    }
