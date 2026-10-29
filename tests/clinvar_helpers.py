"""Synthetic single-allele ClinVar summary; not an observed clinical assertion."""

def variant():
    return {"uid": "13961", "accession_version": "VCV000013961.143", "variation_set": [{
        "variation_name": "NM_004333.6(BRAF):c.1799T>A (p.Val600Glu)",
        "variation_xrefs": [{"db_source": "dbSNP", "db_id": "113488022"}],
        "canonical_spdi": "NC_000007.14:140753335:A:T",
        "variation_loc": [{"assembly_name": "GRCh38", "chr": "7", "start": "140753336", "stop": "140753336"},
                          {"assembly_name": "GRCh37", "chr": "7", "start": "140453136", "stop": "140453136"}],
    }], "germline_classification": {"description": "Pathogenic", "review_status": "expert panel"},
       "clinical_impact_classification": {"description": "Tier I - Strong"},
       "oncogenicity_classification": {"description": "Oncogenic"}}
