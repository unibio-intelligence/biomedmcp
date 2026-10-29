"""Synthetic ClinGen shapes based on the separate primary-contract inspection."""


def envelope(data, code=200):
    return {"data": data, "metadata": {}, "status": {"code": code, "name": "OK" if code == 200 else "Error"}}


def allele(protein=False):
    prefix, kind, field = (
        ("PA", "amino-acid", "aminoAcidAlleles") if protein else ("CA", "nucleotide", "genomicAlleles")
    )
    return {
        "@id": f"http://reg.genome.network/allele/{prefix}1",
        "type": kind,
        field: [{"hgvs": ["NP_004324.2:p.Val600Glu" if protein else "NC_000007.14:g.140753336A>T"]}],
    }


ASSERTION = {
    "caId": "CA1",
    "classification": "Pathogenic",
    "ep": "Synthetic panel",
    "uuid": "synthetic-1",
    "docVersion": "1.0",
}
SPECIFICATION = {
    "@id": "https://cspec.genome.network/cspec/SequenceVariantInterpretation/id/GN001/version/1.0"
}
LINK = {"entType": "CivicEvidence", "entId": "synthetic-1", "ldhId": "1"}
