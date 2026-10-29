"""Synthetic ClinicalTrials.gov records and dated documented request checks."""

from copy import deepcopy

STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT04368728", "briefTitle": "Synthetic vaccine trial"},
        "statusModule": {"overallStatus": "COMPLETED"},
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE2", "PHASE3"],
            "enrollmentInfo": {"count": 100, "type": "ACTUAL"},
        },
        "conditionsModule": {"conditions": ["COVID-19"]},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Synthetic sponsor", "class": "INDUSTRY"}},
        "eligibilityModule": {
            "sex": "ALL",
            "stdAges": ["ADULT"],
            "eligibilityCriteria": "Synthetic eligibility",
        },
        "contactsLocationsModule": {
            "locations": [{"facility": "Synthetic site", "country": "United States"}]
        },
        "outcomesModule": {"primaryOutcomes": [{"measure": "Synthetic endpoint", "timeFrame": "1 year"}]},
        "armsInterventionsModule": {"interventions": [{"type": "BIOLOGICAL", "name": "Synthetic vaccine"}]},
        "referencesModule": {
            "references": [{"pmid": "123", "type": "RESULT", "citation": "Synthetic reference"}]
        },
    },
    "hasResults": False,
}
REQUEST_FIELDS = {
    "format",
    "markupFormat",
    "query.cond",
    "query.term",
    "query.locn",
    "query.titles",
    "query.intr",
    "query.outc",
    "query.spons",
    "query.lead",
    "query.id",
    "query.patient",
    "filter.overallStatus",
    "filter.geo",
    "filter.ids",
    "filter.advanced",
    "filter.synonyms",
    "postFilter.overallStatus",
    "postFilter.geo",
    "postFilter.ids",
    "postFilter.advanced",
    "postFilter.synonyms",
    "aggFilters",
    "geoDecay",
    "fields",
    "sort",
    "countTotal",
    "pageSize",
    "pageToken",
}


def study(nct_id="NCT04368728"):
    row = deepcopy(STUDY)
    row["protocolSection"]["identificationModule"]["nctId"] = nct_id
    return row


def documented_request(request):
    assert request.url.host == "clinicaltrials.gov" and request.method == "GET"
    if request.url.path == "/api/v2/studies":
        assert set(request.url.params) <= REQUEST_FIELDS
        assert 1 <= int(request.url.params.get("pageSize", 10)) <= 100
    else:
        assert request.url.path.startswith("/api/v2/studies/NCT")
        assert set(request.url.params) <= {"fields", "format", "markupFormat"}
    if "fields" in request.url.params:
        assert "/" not in request.url.params["fields"]
