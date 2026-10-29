"""CIViC malformed-response, scientific identity and actual MCP contracts."""

from copy import deepcopy

import pytest
from civic_helpers import ASSERTION, EVIDENCE, connection, response
from native_helpers import HTTP

from biomedmcp.errors import ResearchError
from biomedmcp.native.variants import Variants

FOCUS = {"variant": "BRAF V600E", "gene": "BRAF", "drug": "imatinib", "disease": "melanoma"}


@pytest.mark.parametrize("entity", list(FOCUS))
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"data": None},
        {"data": {}},
        {"data": {"evidenceItems": connection()}},
        {"data": {"evidenceItems": None, "assertions": connection()}},
        {"data": {"evidenceItems": {"nodes": []}, "assertions": connection()}},
        {"error": "credential-sentinel"},
        {"errors": [{"message": "credential-sentinel"}], **response((), ())},
    ],
)
async def test_invalid_envelope_never_becomes_healthy_empty(entity, payload, caplog):
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(payload)).civic(FOCUS[entity], entity)
    assert caught.value.code == "invalid_source_response"
    assert "credential-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("entity", list(FOCUS))
async def test_populated_and_explicit_empty_connections_are_distinct(entity):
    populated = await Variants(HTTP(response())).civic(FOCUS[entity], entity)
    assert populated["evidenceItems"]["nodes"][0]["source"]["citation"] == "Synthetic citation"
    empty = await Variants(HTTP(response((), ()))).civic(FOCUS[entity], entity)
    assert empty["records"] == [] and empty["coverage"]["evidenceItems"]["has_more"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", True),
        ("id", -1),
        ("name", None),
        ("status", "SUBMITTED"),
        ("molecularProfile", None),
        ("molecularProfile", {}),
        ("source", None),
        ("source", {"citation": "partial"}),
        ("evidenceType", "invented"),
        ("evidenceDirection", "invented"),
        ("evidenceLevel", "invented"),
        ("significance", None),
        ("therapies", [None]),
        ("disease", []),
    ],
)
async def test_partial_scientific_evidence_fields_fail_before_filtering(field, value):
    item = {**deepcopy(EVIDENCE), field: value}
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(response((item,)))).civic("BRAF V600E")
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_direction",
        "null_profile_variant",
        "missing_gene_id",
        "string_year",
        "null_retraction",
        "invalid_total",
        "missing_page",
        "nonbool_next",
        "nonadvancing_cursor",
    ],
)
async def test_nested_partial_response_and_paging_are_not_negative_evidence(mutation):
    data = response()
    item = data["data"]["evidenceItems"]["nodes"][0]
    page = data["data"]["evidenceItems"]
    if mutation == "missing_direction":
        del item["evidenceDirection"]
    elif mutation == "null_profile_variant":
        item["molecularProfile"]["variants"] = [None]
    elif mutation == "missing_gene_id":
        del item["molecularProfile"]["variants"][0]["feature"]["featureInstance"]["entrezId"]
    elif mutation == "string_year":
        item["source"]["publicationYear"] = "2024"
    elif mutation == "null_retraction":
        item["source"]["retracted"] = None
    elif mutation == "invalid_total":
        page["totalCount"] = 0
    elif mutation == "missing_page":
        del page["pageInfo"]
    elif mutation == "nonbool_next":
        page["pageInfo"]["hasNextPage"] = "false"
    else:
        page.update(totalCount=2, pageInfo={"hasNextPage": True, "endCursor": None})
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(data)).civic("BRAF V600E")
    assert caught.value.code == "invalid_source_response"


async def test_variant_compound_profiles_are_not_credited_to_one_protein_change():
    compound = deepcopy(EVIDENCE)
    compound["id"] = 2
    compound["molecularProfile"].update(name="BRAF V600E + TP53 R175H", isMultiVariant=True, isComplex=True)
    data = await Variants(HTTP(response((EVIDENCE, compound)))).civic("BRAF V600E")
    assert [r["id"] for r in data["evidenceItems"]["nodes"]] == [1]
    assert data["coverage"]["evidenceItems"]["filtered"] == 1


