"""HPO OLS search and exact-record contracts, including agent follow-up and cache behavior."""

from copy import deepcopy

import httpx
import pytest
from native_helpers import HTTP

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError
from biomedmcp.native.providers import NativeProviders

TERM_ID = "HP:0001250"
TERM = {
    "iri": "http://purl.obolibrary.org/obo/HP_0001250",
    "obo_id": TERM_ID,
    "short_form": "HP_0001250",
    "ontology_name": "hp",
    "ontology_prefix": "HP",
    "label": "Synthetic phenotype",
    "description": ["Synthetic ontology definition, not a clinical observation."],
    "is_obsolete": False,
    "is_defining_ontology": True,
    "term_replaced_by": None,
    "synonyms": ["Synthetic synonym"],
}


def search_page(rows=None, *, total=1, start=0):
    return {
        "response": {
            "docs": [deepcopy(TERM) | {"type": "class"}] if rows is None else rows,
            "numFound": total,
            "start": start,
        },
        "responseHeader": {"status": 0},
    }


def record_page(row=None):
    return {
        "_embedded": {"terms": [deepcopy(TERM) if row is None else row]},
        "page": {"size": 1, "totalElements": 1, "totalPages": 1, "number": 0},
    }


async def acquire(payload, mode, *, offset=0):
    provider = NativeProviders(SourceAdapters(), HTTP(payload))
    if mode == "search":
        return await provider.search("phenotype", "ols", "synthetic", {}, 2, offset)
    return await provider.record("phenotype", TERM_ID)


@pytest.mark.parametrize("mode", ["search", "record"])
@pytest.mark.parametrize(
    "payload", [{}, None, [], "broken", {"error": "ols-secret-sentinel"}, {"errors": ["ols-secret-sentinel"]}]
)
async def test_invalid_shapes_never_become_healthy_ontology_evidence(mode, payload):
    with pytest.raises(ResearchError) as caught:
        await acquire(payload, mode)
    assert caught.value.code == "invalid_source_response"
    assert "ols-secret-sentinel" not in str(caught.value)


@pytest.mark.parametrize("mode", ["search", "record"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("iri", None),
        ("iri", "https://exfil.invalid/HP_0001250"),
        ("obo_id", "MP:0001250"),
        ("obo_id", "HP:0001251"),
        ("short_form", "HP_0001251"),
        ("ontology_name", "mp"),
        ("ontology_prefix", "MP"),
        ("label", None),
        ("label", ""),
        ("description", "missing list"),
        ("description", [None]),
        ("synonyms", [123]),
        ("is_obsolete", "false"),
        ("is_defining_ontology", 1),
        ("term_replaced_by", []),
        ("annotation", []),
        ("obo_synonym", [None]),
        ("obo_definition_citation", [{"definition": 1}]),
        ("obo_xref", [{"id": 1}]),
    ],
)
async def test_identity_and_selected_nested_science_fields_are_validated(mode, field, value):
    row = deepcopy(TERM) | {field: value}
    payload = search_page([row | {"type": "class"}]) if mode == "search" else record_page(row)
    with pytest.raises(ResearchError) as caught:
        await acquire(payload, mode)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("mode", ["search", "record"])
async def test_populated_records_preserve_qualified_identity_and_raw_definitions(mode):
    row = deepcopy(TERM) | {
        "annotation": {"has_alternative_id": ["HP:0001275"]},
        "provider_uninterpreted": {"measurement": "unknown"},
    }
    result = await acquire(
        search_page([row | {"type": "class"}]) if mode == "search" else record_page(row), mode
    )
    normalized = result["records"][0] if mode == "search" else result
    assert normalized["id"] == TERM_ID and normalized["obo_id"] == TERM_ID
    assert normalized["description"] == TERM["description"]
    assert normalized["annotation"] == row["annotation"]
    assert normalized["provider_uninterpreted"] == row["provider_uninterpreted"]
    assert normalized["term_replaced_by"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"docs": None},
        {"docs": [{}]},
        {"numFound": None},
        {"numFound": True},
        {"numFound": "1"},
        {"numFound": -1},
        {"numFound": 0},
        {"start": 1},
        {"start": True},
        {"docs": []},
    ],
)
async def test_search_metadata_cannot_hide_malformed_or_nonadvancing_windows(patch):
    payload = search_page()
    payload["response"].update(patch)
    with pytest.raises(ResearchError) as caught:
        await acquire(payload, "search")
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("field", ["numFound", "start", "docs"])
async def test_search_requires_explicit_pagination_fields(field):
    payload = search_page()
    del payload["response"][field]
    with pytest.raises(ResearchError):
        await acquire(payload, "search")


