"""Open Targets missing responses cannot become scientific evidence of absence."""

from copy import deepcopy

import pytest
from opentargets_mcp import queries
from opentargets_mcp.queries import OpenTargetsClient
from test_qualified_gene_identity import GeneAdapters

from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError

QUERY = "query($id:String!){target(ensemblId:$id){id approvedSymbol associatedDiseases(page:{index:0,size:2}){count rows{disease{id name} score datatypeScores{id score}}}}}"
IDENTITY = "ENSG00000157764"


def response(rows=(), count=None):
    return {
        "data": {
            "target": {
                "id": IDENTITY,
                "approvedSymbol": "BRAF",
                "associatedDiseases": {"count": len(rows) if count is None else count, "rows": list(rows)},
            }
        }
    }


class Transport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        parent = self

        class Result:
            def raise_for_status(self):
                pass

            def json(self):
                return deepcopy(parent.payload)

        return Result()


async def invoke(monkeypatch, payload, query=QUERY):
    transport = Transport(payload)
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: transport)
    return await OpenTargetsClient()._query(query, {"id": IDENTITY})


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": None},
        {"data": {}},
        {"data": {"target": {}}},
        {"data": {"target": {"id": "ENSG00000141510", "approvedSymbol": "BRAF"}}},
    ],
)
async def test_incomplete_graphql_response_is_not_healthy(monkeypatch, payload):
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, payload)
    assert caught.value.code == "invalid_source_response"


async def test_missing_composed_response_cannot_mint_cached_empty_evidence():
    class MissingTarget(GeneAdapters):
        async def call(self, source, operation, params):
            if source == "opentargets":
                self.calls.append((source, operation, params))
                return {}
            return await super().call(source, operation, params)

    adapters = MissingTarget()
    service = ResearchService(adapters=adapters)
    request = GetRequest(entity="gene", id="673", sections=["record", "diseases", "druggability"])
    first = await service.get(request, scope="public")
    second = await service.get(request, scope="public")
    assert first.outcome == second.outcome == "partial"
    for result in (first, second):
        assert result.sections["record"].outcome == "data"
        for name in ("diseases", "druggability"):
            assert result.sections[name].outcome == "error"
            assert result.sections[name].error["code"] == "invalid_source_response"
            assert result.sections[name].evidence_ids == []
    assert len([c for c in adapters.calls if c[0] == "opentargets"]) == 2


@pytest.mark.parametrize(
    "payload",
    [[], "unexpected", {"errors": []}, {"data": response()["data"], "errorType": "provider failure"}],
)
async def test_wrong_envelope_types_and_application_markers(monkeypatch, payload):
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, payload)
    assert caught.value.code == "invalid_source_response"


async def test_partial_graphql_application_failure_has_no_successful_evidence(monkeypatch):
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, {**response(), "errors": [{"message": "untrusted credential-shaped text"}]})
    assert caught.value.code == "upstream_error"
    assert "untrusted" not in str(caught.value)


@pytest.mark.parametrize("score", [True, "0.5", float("nan"), float("inf"), -0.1, 1.1, None, 10**400])
async def test_association_scores_are_finite_reported_source_assessments(monkeypatch, score):
    from opentargets_helpers import association

    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, response([association(score)]))
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("count", [True, "1", 1.5, -1, None, 2**63])
async def test_provider_counts_are_not_coerced_or_negative(monkeypatch, count):
    payload = response()
    payload["data"]["target"]["associatedDiseases"]["count"] = count
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, payload)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "damage", ["rows", "disease_id", "datatypeScores", "score", "null_row", "total", "extra"]
)
async def test_partial_nested_association_cannot_be_healthy(monkeypatch, damage):
    from opentargets_helpers import association

    payload = response([association()])
    target = payload["data"]["target"]
    group = target["associatedDiseases"]
    row = group["rows"][0]
    if damage == "rows":
        group["rows"] = {}
    elif damage == "disease_id":
        row["disease"].pop("id")
    elif damage == "null_row":
        group["rows"] = [None]
    elif damage == "total":
        group["count"] = 0
    elif damage == "extra":
        row["unqueried_unsupported_claim"] = "source data"
    else:
        row.pop(damage)
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, payload)
    assert caught.value.code == "invalid_source_response"


async def test_explicit_empty_collection_and_null_root_have_different_outcomes(monkeypatch):
    result = await invoke(monkeypatch, response())
    assert result["target"]["associatedDiseases"] == {"count": 0, "rows": []}
    with pytest.raises(ResearchError) as caught:
        await invoke(monkeypatch, {"data": {"target": None}})
    assert caught.value.code == "source_not_found"


