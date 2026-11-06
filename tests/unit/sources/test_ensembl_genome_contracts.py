"""Genome metadata acquisition through the actual adapter, with synthetic HTTP."""

from copy import deepcopy

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError

ASSEMBLY = {
    "assembly_name": "SyntheticAssembly",
    "assembly_accession": None,
    "karyotype": ["1", "X"],
    "top_level_region": [{"name": "1", "coord_system": "chromosome", "length": 100}],
}


@pytest.fixture
def genome_http(monkeypatch):
    original = httpx.AsyncClient
    state = {"payload": deepcopy(ASSEMBLY), "requests": []}

    def respond(request):
        assert request.url.host == "rest.ensembl.org"
        state["requests"].append(request)
        if isinstance(state["payload"], Exception):
            raise state["payload"]
        return httpx.Response(200, json=state["payload"])

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    return state


async def genome(info_type, species="homo_sapiens"):
    return await SourceAdapters().call(
        "ensembl", "get_genome_info", {"info_type": info_type, "species": species}
    )


async def test_karyotype_uses_assembly_and_keeps_context(genome_http):
    result = await genome("karyotype", "mouse")
    assert genome_http["requests"][0].url.path == "/info/assembly/mus_musculus"
    assert result == {
        "species": "mus_musculus",
        "assembly_name": "SyntheticAssembly",
        "karyotype": ["1", "X"],
        "assembly": ASSEMBLY,
    }


async def test_explicit_empty_karyotype_preserves_assembly(genome_http):
    genome_http["payload"]["karyotype"] = []
    result = await genome("karyotype")
    assert result["karyotype"] == []
    assert result["assembly"]["top_level_region"] == ASSEMBLY["top_level_region"]


@pytest.mark.parametrize("info_type", ["assembly", "karyotype"])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"error": "synthetic-credential-sentinel"},
        {**ASSEMBLY, "assembly_name": None},
        {**ASSEMBLY, "karyotype": None},
        {**ASSEMBLY, "karyotype": [None]},
        {**ASSEMBLY, "top_level_region": None},
        {**ASSEMBLY, "top_level_region": [{}]},
        {**ASSEMBLY, "top_level_region": [{"name": "1", "coord_system": "chromosome", "length": True}]},
    ],
)
async def test_malformed_assembly_fails_before_evidence(genome_http, info_type, payload):
    genome_http["payload"] = payload
    with pytest.raises(ResearchError) as failure:
        await genome(info_type)
    assert failure.value.code == "invalid_source_response"
    assert "synthetic-credential-sentinel" not in str(failure.value)


async def test_species_catalog_uses_explicit_collection(genome_http):
    genome_http["payload"] = {"species": [{"name": "mus_musculus", "assembly": "SyntheticAssembly"}]}
    assert await genome("species") == genome_http["payload"]
    assert genome_http["requests"][0].url.path == "/info/species"


@pytest.mark.parametrize("payload", [{}, None, {"species": None}, {"species": [{}]}])
async def test_malformed_species_catalog_fails(genome_http, payload):
    genome_http["payload"] = payload
    with pytest.raises(ResearchError) as failure:
        await genome("species")
    assert failure.value.code == "invalid_source_response"


async def test_species_path_injection_rejected_without_http(genome_http):
    with pytest.raises(ResearchError) as failure:
        await genome("assembly", "homo_sapiens/other?x=1")
    assert failure.value.code == "invalid_parameters"
    assert genome_http["requests"] == []


async def test_network_exception_is_sanitized_before_adapter_logging(genome_http, caplog):
    sentinel = "synthetic-credential-sentinel"
    genome_http["payload"] = httpx.ConnectError(f"provider failed with api_key={sentinel}")
    with pytest.raises(ResearchError) as failure:
        await genome("assembly")
    assert failure.value.code == "source_unavailable"
    assert sentinel not in caplog.text + str(failure.value)


async def test_public_failure_retries_without_cached_empty_evidence(genome_http, monkeypatch):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    params = {"source": "ensembl", "operation": "get_genome_info", "params": {"info_type": "assembly"}}
    genome_http["payload"] = {}
    async with Client(create_server(service=ResearchService())) as client:
        failed = (await client.call_tool("query_source", params, raise_on_error=False)).structured_content
        assert failed["outcome"] == "error"
        assert failed["sections"]["ensembl"]["error"]["code"] == "invalid_source_response"
        assert failed["records"] == [] and failed["provenance"] == []
        genome_http["payload"] = deepcopy(ASSEMBLY)
        recovered = (await client.call_tool("query_source", params)).data
        assert recovered["outcome"] == "data"
        assert recovered["sections"]["ensembl"]["data"] == ASSEMBLY
        assert recovered["provenance"]
    assert len(genome_http["requests"]) == 2
