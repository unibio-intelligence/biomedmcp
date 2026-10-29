"""Reactome acquisition semantics using pinned official controller/model contracts."""

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt

PID = "R-HSA-109581"
PATHWAY = {
    "stId": PID,
    "displayName": "Synthetic pathway",
    "schemaClass": "Pathway",
    "speciesName": "Homo sapiens",
}
REACTION = {**PATHWAY, "stId": "R-HSA-900001", "schemaClass": "Reaction"}
ENTRY = {
    "id": PID,
    "stId": PID,
    "name": "Synthetic pathway",
    "exactType": "Pathway",
    "type": "Pathway",
    "species": ["Homo sapiens"],
}
INDEX_ENTRY = {
    "id": "109581",
    "source": "reactome",
    "fields": {
        "stid": [PID],
        "name": ["Synthetic pathway"],
        "type": ["Pathway"],
        "species": ["Homo sapiens"],
    },
}
SEARCH = {"entries": [INDEX_ENTRY], "hitCount": 2}
INDEX = {
    "domains": [
        {
            "id": "reactome",
            "indexInfos": [
                {"name": "Release version", "value": "97"},
                {"name": "Last modification date", "value": "2026-10-16"},
            ],
        }
    ]
}
SEARCH_PATH = "/ebisearch/ws/rest/reactome"
PARTICIPANT = {
    "peDbId": 17,
    "displayName": "Synthetic protein",
    "schemaClass": "EntityWithAccessionedSequence",
    "refEntities": [
        {
            "dbId": 18,
            "stId": "R-HSA-900002",
            "identifier": "P00533",
            "schemaClass": "ReferenceGeneProduct",
            "displayName": "Synthetic protein",
        }
    ],
}
DIAGRAM = {"stableId": PID, "dbId": 109581, "nodes": [], "edges": [], "compartments": []}


@pytest.fixture
def reactome_http(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    state = {"requests": [], "payloads": {}}

    def respond(request):
        state["requests"].append(request)
        if request.url.host == "mygene.info":
            taxid = 10090 if "10090" in str(request.url) else 9606
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "_id": "2064" if taxid == 9606 else "13866",
                            "symbol": "ERBB2" if taxid == 9606 else "Erbb2",
                            "taxid": taxid,
                            "entrezgene": 2064 if taxid == 9606 else 13866,
                            "ensembl": {"gene": "ENSG00000141736" if taxid == 9606 else "ENSMUSG00000062312"},
                        }
                    ],
                    "total": 1,
                },
            )
        assert request.url.host in {"reactome.org", "www.ebi.ac.uk"}
        if request.url.host == "www.ebi.ac.uk" and "query" not in request.url.params:
            return httpx.Response(200, json=INDEX)
        payload = state["payloads"].get(request.url.path, PATHWAY)
        if callable(payload):
            return payload(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    return state


async def test_search_flattens_entries_and_preserves_provider_continuation(reactome_http):
    state = reactome_http

    def search(request):
        start = int(request.url.params.get("start", 0))
        return httpx.Response(
            200,
            json={
                **SEARCH,
                "entries": [
                    {
                        **INDEX_ENTRY,
                        "id": "109581" if start == 0 else "900003",
                        "fields": {**INDEX_ENTRY["fields"], "stid": [PID if start == 0 else "R-HSA-900003"]},
                    }
                ],
            },
        )

    state["payloads"][SEARCH_PATH] = search
    async with Client(create_server(service=ResearchService())) as client:
        first = (
            await client.call_tool("search", {"entity": "pathway", "query": "apoptosis", "limit": 1})
        ).structured_content
        assert first["records"][0]["id"] == PID
        assert first["next_cursor"] and verify_receipt(first)
        second = (
            await client.call_tool(
                "search",
                {"entity": "pathway", "query": "apoptosis", "limit": 1, "cursor": first["next_cursor"]},
            )
        ).structured_content
    assert second["records"][0]["id"] == "R-HSA-900003" and second["next_cursor"] is None
    requests = [r for r in state["requests"] if "query" in r.url.params]
    assert [r.url.params["start"] for r in requests] == ["0", "1"]
    assert all(
        r.url.params["query"].endswith(' AND type:Pathway AND species:"Homo sapiens"')
        and r.url.params["size"] == "1"
        for r in requests
    )
    assert first["records"][0]["search_index"]["release_version"] == "97"


@pytest.mark.parametrize(
    "detail,payload",
    [
        ("basic", {**PATHWAY, "stId": "R-HSA-900004"}),
        ("participants", [None]),
        ("hierarchy", {"error": "synthetic-credential-sentinel"}),
    ],
)
async def test_wrong_identity_and_malformed_shapes_fail_before_evidence(reactome_http, detail, payload):
    state = reactome_http
    path = (
        f"/ContentService/data/query/{PID}"
        if detail == "basic"
        else f"/ContentService/data/participants/{PID}"
        if detail == "participants"
        else f"/ContentService/data/pathway/{PID}/containedEvents"
    )
    state["payloads"][path] = payload
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call(
            "reactome", "get_pathway_info", {"pathway_id": PID, "detail_level": detail}
        )
    assert caught.value.code == "invalid_source_response"


async def test_public_gene_membership_uses_mapping_and_preserves_mouse_species(reactome_http):
    state = reactome_http
    state["payloads"]["/ContentService/data/mapping/UniProt/Erbb2/pathways"] = [
        {**PATHWAY, "stId": "R-MMU-900001", "speciesName": "Mus musculus"}
    ]
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "get", {"entity": "gene", "id": "Erbb2", "species": 10090, "sections": ["pathways"]}
            )
        ).structured_content
    assert result["outcome"] == "data", result
    request = state["requests"][-1]
    assert request.url.path == "/ContentService/data/mapping/UniProt/Erbb2/pathways"
    assert request.url.params["species"] == "10090"
    assert result["sections"]["pathways"]["data"]["species"] == "10090"


