from copy import deepcopy

ASSOCIATION = {
    "association_id": 123,
    "accession_id": "GCST123456",
    "p_value": 1e-8,
    "pvalue_mantissa": 1,
    "pvalue_exponent": -8,
    "multi_snp_haplotype": False,
    "snp_interaction": False,
    "snp_allele": [{"rs_id": "rs7412", "effect_allele": "T"}],
    "efo_traits": [{"efo_id": "EFO_0000001", "efo_trait": "Synthetic trait"}],
    "bg_efo_traits": [],
    "reported_trait": ["Synthetic trait"],
    "mapped_genes": ["BRAF"],
    "locations": ["7:140000000"],
    "risk_frequency": "NR",
}


def row(identity=123, **updates):
    return deepcopy(ASSOCIATION) | {"association_id": identity} | updates


def page(rows=None, *, total=None, size=10, number=0):
    rows = [row()] if rows is None else rows
    total = len(rows) if total is None else total
    result = {
        "page": {
            "size": size,
            "totalElements": total,
            "totalPages": (total + size - 1) // size,
            "number": number,
        }
    }
    if rows:
        result["_embedded"] = {"associations": rows}
    return result
