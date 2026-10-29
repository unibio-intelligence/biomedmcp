"""Synthetic gnomAD measurements conforming to the dated official selection."""

from copy import deepcopy

IDENTITY = {
    "chromosome": "7",
    "position": 140753336,
    "reference": "A",
    "alternate": "T",
    "assembly": "grch38",
}
GENE_ID = "ENSG00000157764"
GENE_IDENTITY = {"symbol": "BRAF", "entrez_id": "673", "ensembl_ids": [GENE_ID], "species": 9606}


def frequency(ac=2, an=100):
    return {
        "ac": ac,
        "an": an,
        "homozygote_count": 0,
        "hemizygote_count": 0,
        "filters": [],
        "populations": [{"id": "afr", "ac": ac, "an": an, "homozygote_count": 0, "hemizygote_count": 0}],
    }


def population():
    return {
        "data": {
            "variant": {
                "variant_id": "7-140753336-A-T",
                "reference_genome": "GRCh38",
                "chrom": "7",
                "pos": 140753336,
                "ref": "A",
                "alt": "T",
                "exome": frequency(),
                "genome": frequency(),
                "joint": frequency(),
            }
        }
    }


def constraint():
    return {
        "data": {
            "gene": {
                "gene_id": GENE_ID,
                "symbol": "BRAF",
                "ncbi_id": "673",
                "reference_genome": "GRCh38",
                "canonical_transcript_id": "ENST00000288602",
                "mane_select_transcript": None,
                "gnomad_constraint": {
                    "pli": 0.9,
                    "oe_lof_upper": 0.2,
                    "mis_z": -1.2,
                    "syn_z": 0.2,
                    "flags": [],
                },
            }
        }
    }


def clone(value):
    return deepcopy(value)
