"""GTEx provider errors and malformed measurements cannot become evidence of absence."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from gtex_helpers import (
    GENCODE,
    VARIANT,
    annotation,
    association,
    dataset,
    dynamic,
    egene,
    expression,
    expression_source_rows,
    gene,
    page,
    qtl_source_rows,
    sample,
    service,
    tissue,
    variant,
)
from gtex_mcp.contracts import CONTRACT
from gtex_mcp.gtex_client import GTExClient
from gtex_mcp.unified import UnifiedGTExTools

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server

SENTINEL = "synthetic-gtex-credential-sentinel"
COLLECTIONS = (
    "/expression/medianGeneExpression",
    "/expression/geneExpression",
    "/expression/topExpressedGene",
    "/association/egene",
    "/association/sgene",
    "/association/singleTissueEqtl",
    "/association/singleTissueSqtl",
    "/association/metasoft",
    "/reference/gene",
    "/reference/transcript",
    "/reference/exon",
    "/dataset/variant",
    "/dataset/tissueSiteDetail",
    "/dataset/sample",
)
ENDPOINTS = COLLECTIONS + ("/", "/metadata/dataset", "/association/dyneqtl", "/association/dynsqtl")


def request_parameters(endpoint):
    values = {
        "geneId": "BRAF",
        "gencodeId": GENCODE,
        "variantId": VARIANT,
        "tissueSiteDetailId": "Thyroid",
        "phenotypeId": "chr7:100:200:clu_1",
    }
    return {name: values[name] for name in CONTRACT["requests"][endpoint]["required"]}


@pytest.fixture
async def gtex_response():
    clients = []

    def install(payload, *, status=200):
        def handler(request):
            if isinstance(payload, Exception):
                raise payload
            if callable(payload):
                return payload(request)
            return httpx.Response(status, json=payload)

        client = GTExClient()
        client._rate_limit_delay = 0
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield install
    for client in clients:
        await client.close()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": []}, {"error": SENTINEL}, None])
async def test_missing_response_shape_fails_closed(gtex_response, endpoint, payload, caplog, capsys):
    with pytest.raises(ToolError) as caught:
        await gtex_response(payload)._make_request(endpoint, params=request_parameters(endpoint))
    assert json.loads(str(caught.value))["code"] == "invalid_source_response"
    output = capsys.readouterr()
    assert SENTINEL not in str(caught.value) + caplog.text + output.out + output.err


@pytest.mark.parametrize("endpoint", COLLECTIONS)
async def test_explicit_empty_collection_has_qualified_paging(gtex_response, endpoint):
    payload = page([])
    assert (
        await gtex_response(payload)._make_request(endpoint, params=request_parameters(endpoint)) == payload
    )


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/reference/gene", page([gene()])),
        ("/expression/medianGeneExpression", page([expression()])),
        ("/expression/geneExpression", page([expression(detailed=True)])),
        ("/association/singleTissueEqtl", page([association()])),
        ("/association/singleTissueSqtl", page([association(splicing=True)])),
        ("/association/dyneqtl", dynamic()),
        ("/association/dynsqtl", dynamic(splicing=True)),
        ("/expression/topExpressedGene", page([expression()])),
        ("/association/egene", page([egene()])),
        ("/association/sgene", page([egene(splicing=True)])),
        (
            "/association/metasoft",
            page(
                [
                    {
                        "gencodeId": GENCODE,
                        "datasetId": "gtex_v10",
                        "metaP": 0.01,
                        "variantId": VARIANT,
                        "tissues": {"Thyroid": {"mValue": 0.9, "pValue": 0.01, "se": 0.1, "nes": -0.5}},
                    }
                ]
            ),
        ),
        ("/reference/transcript", page([annotation()])),
        ("/reference/exon", page([annotation(exon=True)])),
        ("/dataset/variant", page([variant()])),
        ("/dataset/tissueSiteDetail", page([tissue()])),
        ("/dataset/sample", page([sample()])),
        ("/metadata/dataset", [dataset()]),
        ("/", service()),
    ],
)
async def test_valid_measurements_are_preserved(gtex_response, endpoint, payload):
    assert (
        await gtex_response(payload)._make_request(endpoint, params=request_parameters(endpoint)) == payload
    )


@pytest.mark.parametrize("measurements", [[], [0.0, 0.0]])
async def test_absent_donor_measurements_are_distinct_from_measured_zero(gtex_response, measurements):
    row = {**expression(detailed=True), "data": measurements}
    client = gtex_response(page([row]))
    if measurements:
        assert (await client.get_gene_expression(GENCODE, "Thyroid"))["data"] == [row]
    else:
        with pytest.raises(ToolError):
            await client.get_gene_expression(GENCODE, "Thyroid")


@pytest.mark.parametrize(
    "field,value",
    [
        ("median", -1),
        ("median", True),
        ("median", "1.5"),
        ("median", float("nan")),
        ("median", float("inf")),
        ("unit", "counts"),
        ("gencodeId", ""),
    ],
)
async def test_malformed_expression_fails(gtex_response, field, value):
    row = {**expression(), field: value}
    # httpx's JSON encoder rejects nonfinite values, so preserve the raw provider JSON text.
    client = gtex_response(page([row]))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=json.dumps(page([row]))))
    )
    with pytest.raises(ToolError):
        await client.get_median_gene_expression(GENCODE)


@pytest.mark.parametrize("field,value", [("pValue", -0.1), ("pValue", 1.01), ("nes", True), ("pos", -1)])
async def test_malformed_association_fails(gtex_response, field, value):
    with pytest.raises(ToolError):
        await gtex_response(page([{**association(), field: value}])).get_single_tissue_eqtls(
            GENCODE, "Thyroid"
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("data", [1]),
        ("genotypes", [0, 1, 3]),
        ("hetCount", 2),
        ("error", -0.5),
        ("maf", 1.01),
        ("data", [-1, 1, 2]),
    ],
)
async def test_dynamic_measurement_denominators_fail_when_inconsistent(gtex_response, field, value):
    with pytest.raises(ToolError):
        await gtex_response({**dynamic(), field: value}).calculate_dynamic_eqtl(GENCODE, VARIANT, "Thyroid")


@pytest.mark.parametrize(
    "field,value",
    [
        ("page", -1),
        ("page", 1),
        ("numberOfPages", 0),
        ("totalNumberOfItems", 0),
        ("maxItemsPerPage", 0),
        ("maxItemsPerPage", True),
    ],
)
async def test_inconsistent_paging_fails(gtex_response, field, value):
    payload = page([expression()])
    payload["paging_info"][field] = value
    with pytest.raises(ToolError):
        await gtex_response(payload).get_median_gene_expression(GENCODE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gencodeId", "ENSG00000012048.22"),
        ("datasetId", "gtex_v8"),
        ("tissueSiteDetailId", "Liver"),
    ],
)
async def test_unrequested_measurement_identity_fails(gtex_response, field, value):
    payload = page([{**expression(detailed=True), field: value}])
    with pytest.raises(ToolError):
        await gtex_response(payload).get_gene_expression(GENCODE, "Thyroid")


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
async def test_http_failures_keep_classification_without_raw_body(
    gtex_response, caplog, capsys, status, code
):
    with pytest.raises(ToolError) as caught:
        await gtex_response({"detail": SENTINEL}, status=status).get_median_gene_expression(GENCODE)
    assert json.loads(str(caught.value))["code"] == code
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    output = capsys.readouterr()
    assert SENTINEL not in str(caught.value) + caplog.text + output.out + output.err


async def test_returned_provider_views_are_not_mutated(gtex_response):
    payload = page([expression()])
    original = deepcopy(payload)
    await gtex_response(payload).get_median_gene_expression(GENCODE)
    assert payload == original


@pytest.mark.parametrize("selector", ["BRAF", "braf", "ENSG00000157764", GENCODE])
async def test_exact_gene_identity_is_qualified_even_for_versioned_ids(gtex_response, selector):
    client = gtex_response(page([gene("OTHER", "ENSG00000012048.22"), gene()]))
    assert await UnifiedGTExTools(client)._resolve_gene_id(selector) == GENCODE


@pytest.mark.parametrize(
    "payload",
    [
        page([]),
        page([gene("OTHER", "ENSG00000012048.22")]),
        page([gene(), gene(identifier="ENSG00000012048.22")]),
        page([gene()], total=500),
    ],
)
async def test_missing_ambiguous_or_incomplete_gene_identity_is_not_first_row(gtex_response, payload):
    with pytest.raises(ToolError):
        await UnifiedGTExTools(gtex_response(payload))._resolve_gene_id("BRAF")


async def test_versioned_identifier_from_other_release_is_not_accepted(gtex_response):
    with pytest.raises(ToolError):
        await UnifiedGTExTools(gtex_response(page([gene()])))._resolve_gene_id("ENSG00000157764.13")
    with pytest.raises(ToolError):
        await UnifiedGTExTools(gtex_response(page([{**gene(), "gencodeVersion": "v26"}])))._resolve_gene_id(
            GENCODE
        )


@pytest.mark.parametrize(
    "info_type,payload", [("dataset", [dataset()]), ("tissues", page([tissue()])), ("service", service())]
)
async def test_unified_metadata_preserves_records_and_actual_provider_shapes(
    gtex_response, info_type, payload
):
    result = await UnifiedGTExTools(gtex_response(payload)).get_metadata(info_type)
    if info_type == "tissues":
        assert result["data"] == payload["data"] and result["paging_info"] == payload["paging_info"]
        assert result["coverage"]["accessible_window_exhausted"]
    else:
        assert result == ({"data": payload} if info_type == "dataset" else payload)


@pytest.mark.parametrize("operation", ["get_metadata", "get_sample"])
async def test_unified_tool_preserves_safe_provider_failure(gtex_response, operation, caplog, capsys):
    unified = UnifiedGTExTools(gtex_response({"detail": SENTINEL}, status=503))
    with pytest.raises(ToolError) as caught:
        if operation == "get_metadata":
            await unified.get_metadata("dataset")
        else:
            await unified.get_sample("GTEX-1117F-0003-SM-58Q7G")
    assert json.loads(str(caught.value))["code"] == "source_unavailable"
    output = capsys.readouterr()
    assert SENTINEL not in str(caught.value) + caplog.text + output.out + output.err


async def test_application_error_with_empty_shape_is_not_healthy_empty(gtex_response):
    with pytest.raises(ToolError):
        await gtex_response({**page([]), "error": SENTINEL}).get_median_gene_expression(GENCODE)


@pytest.fixture
async def gtex_service(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    state = {"responses": {}, "requests": []}

    def handler(request):
        assert request.url.host == "gtexportal.org"
        state["requests"].append(request)
        endpoint = request.url.path.removeprefix("/api/v2")
        if endpoint == "/reference/gene":
            return httpx.Response(200, json=page([gene()]))
        if endpoint == "/dataset/variant":
            return httpx.Response(200, json=page([variant()]))
        payload = state["responses"][endpoint]
        return payload(request) if callable(payload) else httpx.Response(200, json=payload)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    from gtex_mcp import server

    await server.client.close()
    monkeypatch.setattr(server.client, "_rate_limit_delay", 0)
    yield ResearchService(), state
    await server.client.close()


@pytest.mark.parametrize("splicing", [False, True])
async def test_dynamic_qtl_is_one_record_and_standard_error_is_not_service_error(gtex_service, splicing):
    research, state = gtex_service
    qtl = "sqtl" if splicing else "eqtl"
    state["responses"]["/association/dyn" + qtl] = dynamic(splicing=splicing)
    state["responses"]["/association/singleTissueSqtl"] = page([association(splicing=True)])
    parameters = {"tissue_id": "Thyroid", "analysis_mode": "dynamic", "variant_id": VARIANT}
    if splicing:
        parameters["phenotype_id"] = "chr7:100:200:clu_1"
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get",
                {
                    "entity": "gene",
                    "id": "BRAF",
                    "sections": [qtl],
                    "sources": ["gtex"],
                    "section_parameters": {qtl: parameters},
                },
            )
        ).data
    assert result["outcome"] == "data", result
    section = result["sections"][qtl]
    assert qtl_source_rows(section["data"]["records"]) == [dynamic(splicing=splicing)]
    assert result["provenance"][0]["source"] == "gtex"
    request = next(r for r in state["requests"] if r.url.path.endswith("dyn" + qtl))
    assert request.url.params["phenotypeId" if splicing else "gencodeId"] == (
        "chr7:100:200:clu_1" if splicing else GENCODE
    )
    assert "geneId" not in request.url.params


@pytest.mark.parametrize("payload", [None, {}, {"data": []}, {"error": SENTINEL}])
async def test_malformed_expression_is_unavailable_and_not_cached_as_absence(
    gtex_service, payload, caplog, capsys
):
    research, state = gtex_service
    state["responses"]["/expression/medianGeneExpression"] = payload
    arguments = {"entity": "gene", "id": "BRAF", "sections": ["expression"], "sources": ["gtex"]}
    async with Client(create_server(service=research)) as client:
        failed = (await client.call_tool_mcp("get", arguments)).structured_content
        assert failed["outcome"] == "error", failed
        assert failed["sections"]["expression"]["outcome"] == "error"
        state["responses"]["/expression/medianGeneExpression"] = page([expression()])
        recovered = (await client.call_tool_mcp("get", arguments)).structured_content
    assert recovered["outcome"] == "data", recovered
    assert expression_source_rows(recovered["sections"]["expression"]["data"]["data"]) == [expression()]
    output = capsys.readouterr()
    assert SENTINEL not in json.dumps(failed) + caplog.text + output.out + output.err


@pytest.mark.parametrize("failure", ["json", "connect"])
async def test_decode_and_network_failures_are_sanitized_before_mcp_logging(
    gtex_service, failure, caplog, capsys
):
    research, state = gtex_service

    def response(request):
        if failure == "connect":
            raise httpx.ConnectError(SENTINEL, request=request)
        return httpx.Response(200, text=SENTINEL)

    state["responses"]["/expression/medianGeneExpression"] = response
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool_mcp(
                "get",
                {
                    "entity": "gene",
                    "id": "BRAF",
                    "sections": ["expression"],
                    "sources": ["gtex"],
                },
            )
        ).structured_content
    assert result["outcome"] == "error"
    output = capsys.readouterr()
    assert SENTINEL not in json.dumps(result) + caplog.text + output.out + output.err


@pytest.mark.parametrize(
    "payload",
    [
        page([]),
        page([association()]),
        page([{**association(splicing=True), "gencodeId": "ENSG00000012048.22"}]),
    ],
)
async def test_dynamic_sqtl_cannot_join_an_unqualified_intron(gtex_service, payload):
    research, state = gtex_service
    state["responses"]["/association/singleTissueSqtl"] = payload
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool_mcp(
                "get",
                {
                    "entity": "gene",
                    "id": "BRAF",
                    "sections": ["sqtl"],
                    "sources": ["gtex"],
                    "section_parameters": {
                        "sqtl": {
                            "tissue_id": "Thyroid",
                            "analysis_mode": "dynamic",
                            "variant_id": VARIANT,
                            "phenotype_id": "chr7:100:200:clu_1",
                        }
                    },
                },
            )
        ).structured_content
    assert result["outcome"] == "error"
    assert not any(r.url.path.endswith("dynsqtl") for r in state["requests"])


async def test_dynamic_sqtl_qualifies_intron_on_a_later_provider_page(gtex_service):
    research, state = gtex_service

    def associations(request):
        index = int(request.url.params["page"])
        row = association(splicing=True)
        if index == 0:
            row["phenotypeId"] = "chr7:300:400:clu_2"
        return httpx.Response(200, json=page([row], total=2, size=1, index=index))

    state["responses"]["/association/singleTissueSqtl"] = associations
    state["responses"]["/association/dynsqtl"] = dynamic(splicing=True)
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get",
                {
                    "entity": "gene",
                    "id": "BRAF",
                    "sections": ["sqtl"],
                    "sources": ["gtex"],
                    "section_parameters": {
                        "sqtl": {
                            "tissue_id": "Thyroid",
                            "analysis_mode": "dynamic",
                            "variant_id": VARIANT,
                            "phenotype_id": "chr7:100:200:clu_1",
                        }
                    },
                },
            )
        ).data
    assert result["outcome"] == "data", result
    assert [r.url.params["page"] for r in state["requests"] if r.url.path.endswith("singleTissueSqtl")] == [
        "0",
        "1",
    ]


@pytest.mark.parametrize(
    "operation,params,payload",
    [
        ("get_metadata", {"info_type": "dataset"}, [dataset()]),
        ("get_sample", {"sample_id": "GTEX-1117F-0003-SM-58Q7G"}, page([sample()])),
    ],
)
async def test_actual_advanced_mcp_metadata_and_sample_contract(gtex_service, operation, params, payload):
    research, state = gtex_service
    state["responses"]["/metadata/dataset" if operation == "get_metadata" else "/dataset/sample"] = payload
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "gtex",
                    "operation": operation,
                    "params": params,
                },
            )
        ).data
    assert result["outcome"] == "data", result
    data = result["sections"]["gtex"]["data"]
    if operation == "get_metadata":
        assert data == {"data": payload}
    else:
        assert data["data"] == payload["data"] and data["paging_info"] == payload["paging_info"]
        assert data["coverage"]["accessible_window_exhausted"]


@pytest.mark.parametrize("value", [False, [], 123])
async def test_required_metadata_description_keeps_its_declared_type(gtex_response, value):
    with pytest.raises(ToolError):
        await gtex_response([{**dataset(), "description": value}]).get_dataset_info()


def test_contract_extraction_preserves_fields_named_like_schema_annotations():
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/update-gtex-contract.py"))
    response_schema = {
        "type": "object",
        "description": "Schema annotation is omitted",
        "properties": {
            "description": {"type": "string", "description": "Field annotation is omitted"},
            "title": {"type": "integer"},
            "example": {"type": "boolean"},
        },
        "required": ["description", "title", "example"],
    }
    source = {
        "info": {"version": "2.0.0"},
        "openapi": "3.1.0",
        "components": {"schemas": {}},
        "paths": {
            "/api/v2" + path: {
                "get": {
                    "responses": {
                        "200": {
                            "content": {"application/json": {"schema": response_schema}},
                        }
                    }
                }
            }
            for path in module["ENDPOINTS"]
        },
    }
    extracted = module["extract"](json.dumps(source).encode(), "2026-10-09")
    schema = extracted["endpoints"]["/"]
    assert schema["properties"] == {
        "description": {"type": "string"},
        "title": {"type": "integer"},
        "example": {"type": "boolean"},
    }
    assert "description" not in schema
