import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from gwas_helpers import ASSOCIATION, page, row
from native_helpers import HTTP
from test_research_contracts import Adapters

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native import gwas
from biomedmcp.native.providers import NativeProviders


@pytest.mark.parametrize(
    "body",
    [
        {},
        None,
        [],
        {"error": "upstream"},
        {"success": False},
        {"page": {}},
        {"associations": []},
        {"_embedded": {"associations": []}},
    ],
)
async def test_malformed_page_is_not_absence(body):
    with pytest.raises(ResearchError) as error:
        await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF", include_page=True)
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "field,value",
    [
        ("association_id", None),
        ("association_id", True),
        ("association_id", 0),
        ("association_id", "123"),
        ("accession_id", None),
        ("accession_id", "wrong"),
        ("p_value", True),
        ("p_value", False),
        ("p_value", "1e-8"),
        ("p_value", -1),
        ("p_value", 1.1),
        ("p_value", float("nan")),
        ("p_value", float("inf")),
        ("pvalue_mantissa", False),
        ("pvalue_mantissa", 0),
        ("pvalue_exponent", True),
        ("pvalue_exponent", -10001),
        ("multi_snp_haplotype", "false"),
        ("snp_interaction", 0),
        ("mapped_genes", "BRAF"),
        ("reported_trait", [None]),
        ("locations", [1]),
        ("snp_allele", [{}]),
        ("efo_traits", [{}]),
        ("bg_efo_traits", "EFO_0000001"),
        ("pubmed_id", 123),
        ("ci_lower", float("nan")),
        ("beta_num", float("inf")),
        ("or_per_copy_num", 0),
        ("beta", {}),
        ("risk_frequency", 0.1),
    ],
)
async def test_invalid_scientific_fields_fail_before_filtering(field, value):
    with pytest.raises(ResearchError) as error:
        await NativeProviders(Adapters(), HTTP(page([row(**{field: value})]))).gwas("BRAF", {"p_value": 1e-9})
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("missing", ["association_id", "accession_id", "p_value"])
def test_missing_minimum_record_fields_are_rejected(missing):
    value = deepcopy(ASSOCIATION)
    del value[missing]
    with pytest.raises(ResearchError):
        gwas.record(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("size", False),
        ("size", 0),
        ("size", 2),
        ("totalElements", -1),
        ("totalElements", True),
        ("totalElements", "1"),
        ("totalPages", 0),
        ("number", 1),
    ],
)
async def test_invalid_page_metadata_cannot_be_cached_as_empty(field, value):
    body = page()
    body["page"][field] = value
    with pytest.raises(ResearchError) as error:
        await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF", include_page=True)
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("body", [page([]), page([]) | {"_embedded": {"associations": []}}])
async def test_zero_total_allows_observed_omitted_or_explicit_empty_collection(body):
    payload = await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF", include_page=True)
    assert payload["records"] == [] and payload["_provider_page"]["exhausted"]
    assert payload["coverage"]["total_source_associations"] == 0


async def test_documented_content_and_snake_case_page_projection_is_explicit():
    body = {
        "content": [row()],
        "page": {"size": 10, "total_elements": 1, "total_pages": 1, "number": 0},
        "links": [],
    }
    result = await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF", include_page=True)
    assert result["records"][0]["id"] == "123"
    body["_embedded"] = {"associations": []}
    with pytest.raises(ResearchError):
        await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF")


@pytest.mark.parametrize("rows,total", [([row()], 2), ([], 1), ([row(), row()], 2)])
async def test_incomplete_or_duplicate_windows_fail(rows, total):
    with pytest.raises(ResearchError):
        await NativeProviders(Adapters(), HTTP(page(rows, total=total, size=2))).gwas("BRAF", limit=2)


@pytest.mark.parametrize("value,status", [(None, "not_reported"), (0.0, "precision_unavailable")])
async def test_missing_precision_is_retained_not_filtered_into_negative_evidence(value, status):
    payload = await NativeProviders(
        Adapters(), HTTP(page([row(p_value=value, pvalue_mantissa=None, pvalue_exponent=None)]))
    ).gwas("BRAF", {"p_value": 1e-10}, include_page=True)
    record = payload["records"][0]
    assert record["p_value_status"] == status and record["p_value_decimal"] is None
    assert payload["section_outcomes"]["p_value_interpretation"]["outcome"] == "partial"
    assert payload["_provider_page"]["filtered_count"] == 0


