"""Synthetic current NCBI orthology/virus contracts; no source permissions inferred."""

import hashlib
import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from ncbi_helpers import documented_request

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.catalog import ADVANCED

PARAMS = {"gene_id": 123456, "source_tax_id": 9606, "target_tax_ids": [10090], "max_results": 2}
SOURCE = {
    "gene": {
        "gene_id": "123456",
        "tax_id": "9606",
        "symbol": "SYNTHETIC_HUMAN",
        "gene_groups": [{"id": "100", "method": "NCBI Ortholog"}],
        "protein_count": 0,
    }
}
TARGET = {
    "gene": {
        "gene_id": "234567",
        "tax_id": "10090",
        "symbol": "SYNTHETIC_MOUSE",
        "gene_groups": [{"id": "100", "method": "NCBI Ortholog"}],
    }
}
VIRUS = {
    "accession": "NC_999999.1",
    "virus": {"tax_id": 12345, "organism_name": "Synthetic virus"},
    "is_annotated": False,
    "is_complete": False,
    "length": 100,
    "protein_count": 0,
}


def page(rows, total=None, token=None):
    result = {"reports": deepcopy(rows), "total_count": len(rows) if total is None else total}
    if token:
        result["next_page_token"] = token
    return result


@pytest.fixture
def ncbi_http(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    requests = []

    def install(body, *, source=None):
        def handler(request):
            requests.append(request)
            documented_request(request)
            if "/gene/" in request.url.path and request.url.path.endswith("/dataset_report"):
                response = source if source is not None else page([SOURCE])
            else:
                response = body(request) if callable(body) else body
            return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters(), requests

    return install


async def test_reported_group_assertions_preserve_source_identity_and_no_similarity(ncbi_http):
    adapter, requests = ncbi_http(page([TARGET]))
    result = await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert [request.url.path for request in requests] == [
        "/datasets/v2/gene/id/123456/dataset_report",
        "/datasets/v2/gene/id/123456/orthologs",
    ]
    assert requests[1].url.params["taxon_filter"] == "10090"
    assert "similarity_threshold" not in requests[1].url.params
    assertion = result["relationship_assertions"][0]
    assert (
        assertion["assertion_type"] == "provider_inferred_orthology"
        and assertion["method"] == "NCBI Ortholog"
    )
    assert assertion["source_gene_id"] == "123456" and assertion["target_tax_id"] == "10090"
    assert assertion["group_ids"] == ["100"]
    assert assertion["sequence_identity_percent"] is None and assertion["functional_equivalence"] is None
    assert len(assertion["inputs"]) == 2 and assertion["inputs"][1]["locator"] == "/reports/0"
    expected = hashlib.sha256(json.dumps(TARGET, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert assertion["inputs"][1]["record_sha256"] == expected and assertion["inputs"][1]["time_dependent"]
    assert result["status"] == "partial"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"error": "synthetic-key-sentinel"},
        {"reports": []},
        {"reports": [TARGET], "total_count": 0},
        {"reports": [TARGET], "total_count": True},
        {"reports": [TARGET], "total_count": -1},
        {"reports": [TARGET], "total_count": 3},
        {"reports": [], "total_count": 1},
        {"reports": [None], "total_count": 1},
        {"reports": [TARGET], "total_count": 1, "next_page_token": " "},
        {
            "reports": [TARGET],
            "total_count": 1,
            "messages": [{"error": {"reason": "synthetic-key-sentinel"}}],
        },
    ],
)
async def test_bad_ortholog_envelopes_are_not_healthy_empty(ncbi_http, payload):
    adapter, _ = ncbi_http(payload)
    with pytest.raises(ResearchError) as caught:
        await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert caught.value.code == "invalid_source_response"
    assert "synthetic-key-sentinel" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"gene_id": "123457"},
        {"tax_id": "10090"},
        {"gene_id": "0"},
        {"tax_id": 9606},
        {"symbol": ""},
        {"gene_groups": [{}]},
    ],
)
async def test_source_identity_fails_before_ortholog_acquisition(ncbi_http, changes):
    row = deepcopy(SOURCE)
    row["gene"].update(changes)
    adapter, requests = ncbi_http(page([TARGET]), source=page([row]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [page([]), page([SOURCE, TARGET]), page([SOURCE], 2, "more")])
async def test_source_identity_never_selects_first_candidate(ncbi_http, payload):
    adapter, requests = ncbi_http(page([TARGET]), source=payload)
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"gene_id": 234567},
        {"tax_id": "0"},
        {"symbol": None},
        {"gene_groups": [None]},
        {"gene_groups": [{"id": "100", "method": None}]},
        {"protein_count": -1},
        {"transcript_count": True},
        {"ensembl_gene_ids": [None]},
        {"swiss_prot_accessions": [""]},
    ],
)
async def test_every_target_row_validated_before_filtering(ncbi_http, changes):
    bad = deepcopy(TARGET)
    bad["gene"]["gene_id"] = "345678"
    bad["gene"].update(changes)
    bad["gene"]["tax_id"] = "10116" if "tax_id" not in changes else changes["tax_id"]
    adapter, _ = ncbi_http(page([TARGET, bad]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "find_orthologs", PARAMS)


@pytest.mark.parametrize(
    "groups",
    [[], [{"id": "101", "method": "NCBI Ortholog"}], [{"id": "100", "method": "different inference"}]],
)
async def test_missing_conflicting_and_other_groups_remain_unqualified(ncbi_http, groups):
    row = deepcopy(TARGET)
    row["gene"]["gene_groups"] = groups
    adapter, _ = ncbi_http(page([row]))
    result = await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert result["records"] == [row] and not result["relationship_assertions"]
    assert result["unqualified_candidates"][0]["reason"] == "shared_reported_ortholog_group_unavailable"


async def test_source_and_other_taxa_filtered_without_losing_raw_continuation(ncbi_http):
    other = deepcopy(TARGET)
    other["gene"].update(gene_id="345678", tax_id="10116")
    adapter, _ = ncbi_http(page([SOURCE, other], 3, "next-page"))
    result = await adapter.call("ncbi", "find_orthologs", PARAMS)
    assert result["records"] == [] and result["_provider_page"]["continuation"] == "next-page"
    assert result["_provider_page"]["raw_count"] == 2 and result["_provider_page"]["filtered_count"] == 2
    assert (
        result["source_window_records"] == [SOURCE, other]
        and result["unqualified_candidates"][0]["record"] == other
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"gene_id": True},
        {"source_tax_id": 0},
        {"target_tax_ids": []},
        {"target_tax_ids": [10090, 10090]},
        {"target_tax_ids": [9606]},
        {"target_tax_ids": [False]},
        {"gene_id": 1 << 64},
        {"max_results": 26},
        {"page_token": ""},
        {"similarity_threshold": 80},
        {"gene_symbol": "BRAF"},
    ],
)
async def test_invalid_and_retired_ortholog_arguments_fail_before_http(ncbi_http, changes):
    adapter, requests = ncbi_http(page([TARGET]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "find_orthologs", PARAMS | changes)
    assert not requests


async def test_actual_public_mcp_partial_continuation_cache_and_recovery(ncbi_http):
    token = "t" * 8192

    def handler(request):
        if "page_token" in request.url.params:
            assert request.url.params["page_token"] == token
            return page([TARGET], 2)
        return page([SOURCE], 2, token)

    adapter, requests = ncbi_http(handler)
    params = PARAMS | {"max_results": 1}
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        first = (
            await client.call_tool(
                "query_source", {"source": "ncbi", "operation": "find_orthologs", "params": params}
            )
        ).data
        assert first["outcome"] == "partial"
        action = first["next_actions"][0]
        assert action["arguments"]["params"] == params | {"page_token": token}
        following = (await client.call_tool(action["tool"], action["arguments"])).data
        assert following["outcome"] == "partial" and not following["next_actions"]
        assertions = following["sections"]["ncbi"]["data"]["relationship_assertions"]
        assert len(assertions) == 1 and assertions[0]["inputs"][1]["locator"] == "/reports/0"
        assert "_provider_page" not in following["sections"]["ncbi"]["data"]
    assert len(requests) == 4


async def test_actual_public_mcp_invalid_is_uncached_and_provider_recovery_succeeds(ncbi_http):
    hits = []

    def handler(request):
        hits.append(request)
        return {"error": "synthetic-key-sentinel"} if len(hits) == 1 else page([TARGET])

    adapter, _ = ncbi_http(handler)
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        args = {"source": "ncbi", "operation": "find_orthologs", "params": PARAMS}
        failed = await client.call_tool("query_source", args, raise_on_error=False)
        bad = json.loads(failed.content[0].text)
        good = (await client.call_tool("query_source", args)).data
    assert bad["outcome"] == "error" and bad["sections"]["ncbi"]["error"]["code"] == "invalid_source_response"
    assert good["outcome"] == "partial" and len(hits) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"accession": "NC_999999"},
        {"accession": "NC_999999.1/other"},
        {"tax_id": False},
        {"include_proteins": True},
    ],
)
async def test_virus_arguments_fail_before_io(ncbi_http, changes):
    adapter, requests = ncbi_http(page([VIRUS]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "get_virus_info", {"accession": "NC_999999.1"} | changes)
    assert not requests


async def test_virus_report_current_route_nullable_counts_and_reported_zero(ncbi_http):
    adapter, requests = ncbi_http(page([VIRUS]))
    result = await adapter.call("ncbi", "get_virus_info", {"accession": "NC_999999.1", "tax_id": 12345})
    assert requests[0].url.path == "/datasets/v2/virus/accession/NC_999999.1/dataset_report"
    assert set(requests[0].url.params) == {"returned_content", "page_size"}
    assert result["records"] == [VIRUS]
    assert result["reported_counts"][0] == {
        "length": 100,
        "protein_count": 0,
        "gene_count": None,
        "mature_peptide_count": None,
    }
    assert result["records_provenance"][0]["time_dependent"]


@pytest.mark.parametrize(
    "changes",
    [
        {"accession": "NC_999999.2"},
        {"virus": {"tax_id": 54321, "organism_name": "Other"}},
        {"virus": {"tax_id": True}},
        {"virus": {}},
        {"virus": {"tax_id": 12345, "organism_name": " "}},
        {"length": 0},
        {"length": "100"},
        {"protein_count": -1},
        {"gene_count": True},
        {"is_annotated": "false"},
    ],
)
async def test_virus_identity_and_known_measurements_cannot_silently_change(ncbi_http, changes):
    adapter, _ = ncbi_http(page([VIRUS | changes]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "get_virus_info", {"accession": "NC_999999.1", "tax_id": 12345})


async def test_virus_explicit_empty_report_and_multiple_identity_fail_closed(ncbi_http):
    adapter, _ = ncbi_http(page([]))
    empty = await adapter.call("ncbi", "get_virus_info", {"accession": "NC_999999.1"})
    assert empty["records"] == [] and empty["pagination"]["accessible_window_exhausted"]
    adapter, _ = ncbi_http(page([VIRUS, VIRUS]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "get_virus_info", {"accession": "NC_999999.1"})


async def test_retired_routes_are_absent_from_registry_and_backend_catalog():
    names = {row["name"] for row in await SourceAdapters().catalog("ncbi")}
    retired = {"compare_genomes", "get_database_stats", "get_phylogenetic_tree", "get_gene_data"}
    assert not names & retired and not ADVANCED["ncbi"] & retired
    assert len(ADVANCED["ncbi"]) == 7


@pytest.mark.parametrize("mode", ["genes", "proteins", "viruses", "features"])
async def test_unqualified_search_modes_not_advertised_or_executable(ncbi_http, mode):
    adapter, requests = ncbi_http(page([]))
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "search_ncbi_data", {"query": "example", "data_type": mode})
    assert not requests


@pytest.mark.source_permissions
async def test_ncbi_public_data_grant_is_eligible_after_source_review():
    assert SourceAdapters().availability("ncbi")[0]


async def test_multiple_taxon_filters_use_documented_repeated_query_parameters(ncbi_http):
    adapter, requests = ncbi_http(page([TARGET]))
    await adapter.call("ncbi", "find_orthologs", PARAMS | {"target_tax_ids": [10090, 10116]})
    assert requests[1].url.params.get_list("taxon_filter") == ["10090", "10116"]