async def test_pathway_events_include_subpathways_and_reactions(reactome_http):
    reactome_http["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [PATHWAY, REACTION]
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool("get", {"entity": "pathway", "id": PID, "sections": ["events"]})
        ).structured_content
    assert result["sections"]["events"]["data"]["hierarchy"] == [PATHWAY, REACTION]


async def test_diagram_json_is_geometry_not_a_pathway_record(reactome_http):
    reactome_http["payloads"][f"/download/current/diagram/{PID}.json"] = DIAGRAM
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "reactome",
                    "operation": "get_pathway_diagram",
                    "params": {"pathway_id": PID, "output_format": "json"},
                },
            )
        ).structured_content
    assert result["sections"]["reactome"]["data"]["diagram"] == DIAGRAM
    assert verify_receipt(result)


async def test_participant_references_are_not_pairwise_interactions(reactome_http):
    reactome_http["payloads"]["/ContentService/data/participants/P00533"] = [PARTICIPANT]
    interactions = {
        "resource": "static",
        "entities": [
            {
                "acc": "P00533",
                "count": 1,
                "interactors": [{"acc": "P12345", "score": 0.5, "id": 20, "evidences": 1}],
            }
        ],
    }
    reactome_http["payloads"]["/ContentService/interactors/static/molecule/P00533/details"] = interactions
    result = await SourceAdapters().call("reactome", "get_protein_interactions", {"protein_id": "P00533"})
    assert result["interactions"] == interactions
    assert reactome_http["requests"][-1].url.path.endswith("/interactors/static/molecule/P00533/details")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entries": []},
        {**SEARCH, "hitCount": True},
        {**SEARCH, "hitCount": -1},
        {**SEARCH, "entries": [None]},
        {
            **SEARCH,
            "entries": [{**INDEX_ENTRY, "fields": {**INDEX_ENTRY["fields"], "species": ["Mus musculus"]}}],
        },
        {
            **SEARCH,
            "entries": [{**INDEX_ENTRY, "fields": {**INDEX_ENTRY["fields"], "stid": ["R-HSA-900005"]}}],
        },
        {**SEARCH, "entries": [INDEX_ENTRY, INDEX_ENTRY]},
        {**SEARCH, "entries": []},
        {**SEARCH, "entries": [{**INDEX_ENTRY, "fields": {**INDEX_ENTRY["fields"], "type": ["Disease"]}}]},
    ],
)
async def test_malformed_or_foreign_search_window_cannot_be_empty_or_cached(reactome_http, payload):
    reactome_http["payloads"][SEARCH_PATH] = payload
    service = ResearchService()
    args = {"entity": "pathway", "query": "apoptosis", "limit": 1}
    async with Client(create_server(service=service)) as client:
        failed = (await client.call_tool_mcp("search", args)).structured_content
        assert failed["outcome"] == "error" and not failed["provenance"], failed
        reactome_http["payloads"][SEARCH_PATH] = {**SEARCH, "hitCount": 1}
        fixed = (await client.call_tool("search", args)).structured_content
    assert fixed["outcome"] == "data" and fixed["records"][0]["id"] == PID
    assert len(reactome_http["requests"]) == 4 and verify_receipt(fixed)


async def test_explicit_zero_search_retains_no_matches(reactome_http):
    reactome_http["payloads"][SEARCH_PATH] = {"entries": [], "hitCount": 0}
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool("search", {"entity": "pathway", "query": "synthetic-zero"})
        ).structured_content
    assert result["outcome"] == "empty" and result["records"] == [] and result["next_cursor"] is None
    assert verify_receipt(result)