async def test_substring_gene_and_therapy_matches_are_not_exact_identity():
    for entity in ["gene", "drug", "disease"]:
        item = deepcopy(EVIDENCE)
        if entity == "gene":
            item["molecularProfile"]["variants"][0]["feature"]["featureInstance"]["name"] = "BRAF-AS1"
        elif entity == "drug":
            item["therapies"][0]["name"] = "imatinib-like"
        else:
            item["disease"]["name"] = item["disease"]["displayName"] = "melanoma-like"
        data = await Variants(HTTP(response((item,), ()))).civic(FOCUS[entity], entity)
        assert not data["evidenceItems"]["nodes"]


async def test_nullable_source_measurements_and_disease_remain_explicit():
    item = deepcopy(EVIDENCE)
    item["disease"] = None
    item["source"].update(citation=None, publicationYear=None)
    result = await Variants(HTTP(response((item,), ()))).civic("BRAF V600E")
    assert result["evidenceItems"]["nodes"][0]["source"]["publicationYear"] is None


async def test_request_validates_against_immutable_official_schema():
    import json
    from pathlib import Path

    from graphql import build_client_schema, parse, validate

    snapshot = json.loads((Path(__file__).parent / "fixtures/civic-schema-2026-10-09.json").read_text())
    schema = build_client_schema({"__schema": snapshot["schema"]})
    for entity, focus in FOCUS.items():
        http = HTTP(response())
        await Variants(http).civic(focus, entity)
        assert validate(schema, parse(http.calls[0][2]["body"]["query"])) == []


def test_runtime_projection_matches_full_official_schema():
    import json
    from pathlib import Path

    from graphql import build_client_schema

    from biomedmcp.native.civic import TYPES

    snapshot = json.loads((Path(__file__).parent / "fixtures/civic-schema-2026-10-09.json").read_text())
    schema = build_client_schema({"__schema": snapshot["schema"]})
    for name, projection in TYPES.items():
        official = schema.get_type(name)
        if projection["kind"] == "ENUM":
            assert projection["values"] == list(official.values)
        elif projection["kind"] == "UNION":
            assert projection["members"] == [t.name for t in official.types]
        else:
            for field, ref in projection["fields"].items():
                assert ref == str(official.fields[field].type)
            if projection["kind"] == "INTERFACE":
                assert set(projection["members"]) == {t.name for t in schema.get_possible_types(official)}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": True},
        {"limit": 26},
        {"limit": 0},
        {"collection": []},
        {"collection": "invented"},
        {"after": "opaque"},
    ],
)
async def test_invalid_native_parameters_fail_before_provider_io(params):
    http = HTTP(response())
    with pytest.raises(ResearchError) as caught:
        await Variants(http).civic("BRAF V600E", **params)
    assert caught.value.code == "invalid_parameters" and not http.calls


async def test_gene_identity_checks_entrez_and_preserves_fusion_partners():
    item = deepcopy(EVIDENCE)
    feature = item["molecularProfile"]["variants"][0]["feature"]
    feature.update(
        featureType="FUSION",
        featureInstance={
            "__typename": "Fusion",
            "knownPartnerGenes": [{"name": "BRAF", "entrezId": 673}, {"name": "KIAA1549", "entrezId": 57670}],
        },
    )
    item["molecularProfile"].update(name="KIAA1549::BRAF", isComplex=True)
    item["molecularProfile"]["variants"][0].update(__typename="FusionVariant", name="KIAA1549::BRAF")
    result = await Variants(HTTP(response((item,), ()))).civic("BRAF", "gene", entrez_id="673")
    assert result["evidenceItems"]["nodes"][0]["molecularProfile"]["name"] == "KIAA1549::BRAF"
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(response((item,), ()))).civic("BRAF", "gene", entrez_id="999")
    assert caught.value.code == "identity_mismatch"