async def test_underflow_preserves_reported_components_and_filters_using_decimal():
    payload = await NativeProviders(
        Adapters(), HTTP(page([row(p_value=0.0, pvalue_mantissa=3, pvalue_exponent=-400)]))
    ).gwas("BRAF", {"p_value": 5e-324}, include_page=True)
    record = payload["records"][0]
    assert record["p_value"] == 0 and record["p_value_status"] == "float_underflow"
    assert Decimal(record["p_value_decimal"]) == Decimal("3e-400")
    assert "section_outcomes" not in payload


async def test_conflicting_representations_are_preserved_with_unknown_filter_match():
    payload = await NativeProviders(Adapters(), HTTP(page([row(p_value=0.1)]))).gwas(
        "BRAF", {"p_value": 1e-10}, include_page=True
    )
    record = payload["records"][0]
    assert record["p_value"] == 0.1 and record["p_value_components_decimal"] == "1E-8"
    assert record["p_value_status"] == "conflicting_representations" and record["p_value_decimal"] is None
    assert payload["section_outcomes"]["p_value_interpretation"]["outcome"] == "partial"


@pytest.mark.parametrize(
    "updates",
    [
        {"pvalue_mantissa": None},
        {"pvalue_exponent": None},
        {"pvalue_mantissa": 2, "pvalue_exponent": 0},
        {"ci_lower": 2, "ci_upper": 1},
    ],
)
def test_incoherent_components_or_intervals_fail(updates):
    with pytest.raises(ResearchError):
        gwas.record(row(**updates))


async def test_exact_record_identity_and_rs_query_are_enforced():
    with pytest.raises(ResearchError):
        await NativeProviders(Adapters(), HTTP(row(999))).record("gwas", "123")
    with pytest.raises(ResearchError):
        await NativeProviders(
            Adapters(), HTTP(page([row(snp_allele=[{"rs_id": "rs1", "effect_allele": "A"}])]))
        ).gwas("rs7412")
    http = HTTP(page())
    result = await NativeProviders(Adapters(), http).gwas("rs7412", {"gene": "BRAF", "trait": "asthma"})
    assert result[0]["id"] == "123"
    assert http.calls[0][1] == gwas.BASE
    assert http.calls[0][2]["params"]["rs_id"] == "rs7412"
    assert http.calls[0][2]["params"]["mapped_gene"] == "BRAF"
    assert http.calls[0][2]["params"]["efo_trait"] == "asthma"


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/gwas/rest/api/v2/associations/123",
        gwas.BASE + "/999",
        gwas.BASE + "/123?key=sentinel",
        "http://www.ebi.ac.uk/gwas/rest/api/v2/associations/123",
    ],
)
def test_wrong_record_link_cannot_qualify_identity(href):
    with pytest.raises(ResearchError):
        gwas.record(row(_links={"self": {"href": href}}))


@pytest.mark.parametrize(
    "href",
    [
        gwas.BASE + "?mapped_gene=BRAF&extended_geneset=false&size=10&page=0&sort=p_value&direction=asc",
        "https://evil.example/?page=1",
        gwas.BASE + "?mapped_gene=OTHER&extended_geneset=false&size=10&page=1&sort=p_value&direction=asc",
    ],
)
async def test_nonadvancing_or_wrong_query_next_link_is_rejected(href):
    body = page([row(i) for i in range(1, 11)], total=11) | {"_links": {"next": {"href": href}}}
    with pytest.raises(ResearchError):
        await NativeProviders(Adapters(), HTTP(body)).gwas("BRAF")


