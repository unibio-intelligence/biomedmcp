"""Synthetic CIViC fields independently conforming to the official schema."""

from copy import deepcopy

SOURCE = {
    "id": 123,
    "citation": "Synthetic citation",
    "sourceType": "PUBMED",
    "publicationYear": 2024,
    "sourceUrl": "https://pubmed.ncbi.nlm.nih.gov/123/",
    "retracted": False,
    "link": "https://civicdb.org/links/sources/123",
}
PROFILE = {
    "id": 10,
    "name": "BRAF V600E",
    "deprecated": False,
    "isComplex": False,
    "isMultiVariant": False,
    "variants": [
        {
            "__typename": "Variant",
            "id": 1,
            "name": "V600E",
            "feature": {
                "id": 1,
                "name": "BRAF",
                "featureType": "GENE",
                "featureInstance": {"__typename": "Gene", "name": "BRAF", "entrezId": 673},
            },
        }
    ],
}
DISEASE = {"id": 1, "name": "melanoma", "displayName": "melanoma"}
THERAPY = {"id": 1, "name": "imatinib"}
EVIDENCE = {
    "id": 1,
    "name": "EID1",
    "link": "https://civicdb.org/links/evidence/1",
    "description": "Synthetic directional evidence",
    "evidenceType": "PREDICTIVE",
    "evidenceLevel": "B",
    "evidenceDirection": "SUPPORTS",
    "significance": "SENSITIVITYRESPONSE",
    "status": "ACCEPTED",
    "molecularProfile": PROFILE,
    "disease": DISEASE,
    "therapies": [THERAPY],
    "source": SOURCE,
}
ASSERTION = {
    "id": 1,
    "name": "AID1",
    "link": "https://civicdb.org/links/assertions/1",
    "assertionType": "PREDICTIVE",
    "assertionDirection": "SUPPORTS",
    "ampLevel": "TIER_I_LEVEL_A",
    "significance": "SENSITIVITYRESPONSE",
    "status": "ACCEPTED",
    "summary": "Synthetic assertion",
    "molecularProfile": PROFILE,
    "disease": DISEASE,
    "therapies": [THERAPY],
}


def connection(rows=(), *, total=None, more=False, cursor=None):
    return {
        "nodes": deepcopy(list(rows)),
        "totalCount": len(rows) if total is None else total,
        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
    }


def response(evidence=(EVIDENCE,), assertions=(ASSERTION,)):
    return {"data": {"evidenceItems": connection(evidence), "assertions": connection(assertions)}}
