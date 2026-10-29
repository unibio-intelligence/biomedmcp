"""Real retained UniProt adapter response contracts; no provider traffic."""

from copy import deepcopy

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError

PROTEIN = {
    "primaryAccession": "P15056",
    "uniProtkbId": "BRAF_HUMAN",
    "entryType": "UniProtKB reviewed (Swiss-Prot)",
    "organism": {"taxonId": 9606, "scientificName": "Homo sapiens"},
    "proteinDescription": {
        "recommendedName": {"fullName": {"value": "Serine/threonine-protein kinase B-raf"}}
    },
    "genes": [{"geneName": {"value": "BRAF"}}],
    "comments": [
        {
            "commentType": "SIMILARITY",
            "texts": [
                {
                    "value": "Belongs to the protein kinase superfamily.",
                    "evidences": [{"evidenceCode": "ECO:0000305"}],
                }
            ],
        }
    ],
    "sequence": {"value": "MAV", "length": 3, "molWeight": 300},
    "features": [{"type": "Domain", "location": {"start": {"value": 1}, "end": {"value": 3}}}],
    "uniProtKBCrossReferences": [
        {"database": "PDB", "id": "1ABC", "properties": [{"key": "Chains", "value": "A=1-3"}]}
    ],
}


@pytest.fixture
def adapter_http(monkeypatch):
    original = httpx.AsyncClient

    def install(payload, *, status=200, headers=None):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(status, json=deepcopy(payload), headers=headers)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters(), calls

    return install


@pytest.mark.parametrize(
    "operation,params",
    [
        ("query_proteins", {"query": "P15056"}),
        ("analyze_evolution", {"accession": "P15056"}),
        ("analyze_structure_function", {"accession": "P15056"}),
        ("analyze_biological_context", {"accession": "P15056"}),
        ("get_metadata", {"accession": "P15056"}),
        ("validate_accession", {"accession": "P15056"}),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"error": "synthetic-provider-key"},
        {"primaryAccession": None},
        {"primaryAccession": "P15056", "sequence": None},
    ],
)
async def test_direct_record_malformed_response_is_failure(adapter_http, operation, params, payload, caplog):
    adapter, calls = adapter_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", operation, params)
    assert caught.value.code == "invalid_source_response"
    assert not caught.value.retryable
    assert "synthetic-provider-key" not in caplog.text + str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("primaryAccession", "wrong"),
        ("organism", []),
        ("organism", {"taxonId": True}),
        ("organism", {"taxonId": -1}),
        ("genes", [{}]),
        ("genes", [{"geneName": {"value": 123}}]),
        ("sequence", {"value": "MAV", "length": 4}),
        ("sequence", {"value": "MAV", "length": True}),
        ("sequence", {"value": "<html>"}),
        ("features", [{"type": "Domain", "location": {"start": {"value": 3}, "end": {"value": 1}}}]),
        ("features", [None]),
        ("uniProtKBCrossReferences", [{"database": "PDB"}]),
        ("uniProtKBCrossReferences", [{"database": "PDB", "id": "1ABC", "properties": [{"key": "Chains"}]}]),
        ("proteinDescription", {"recommendedName": {"fullName": None}}),
    ],
)
async def test_search_rejects_partial_nested_scientific_fields(adapter_http, field, value):
    protein = {**deepcopy(PROTEIN), field: value}
    adapter, _ = adapter_http({"results": [protein]})
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "BRAF", "query_type": "advanced"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"results": None},
        {"results": [None]},
        {"results": [{}]},
        {"results": [], "messages": ["error"]},
    ],
)
async def test_search_invalid_envelope_cannot_be_empty(adapter_http, payload):
    adapter, _ = adapter_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "BRAF", "query_type": "advanced"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("rows", [[], [PROTEIN], [{"primaryAccession": "P15056"}]])
async def test_valid_search_empty_populated_and_compact_projection(adapter_http, rows):
    adapter, _ = adapter_http({"results": rows})
    result = await adapter.call("uniprot", "query_proteins", {"query": "BRAF", "query_type": "advanced"})
    assert result["results"] == rows
    assert result["_provider_page"]["exhausted"]


async def test_exact_record_identity_and_secondary_accession(adapter_http):
    adapter, _ = adapter_http({**PROTEIN, "primaryAccession": "P04637"})
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "P15056"})
    assert caught.value.code == "identity_mismatch"
    adapter, _ = adapter_http({**PROTEIN, "secondaryAccessions": ["Q00001"]})
    result = await adapter.call("uniprot", "query_proteins", {"query": "Q00001"})
    assert result["primaryAccession"] == "P15056"
    assert result["secondaryAccessions"] == ["Q00001"]


async def test_requested_full_sequence_cannot_be_missing(adapter_http):
    adapter, _ = adapter_http({"primaryAccession": "P15056"})
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "P15056", "include_sequence": True})
    assert caught.value.code == "invalid_source_response"


async def test_compare_retains_success_and_classifies_invalid_peer(adapter_http, monkeypatch):
    original = httpx.AsyncClient

    def handler(request):
        payload = PROTEIN if request.url.path.endswith("P15056") else {}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    result = await SourceAdapters().call("uniprot", "compare_proteins", {"accessions": ["P15056", "P04637"]})
    assert result["results"][0]["data"]["primaryAccession"] == "P15056"
    assert result["results"][1]["error"]["code"] == "invalid_source_response"
    assert result["section_outcomes"]["P15056"]["outcome"] == "data"
    assert result["section_outcomes"]["P04637"]["outcome"] == "unavailable"


