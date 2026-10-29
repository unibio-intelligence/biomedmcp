"""Synthetic STRING network rows; no claim about live provider health."""


def edge(species=9606, **changes):
    return {
        "stringId_A": f"{species}.ENSP00000288602",
        "stringId_B": f"{species}.ENSP00000275493",
        "preferredName_A": "BRAF" if species == 9606 else "Braf",
        "preferredName_B": "EGFR" if species == 9606 else "Egfr",
        "ncbiTaxonId": species,
        "score": 0.8,
        **dict.fromkeys(("nscore", "fscore", "pscore", "ascore", "escore", "dscore", "tscore"), 0.0),
        **changes,
    }