@pytest.mark.parametrize("mode", ["search", "get"])
async def test_actual_mcp_invalid_result_is_uncached_then_success_has_provenance(monkeypatch, mode):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={} if len(calls) == 1 else page() if mode == "search" else row())

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler))
    )
    args = {"entity": "gwas", "query": "BRAF"} if mode == "search" else {"entity": "gwas", "id": "123"}
    async with Client(create_server(service=ResearchService())) as client:
        failed = (await client.call_tool(mode, args, raise_on_error=False)).structured_content
        good = (await client.call_tool(mode, args, raise_on_error=False)).structured_content
        cached = (await client.call_tool(mode, args, raise_on_error=False)).structured_content
    assert failed["outcome"] == "error"
    assert next(iter(failed["sections"].values()))["error"]["code"] == "invalid_source_response"
    assert good["outcome"] == cached["outcome"] == "data" and len(calls) == 2
    assert good["provenance"][0]["sources"] == ["gwas"]


async def test_actual_variant_gwas_followup_is_canonical_and_executable(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        number = int(request.url.params["page"])
        assert request.url.path == "/gwas/rest/api/v2/associations"
        assert request.url.params["rs_id"] == "rs7412"
        return httpx.Response(200, json=page([row(123 + number)], total=2, size=1, number=number))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler))
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "variant_evidence",
                {"id": "rs7412", "sections": ["gwas"], "section_parameters": {"gwas": {"limit": 1}}},
            )
        ).structured_content
        action = next(a for a in result["next_actions"] if a["tool"] == "variant_evidence")
        continued = (await client.call_tool(action["tool"], action["arguments"])).structured_content
    assert [r["id"] for r in result["sections"]["gwas"]["data"]["records"]] == ["123"]
    assert [r["id"] for r in continued["sections"]["gwas"]["data"]["records"]] == ["124"]
    assert [r.url.params["page"] for r in calls] == ["0", "1"]
    assert action["arguments"]["id"] == "rs7412" and action["arguments"]["sources"] == ["gwas"]


def test_retained_official_projection_passes_without_inventing_build():
    fixture = json.loads((Path(__file__).parent / "fixtures/gwas-contract-2026-10-11.json").read_text())
    params = {
        "mapped_gene": "BRAF",
        "extended_geneset": "false",
        "size": 2,
        "page": 0,
        "sort": "p_value",
        "direction": "asc",
    }
    result = gwas.window(fixture["gene_page"], params)
    assert len(result["records"]) == 2 and result["coverage"]["assembly"] == "not_qualified"
    assert result["coverage"]["total_source_associations"] == 55
    assert gwas.record(fixture["record"], requested_id="103252357")["id"] == "103252357"


@pytest.mark.parametrize(
    "filters",
    [{"p_value": True}, {"p_value": float("nan")}, {"p_value": "1e-8"}, {"gene": ""}, {"trait": []}],
)
async def test_invalid_filters_are_rejected_before_provider_reads(filters):
    http = HTTP()
    with pytest.raises(ResearchError) as error:
        await NativeProviders(Adapters(), http).gwas("BRAF", filters)
    assert error.value.code == "invalid_parameters" and not http.calls


@pytest.mark.parametrize("mode", ["search", "record"])
async def test_actual_mcp_conflicting_p_values_remain_partial_and_uncached(monkeypatch, mode):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page([row(p_value=0.1)]) if mode == "search" else row(p_value=0.1))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler))
    )
    operation = "search" if mode == "search" else "get"
    args = (
        {"entity": "gwas", "query": "BRAF", "filters": {"p_value": 1e-12}}
        if mode == "search"
        else {"entity": "gwas", "id": "123"}
    )
    async with Client(create_server(service=ResearchService())) as client:
        first = (await client.call_tool(operation, args)).structured_content
        again = (await client.call_tool(operation, args)).structured_content
    assert first["outcome"] == again["outcome"] == "partial" and len(calls) == 2
    if mode == "search":
        assert first["records"][0]["p_value_status"] == "conflicting_representations"


async def test_later_failed_search_window_retains_acquired_association():
    from biomedmcp.contracts import SearchRequest

    http = HTTP(
        page(
            [row(1, p_value=1e-12, pvalue_exponent=-12), row(2, p_value=0.1, pvalue_exponent=-1)],
            total=4,
            size=2,
        ),
        {},
    )
    result = await ResearchService(http=http).search(
        SearchRequest(entity="gwas", query="BRAF", limit=2, filters={"p_value": 1e-10}), scope="alice"
    )
    assert result.outcome == "partial" and [r["id"] for r in result.records] == ["1"]
    assert result.sections["gwas"].error["code"] == "invalid_source_response"
    assert result.provenance and result.provenance[0].sources == ["gwas"]


