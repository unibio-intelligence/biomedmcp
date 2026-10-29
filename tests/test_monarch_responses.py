"""Current Monarch direct-association contracts and evidence preservation."""

from copy import deepcopy

import pytest
from native_helpers import HTTP

from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService


def association(section="genes", **changes):
    categories = {
        "genes": "biolink:CorrelatedGeneToDiseaseAssociation",
        "phenotypes": "biolink:DiseaseToPhenotypicFeatureAssociation",
        "models": "biolink:GenotypeToDiseaseAssociation",
    }
    row = {
        "id": "synthetic-association",
        "subject": "HGNC:1097",
        "object": "MONDO:0005105",
        "subject_category": "biolink:Gene",
        "object_category": "biolink:Disease",
        "category": categories[section],
        "predicate": "biolink:gene_associated_with_condition",
        "primary_knowledge_source": "infores:synthetic",
        "publications": ["PMID:1"],
        "subject_taxon": "NCBITaxon:9606",
    }
    if section == "phenotypes":
        row.update(
            subject="MONDO:0005105",
            object="HP:0001250",
            subject_category="biolink:Disease",
            object_category="biolink:PhenotypicFeature",
            predicate="biolink:has_phenotype",
        )
    if section == "models":
        row.update(
            subject="MGI:1",
            subject_category="biolink:Genotype",
            predicate="biolink:model_of",
            subject_taxon="NCBITaxon:10090",
        )
    return {**row, **changes}


async def disease_result(payload, section="genes"):
    http = HTTP(payload)
    value = await ResearchService(http=http).get(
        GetRequest(entity="disease", id="MONDO:0005105", sections=[section]), scope="audit"
    )
    return value, http


@pytest.mark.parametrize("section", ["genes", "phenotypes", "models"])
async def test_monarch_current_categories_preserve_identity_and_evidence(section):
    row = association(section)
    value, http = await disease_result({"items": [row], "total": 1, "limit": 25, "offset": 0}, section)
    assert value.sections[section].outcome == "data"
    assert value.sections[section].data["records"] == [row]
    params = http.calls[0][2]["params"]
    assert params["direct"] is True and params["limit"] == 25
    if section == "genes":
        assert set(params["category"]) == {
            "biolink:CausalGeneToDiseaseAssociation",
            "biolink:CorrelatedGeneToDiseaseAssociation",
        }
    if section == "models":
        assert params["predicate"] == "biolink:model_of"
    assert value.provenance[0].source == "monarch"


@pytest.mark.parametrize("section", ["genes", "phenotypes", "models"])
async def test_monarch_explicit_empty_is_valid_but_missing_collection_is_failure(section):
    value, _ = await disease_result({"items": [], "total": 0, "limit": 25, "offset": 0}, section)
    assert value.sections[section].outcome == "empty"
    value, _ = await disease_result({"total": 0}, section)
    assert value.sections[section].error["code"] == "invalid_source_response"


@pytest.mark.parametrize(
    "change",
    [
        {"object": "MONDO:999"},
        {"subject": {}},
        {"subject_category": "biolink:Protein"},
        {"category": "biolink:GenotypeToDiseaseAssociation"},
        {"predicate": None},
        {"id": ""},
    ],
)
async def test_monarch_incorrect_identity_or_category_never_becomes_evidence(change):
    value, _ = await disease_result({"items": [association(**change)], "total": 1, "limit": 25, "offset": 0})
    assert value.sections["genes"].error["code"] == "invalid_source_response"
    assert not value.sections["genes"].evidence_ids


@pytest.mark.parametrize(
    "payload",
    [
        {"items": [], "total": -1, "limit": 25, "offset": 0},
        {"items": [], "total": True, "limit": 25, "offset": 0},
        {"items": [], "total": 0, "limit": 25, "offset": 1},
        {"items": [association()], "total": 0, "limit": 25, "offset": 0},
    ],
)
async def test_monarch_invalid_window_metadata_is_not_empty_success(payload):
    value, _ = await disease_result(deepcopy(payload))
    assert value.sections["genes"].error["code"] == "invalid_source_response"


async def test_monarch_bounded_window_preserves_total_and_partial_coverage():
    value, _ = await disease_result({"items": [association()], "total": 50, "limit": 25, "offset": 0})
    section = value.sections["genes"]
    assert section.outcome == "partial" and section.data["total"] == 50
    assert not section.data["complete"] and section.data["records"]
    assert "Partial source sections: coverage" in section.warnings


async def test_monarch_model_route_rejects_non_model_associations():
    value, _ = await disease_result(
        {
            "items": [association("models", predicate="biolink:associated_with")],
            "total": 1,
            "limit": 25,
            "offset": 0,
        },
        "models",
    )
    assert value.sections["models"].error["code"] == "invalid_source_response"


async def test_old_monarch_cache_cannot_bypass_direct_identity_validation():
    from biomedmcp.native import REVISION
    from biomedmcp.runtime import ProviderRuntime

    runtime = ProviderRuntime()
    request = GetRequest(entity="disease", id="MONDO:0005105", sections=["phenotypes"])

    async def legacy_payload():
        return [association("phenotypes", subject="MONDO:9999999")]

    await runtime.invoke(
        "monarch",
        {
            "operation": "get:phenotypes",
            "params": request.model_dump(mode="json"),
            "version": None,
            "implementation": REVISION,
        },
        legacy_payload,
        scope="audit",
    )
    row = association("phenotypes")
    http = HTTP({"items": [row], "total": 1, "limit": 25, "offset": 0})
    service = ResearchService(runtime=runtime, http=http)
    result = await service.get(request, scope="audit")
    assert len(http.calls) == 1
    assert result.sections["phenotypes"].data["records"] == [row]
    assert result.provenance[0].cached is False
    repeated = await service.get(request, scope="audit")
    assert len(http.calls) == 1 and repeated.provenance[0].cached is True