async def test_invalid_query_stops_before_outbound(monkeypatch):
    transport = Transport(response())
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: transport)
    with pytest.raises(ResearchError) as caught:
        await OpenTargetsClient()._query('query{target(ensemblId:"ENSG00000157764"){tep{name}}}')
    assert caught.value.code == "source_contract_changed" and transport.calls == []


async def test_unselected_root_identity_is_acquired_and_verified(monkeypatch):
    from biomedmcp.native.opentargets import IDENTITY_ALIAS

    query = "query($id:String!){T:target(ensemblId:$id){approvedSymbol}}"
    transport = Transport({"data": {"T": {"approvedSymbol": "BRAF", IDENTITY_ALIAS: IDENTITY}}})
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: transport)
    result = await OpenTargetsClient()._query(query, {"id": IDENTITY})
    assert result == {"T": {"approvedSymbol": "BRAF"}}
    assert IDENTITY_ALIAS in transport.calls[0][1]["json"]["query"]
    with pytest.raises(ResearchError):
        transport.payload = {"data": {"T": {"approvedSymbol": "BRAF", IDENTITY_ALIAS: "ENSG00000141510"}}}
        await OpenTargetsClient()._query(query, {"id": IDENTITY})


@pytest.mark.parametrize(
    "root,arg,identity",
    [
        ("disease", "efoId", "EFO_0000305"),
        ("drug", "chemblId", "CHEMBL1"),
        ("variant", "variantId", "7_140753336_A_T"),
        ("study", "studyId", "synthetic-study"),
    ],
)
@pytest.mark.parametrize("wrong", [False, True])
async def test_each_single_entity_root_preserves_requested_identity(monkeypatch, root, arg, identity, wrong):
    query = f"query($id:String!){{{root}({arg}:$id){{id}}}}"
    transport = Transport({"data": {root: {"id": "wrong-entity" if wrong else identity}}})
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: transport)
    if wrong:
        with pytest.raises(ResearchError) as caught:
            await OpenTargetsClient()._query(query, {"id": identity})
        assert caught.value.code == "invalid_source_response"
    else:
        assert (await OpenTargetsClient()._query(query, {"id": identity}))[root]["id"] == identity


async def test_aliases_fragments_and_directives_preserve_field_meaning(monkeypatch):
    query = "query($id:String!,$include:Boolean!){target(ensemblId:$id){id ...Identity approvedName @include(if:$include)}} fragment Identity on Target{symbol:approvedSymbol}"
    transport = Transport({"data": {"target": {"id": IDENTITY, "symbol": "BRAF"}}})
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: transport)
    result = await OpenTargetsClient()._query(query, {"id": IDENTITY, "include": False})
    assert result["target"]["symbol"] == "BRAF" and "approvedName" not in result["target"]
    with pytest.raises(ResearchError):
        await OpenTargetsClient()._query(query, {"id": IDENTITY, "include": True})


async def test_abstract_entity_requires_valid_concrete_typename(monkeypatch):
    from biomedmcp.native.opentargets import plan
    from biomedmcp.native.opentargets import response as validate_response

    query = 'query{search(queryString:"BRAF",entityNames:["target"],page:{index:0,size:1}){hits{id object{...on Target{id approvedSymbol}}}}}'
    wire, _, _ = plan(query)
    assert "__typename" in wire
    payload = {
        "data": {
            "search": {
                "hits": [
                    {
                        "id": IDENTITY,
                        "object": {"__typename": "Target", "id": IDENTITY, "approvedSymbol": "BRAF"},
                    }
                ]
            }
        }
    }
    assert validate_response(payload, query)["search"]["hits"][0]["object"]["__typename"] == "Target"
    payload["data"]["search"]["hits"][0]["object"]["__typename"] = "UnknownEntity"
    with pytest.raises(ResearchError):
        validate_response(payload, query)


@pytest.mark.parametrize(
    "damage", ["target", "ensembl_id", "associated_diseases", "symbol", "tractability", "baselineExpression"]
)
async def test_composed_profile_rejects_missing_or_foreign_scientific_fields(damage):
    from opentargets_helpers import profile
    from test_qualified_gene_identity import HUMAN

    from biomedmcp.native.identity import qualify_gene
    from biomedmcp.native.opentargets import target_profile

    payload = profile()
    if damage in {"target", "ensembl_id", "associated_diseases"}:
        payload.pop(damage)
    elif damage == "symbol":
        payload["target"]["approvedSymbol"] = "TP53"
    else:
        payload["target"].pop(damage)
    with pytest.raises(ResearchError) as caught:
        target_profile(payload, qualify_gene(HUMAN, 9606), IDENTITY)
    assert caught.value.code == "invalid_source_response"