@pytest.mark.parametrize("status", [1, True, "0", None])
async def test_non_success_search_header_is_not_evidence(status):
    payload = search_page()
    payload["responseHeader"]["status"] = status
    with pytest.raises(ResearchError):
        await acquire(payload, "search")


@pytest.mark.parametrize("rows,total,offset", [([], 0, 0), ([], 1, 1)])
async def test_explicit_empty_search_window_is_distinct_from_failed_lookup(rows, total, offset):
    result = await acquire(search_page(rows, total=total, start=offset), "search", offset=offset)
    assert result["records"] == []
    assert result["_provider_page"]["exhausted"] and result["_provider_page"]["total"] == total


@pytest.mark.parametrize(
    "patch",
    [
        {"size": True},
        {"totalElements": 0},
        {"totalElements": 2},
        {"totalPages": 2},
        {"number": 1},
        {"size": "1"},
    ],
)
async def test_exact_lookup_requires_one_complete_identity_qualified_record(patch):
    payload = record_page()
    payload["page"].update(patch)
    with pytest.raises(ResearchError):
        await acquire(payload, "record")


@pytest.mark.parametrize(
    "payload",
    [
        {"_embedded": {"terms": []}},
        {"_embedded": {"terms": []}, "page": {"size": 0, "totalElements": 0, "totalPages": 1, "number": 0}},
        {
            "_embedded": {"terms": [TERM, TERM]},
            "page": {"size": 2, "totalElements": 2, "totalPages": 1, "number": 0},
        },
        {"_embedded": None},
        {"_embedded": {"terms": None}},
        {"page": {"totalElements": 1}},
    ],
)
async def test_missing_ambiguous_and_empty_exact_records_fail_closed(payload):
    with pytest.raises(ResearchError):
        await acquire(payload, "record")


async def test_search_raw_id_is_separate_from_executable_hpo_id():
    row = deepcopy(TERM) | {"type": "class", "id": "hp+provider-internal-id"}
    result = await acquire(search_page([row]), "search")
    assert result["records"][0]["id"] == TERM_ID
    assert result["records"][0]["source_record_id"] == "hp+provider-internal-id"


async def test_obsolete_record_preserves_replacement_without_following_or_joining_it():
    row = deepcopy(TERM) | {
        "is_obsolete": True,
        "term_replaced_by": "http://purl.obolibrary.org/obo/HP_0001251",
    }
    result = await acquire(record_page(row), "record")
    assert result["id"] == TERM_ID and result["is_obsolete"] is True
    assert result["term_replaced_by"] == row["term_replaced_by"]


@pytest.mark.parametrize("mode", ["search", "get"])
async def test_actual_mcp_failed_result_is_uncached_then_success_has_attribution(monkeypatch, mode):
    from fastmcp import Client
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "search":
            assert request.url.params["ontology"] == "hp" and request.url.params["type"] == "class"
            assert request.url.params["local"] == "true"
        else:
            assert request.url.params["obo_id"] == TERM_ID
        return httpx.Response(
            200, json={} if len(calls) == 1 else search_page() if mode == "search" else record_page()
        )

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    params = (
        {"entity": "phenotype", "query": "synthetic", "limit": 2}
        if mode == "search"
        else {"entity": "phenotype", "id": TERM_ID}
    )
    async with Client(create_server(service=ResearchService())) as client:
        first = (await client.call_tool(mode, params, raise_on_error=False)).structured_content
        second = (await client.call_tool(mode, params)).data
        third = (await client.call_tool(mode, params)).data
    assert first["outcome"] == "error" and not first["provenance"]
    assert next(iter(first["sections"].values()))["error"]["code"] == "invalid_source_response"
    assert second["outcome"] == third["outcome"] == "data"
    assert second["provenance"][0]["source"] == "ols" and third["provenance"][0]["cached"]
    assert len(calls) == 2


async def test_actual_mcp_resolve_followup_uses_hpo_id_and_executes(monkeypatch):
    from fastmcp import Client
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=search_page())
        assert request.url.params["obo_id"] == TERM_ID
        return httpx.Response(200, json=record_page())

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    async with Client(create_server(service=ResearchService())) as client:
        resolved = (await client.call_tool("resolve", {"entity": "phenotype", "query": "synthetic"})).data
        action = resolved["next_actions"][0]
        assert action["tool"] == "get" and action["arguments"]["id"] == TERM_ID
        acquired = (await client.call_tool(action["tool"], action["arguments"])).data
    assert acquired["outcome"] == "data" and acquired["sections"]["record"]["data"]["id"] == TERM_ID
    assert len(calls) == 2