async def test_full_pathway_keeps_good_peers_with_explicit_failure(reactome_http):
    state = reactome_http
    state["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = {
        "error": "synthetic-source-sentinel"
    }
    state["payloads"][f"/ContentService/data/participants/{PID}"] = [PARTICIPANT]
    result = await SourceAdapters().call(
        "reactome", "get_pathway_info", {"pathway_id": PID, "detail_level": "full"}
    )
    assert result["basic"] == PATHWAY and result["participants"] == [PARTICIPANT]
    assert "hierarchy" not in result
    assert result["section_outcomes"]["hierarchy"]["error"]["code"] == "invalid_source_response"
    assert "synthetic-source-sentinel" not in str(result)


async def test_public_pathway_partial_then_valid_retry_keeps_successful_events(reactome_http):
    state = reactome_http
    state["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [REACTION]
    state["payloads"][f"/ContentService/data/participants/{PID}"] = {"error": "synthetic-failed-participants"}
    args = {"entity": "pathway", "id": PID, "sections": ["record", "genes", "events"]}
    async with Client(create_server(service=ResearchService())) as client:
        failed = (await client.call_tool("get", args)).structured_content
        assert failed["outcome"] == "partial" and failed["sections"]["events"]["data"]["hierarchy"] == [
            REACTION
        ]
        assert failed["sections"]["genes"]["outcome"] == "error"
        state["payloads"][f"/ContentService/data/participants/{PID}"] = [PARTICIPANT]
        fixed = (await client.call_tool("get", args)).structured_content
    assert fixed["outcome"] == "data" and fixed["sections"]["genes"]["data"]["participants"] == [PARTICIPANT]
    assert verify_receipt(failed) and verify_receipt(fixed)
    assert [r.url.path for r in state["requests"]].count(f"/ContentService/data/participants/{PID}") == 2


@pytest.mark.parametrize(
    "operation,params",
    [
        ("search_pathways", {"query": "apoptosis", "search_type": "disease"}),
        ("search_pathways", {"query": "apoptosis", "offset": True}),
        ("find_pathways_by_gene", {"gene": "ERBB2", "include_disease": False}),
        ("get_pathway_info", {"pathway_id": PID, "species": "Mus musculus"}),
        ("get_pathway_info", {"pathway_id": "../synthetic-credential"}),
        ("get_protein_interactions", {"protein_id": "P00533", "interaction_type": "regulatory"}),
        ("get_protein_interactions", {"protein_id": "P00533", "species": "Homo sapiens"}),
        ("get_protein_interactions", {"protein_id": "P00533", "page": -1}),
        ("get_pathway_diagram", {"pathway_id": "R-HSA-109581?token=synthetic"}),
    ],
)
async def test_unconsumed_or_unsafe_parameters_reject_before_io(reactome_http, operation, params):
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("reactome", operation, params)
    assert caught.value.code == "invalid_parameters" and reactome_http["requests"] == []


OPERATIONS = [
    ("search_pathways", {"query": "apoptosis"}),
    ("get_pathway_info", {"pathway_id": PID}),
    ("find_pathways_by_gene", {"gene": "ERBB2"}),
    ("find_pathways_by_disease", {"disease": "synthetic-disease"}),
    ("get_protein_interactions", {"protein_id": "P00533"}),
    ("get_pathway_diagram", {"pathway_id": PID}),
]


@pytest.mark.parametrize("operation,params", OPERATIONS)
@pytest.mark.parametrize("failure", ["connect", "503", "json"])
async def test_all_adapter_failures_are_sanitized_before_logs(
    monkeypatch, caplog, capsys, operation, params, failure
):
    original = httpx.AsyncClient
    sentinel = "synthetic-reactome-secret-sentinel"

    def respond(request):
        if failure == "connect":
            raise httpx.ConnectError(sentinel, request=request)
        if failure == "503":
            return httpx.Response(503, json={"error": sentinel})
        return httpx.Response(200, text=sentinel)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("reactome", operation, params)
    assert caught.value.code == ("invalid_source_response" if failure == "json" else "source_unavailable")
    output = capsys.readouterr()
    assert sentinel not in str(caught.value) + caplog.text + output.out + output.err


@pytest.mark.parametrize(
    "kind,body,media",
    [
        ("svg", b'<svg xmlns="http://www.w3.org/2000/svg"><text>synthetic</text></svg>', "image/svg+xml"),
        ("png", b"\x89PNG\r\n\x1a\nsynthetic-signature-only", "image/png"),
    ],
)
async def test_diagram_images_preserve_external_locator_and_acquired_byte_hash(
    reactome_http, kind, body, media
):
    import hashlib

    state = reactome_http
    path = f"/ContentService/exporter/diagram/{PID}.{kind}"
    state["payloads"][path] = lambda request: httpx.Response(
        200, content=body, headers={"content-type": media}
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "reactome",
                    "operation": "get_pathway_diagram",
                    "params": {"pathway_id": PID, "output_format": kind},
                },
            )
        ).structured_content
    asset = result["sections"]["reactome"]["data"]["asset"]
    assert asset["sha256"] == hashlib.sha256(body).hexdigest() and asset["byte_count"] == len(body)
    assert asset["media_type"] == media and asset["url"] == "https://reactome.org" + path
    assert asset["validation"] == "media_and_signature_only" and verify_receipt(result)


