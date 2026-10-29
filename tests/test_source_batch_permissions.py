"""Actual shipped permissions, canonical MCP reads, exclusions and cache gates."""

import json

import httpx
import pytest
from fastmcp import Client
from interpro_helpers import body, protein

from biomedmcp import source_licensing, transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions

ASSEMBLY = {
    "assembly_name": "GRCh38.p14",
    "karyotype": ["1"],
    "top_level_region": [
        {
            "name": "1",
            "coord_system": "chromosome",
            "length": 248956422,
            "restricted_annotation": "restricted-sentinel",
        }
    ],
    "unqualified_annotation": "restricted-sentinel",
}
RECALL = {
    "recall_number": "D-1234-2026",
    "classification": "Class II",
    "report_date": "20261013",
    "reason_for_recall": "restricted-sentinel",
    "product_description": "restricted-sentinel",
    "openfda": {"GMDN": "restricted-sentinel"},
}


def mock_http(monkeypatch, respond):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return respond(request)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    return calls


async def test_ensembl_scoped_catalog_and_projection_survive_cache_without_annotations(monkeypatch):
    calls = mock_http(monkeypatch, lambda r: httpx.Response(200, json=ASSEMBLY))
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        capability = (await client.call_tool("capabilities", {"source": "ensembl"})).data
        assert "get_genome_info" in [op["name"] for op in capability["operations"]]
        assert "get_sequences" in [op["name"] for op in capability["operations"]]
        args = {"source": "ensembl", "operation": "get_genome_info", "params": {"info_type": "assembly"}}
        for _ in range(2):
            result = (await client.call_tool("query_source", args)).data
            assert result["outcome"] == "data" and result["provenance"]
            assert result["sections"]["ensembl"]["data"]["top_level_region"][0]["length"] == 248956422
            assert "restricted-sentinel" not in json.dumps(result)
    assert len(calls) == 1 and calls[0].url.path == "/info/assembly/homo_sapiens"


def test_ensembl_existing_operations_enabled_with_conditional_notice():
    assert source_licensing.operation_allowed("ensembl", "get_sequences")
    assert "conditional" in source_licensing.notice("ensembl")


async def test_interpro_primary_projection_excludes_member_content_before_cache(monkeypatch):
    page = body()
    page["results"][0]["metadata"]["member_databases"] = {"smart": {"SM001": "restricted-sentinel"}}
    page["results"][0]["metadata"]["unqualified"] = "restricted-sentinel"
    page["results"][0]["proteins"][0]["entry_protein_locations"][0]["model"] = "restricted-sentinel"

    def respond(request):
        if request.url.host == "rest.uniprot.org":
            return httpx.Response(200, json=protein())
        assert request.url.path == "/interpro/api/entry/interpro/protein/uniprot/P15056/"
        return httpx.Response(200, json=page, headers={"InterPro-Version": "110.0"})

    calls = mock_http(monkeypatch, respond)
    async with Client(create_server(service=ResearchService())) as client:
        args = {"entity": "protein", "id": "P15056", "sections": ["domains"]}
        for _ in range(2):
            result = (await client.call_tool("get", args)).data
            assert result["provenance"][0]["sources"] == ["interpro", "uniprot"]
            row = result["sections"]["domains"]["data"]["records"][0]
            assert row["metadata"]["accession"] == "IPR000719"
            assert "member_databases" not in row["metadata"] and "go_terms" not in row["metadata"]
            assert "restricted-sentinel" not in json.dumps(result)
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 1


async def test_openfda_drug_recalls_are_facts_with_excluded_content(monkeypatch):
    calls = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"results": [RECALL]}))
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "openfda", "operation": "search_recalls", "params": {"query": "aspirin"}},
            )
        ).data
        assert result["outcome"] == "data" and result["provenance"]
        assert "restricted-sentinel" not in json.dumps(result)
    assert len(calls) == 1 and calls[0].url.path == "/drug/enforcement.json"


@pytest.mark.parametrize("endpoint", ["device/udi", "food/enforcement"])
async def test_openfda_exceptions_never_reach_http(monkeypatch, endpoint):
    calls = mock_http(monkeypatch, lambda r: pytest.fail("Held endpoint reached HTTP"))
    from openfda_mcp.server import fda_api_request

    with pytest.raises(ResearchError) as error:
        await fda_api_request(endpoint)
    assert error.value.code == "source_license_unreleased" and not calls