@pytest.mark.parametrize(
    "operation,params,payload",
    [
        ("search", {"entity": "protein", "query": "BRAF"}, {"results": []}),
        ("get", {"entity": "protein", "id": "P15056", "sections": ["record"]}, PROTEIN),
        (
            "query_source",
            {"source": "uniprot", "operation": "analyze_evolution", "params": {"accession": "P15056"}},
            PROTEIN,
        ),
    ],
)
async def test_public_failure_is_not_cached_and_recovery_retains_evidence(
    adapter_http, monkeypatch, operation, params, payload
):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={} if len(calls) == 1 else payload)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        first = (await client.call_tool(operation, params, raise_on_error=False)).structured_content
        second = (await client.call_tool(operation, params)).data
        third = (await client.call_tool(operation, params)).data
    assert first["outcome"] == "error" and not first["provenance"]
    section = next(iter(first["sections"].values()))
    assert section["error"]["code"] == "invalid_source_response"
    assert second["outcome"] == third["outcome"] == ("empty" if operation == "search" else "data")
    assert second["provenance"][0]["source"] == "uniprot"
    assert third["provenance"][0]["cached"] and len(calls) == 2


async def test_public_compare_retries_unavailable_peer_and_then_caches_complete_evidence(monkeypatch):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    counts = {"P15056": 0, "P04637": 0}

    def handler(request):
        accession = request.url.path.rsplit("/", 1)[1]
        counts[accession] += 1
        data = (
            {}
            if accession == "P04637" and counts[accession] == 1
            else {**PROTEIN, "primaryAccession": accession}
        )
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    params = {
        "source": "uniprot",
        "operation": "compare_proteins",
        "params": {"accessions": ["P15056", "P04637"]},
    }
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        first = (await client.call_tool("query_source", params)).data
        second = (await client.call_tool("query_source", params)).data
        third = (await client.call_tool("query_source", params)).data
    assert first["outcome"] == "partial" and first["provenance"]
    peers = first["sections"]["uniprot"]["data"]["results"]
    assert peers[0]["data"]["primaryAccession"] == "P15056"
    assert peers[1]["error"]["code"] == "invalid_source_response"
    assert second["outcome"] == third["outcome"] == "data"
    assert third["provenance"][0]["cached"] and counts == {"P15056": 2, "P04637": 2}


@pytest.mark.parametrize(
    "payload",
    [
        {"primaryAccession": "P15056", "entryType": "Inactive"},
        {"primaryAccession": "P15056", "inactiveReason": {"inactiveReasonType": "DELETED"}},
    ],
)
async def test_inactive_record_is_not_healthy_negative_evidence(adapter_http, payload):
    adapter, _ = adapter_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "P15056"})
    assert caught.value.code == "source_not_found"


async def test_unknown_feature_positions_and_optional_annotations_are_valid(adapter_http):
    record = {
        **PROTEIN,
        "features": [
            {"type": "Region", "location": {"start": {"modifier": "UNKNOWN"}, "end": {"modifier": "UNKNOWN"}}}
        ],
        "genes": [],
        "uniProtKBCrossReferences": [],
    }
    adapter, calls = adapter_http(record)
    result = await adapter.call("uniprot", "analyze_evolution", {"accession": "P15056"})
    assert result["features"] == record["features"]
    assert calls[0].url.params["fields"].split(",")[0] == "accession"


async def test_isoform_is_never_silently_changed_to_keyword_search(adapter_http):
    adapter, calls = adapter_http(PROTEIN)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "P15056-2"})
    assert caught.value.code == "identity_mismatch"
    assert calls[0].url.path == "/uniprotkb/P15056-2"


async def test_feature_projection_uses_dated_supported_columns(adapter_http):
    import json
    from pathlib import Path

    from uniprot_mcp.server import FEATURE_FIELDS

    contract = json.loads(
        (Path(__file__).parent / "fixtures/uniprot-field-contract-2026-10-09.json").read_text()
    )
    assert list(FEATURE_FIELDS) == contract["feature_fields"]
    adapter, calls = adapter_http(PROTEIN)
    await adapter.call(
        "uniprot", "query_proteins", {"query": "P15056", "include_features": True, "include_sequence": True}
    )
    selected = calls[0].url.params["fields"].split(",")
    assert set(selected) <= set(contract["fields"])
    assert "ft_*" not in selected and set(FEATURE_FIELDS) <= set(selected)
    assert selected.count("accession") == 1


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "source_authentication_failed"),
        (403, "source_access_denied"),
        (404, "source_not_found"),
        (429, "source_rate_limited"),
        (503, "source_unavailable"),
    ],
)
async def test_http_failures_keep_classification_without_raw_provider_text(
    adapter_http, status, code, caplog, capsys
):
    adapter, calls = adapter_http({"messages": ["synthetic-provider-key"]}, status=status)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("uniprot", "query_proteins", {"query": "P15056"})
    assert caught.value.code == code
    captured = capsys.readouterr()
    assert "synthetic-provider-key" not in caplog.text + captured.err + captured.out + str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize("comparison_type", ["sequence", "function", "structure"])
async def test_every_advertised_comparison_view_retains_qualified_records(adapter_http, comparison_type):
    original = httpx.AsyncClient
    fields = []

    def handler(request):
        accession = request.url.path.rsplit("/", 1)[1]
        fields.append(request.url.params["fields"])
        return httpx.Response(200, json={**PROTEIN, "primaryAccession": accession})

    adapter, _ = adapter_http(PROTEIN)
    from pytest import MonkeyPatch

    with MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        result = await adapter.call(
            "uniprot",
            "compare_proteins",
            {"accessions": ["P15056", "P04637"], "comparison_type": comparison_type},
        )
    assert [r["data"]["primaryAccession"] for r in result["results"]] == ["P15056", "P04637"]
    assert all("accession" in f.split(",") for f in fields)