async def test_actual_mcp_observed_zero_total_is_attributed_empty(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kwargs: real(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page([])))
        ),
    )
    async with Client(create_server(service=ResearchService())) as client:
        result = (await client.call_tool("search", {"entity": "gwas", "query": "BRAF"})).structured_content
    assert result["outcome"] == "empty" and result["records"] == []
    assert result["sections"]["gwas"]["outcome"] == "empty" and result["provenance"][0]["sources"] == ["gwas"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("resolution", "empty"),
        ("section_outcomes", {"forged": {"outcome": "partial"}}),
        ("id", "999"),
        ("p_value_status", "forged_measurement"),
    ],
)
def test_unqualified_source_fields_cannot_replace_service_control(field, value):
    from biomedmcp.evidence import scientific_outcome

    result = gwas.record(row(**{field: value}))
    assert result["id"] == "123" and result["p_value_status"] == "reported"
    assert scientific_outcome(result) == "data"
    assert result["source_fields"][field] == value
    assert field not in result or field in {"id", "p_value_status"}


@pytest.mark.parametrize(
    "field,marker",
    [
        ("efo_traits", {"error": "partial failure"}),
        ("bg_efo_traits", {"success": False}),
        ("snp_allele", {"errors": ["partial failure"]}),
    ],
)
def test_nested_application_failures_do_not_become_healthy_metadata(field, marker):
    nested = (
        {"rs_id": "rs7412", "effect_allele": "T"}
        if field == "snp_allele"
        else {"efo_id": "EFO_0000001", "efo_trait": "Synthetic trait"}
    )
    with pytest.raises(ResearchError) as error:
        gwas.record(row(**{field: [nested | marker]}))
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("number,total,expected", [(100000, 100002, "partial"), (100000, 100001, "data")])
async def test_last_supported_variant_page_keeps_valid_evidence(monkeypatch, number, total, expected):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=page([row()], total=total, size=1, number=number))

    monkeypatch.setattr(transport, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "variant_evidence",
                {
                    "id": "rs7412",
                    "sections": ["gwas"],
                    "section_parameters": {"gwas": {"limit": 1, "page": number}},
                },
            )
        ).structured_content
    data = result["sections"]["gwas"]["data"]
    assert result["outcome"] == expected and data["records"][0]["id"] == "123"
    assert result["next_actions"] == [] and len(result["provenance"]) == 1 and len(calls) == 1
    assert data["coverage"]["provider_window_exhausted"] is (expected == "data")
    if expected == "partial":
        assert data["coverage"]["continuation_reason"] == "supported_page_range_exceeded"
        assert data["coverage"]["next_provider_page"] == 100001
    else:
        assert "continuation_status" not in data["coverage"]


async def test_penultimate_variant_page_action_reaches_last_supported_page(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    real = httpx.AsyncClient
    calls = []

    def handler(request):
        number = int(request.url.params["page"])
        calls.append(number)
        return httpx.Response(200, json=page([row(number + 1)], total=100002, size=1, number=number))

    monkeypatch.setattr(transport, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    async with Client(create_server(service=ResearchService())) as client:
        first = (
            await client.call_tool(
                "variant_evidence",
                {
                    "id": "rs7412",
                    "sections": ["gwas"],
                    "section_parameters": {"gwas": {"limit": 1, "page": 99999}},
                },
            )
        ).structured_content
        action = next(a for a in first["next_actions"] if a["tool"] == "variant_evidence")
        last = (await client.call_tool(action["tool"], action["arguments"])).structured_content
    assert action["arguments"]["section_parameters"]["gwas"]["page"] == 100000
    assert last["outcome"] == "partial" and last["next_actions"] == []
    assert [
        first["sections"]["gwas"]["data"]["records"][0]["id"],
        last["sections"]["gwas"]["data"]["records"][0]["id"],
    ] == ["100000", "100001"]
    assert calls == [99999, 100000]
