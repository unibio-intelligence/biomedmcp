"""NCBI assembly acquisition must follow its dated official contract."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from ncbi_helpers import ANNOTATION, ASSEMBLY, NAMES, SEQUENCE_REPORT, TAXONOMY, documented_request

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.dispatch import prepare
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server


@pytest.fixture
def datasets_http(monkeypatch):
    original = httpx.AsyncClient
    requests = []
    monkeypatch.setenv("UBI_PROFILE", "local")

    def install(payload, *, inspect=True):
        def handler(request):
            requests.append(request)
            if inspect:
                documented_request(request)
            return payload(request) if callable(payload) else httpx.Response(200, json=payload)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters(), requests

    return install


@pytest.mark.parametrize(
    "params,path,extra",
    [
        (
            {
                "query": "Homo sapiens",
                "max_results": 2,
                "assembly_level": "chromosome",
                "assembly_source": "refseq",
            },
            "/genome/taxon/Homo sapiens/dataset_report",
            {"filters.assembly_level": "chromosome", "filters.assembly_source": "refseq"},
        ),
        (
            {"query": "GRCh38", "tax_id": 9606, "max_results": 2},
            "/genome/taxon/9606/dataset_report",
            {"filters.search_text": "GRCh38"},
        ),
        (
            {"query": "GRCh38.p14", "data_type": "assemblies", "max_results": 2},
            "/genome/assembly_name/GRCh38.p14/dataset_report",
            {},
        ),
        (
            {"query": "GCF_000001405.40", "data_type": "assemblies", "max_results": 2},
            "/genome/accession/GCF_000001405.40/dataset_report",
            {},
        ),
    ],
)
async def test_assembly_discovery_uses_documented_routes_filters_and_continuation(
    datasets_http, params, path, extra
):
    adapter, requests = datasets_http({"reports": [ASSEMBLY], "total_count": 2, "next_page_token": "next"})
    result = await adapter.call("ncbi", "search_ncbi_data", params)
    assert requests[0].url.path == "/datasets/v2" + path
    assert requests[0].url.params["page_size"] == "2"
    assert all(requests[0].url.params[name] == value for name, value in extra.items())
    assert result["records"] == [ASSEMBLY]
    assert result["pagination"]["total"] == 2 and not result["pagination"]["accessible_window_exhausted"]
    assert result["_provider_page"]["continuation"] == "next"


@pytest.mark.parametrize("info_type", ["full", "summary"])
async def test_known_assembly_identity_and_annotation_metadata_are_preserved(datasets_http, info_type):
    adapter, requests = datasets_http({"reports": [ASSEMBLY], "total_count": 1})
    result = await adapter.call(
        "ncbi", "get_genome_data", {"accession": ASSEMBLY["accession"], "info_type": info_type}
    )
    assert result["records"][0]["accession"] == ASSEMBLY["accession"]
    assert result["records"][0]["organism"]["tax_id"] == 9606
    assert result["records"][0]["annotation_info"]["release_date"] == "2026-01-01"
    assert requests[0].url.params["page_size"] == "1"


async def test_annotation_acquisition_uses_exact_symbols_types_and_locations(datasets_http):
    adapter, requests = datasets_http({"reports": [ANNOTATION], "total_count": 1})
    params = {
        "accession": ASSEMBLY["accession"],
        "info_type": "annotation",
        "symbols": ["BRCA1"],
        "gene_types": ["protein-coding"],
        "chromosome": "17",
        "start_position": 43044295,
        "end_position": 43170327,
        "page_size": 2,
    }
    result = await adapter.call("ncbi", "get_genome_data", params)
    assert requests[0].url.path.endswith("/annotation_report")
    assert requests[0].url.params["locations"] == "17:43044295-43170327"
    assert (
        requests[0].url.params["symbols"] == "BRCA1"
        and requests[0].url.params["gene_types"] == "protein-coding"
    )
    assert result["records"] == [ANNOTATION]
    assert result["assembly_accession"] == ASSEMBLY["accession"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"reports": {}},
        {"reports": [None]},
        {"reports": [{"accession": "WRONG"}]},
        {"reports": [ASSEMBLY], "total_count": 0},
        {"reports": [ASSEMBLY], "next_page_token": 5},
        {"reports": [ASSEMBLY], "next_page_token": "x" * 8193},
        {"reports": [ASSEMBLY], "error": "synthetic-datasets-sentinel"},
        {"reports": [ASSEMBLY], "total_count": True},
    ],
)
async def test_malformed_provider_pages_never_become_healthy_empty(datasets_http, payload, caplog, capsys):
    adapter, _ = datasets_http(payload, inspect=False)
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "search_ncbi_data", {"query": "Homo sapiens", "max_results": 2})
    captured = capsys.readouterr()
    assert "synthetic-datasets-sentinel" not in caplog.text + captured.out + captured.err


@pytest.mark.parametrize("payload", [{"reports": [], "total_count": 0}, {"total_count": 0}])
async def test_explicit_zero_results_are_distinct_from_malformed_pages(datasets_http, payload):
    adapter, _ = datasets_http(payload)
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "ncbi", "operation": "search_ncbi_data", "params": {"query": "Homo sapiens"}},
            )
        ).data
    assert result["outcome"] == "empty" and result["provenance"]


@pytest.mark.parametrize(
    "operation,params",
    [
        ("search_ncbi_data", {"query": "Homo sapiens", "chromosome": "1"}),
        ("search_ncbi_data", {"query": "Homo sapiens", "rank": "species"}),
        ("search_ncbi_data", {"query": "Homo sapiens", "max_results": 26}),
        ("get_genome_data", {"accession": "../../users"}),
        ("get_genome_data", {"accession": ASSEMBLY["accession"], "chromosome": "17"}),
        (
            "get_genome_data",
            {
                "accession": ASSEMBLY["accession"],
                "info_type": "annotation",
                "start_position": 5,
                "end_position": 2,
            },
        ),
    ],
)
async def test_invalid_or_inapplicable_parameters_rejected_during_preflight(datasets_http, operation, params):
    adapter, requests = datasets_http({"reports": [ASSEMBLY]})
    with pytest.raises(ResearchError):
        await prepare(
            ResearchService(adapters=adapter),
            "query_source",
            {"source": "ncbi", "operation": operation, "params": params},
            scope="datasets-test",
        )
    assert requests == []


async def test_public_continuation_preserves_a_long_token_and_exact_parameters(datasets_http):
    token = "t" * 8192

    def handler(request):
        if "page_token" in request.url.params:
            assert request.url.params["page_token"] == token
            assert request.url.params["filters.assembly_source"] == "refseq"
            row = deepcopy(ASSEMBLY)
            row["accession"] = "GCF_000001405.41"
            return httpx.Response(200, json={"reports": [row], "total_count": 2})
        return httpx.Response(200, json={"reports": [ASSEMBLY], "total_count": 2, "next_page_token": token})

    adapter, requests = datasets_http(handler)
    params = {"query": "Homo sapiens", "max_results": 1, "assembly_source": "refseq"}
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        first = (
            await client.call_tool(
                "query_source", {"source": "ncbi", "operation": "search_ncbi_data", "params": params}
            )
        ).data
        action = first["next_actions"][0]
        assert action["tool"] == "query_source" and action["arguments"]["params"] == {
            **params,
            "page_token": token,
        }
        second = (await client.call_tool(action["tool"], action["arguments"])).data
    assert len(requests) == 2 and not second["next_actions"]
    assert second["sections"]["ncbi"]["data"]["records"][0]["accession"] == "GCF_000001405.41"


@pytest.mark.parametrize("info_type", ["full", "summary"])
async def test_exact_metadata_continuation_can_reach_protobuf_empty_final_window(datasets_http, info_type):
    # Observed NCBI contract: total_count=1 still has a token; its final page
    # contains only total_count=1, without reports or a next_page_token.
    def handler(request):
        assert request.url.params["page_size"] == "1"
        return httpx.Response(
            200,
            json={"total_count": 1}
            if "page_token" in request.url.params
            else {"reports": [ASSEMBLY], "total_count": 1, "next_page_token": "final-window"},
        )

    adapter, requests = datasets_http(handler)
    params = {"accession": ASSEMBLY["accession"], "info_type": info_type}
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        first = (
            await client.call_tool(
                "query_source",
                {"source": "ncbi", "operation": "get_genome_data", "params": params, "freshness": "fresh"},
            )
        ).data
        action = first["next_actions"][0]
        assert action["arguments"]["freshness"] == "fresh"
        second = (await client.call_tool(action["tool"], action["arguments"])).data
    assert len(requests) == 2 and second["outcome"] == "empty" and second["provenance"]
    assert (
        not second["next_actions"]
        and second["sections"]["ncbi"]["data"]["pagination"]["accessible_window_exhausted"]
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"total_count": 1},
        {"reports": []},
        {"reports": [{**ASSEMBLY, "error": {}}], "total_count": 1},
        {"reports": [ASSEMBLY], "total_count": 2},
        {"reports": [ASSEMBLY, ASSEMBLY], "total_count": 2},
        {"reports": [ASSEMBLY], "messages": [{"error": {"reason": "synthetic-provider-error"}}]},
        {"reports": [ASSEMBLY], "arbitrary": float("nan")},
    ],
)
async def test_incomplete_duplicate_and_error_reports_fail_safely(datasets_http, payload):
    adapter, _ = datasets_http(lambda _: httpx.Response(200, content=json.dumps(payload)), inspect=False)
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "search_ncbi_data", {"query": "Homo sapiens", "max_results": 2})


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "BRCA2"},
        {"gene_id": "0"},
        {"gene_type": "pseudogene"},
        {"annotations": [{"assembly_accession": "GCF_000001405.39"}]},
    ],
)
async def test_annotation_identity_and_requested_filters_cannot_change(datasets_http, changes):
    record = deepcopy(ANNOTATION)
    record["annotation"].update(changes)
    adapter, _ = datasets_http({"reports": [record], "total_count": 1})
    with pytest.raises(ResearchError):
        await adapter.call(
            "ncbi",
            "get_genome_data",
            {
                "accession": ASSEMBLY["accession"],
                "info_type": "annotation",
                "symbols": ["BRCA1"],
                "gene_types": ["protein-coding"],
            },
        )


async def test_nonadvancing_token_does_not_offer_an_infinite_public_action(datasets_http):
    adapter, _ = datasets_http({"reports": [ASSEMBLY], "total_count": 2, "next_page_token": "same"})
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "search_ncbi_data", {"query": "Homo sapiens", "page_token": "same"})


async def test_provider_warnings_and_metadata_projection_preserve_attribution(datasets_http):
    warning = {"warning": {"message": "Synthetic warning; inspect annotation availability."}}
    adapter, _ = datasets_http({"reports": [ASSEMBLY], "total_count": 1, "messages": [warning]})
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "ncbi",
                    "operation": "get_genome_data",
                    "params": {"accession": ASSEMBLY["accession"], "include_annotation": False},
                },
            )
        ).data
    section = result["sections"]["ncbi"]
    assert section["data"]["provider_messages"] == [warning] and section["warnings"] and result["provenance"]
    assert "annotation_info" not in section["data"]["records"][0]
    assert section["data"]["records"][0]["organism"]["tax_id"] == 9606


@pytest.mark.parametrize("selector", [{"tax_id": 9606}, {"organism": "Homo sapiens"}])
@pytest.mark.parametrize("info_type", ["info", "lineage", "organism"])
async def test_taxonomy_uses_documented_identity_and_lineage_reports(datasets_http, selector, info_type):
    def handler(request):
        row = ASSEMBLY if "/genome/" in request.url.path else TAXONOMY
        return httpx.Response(200, json={"reports": [row], "total_count": 1})

    adapter, requests = datasets_http(handler)
    result = await adapter.call("ncbi", "get_taxonomy_data", {**selector, "info_type": info_type})
    assert result["records"][0]["taxonomy"]["tax_id"] == 9606
    assert result["lineage"]["ancestor_tax_ids"] == [1, 9605]
    assert requests[0].url.path.endswith("/dataset_report")
    if info_type == "organism":
        assert result["available_genomes"]["records"] == [ASSEMBLY]
        assert requests[1].url.path == "/datasets/v2/genome/taxon/9606/dataset_report"


async def test_taxonomy_names_match_resolved_identity_and_keep_name_classes(datasets_http):
    adapter, requests = datasets_http(
        lambda request: httpx.Response(
            200,
            json={
                "reports": [NAMES if request.url.path.endswith("/name_report") else TAXONOMY],
                "total_count": 1,
            },
        )
    )
    result = await adapter.call("ncbi", "get_taxonomy_data", {"organism": "human", "include_synonyms": True})
    assert requests[1].url.path == "/datasets/v2/taxonomy/taxon/9606/name_report"
    assert result["names"]["records"][0]["taxonomy"]["curator_common_name"] == "human"


@pytest.mark.parametrize("report_type", ["info", "stats", "quality", "sequence_report", "annotation_report"])
async def test_assembly_reports_preserve_exact_assembly_and_report_semantics(datasets_http, report_type):
    def handler(request):
        row = (
            SEQUENCE_REPORT
            if request.url.path.endswith("/sequence_reports")
            else ANNOTATION
            if request.url.path.endswith("/annotation_report")
            else ASSEMBLY
        )
        return httpx.Response(200, json={"reports": [row], "total_count": 1})

    adapter, _ = datasets_http(handler)
    result = await adapter.call(
        "ncbi", "get_assembly_data", {"assembly_accession": ASSEMBLY["accession"], "report_type": report_type}
    )
    assert result["assembly_accession"] == ASSEMBLY["accession"] and result["records"]
    if report_type == "quality":
        assert all(metric["outcome"] == "unavailable" for metric in result["quality_metrics"].values())


async def test_missing_quality_is_partial_public_evidence_with_no_fabricated_zero(datasets_http):
    adapter, _ = datasets_http({"reports": [ASSEMBLY], "total_count": 1})
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "ncbi",
                    "operation": "get_assembly_data",
                    "params": {"assembly_accession": ASSEMBLY["accession"], "report_type": "quality"},
                },
            )
        ).data
    assert result["outcome"] == "partial" and result["provenance"]
    assert all(
        metric["value"] is None for metric in result["sections"]["ncbi"]["data"]["quality_metrics"].values()
    )


@pytest.mark.parametrize("kind,accession", [("bioproject", "PRJNA31257"), ("biosample", "SAMN02604091")])
async def test_project_sample_genomes_match_the_requested_association(datasets_http, kind, accession):
    row = deepcopy(ASSEMBLY)
    row["assembly_info"].update(
        {"bioproject_accession": "PRJNA31257", "biosample": {"accession": "SAMN02604091"}}
    )
    adapter, requests = datasets_http({"reports": [row], "total_count": 1})
    result = await adapter.call(
        "ncbi",
        "search_project_sample",
        {"accession": accession, "search_type": kind, "data_type": "genomes", "max_results": 2},
    )
    assert result["records"] == [row]
    assert requests[0].url.path == "/datasets/v2/genome/" + kind + "/" + accession + "/dataset_report"


@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_taxonomy_data", {}),
        ("get_taxonomy_data", {"tax_id": 0}),
        ("get_taxonomy_data", {"tax_id": 9606, "organism": "mouse"}),
        ("get_taxonomy_data", {"organism": "../human"}),
        ("get_assembly_data", {"assembly_accession": "GCF_000001405"}),
        ("get_assembly_data", {"assembly_accession": ASSEMBLY["accession"], "page_size": 26}),
        ("search_project_sample", {"accession": "PRJNA31257", "search_type": "biosample"}),
        ("search_project_sample", {"accession": "PRJNA31257", "data_type": "genes"}),
    ],
)
async def test_new_ncbi_plans_reject_invalid_parameters_without_io(datasets_http, operation, params):
    adapter, requests = datasets_http({"reports": [ASSEMBLY]})
    with pytest.raises(ResearchError):
        await prepare(
            ResearchService(adapters=adapter),
            "query_source",
            {"source": "ncbi", "operation": operation, "params": params},
            scope="datasets-test",
        )
    assert not requests


@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_taxonomy_data", {"tax_id": 9606}),
        ("get_assembly_data", {"assembly_accession": ASSEMBLY["accession"]}),
        ("search_project_sample", {"accession": "PRJNA31257"}),
    ],
)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"reports": None},
        {"reports": [{}]},
        {"reports": [], "messages": [{"error": {"reason": "synthetic-private-sentinel"}}]},
        {"reports": [], "total_count": True},
    ],
)
async def test_each_extended_ncbi_family_rejects_malformed_primary_evidence(
    datasets_http, operation, params, payload, caplog, capsys
):
    adapter, _ = datasets_http(payload)
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool_mcp(
                "query_source", {"source": "ncbi", "operation": operation, "params": params}
            )
        ).structured_content
    assert result["outcome"] == "error" and not result["provenance"]
    captured = capsys.readouterr()
    assert "synthetic-private-sentinel" not in json.dumps(result) + caplog.text + captured.out + captured.err


@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_taxonomy_data", {"tax_id": 9606}),
        ("get_assembly_data", {"assembly_accession": ASSEMBLY["accession"]}),
        ("search_project_sample", {"accession": "PRJNA31257"}),
    ],
)
async def test_extended_ncbi_families_accept_explicit_provider_zero(datasets_http, operation, params):
    adapter, _ = datasets_http({"reports": [], "total_count": 0})
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source", {"source": "ncbi", "operation": operation, "params": params}
            )
        ).data
    assert result["outcome"] == "empty" and result["provenance"]


async def test_failed_taxonomy_enrichment_is_partial_and_not_cached_as_healthy(datasets_http):
    attempts = 0

    def handler(request):
        nonlocal attempts
        if "/genome/" in request.url.path:
            attempts += 1
            return httpx.Response(
                200, json={} if attempts == 1 else {"reports": [ASSEMBLY], "total_count": 1}
            )
        return httpx.Response(200, json={"reports": [TAXONOMY], "total_count": 1})

    adapter, requests = datasets_http(handler)
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        call = {
            "source": "ncbi",
            "operation": "get_taxonomy_data",
            "params": {"tax_id": 9606, "info_type": "organism"},
        }
        first = (await client.call_tool("query_source", call)).data
        second = (await client.call_tool("query_source", call)).data
        third = (await client.call_tool("query_source", call)).data
    assert first["outcome"] == "partial" and first["provenance"]
    assert first["sections"]["ncbi"]["data"]["available_genomes"]["records"] is None
    assert second["outcome"] == third["outcome"] == "data" and len(requests) == 4
    assert third["provenance"][0]["cached"] is True


async def test_taxonomy_ambiguity_prevents_unqualified_genome_and_name_joins(datasets_http):
    other = deepcopy(TAXONOMY)
    other["taxonomy"].update(tax_id=10090, current_scientific_name={"name": "Mus musculus"}, parents=[1])
    other["taxonomy"].pop("classification")
    adapter, requests = datasets_http({"reports": [TAXONOMY, other], "total_count": 2})
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "ncbi",
                    "operation": "get_taxonomy_data",
                    "params": {
                        "organism": "ambiguous fixture",
                        "info_type": "organism",
                        "include_synonyms": True,
                    },
                },
            )
        ).data
    assert result["outcome"] == "ambiguous" and len(requests) == 1
    assert "available_genomes" not in result["sections"]["ncbi"]["data"]


async def test_taxonomy_secondary_page_keeps_full_token_and_original_scope(datasets_http):
    token = "g" * 8192

    def handler(request):
        if "/taxonomy/" in request.url.path:
            return httpx.Response(200, json={"reports": [TAXONOMY], "total_count": 1})
        if "page_token" in request.url.params:
            assert request.url.params["page_token"] == token
            row = deepcopy(ASSEMBLY)
            row["accession"] = "GCF_000001405.41"
            return httpx.Response(200, json={"reports": [row], "total_count": 2})
        return httpx.Response(200, json={"reports": [], "total_count": 2, "next_page_token": token})

    adapter, _ = datasets_http(handler)
    params = {"tax_id": 9606, "info_type": "organism", "genome_page_size": 1}
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        first = (
            await client.call_tool(
                "query_source", {"source": "ncbi", "operation": "get_taxonomy_data", "params": params}
            )
        ).data
        assert first["outcome"] == "partial"
        action = first["next_actions"][0]
        assert action["arguments"]["params"] == {**params, "genome_page_token": token}
        second = (await client.call_tool(action["tool"], action["arguments"])).data
    assert "_provider_pages" not in first["sections"]["ncbi"]["data"]
    assert (
        not second["next_actions"]
        and second["sections"]["ncbi"]["data"]["available_genomes"]["records"][0]["accession"]
        == "GCF_000001405.41"
    )


async def test_quality_preserves_measured_zero_and_distinct_raw_scales(datasets_http):
    row = deepcopy(ASSEMBLY)
    row["checkm_info"] = {
        "completeness": 99.48,
        "contamination": 0.0,
        "checkm_version": "v1.2.4",
        "checkm_marker_set": "Escherichia coli",
    }
    row["annotation_info"]["busco"] = {
        "complete": 0.98,
        "busco_lineage": "primates_odb10",
        "busco_ver": "5.7.1",
    }
    adapter, _ = datasets_http({"reports": [row], "total_count": 1})
    result = await adapter.call(
        "ncbi", "get_assembly_data", {"assembly_accession": row["accession"], "report_type": "quality"}
    )
    assert result["quality_metrics"]["contamination"]["outcome"] == "data"
    assert result["quality_metrics"]["contamination"]["value"]["contamination"] == 0.0
    assert result["quality_metrics"]["checkm"]["units"] == "percent"
    assert (
        result["quality_metrics"]["busco"]["value"]["complete"] == 0.98
        and result["quality_metrics"]["busco"]["units"] == "provider_native_score"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("checkm_info", {"completeness": -1.0}),
        ("checkm_info", {"completeness": 101.0}),
        ("assembly_stats", {"number_of_contigs": -1}),
        ("assembly_stats", {"total_sequence_length": "not-numeric"}),
        ("assembly_stats", {"gc_percent": 101.0}),
    ],
)
async def test_invalid_quantitative_assembly_fields_are_rejected(datasets_http, field, value):
    row = deepcopy(ASSEMBLY)
    row[field] = value
    adapter, _ = datasets_http({"reports": [row], "total_count": 1})
    with pytest.raises(ResearchError):
        await adapter.call(
            "ncbi", "get_assembly_data", {"assembly_accession": row["accession"], "report_type": "quality"}
        )


async def test_project_association_is_exact_not_a_substring_of_another_id(datasets_http):
    row = deepcopy(ASSEMBLY)
    row["assembly_info"].update(
        bioproject_accession="PRJNA31257", bioproject_lineage=[{"bioprojects": [{"accession": "PRJNA31257"}]}]
    )
    adapter, _ = datasets_http({"reports": [row], "total_count": 1})
    with pytest.raises(ResearchError):
        await adapter.call("ncbi", "search_project_sample", {"accession": "PRJNA3125"})
