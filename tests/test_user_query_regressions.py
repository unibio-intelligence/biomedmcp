"""Regression coverage for realistic research requests observed in production."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from native_helpers import HTTP
from test_live_contract_regressions import DiseaseAdapters
from test_research_contracts import Adapters

from biomedmcp.contracts import Entity, ResearchResult
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.evidence import scientific_outcome
from biomedmcp.native.providers import NativeProviders
from biomedmcp.output_contracts import validate_output
from biomedmcp.receipts import verify_receipt


@pytest.mark.parametrize("resolution", [[1.74], {"value": 1.74}, None, 1.74])
def test_source_measurements_named_resolution_are_not_identity_statuses(resolution):
    assert scientific_outcome({"resolution": resolution, "pdb_id": "4hhb"}) == "data"


async def test_structure_quality_retains_resolution_and_partial_validation_status():
    class QualityAdapters(Adapters):
        async def call(self, source, operation, params):
            return {
                "pdb_id": "4hhb",
                "resolution": [1.74],
                "resolution_units": "angstroms",
                "section_outcomes": {"validation_summary": {"outcome": "unavailable"}},
            }

    result = await execute(
        ResearchService(adapters=QualityAdapters()),
        "query_source",
        {"source": "pdb", "operation": "get_structure_quality", "params": {"pdb_id": "4HHB"}},
        scope="public",
    )
    assert result.outcome == "partial"
    assert result.sections["pdb"].data["resolution"] == [1.74]
    wire = result.model_dump(mode="json")
    validate_output("query_source", wire)
    assert verify_receipt(wire)


@pytest.mark.parametrize(
    "failure", [ValueError("private value"), TypeError("private value"), KeyError("private value")]
)
async def test_sanitized_adapter_failures_still_satisfy_public_error_schema(failure):
    class FailedAdapters(Adapters):
        async def call(self, *args):
            raise failure

    result = await execute(
        ResearchService(adapters=FailedAdapters()),
        "query_source",
        {"source": "pdb", "operation": "get_structure_quality", "params": {"pdb_id": "4HHB"}},
        scope="public",
    )
    wire = result.model_dump(mode="json")
    validate_output("query_source", wire)
    assert result.sections["pdb"].error["correction"]
    assert "private value" not in str(wire)
    assert verify_receipt(wire)


@pytest.mark.parametrize("query", ["warfarin", "CYP2C9", "sodium warfarin", "drug,or.(name)"])
async def test_pgx_discovery_searches_gene_and_drug_without_reinterpreting_filters(query):
    http = HTTP([{"pairid": 1, "genesymbol": "CYP2C9", "drugname": "warfarin"}])
    result = await NativeProviders(Adapters(), http).search("pgx", "cpic", query, {}, 3, 3)
    assert result[0]["genesymbol"] == "CYP2C9"
    params = http.calls[0][2]["params"]
    assert "genesymbol" not in params and "drugname" not in params
    assert "genesymbol.eq." in params["or"] and "drugname.ilike." in params["or"]
    assert params["order"] == "pairid.asc" and params["offset"] == 3


async def test_pgx_explicit_gene_and_drug_filters_remain_conjunctive():
    http = HTTP([])
    await NativeProviders(Adapters(), http).search(
        "pgx", "cpic", "warfarin", {"gene": "CYP2C9", "drug": ["warfarin"], "cpic_level": "A"}, 3, 0
    )
    params = http.calls[0][2]["params"]
    assert params["genesymbol"] == "eq.CYP2C9" and params["drugname"] == "ilike.*warfarin*"
    assert params["cpiclevel"] == "eq.A" and "or" not in params


@pytest.mark.parametrize("relation", ["articles", "trials"])
async def test_disease_relations_discover_with_verified_label_and_retain_identity_proof(relation):
    service = ResearchService(adapters=DiseaseAdapters())
    service.search = AsyncMock(return_value=ResearchResult(outcome="data", query={"execution": {}}))
    result = await service.relate(Entity.disease, "MONDO:0005105", relation, scope="public")
    assert service.search.call_args.args[0].query == "melanoma"
    assert result.query["qualified_identity"] == {
        "id": "MONDO:0005105",
        "label": "melanoma",
        "source": "mydisease",
    }
    assert result.query["execution"]["identity_dependencies"] == ["mydisease"]
    assert any(p.source == "mydisease" for p in result.provenance)


@pytest.mark.parametrize(
    "record",
    [
        {"_id": "MONDO:wrong", "name": "melanoma"},
        {"_id": "MONDO:0005105", "mondo": {"mondo": "MONDO:wrong", "label": "melanoma"}},
        {"_id": "MONDO:0005105", "mondo": {"mondo": "MONDO:0005105", "label": ""}},
    ],
)
async def test_disease_identity_failure_prevents_unqualified_discovery(record):
    service = ResearchService(adapters=DiseaseAdapters(record))
    service.search = AsyncMock(return_value=ResearchResult(outcome="empty"))
    result = await service.relate(Entity.disease, "MONDO:0005105", "trials", scope="public")
    service.search.assert_not_awaited()
    assert result.outcome == "error" and result.sections["identity"].error["code"] == "unresolved_identity"


async def test_disease_dossier_literature_uses_the_same_qualified_label():
    service = ResearchService(adapters=DiseaseAdapters())
    service.search = AsyncMock(return_value=ResearchResult(outcome="empty", query={"execution": {}}))
    service.get = AsyncMock(return_value=ResearchResult(outcome="data"))
    await service.research("disease_landscape", "MONDO:0005105", scope="public", sections=["record"])
    assert service.search.await_count == 2
    assert all(call.args[0].query == "melanoma" for call in service.search.await_args_list)


async def test_gene_only_pgx_cursors_are_rejected_before_provider_egress():
    from biomedmcp.contracts import SearchRequest
    from biomedmcp.errors import ResearchError
    from biomedmcp.native import REVISION

    service = ResearchService()
    request = SearchRequest(entity="pgx", query="warfarin", limit=3)
    old = {
        **request.model_dump(mode="json", exclude={"cursor", "freshness"}),
        "implementation": REVISION,
        "contract": "2.0",
    }
    old["filters"].pop("species", None)
    cursor = service.runtime.cursors.encode(query=old, scope="public", offset=3)
    with pytest.raises(ResearchError) as error:
        await service.search(request.model_copy(update={"cursor": cursor}), scope="public", _plan_only=True)
    assert error.value.code == "invalid_cursor"


async def test_cpic_cache_projection_cannot_reuse_gene_only_empty_results(monkeypatch):
    from biomedmcp.native import REVISION

    service = ResearchService(adapters=Adapters())
    params = {"query": "warfarin"}
    original = service.runtime.invoke
    keys = []

    async def invoked(source, request, call, **kwargs):
        keys.append(deepcopy(request))
        return await original(source, request, call, **kwargs)

    monkeypatch.setattr(service.runtime, "invoke", invoked)
    producer = AsyncMock(return_value=[{"pairid": 1, "drugname": "warfarin"}])
    old = {"operation": "search:pgx", "params": params, "version": None, "implementation": REVISION}
    await original("cpic", old, AsyncMock(return_value=[]), scope="public")
    first, _ = await service._invoke("cpic", "search:pgx", params, producer, scope="public")
    second, proof = await service._invoke("cpic", "search:pgx", params, producer, scope="public")
    assert first.data and second.data and proof.cached
    assert keys[0]["projection"] == "cpic-gene-drug-discovery-v1"
    producer.assert_awaited_once()