async def test_mygene_queries_request_only_selected_fields_and_drop_unrequested_data(monkeypatch):
    row = {
        "_id": "7157",
        "symbol": "TP53",
        "name": "tumor protein p53",
        "taxid": 9606,
        "entrezgene": 7157,
        "ensembl": {"gene": "ENSG00000141510"},
        "disease": {"umls": "restricted-sentinel"},
    }
    calls = mock_http(monkeypatch, lambda r: httpx.Response(200, json={"hits": [row], "total": 1}))
    service = ResearchService()
    gene = await service.providers.gene("TP53")
    assert gene["qualified_identity"]["symbol"] == "TP53"
    assert "restricted-sentinel" not in json.dumps(gene)
    assert "disease" not in calls[0].url.params["fields"]


async def test_mygene_arbitrary_fields_are_blocked_before_http(monkeypatch):
    calls = mock_http(monkeypatch, lambda r: pytest.fail("Unqualified fields reached provider"))
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("mygene", "query_genes", {"query": "TP53", "fields": "umls,disease"})
    assert error.value.code == "source_license_unreleased" and not calls


@pytest.mark.parametrize(
    "source",
    ["ensembl", "interpro", "openfda", "fda-devices", "mygene", "gwas", "ncbi", "ncbi-records", "study"],
)
def test_primary_grants_have_explicit_scopes_and_notices(source):
    assert source_licensing.availability(source) == (True, None)
    assert source_licensing.review(source)["scope"]
    assert source_licensing.notice(source, retrieved_at="2026-10-13")


@pytest.mark.parametrize("license", ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "unknown"])
def test_enabling_study_engine_cannot_enable_restrictive_releases(license):
    from biomedmcp.study_installation import require_data_rights

    with pytest.raises(ResearchError):
        require_data_rights(
            {
                "data_rights": {
                    "license": license,
                    "evidence_url": "https://example.org/terms",
                    "scope": "all_declared_files",
                }
            }
        )


@pytest.mark.parametrize("license", ["CC-BY-SA-3.0", "CC-BY-SA-4.0", "ODbL-1.0"])
def test_share_alike_study_rights_are_accepted(license):
    from biomedmcp.study_installation import require_data_rights

    require_data_rights(
        {
            "data_rights": {
                "license": license,
                "evidence_url": "https://example.org/license",
                "scope": "all_declared_files",
            }
        }
    )


def test_annotation_projection_removes_only_documented_held_fields():
    from biomedmcp.native.annotation_permissions import projection

    original = {
        "hits": [
            {
                "_id": "x",
                "sider": {"effect": "restricted"},
                "umls": "restricted",
                "drugcentral": {"name": "allowed"},
                "unknown_contributor": {"value": "unresolved"},
            }
        ]
    }
    value = projection("mychem", original)
    assert "restricted" not in json.dumps(value)
    assert value["hits"][0]["unknown_contributor"]["value"] == "unresolved"
    assert value["hits"][0]["drugcentral"]["name"] == "allowed"
    assert "sider" in original["hits"][0]


@pytest.mark.parametrize("source,entity", [("mychem", "drug"), ("mydisease", "disease")])
async def test_annotation_namespace_exclusions_survive_cache_and_evidence(monkeypatch, source, entity):
    identifier = "AAAAAAAAAAAAAA-BBBBBBBBBB-C" if source == "mychem" else "MONDO:0000001"
    held = {"umls"} | ({"sider"} if source == "mychem" else set())
    row = {
        "_id": identifier,
        "name": "Synthetic record",
        "umls_like": "allowed-lookalike",
        "siderophore": "allowed-lookalike",
        "other.umls": "allowed-other-namespace",
        "annotations": [{"allowed": "retained"}],
    }
    for namespace in held:
        row[namespace] = {"name": "restricted-sentinel"}
        row[namespace.upper() + ".name"] = "restricted-sentinel"
        row["annotations"][0][namespace + ".name"] = "restricted-sentinel"
    calls = mock_http(monkeypatch, lambda request: httpx.Response(200, json=row))
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        for cached in (False, True):
            result = (await client.call_tool("get", {
                "entity": entity, "id": identifier, "sections": ["record"],
            })).data
            assert result["outcome"] == "data"
            assert result["provenance"][0]["cached"] is cached
            section = result["sections"]["record"]
            visible = json.dumps(section["data"])
            assert "restricted-sentinel" not in visible
            assert "allowed-lookalike" in visible and "allowed-other-namespace" in visible
            assert "retained" in visible
            recovered = await service.read_evidence(section["recovery"]["uri"], scope="local")
            assert recovered["value"] == section["data"]
            assert "restricted-sentinel" not in json.dumps(recovered)
    assert len(calls) == 1