@pytest.fixture
async def civic_mcp(monkeypatch):
    import httpx

    from biomedmcp import transport
    from biomedmcp.domain import ResearchService
    from biomedmcp.runtime import ProviderRuntime

    monkeypatch.setenv("UBI_PROFILE", "local")
    state = {"calls": [], "responses": []}
    original = httpx.AsyncClient

    def handler(request):
        assert request.url.host == "civicdb.org"
        state["calls"].append(request)
        return httpx.Response(200, json=deepcopy(state["responses"].pop(0)))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    return ResearchService(runtime=ProviderRuntime(cursor_key=b"c" * 32)), state


@pytest.mark.parametrize("healthy", [response(), response((), ())])
async def test_actual_mcp_invalid_response_is_uncached_and_healthy_recovery_is_cached(civic_mcp, healthy):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    service, state = civic_mcp
    state["responses"] = [{"data": {}}, healthy]
    arguments = {"id": "BRAF V600E", "sections": ["civic"], "sources": ["civic"]}
    async with Client(create_server(service=service)) as client:
        failure = (
            await client.call_tool("variant_evidence", arguments, raise_on_error=False)
        ).structured_content
        recovered = (await client.call_tool("variant_evidence", arguments)).data
        cached = (await client.call_tool("variant_evidence", arguments)).data
    assert failure["outcome"] == "error" and not failure["provenance"]
    assert failure["sections"]["civic"]["error"]["code"] == "invalid_source_response"
    assert (
        recovered["outcome"]
        == cached["outcome"]
        == ("data" if healthy["data"]["evidenceItems"]["nodes"] else "empty")
    )
    assert recovered["provenance"][0]["source"] == "civic"
    assert cached["provenance"][0]["cached"] and len(state["calls"]) == 2


@pytest.mark.parametrize("selected", ["evidenceItems", "assertions"])
async def test_filtered_page_preserves_executable_mcp_continuation(civic_mcp, selected):
    import json

    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    service, state = civic_mcp
    wrong = deepcopy(EVIDENCE if selected == "evidenceItems" else ASSERTION)
    wrong["molecularProfile"]["name"] = "BRAF V600E + TP53 R175H"
    first = response((), ())
    token = "provider-opaque-" + "x" * 5000
    first["data"][selected] = connection([wrong], total=2, more=True, cursor=token)
    second = {
        "data": {selected: connection([EVIDENCE if selected == "evidenceItems" else ASSERTION], total=2)}
    }
    state["responses"] = [first, second]
    async with Client(create_server(service=service)) as client:
        result = (
            await client.call_tool(
                "variant_evidence",
                {"id": "BRAF V600E", "sections": ["civic"], "section_parameters": {"civic": {"limit": 1}}},
            )
        ).data
        assert result["outcome"] == "partial" and len(result["next_actions"]) == 1
        assert not result["sections"]["civic"]["data"][selected]["nodes"]
        action = result["next_actions"][0]
        assert action["tool"] == "variant_evidence"
        assert action["arguments"]["section_parameters"]["civic"]["collection"] == selected
        assert (
            token not in json.dumps(result)
            and len(action["arguments"]["section_parameters"]["civic"]["cursor"]) < 2048
        )
        later = (await client.call_tool(action["tool"], action["arguments"])).data
    assert later["sections"]["civic"]["data"][selected]["nodes"][0]["id"] == 1
    assert later["outcome"] == "data" and not later["next_actions"]
    actual = json.loads(state["calls"][1].content)
    assert actual["variables"] == {"name": "BRAF V600E", "first": 1, "after": token}
    assert ("assertions(" if selected == "evidenceItems" else "evidenceItems(") not in actual["query"]


