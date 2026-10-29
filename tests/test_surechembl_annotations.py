"""Derived patent annotation projections exclude raw text and retain missingness."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions
ID = "US-9095515-B2"


def document():
    annotation = {
        "start": 0,
        "end": 2,
        "category": "chemical",
        "chemicalIds": [2871, 10869],
        "globalFrequency": 19604,
        "matchedText": "unreleased-matched-text",
    }
    section = {
        "lang": "EN",
        "mxwid": "section-1",
        "section": {"content": "😀unreleased-source-html", "annotations": [annotation]},
    }
    return {
        "status": "OK",
        "data": {
            "doc_id": ID,
            "doc_version": 1,
            "contents": {
                "patentDocument": {
                    "abstracts": [section],
                    "descriptions": [],
                    "claimResponses": [],
                    "copyright": "unreleased-copyright-text",
                }
            },
        },
    }


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def install(payload=None, normalization=None):
        calls = []

        def handler(request):
            calls.append(request)
            value = (
                normalization or {"status": "OK", "data": {"US9095515B2": [ID]}}
                if "normalized" in request.url.path
                else document()
                if payload is None
                else payload
            )
            return httpx.Response(
                200,
                content=json.dumps(deepcopy(value), ensure_ascii=True).encode("ascii"),
                headers={"Content-Type": "application/json"},
            )

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return calls

    return install


@pytest.mark.parametrize("mode", ["annotations", "categories", "frequency"])
async def test_current_document_projection_counts_and_input_locators(wire, mode):
    calls = wire()
    result = await SourceAdapters().call(
        "surechembl", "analyze_patent_chemistry", {"patent_number": "US9095515B2", "analysis_type": mode}
    )
    assert calls[0].url.path.endswith("/identifier/normalized/US9095515B2")
    assert calls[1].url.path == f"/api/document/{ID}/contents" and calls[1].url.params["annotated"] == "true"
    assert result["publication_id"] == ID and result["requested_publication"] == "US9095515B2"
    assert "unreleased" not in str(result) and "patentDocument" not in str(result)
    assert result["source_document_version"] == "1"
    assert result["records"][0]["chemical_mapping_status"] == "multiple_source_identifiers"
    assert result["records"][0]["source_annotation_global_frequency"] == 19604
    assert (
        result["denominator"]["chemical_occurrences"] == 1
        and result["denominator"]["chemical_mapping_multiple_ids"] == 1
    )
    assert result["position_units"].startswith("JavaScript UTF-16")
    assert result["coverage"]["whole_document_chemistry_exhaustive"] is False
    if mode == "categories":
        assert result["category_counts"][0]["count"] == 1
        assert result["category_counts"][0]["input_locators"] == ["/records/0/category"]
    elif mode == "frequency":
        assert [r["membership_count"] for r in result["chemical_identifier_memberships"]] == [1, 1]
        assert all(
            r["input_locators"] == ["/records/0/chemical_ids"]
            for r in result["chemical_identifier_memberships"]
        )


async def test_missing_annotation_field_is_partial_not_zero(wire):
    payload = document()
    payload["data"]["contents"]["patentDocument"]["abstracts"][0]["section"].pop("annotations")
    wire(payload)
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "surechembl",
                    "operation": "analyze_patent_chemistry",
                    "params": {"patent_number": ID},
                },
            )
        ).data
    assert result["outcome"] == "partial" and result["provenance"]
    section = result["sections"]["surechembl"]["data"]["sections"][0]
    assert section["annotation_status"] == "not_reported" and section["annotation_count"] is None


async def test_present_empty_annotations_are_source_negative_only_in_selected_sections(wire):
    payload = document()
    payload["data"]["contents"]["patentDocument"]["abstracts"][0]["section"]["annotations"] = []
    wire(payload)
    result = await SourceAdapters().call("surechembl", "analyze_patent_chemistry", {"patent_number": ID})
    assert result["sections"][0]["annotation_status"] == "reported"
    assert result["sections"][0]["annotation_count"] == 0 and result["denominator"]["acquired"] == 0
    assert not result["coverage"]["whole_document_chemistry_exhaustive"]


@pytest.mark.parametrize(
    "mutation",
    [
        "identity",
        "missing_contents",
        "bad_sections",
        "missing_section",
        "wrong_annotations",
        "negative_start",
        "empty_interval",
        "beyond_utf16",
        "category",
        "bad_ids",
        "duplicate_ids",
        "frequency_bool",
        "language",
        "version_bool",
        "bad_unicode",
    ],
)
async def test_present_source_shape_validated_before_projection(wire, mutation):
    payload = document()
    data = payload["data"]
    source = data["contents"]["patentDocument"]
    section = source["abstracts"][0]["section"]
    annotation = section["annotations"][0]
    if mutation == "identity":
        data["doc_id"] = "US-123-A1"
    elif mutation == "missing_contents":
        data.pop("contents")
    elif mutation == "bad_sections":
        source["descriptions"] = None
    elif mutation == "missing_section":
        source["abstracts"][0].pop("section")
    elif mutation == "wrong_annotations":
        section["annotations"] = None
    elif mutation == "negative_start":
        annotation["start"] = -1
    elif mutation == "empty_interval":
        annotation["end"] = 0
    elif mutation == "beyond_utf16":
        annotation["end"] = 1000
    elif mutation == "category":
        annotation["category"] = True
    elif mutation == "bad_ids":
        annotation["chemicalIds"] = [True]
    elif mutation == "duplicate_ids":
        annotation["chemicalIds"] = [2871, 2871]
    elif mutation == "frequency_bool":
        annotation["globalFrequency"] = True
    elif mutation == "language":
        source["abstracts"][0]["lang"] = 42
    elif mutation == "version_bool":
        data["doc_version"] = True
    else:
        section["content"] = "\ud800"
    wire(payload)
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "analyze_patent_chemistry", {"patent_number": ID})
    assert caught.value.code in {"invalid_source_response", "identity_mismatch"}
    assert "unreleased" not in str(caught.value)


async def test_missing_chemical_mapping_remains_unknown(wire):
    payload = document()
    payload["data"]["contents"]["patentDocument"]["abstracts"][0]["section"]["annotations"][0].pop(
        "chemicalIds"
    )
    wire(payload)
    result = await SourceAdapters().call(
        "surechembl", "analyze_patent_chemistry", {"patent_number": ID, "analysis_type": "frequency"}
    )
    assert result["records"][0]["chemical_ids"] is None
    assert result["denominator"]["chemical_mapping_missing"] == 1
    assert result["chemical_identifier_memberships"] == []
    assert result["section_outcomes"]["chemical_mapping"]["outcome"] == "partial"


async def test_ambiguous_normalization_never_selects_first(wire):
    calls = wire(normalization={"status": "OK", "data": {"US9095515B2": [ID, "US-123-A1"]}})
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call(
            "surechembl", "analyze_patent_chemistry", {"patent_number": "US9095515B2"}
        )
    assert caught.value.code == "ambiguous_identity" and len(calls) == 1


@pytest.mark.parametrize(
    "identifier", ["../../private", "US-123-A1?api_key=secret", "us9095515b2", "x" * 100]
)
async def test_invalid_document_path_preflight(wire, identifier):
    calls = wire()
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("surechembl", "analyze_patent_chemistry", {"patent_number": identifier})
    assert caught.value.code == "invalid_parameters" and calls == []