@pytest.mark.parametrize("source", ["mychem", "mydisease"])
async def test_annotation_namespace_exclusions_precede_provider_cache(monkeypatch, source):
    from biomedmcp.native.biothings import BioThingsClient

    row = {"_id": "synthetic", "umls.cui": "restricted-sentinel", "umls_like": "retained"}
    if source == "mychem":
        row["sider.effect"] = "restricted-sentinel"
    calls = mock_http(monkeypatch, lambda request: httpx.Response(200, json=row))
    provider = BioThingsClient("https://example.org", rate_limit=0)
    provider.source = source
    endpoint = "chem/synthetic" if source == "mychem" else "disease/synthetic"
    for _ in range(2):
        result = await provider.get(endpoint)
        assert result == {"_id": "synthetic", "umls_like": "retained"}
    assert len(calls) == 1
    assert all("restricted-sentinel" not in json.dumps(entry.data) for entry in provider._cache.values())


async def test_openfda_recall_schema_describes_only_supported_drug_scope():
    service = ResearchService()
    capability = await service.capabilities(source="openfda")
    operation = next(op for op in capability["operations"] if op["name"] == "search_recalls")
    field = operation["input_schema"]["properties"]["recall_type"]
    assert field["enum"] == ["drug"]
    assert "device" not in field["description"] and "food" not in field["description"]
    assert "drug" in operation["description"]


@pytest.mark.parametrize("source,entity", [("mychem", "drug"), ("mydisease", "disease")])
async def test_source66_cached_annotations_and_evidence_cannot_survive_upgrade(monkeypatch, source, entity):
    from biomedmcp import domain, recovery
    from biomedmcp.native import REVISION, annotation_permissions, biothings

    assert REVISION != "biomedmcp/0.1.0"
    identifier = "AAAAAAAAAAAAAA-BBBBBBBBBB-C" if source == "mychem" else "MONDO:0000001"
    row = {"_id": identifier, "umls.cui": "restricted-sentinel", "name": "Retained name"}
    if source == "mychem":
        row["sider.effect"] = "restricted-sentinel"
    calls = mock_http(monkeypatch, lambda request: httpx.Response(200, json=row))
    service = ResearchService()
    arguments = {"entity": entity, "id": identifier, "sections": ["record"]}
    async with Client(create_server(service=service)) as client:
        # Recreate the preceding implementation's actual cache and snapshot keys.
        with monkeypatch.context() as old:
            old.setattr(domain, "REVISION", "biomedmcp/0.1.0")
            old.setattr(recovery, "REVISION", "biomedmcp/0.1.0")
            old.setattr(annotation_permissions, "projection", lambda source, value: value)
            old.setattr(biothings, "permission_projection", lambda source, value: value)
            historic = (await client.call_tool("get", arguments)).data
            cached = (await client.call_tool("get", arguments)).data
            assert cached["provenance"][0]["cached"]
            assert "restricted-sentinel" in json.dumps(cached["sections"]["record"]["data"])
            uri = historic["sections"]["record"]["recovery"]["uri"]
            assert "restricted-sentinel" in json.dumps(await service.read_evidence(uri, scope="local"))
        assert len(calls) == 1
        fresh = (await client.call_tool("get", arguments)).data
        assert not fresh["provenance"][0]["cached"] and len(calls) == 2
        assert "restricted-sentinel" not in json.dumps(fresh)
        assert "Retained name" in json.dumps(fresh["sections"]["record"]["data"])
        with pytest.raises(ResearchError) as error:
            await service.read_evidence(uri, scope="local")
        assert error.value.code == "evidence_unavailable"