async def test_valid_profile_keeps_nullable_expression_and_truthful_coverage():
    from opentargets_helpers import association, expression, profile
    from test_qualified_gene_identity import HUMAN

    from biomedmcp.native.identity import qualify_gene
    from biomedmcp.native.opentargets import disease_associations, druggability, target_profile

    payload = profile(rows=[association()], count=10)
    row = expression()
    row["median"] = None
    payload["target"]["baselineExpression"] = {"count": 1, "rows": [row]}
    qualified = target_profile(payload, qualify_gene(HUMAN, 9606), IDENTITY)
    assert qualified["target"]["baselineExpression"]["rows"][0]["median"] is None
    assert disease_associations(qualified)["coverage"]["exhaustive"] is False
    assert druggability(qualified)["tractability"] == payload["target"]["tractability"]
    assert "causality" in " ".join(qualified["warnings"])


async def test_actual_mcp_retry_cache_and_recovery_preserves_scientific_fields(monkeypatch):
    import json

    from fastmcp import Client
    from opentargets_helpers import expression, profile, project
    from test_qualified_gene_identity import HUMAN

    from biomedmcp.adapters import SourceAdapters
    from biomedmcp.mcp.server import create_server

    class Adapters(SourceAdapters):
        async def call(self, source, operation, params):
            if source == "mygene":
                return {"hits": [deepcopy(HUMAN)]}
            return await super().call(source, operation, params)

    source = profile()
    rows = [expression(i) for i in range(30)]
    source["target"]["baselineExpression"] = {"count": 30, "rows": rows}
    full = {"data": {"target": {**source["target"], "associatedDiseases": source["associated_diseases"]}}}

    class Provider(Transport):
        async def post(self, url, **kwargs):
            if self.calls:
                self.payload = project(full, kwargs["json"]["query"])
            return await super().post(url, **kwargs)

    provider = Provider({})
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    arguments = {
        "entity": "gene",
        "id": "673",
        "sections": ["record", "target_evidence", "diseases", "druggability"],
    }
    async with Client(create_server(service=ResearchService(adapters=Adapters()))) as client:
        failed = (await client.call_tool("get", arguments)).data
        good = (await client.call_tool("get", arguments)).data
        cached = (await client.call_tool("get", arguments)).data
        assert failed["outcome"] == "partial" and failed["sections"]["record"]["outcome"] == "data"
        for name in ("target_evidence", "diseases", "druggability"):
            assert failed["sections"][name]["error"]["code"] == "invalid_source_response"
            assert failed["sections"][name]["evidence_ids"] == []
        section = good["sections"]["target_evidence"]
        omission = next(
            o for o in section["recovery"]["omissions"] if o["pointer"] == "/target/baselineExpression/rows"
        )
        recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
        assert recovered["value"] == rows[25:] and recovered["evidence_ids"] == section["evidence_ids"]
        assert cached["sections"]["target_evidence"]["evidence_ids"] == section["evidence_ids"]
        assert all(p["cached"] for p in cached["provenance"] if p["source"] == "opentargets")
    assert len(provider.calls) == 3


async def test_malformed_row_beyond_display_bound_is_rejected_before_evidence():
    from opentargets_helpers import expression, profile
    from test_qualified_gene_identity import HUMAN

    from biomedmcp.native.identity import qualify_gene
    from biomedmcp.native.opentargets import target_profile

    payload = profile()
    payload["target"]["baselineExpression"] = {"count": 26, "rows": [expression(i) for i in range(25)] + [{}]}
    with pytest.raises(ResearchError) as caught:
        target_profile(payload, qualify_gene(HUMAN, 9606), IDENTITY)
    assert caught.value.code == "invalid_source_response"


async def test_merged_root_fields_follow_graphql_semantics_without_mutating_source():
    from biomedmcp.native.opentargets import IDENTITY_ALIAS
    from biomedmcp.native.opentargets import response as validate_response

    query = "query($id:String!){target(ensemblId:$id){approvedSymbol} target(ensemblId:$id){approvedName}}"
    payload = {
        "data": {
            "target": {"approvedSymbol": "BRAF", "approvedName": "Synthetic name", IDENTITY_ALIAS: IDENTITY}
        }
    }
    before = deepcopy(payload)
    result = validate_response(payload, query, {"id": IDENTITY})
    assert result == {"target": {"approvedSymbol": "BRAF", "approvedName": "Synthetic name"}}
    assert payload == before