@pytest.mark.parametrize(
    "change",
    ["account", "identity", "limit", "collection", "signature", "expired", "missing_state", "bad_state"],
)
async def test_signed_civic_cursor_rejects_replay_before_any_provider_io(civic_mcp, change, monkeypatch):
    from biomedmcp import runtime
    from biomedmcp.contracts import GetRequest
    from biomedmcp.runtime import digest

    service, state = civic_mcp
    data = response((), ())
    data["data"]["evidenceItems"] = connection([EVIDENCE], total=2, more=True, cursor="raw-next")
    state["responses"] = [data]
    request = GetRequest(
        entity="variant", id="BRAF V600E", sections=["civic"], section_parameters={"civic": {"limit": 1}}
    )
    first = await service.get(request, scope="owner")
    arguments = deepcopy(first.next_actions[0]["arguments"])
    params = arguments["section_parameters"]["civic"]
    scope = "another-owner" if change == "account" else "owner"
    if change == "identity":
        arguments["id"] = "BRAF V600K"
    elif change in {"limit", "collection"}:
        params[change] = 2 if change == "limit" else "assertions"
    elif change == "signature":
        params["cursor"] = ("a" if params["cursor"][0] != "a" else "b") + params["cursor"][1:]
    elif change == "expired":
        now = runtime.time.time()
        monkeypatch.setattr(runtime.time, "time", lambda: now + 3601)
    elif change == "missing_state":
        service.runtime.cache.values.clear()
    elif change == "bad_state":
        await service.runtime.cache.put(
            "civic-page:" + digest(params["cursor"]), {"after": "raw-next", "scanned": True}, 3600
        )
    with pytest.raises(ResearchError) as caught:
        await service.get(GetRequest.model_validate(arguments), scope=scope)
    assert caught.value.code == (
        "expired_cursor"
        if change == "missing_state"
        else "cache_invalid_data"
        if change == "bad_state"
        else "invalid_cursor"
    )
    assert len(state["calls"]) == 1


@pytest.mark.parametrize(
    "entity,identifier,record,name",
    [
        (
            "drug",
            "KTUFNOKKBVMGRW-UHFFFAOYSA-N",
            {"_id": "KTUFNOKKBVMGRW-UHFFFAOYSA-N", "chebi": {"name": "imatinib"}},
            "imatinib",
        ),
        ("disease", "MONDO:0005105", {"_id": "MONDO:0005105", "mondo": {"label": "melanoma"}}, "melanoma"),
    ],
)
async def test_drug_and_disease_ids_are_qualified_once_before_name_queries(
    civic_mcp, entity, identifier, record, name, monkeypatch
):
    import json

    from biomedmcp.contracts import GetRequest

    service, state = civic_mcp
    calls = []

    async def call(source, operation, params):
        calls.append((source, operation, params))
        return deepcopy(record)

    monkeypatch.setattr(service.adapters, "call", call)
    state["responses"] = [response()]
    result = await service.get(
        GetRequest(entity=entity, id=identifier, sections=["record", "civic"]), scope="owner"
    )
    assert result.outcome == "data" and len(calls) == 1
    assert json.loads(state["calls"][0].content)["variables"]["name"] == name
    assert result.sections["civic"].data["qualified_identity"]["source_id"] == identifier
    assert result.query["provider_plan"]["civic"]["identity_dependencies"] == [
        "mychem" if entity == "drug" else "mydisease"
    ]


@pytest.mark.parametrize(
    "record,code",
    [
        ({}, "invalid_source_response"),
        ({"_id": "wrong", "chebi": {"name": "imatinib"}}, "identity_mismatch"),
        ({"_id": "CHEMBL941"}, "unresolved_identity"),
        ({"_id": "CHEMBL941", "chembl": {"pref_name": None}}, "invalid_source_response"),
    ],
)
async def test_failed_naming_dependency_cannot_become_empty_civic(civic_mcp, record, code, monkeypatch):
    from biomedmcp.contracts import GetRequest

    service, state = civic_mcp

    async def call(*args):
        return deepcopy(record)

    monkeypatch.setattr(service.adapters, "call", call)
    result = await service.get(GetRequest(entity="drug", id="CHEMBL941", sections=["civic"]), scope="owner")
    assert result.sections["civic"].error["code"] == code
    assert result.outcome == "error" and not state["calls"] and not result.provenance