@pytest.mark.parametrize(
    "body",
    [
        b"not-xml",
        b'<!DOCTYPE svg [<!ENTITY x "synthetic">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        b'<html xmlns="http://www.w3.org/1999/xhtml"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg">' + b"<g>" * 65 + b"</g>" * 65 + b"</svg>",
    ],
)
async def test_svg_shape_entities_and_depth_fail_safely(reactome_http, body):
    from biomedmcp.errors import ResearchError

    reactome_http["payloads"][f"/ContentService/exporter/diagram/{PID}.svg"] = lambda request: httpx.Response(
        200, content=body, headers={"content-type": "image/svg+xml"}
    )
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call(
            "reactome", "get_pathway_diagram", {"pathway_id": PID, "output_format": "svg"}
        )
    assert caught.value.code == "invalid_source_response"


async def test_reaction_projection_filters_classes_after_validating_raw_events(reactome_http):
    state = reactome_http
    state["payloads"][f"/ContentService/data/pathway/{PID}/containedEvents"] = [PATHWAY, REACTION]
    result = await SourceAdapters().call(
        "reactome", "get_pathway_info", {"pathway_id": PID, "detail_level": "reactions"}
    )
    assert result["reactions"] == [REACTION]
    assert "attributeNames" not in state["requests"][0].url.params


async def test_disease_pathways_remain_literal_pathway_text_matches(reactome_http):
    reactome_http["payloads"][SEARCH_PATH] = SEARCH
    result = await SourceAdapters().call(
        "reactome", "find_pathways_by_disease", {"disease": "MONDO:synthetic"}
    )
    assert result["relation_basis"] == "provider_pathway_text_search" and result["records"][0]["id"] == PID
    assert result["exhausted"] is False and result["total"] == 2
    assert "type:Pathway" in reactome_http["requests"][1].url.params["query"]


async def test_nonempty_serialization_can_omit_empty_diagram_edges(reactome_http):
    value = {"stableId": PID, "dbId": 109581, "nodes": [{"id": 1, "displayName": "Synthetic node"}]}
    reactome_http["payloads"][f"/download/current/diagram/{PID}.json"] = value
    result = await SourceAdapters().call("reactome", "get_pathway_diagram", {"pathway_id": PID})
    assert result["diagram"] == value and "edges" not in result["diagram"]


async def test_source_stream_budget_precedes_json_and_cannot_be_cached(reactome_http):
    reactome_http["payloads"][f"/download/current/diagram/{PID}.json"] = lambda request: httpx.Response(
        200, content=b"x" * 4_000_001
    )
    from biomedmcp.errors import ResearchError

    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("reactome", "get_pathway_diagram", {"pathway_id": PID})
    assert caught.value.code == "source_response_budget"


async def test_wrong_species_membership_rejects_human_mouse_join(reactome_http):
    reactome_http["payloads"]["/ContentService/data/mapping/UniProt/Erbb2/pathways"] = [PATHWAY]
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool_mcp(
                "get", {"entity": "gene", "id": "Erbb2", "species": 10090, "sections": ["pathways"]}
            )
        ).structured_content
    assert (
        result["outcome"] == "error"
        and result["sections"]["pathways"]["error"]["code"] == "invalid_source_response"
    )
    assert result["provenance"] == []


async def test_diagram_geometry_recovery_retains_one_acquired_snapshot(reactome_http):
    import json

    state = reactome_http
    value = {
        **DIAGRAM,
        "nodes": [{"id": index, "displayName": f"Synthetic node {index}"} for index in range(31)],
    }
    state["payloads"][f"/download/current/diagram/{PID}.json"] = value
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "reactome", "operation": "get_pathway_diagram", "params": {"pathway_id": PID}},
            )
        ).structured_content
        section = result["sections"]["reactome"]
        assert len(section["data"]["diagram"]["nodes"]) == 25 and section["truncated"]
        omission = next(row for row in section["recovery"]["omissions"] if row["pointer"] == "/diagram/nodes")
        recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
    assert recovered["value"] == value["nodes"][25:] and recovered["next_uri"] is None
    assert recovered["evidence_ids"] == section["evidence_ids"] and verify_receipt(result)
    assert len(state["requests"]) == 1