@pytest.mark.parametrize(
    "row",
    [
        deepcopy(TERM) | {"type": "property"},
        deepcopy(TERM) | {"type": "class", "is_defining_ontology": False},
        deepcopy(TERM) | {"type": "class", "is_obsolete": True},
    ],
)
async def test_search_cannot_import_nondefining_obsolete_or_nonclass_matches(row):
    with pytest.raises(ResearchError):
        await acquire(search_page([row]), "search")


async def test_search_rejects_duplicate_and_overbudget_source_rows():
    row = deepcopy(TERM) | {"type": "class"}
    for rows in [[row, row], [row, row, row]]:
        with pytest.raises(ResearchError):
            await acquire(search_page(rows, total=len(rows)), "search")


@pytest.mark.parametrize("failure", ["connect", "json", "401", "403", "404", "429", "503"])
async def test_actual_http_failure_is_safe_and_never_means_no_phenotype(monkeypatch, failure, caplog, capsys):
    from fastmcp import Client
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError("ols-secret-sentinel", request=request)
        return (
            httpx.Response(200, text="ols-secret-sentinel")
            if failure == "json"
            else httpx.Response(int(failure), json={"error": "ols-secret-sentinel"})
        )

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool("get", {"entity": "phenotype", "id": TERM_ID}, raise_on_error=False)
        ).structured_content
    assert result["outcome"] == "error" and result["records"] == [] and not result["provenance"]
    assert result["sections"]["record"]["outcome"] in {"error", "unavailable"}
    if failure == "404":
        assert result["sections"]["record"]["error"]["code"] == "source_not_found"
    captured = capsys.readouterr()
    assert "ols-secret-sentinel" not in str(result) + caplog.text + captured.out + captured.err


async def test_actual_mcp_search_continuation_uses_returned_source_offset(monkeypatch):
    from fastmcp import Client
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    offsets = []

    def handler(request):
        offset = int(request.url.params["start"])
        offsets.append(offset)
        rows = []
        for index in range(offset, min(offset + 2, 3)):
            identity = f"HP:{1250 + index:07d}"
            rows.append(
                deepcopy(TERM)
                | {
                    "id": "hp+internal",
                    "obo_id": identity,
                    "short_form": identity.replace(":", "_"),
                    "iri": "http://purl.obolibrary.org/obo/" + identity.replace(":", "_"),
                    "type": "class",
                }
            )
        return httpx.Response(200, json=search_page(rows, total=3, start=offset))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    params = {"entity": "phenotype", "query": "synthetic", "limit": 2}
    async with Client(create_server(service=ResearchService())) as client:
        first = (await client.call_tool("search", params)).data
        assert first["next_cursor"] is not None
        second = (await client.call_tool("search", params | {"cursor": first["next_cursor"]})).data
    assert [r["id"] for r in first["records"] + second["records"]] == [
        "HP:0001250",
        "HP:0001251",
        "HP:0001252",
    ]
    assert offsets == [0, 2] and second["next_cursor"] is None
    assert all(p["source"] == "ols" for p in first["provenance"] + second["provenance"])


async def test_unknown_optional_term_metadata_stays_unknown():
    row = {
        key: value
        for key, value in TERM.items()
        if key not in {"is_obsolete", "is_defining_ontology", "description", "synonyms", "term_replaced_by"}
    }
    result = await acquire(record_page(row), "record")
    assert result["id"] == TERM_ID
    assert "is_obsolete" not in result and "term_replaced_by" not in result and "description" not in result


@pytest.mark.parametrize("mode", ["search", "record"])
async def test_populated_synonym_cross_references_preserve_provider_object_types(mode):
    xref = {
        "database": "PMID",
        "id": "15816939",
        "description": None,
        "url": "https://pubmed.ncbi.nlm.nih.gov/15816939",
    }
    row = deepcopy(TERM) | {
        "obo_synonym": [
            {"name": "Synthetic scoped synonym", "scope": "hasRelatedSynonym", "type": None, "xrefs": [xref]}
        ]
    }
    result = await acquire(
        search_page([row | {"type": "class"}]) if mode == "search" else record_page(row), mode
    )
    normalized = result["records"][0] if mode == "search" else result
    assert normalized["obo_synonym"][0]["xrefs"] == [xref]
    assert normalized["obo_synonym"][0]["scope"] == "hasRelatedSynonym"


@pytest.mark.parametrize("mode", ["search", "record"])
@pytest.mark.parametrize("xref", ["PMID:15816939", {"id": 15816939}])
async def test_malformed_synonym_cross_references_cannot_be_scientific_evidence(mode, xref):
    row = deepcopy(TERM) | {"obo_synonym": [{"name": "Synthetic synonym", "xrefs": [xref]}]}
    with pytest.raises(ResearchError) as caught:
        await acquire(search_page([row | {"type": "class"}]) if mode == "search" else record_page(row), mode)
    assert caught.value.code == "invalid_source_response"
