"""GTEx evidence continuation retains identity and filter semantics through actual MCP."""

import json
from copy import deepcopy

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from gtex_helpers import (
    GENCODE,
    VARIANT,
    association,
    dynamic,
    egene,
    expression,
    expression_source_rows,
    gene,
    page,
    qtl_source_rows,
    sample,
    tissue,
    variant,
)
from gtex_mcp import server as gtex

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.public_catalog import schema


@pytest.fixture
async def paged_gtex(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    state = {"requests": [], "pages": {}, "fail_page": None}

    def handler(request):
        if request.url.host == "mygene.info":
            state["requests"].append(request)
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "_id": "673",
                            "symbol": "BRAF",
                            "taxid": 9606,
                            "entrezgene": 673,
                            "ensembl": {"gene": GENCODE.split(".")[0]},
                        }
                    ],
                    "total": 1,
                },
            )
        assert request.url.host == "gtexportal.org"
        state["requests"].append(request)
        endpoint = request.url.path.removeprefix("/api/v2")
        if endpoint == "/reference/gene":
            assert request.url.params["gencodeVersion"] == "v39"
            return httpx.Response(200, json=page([gene()]))
        if endpoint == "/dataset/variant":
            return httpx.Response(200, json=page([variant()]))
        index = int(request.url.params.get("page", 0))
        if state["fail_page"] == index:
            return httpx.Response(503, text="synthetic-gtex-page-secret")
        if endpoint in {"/association/dyneqtl", "/association/dynsqtl"}:
            return httpx.Response(200, json=state["pages"][endpoint])
        result = state["pages"][endpoint][index]
        return httpx.Response(200, json=deepcopy(result))

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    await gtex.client.close()
    monkeypatch.setattr(gtex.client, "_rate_limit_delay", 0)
    yield ResearchService(), state
    await gtex.client.close()


def arguments(section="expression", **parameters):
    return {
        "entity": "gene",
        "id": "BRAF",
        "species": 9606,
        "sections": [section],
        "sources": ["gtex"],
        "source_versions": {"gtex": "gtex_v10"},
        "section_parameters": {section: {"limit": 2, **parameters}},
    }


@pytest.mark.parametrize(
    "section,endpoint",
    [
        ("expression", "/expression/medianGeneExpression"),
        ("eqtl", "/association/singleTissueEqtl"),
        ("sqtl", "/association/singleTissueSqtl"),
    ],
)
async def test_provider_pages_have_executable_identity_preserving_get_actions(paged_gtex, section, endpoint):
    research, state = paged_gtex
    rows = [expression(tissue="Thyroid"), expression(tissue="Liver"), expression(tissue="Whole_Blood")]
    if section != "expression":
        rows = [association(splicing=section == "sqtl") for _ in range(3)]
        for n, row in enumerate(rows):
            row["variantId"] = f"chr7_{100 + n}_A_T_b38"
            row["pos"] = 100 + n
    state["pages"][endpoint] = {
        0: page(rows[:2], total=3, size=2),
        1: page(rows[2:], total=3, size=2, index=1),
    }
    params = {} if section == "expression" else {"tissue_id": "Thyroid", "p_value_threshold": 0.05}
    async with Client(create_server(service=research)) as client:
        first = (await client.call_tool("get", arguments(section, **params))).data
        assert first["outcome"] == "data", first
        observed = first["sections"][section]["data"]["data"]
        assert (
            expression_source_rows(observed) if section == "expression" else qtl_source_rows(observed)
        ) == rows[:2]
        action = first["next_actions"][0]
        import jsonschema

        jsonschema.validate(action["arguments"], schema(action["tool"]))
        assert action["tool"] == "get"
        assert action["arguments"]["source_versions"] == {"gtex": "gtex_v10"}
        assert action["arguments"]["section_parameters"][section]["page"] == 1
        last = (await client.call_tool(action["tool"], action["arguments"])).data
    observed = last["sections"][section]["data"]["data"]
    assert (
        expression_source_rows(observed) if section == "expression" else qtl_source_rows(observed)
    ) == rows[2:]
    assert last["next_actions"] == []
    requests = [r for r in state["requests"] if r.url.path.endswith(endpoint)]
    assert [r.url.params["page"] for r in requests] == ["0", "1"]
    assert all(r.url.params["gencodeId"] == GENCODE and r.url.params["itemsPerPage"] == "2" for r in requests)


@pytest.mark.parametrize("filtered_pages", [1, 3])
async def test_entirely_filtered_windows_reach_later_evidence_without_false_absence(
    paged_gtex, filtered_pages
):
    research, state = paged_gtex
    endpoint = "/association/singleTissueEqtl"
    rows = [{**association(), "pValue": 0.5} for _ in range(filtered_pages)] + [association()]
    state["pages"][endpoint] = {
        n: page([row], total=len(rows), size=1, index=n) for n, row in enumerate(rows)
    }
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get", arguments("eqtl", tissue_id="Thyroid", limit=1, p_value_threshold=0.05)
            )
        ).data
        if filtered_pages == 3:
            assert result["outcome"] == "partial", result
            assert result["sections"]["eqtl"]["data"]["data"] == []
            action = result["next_actions"][0]
            assert action["arguments"]["section_parameters"]["eqtl"]["page"] == 3
            result = (await client.call_tool(action["tool"], action["arguments"])).data
    assert qtl_source_rows(result["sections"]["eqtl"]["data"]["data"]) == [association()]
    assert result["outcome"] == "data"
    assert result["next_actions"] == []
    assert all("pValueThreshold" not in r.url.params for r in state["requests"])


async def test_partial_filtering_preserves_raw_coverage_and_next_page(paged_gtex):
    research, state = paged_gtex
    endpoint = "/association/singleTissueEqtl"
    state["pages"][endpoint] = {0: page([{**association(), "pValue": 0.5}, association()], total=3, size=2)}
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool("get", arguments("eqtl", tissue_id="Thyroid", p_value_threshold=0.05))
        ).data
    data = result["sections"]["eqtl"]["data"]
    assert qtl_source_rows(data["data"]) == [association()]
    assert data["coverage"]["raw_count"] == 2 and data["coverage"]["filtered_count"] == 1
    assert data["coverage"]["total"] == 3 and data["coverage"]["next_page"] == 1
    assert result["next_actions"]


@pytest.mark.parametrize(
    "operation,params,endpoint,row",
    [
        ("get_metadata", {"info_type": "tissues"}, "/dataset/tissueSiteDetail", tissue()),
        ("get_sample", {"sample_id": "GTEX-1117F-0003-SM-58Q7G"}, "/dataset/sample", sample()),
    ],
)
async def test_advanced_pages_have_executable_continuation(paged_gtex, operation, params, endpoint, row):
    research, state = paged_gtex
    state["pages"][endpoint] = {0: page([row], total=2, size=1), 1: page([row], total=2, size=1, index=1)}
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "query_source", {"source": "gtex", "operation": operation, "params": {**params, "limit": 1}}
            )
        ).data
        assert result["outcome"] == "data", result
        action = result["next_actions"][0]
        assert action["arguments"]["params"]["page"] == 1
        last = (await client.call_tool(action["tool"], action["arguments"])).data
    assert last["outcome"] == "data" and last["next_actions"] == []
    assert [r.url.params["page"] for r in state["requests"]] == ["0", "1"]


async def test_large_requested_limit_never_hides_rows_between_provider_pages(paged_gtex):
    research, state = paged_gtex
    rows = [expression() for _ in range(26)]
    # Distinct measurements preserve conflicting assertions for the same gene/tissue.
    for n, row in enumerate(rows):
        row["median"] = n
    endpoint = "/expression/medianGeneExpression"
    state["pages"][endpoint] = {
        0: page(rows[:25], total=26, size=25),
        1: page(rows[25:], total=26, size=25, index=1),
    }
    async with Client(create_server(service=research)) as client:
        first = (await client.call_tool("get", arguments(limit=100))).data
        assert len(first["sections"]["expression"]["data"]["data"]) == 25
        action = first["next_actions"][0]
        last = (await client.call_tool(action["tool"], action["arguments"])).data
    assert expression_source_rows(last["sections"]["expression"]["data"]["data"]) == rows[25:]
    assert all(
        r.url.params["itemsPerPage"] == "25" for r in state["requests"] if r.url.path.endswith(endpoint)
    )


async def test_provider_failure_is_not_an_exhausted_empty_page(paged_gtex, caplog, capsys):
    research, state = paged_gtex
    endpoint = "/association/singleTissueEqtl"
    state["pages"][endpoint] = {0: page([{**association(), "pValue": 0.5}], total=2, size=1)}
    state["fail_page"] = 1
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool_mcp("get", arguments("eqtl", tissue_id="Thyroid", limit=1))
        ).structured_content
    assert result["outcome"] == "error", result
    output = capsys.readouterr()
    assert "synthetic-gtex-page-secret" not in json.dumps(result) + caplog.text + output.out + output.err


async def test_recovery_uses_the_qualified_gene_without_unrelated_parent_sources(paged_gtex):
    research, state = paged_gtex
    endpoint = "/expression/medianGeneExpression"
    state["pages"][endpoint] = {
        0: page([expression()], total=2, size=1),
        1: page([expression(tissue="Liver")], total=2, size=1, index=1),
    }
    request = arguments(limit=1)
    request.update(id="673", sections=["record", "expression"], sources=["gtex", "mygene"])
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool("get", request)).data
        assert result["outcome"] == "data", result
        action = result["next_actions"][0]
        assert action["arguments"]["id"] == GENCODE
        assert action["arguments"]["sections"] == ["expression"]
        assert action["arguments"]["sources"] == ["gtex"]
        result = (await client.call_tool(action["tool"], action["arguments"])).data
    assert result["outcome"] == "data", result
    assert sum(r.url.host == "mygene.info" for r in state["requests"]) == 1


async def test_cached_window_and_a_new_client_keep_the_same_continuation(paged_gtex):
    research, state = paged_gtex
    endpoint = "/expression/medianGeneExpression"
    state["pages"][endpoint] = {
        0: page([expression()], total=2, size=1),
        1: page([expression(tissue="Liver")], total=2, size=1, index=1),
    }
    request = arguments(limit=1)
    request.pop("source_versions")
    server = create_server(service=research)
    async with Client(server) as client:
        first = (await client.call_tool("get", request)).data
        count = len(state["requests"])
        cached = (await client.call_tool("get", request)).data
    assert len(state["requests"]) == count
    assert cached["provenance"][0]["cached"] and cached["next_actions"] == first["next_actions"]
    action = cached["next_actions"][0]
    assert action["arguments"]["source_versions"] == {"gtex": "gtex_v10"}
    async with Client(server) as client:
        resumed = (await client.call_tool(action["tool"], action["arguments"])).data
    assert resumed["outcome"] == "data" and resumed["next_actions"] == []


@pytest.mark.parametrize("qtl", ["eqtl", "sqtl"])
async def test_retained_gene_lists_filter_measured_p_values_locally(paged_gtex, qtl):
    _, state = paged_gtex
    row = egene(splicing=qtl == "sqtl")
    endpoint = "/association/egene" if qtl == "eqtl" else "/association/sgene"
    state["pages"][endpoint] = {0: page([{**row, "pValue": 0.5}, row], size=2)}
    result = await gtex.unified.query_qtl(qtl, "genes_list", "Thyroid", p_value_threshold=0.05, limit=2)
    assert qtl_source_rows(result["data"]) == [row]
    assert result["coverage"]["filtered_count"] == 1
    assert "pValueThreshold" not in state["requests"][0].url.params


async def test_metasoft_filter_explicitly_uses_meta_p(paged_gtex):
    research, state = paged_gtex
    row = {"gencodeId": GENCODE, "datasetId": "gtex_v10", "metaP": 0.01, "variantId": VARIANT, "tissues": {}}
    state["pages"]["/association/metasoft"] = {0: page([{**row, "metaP": 0.5}, row], size=2)}
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get",
                arguments(
                    "eqtl",
                    tissue_id="Thyroid",
                    analysis_mode="metasoft",
                    variant_id=VARIANT,
                    p_value_threshold=0.05,
                ),
            )
        ).data
    assert result["outcome"] == "data", result
    data = result["sections"]["eqtl"]["data"]
    assert qtl_source_rows(data["data"]) == [row]
    assert data["coverage"]["p_value_filter"]["measure"] == "metaP"


async def test_calculated_nonsignificant_qtl_is_retained_as_measurement(paged_gtex):
    research, state = paged_gtex
    state["pages"]["/association/dyneqtl"] = {**dynamic(), "pValue": 0.5}
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get",
                arguments(
                    "eqtl",
                    tissue_id="Thyroid",
                    analysis_mode="dynamic",
                    variant_id=VARIANT,
                    p_value_threshold=0.05,
                ),
            )
        ).data
    assert result["outcome"] == "data", result
    data = result["sections"]["eqtl"]["data"]
    assert data["records"][0]["pValue"] == 0.5
    assert data["significance"]["meets_threshold"] is False


@pytest.mark.parametrize(
    "params",
    [{"page": -1}, {"page": True}, {"page": 100001}, {"limit": False}, {"info_type": "dataset", "page": 1}],
)
async def test_invalid_advanced_page_modes_fail_before_provider_reads(paged_gtex, params):
    research, state = paged_gtex
    async with Client(create_server(service=research)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "query_source",
                {"source": "gtex", "operation": "get_metadata", "params": {"info_type": "tissues", **params}},
            )
    assert state["requests"] == []


async def test_provider_cannot_ignore_requested_page_budget(paged_gtex):
    research, state = paged_gtex
    state["pages"]["/expression/medianGeneExpression"] = {0: page([expression()], size=250)}
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool_mcp("get", arguments(limit=2))).structured_content
    assert result["outcome"] == "error"
    assert result["next_actions"] == []


async def test_explicit_empty_final_window_is_distinct_from_filtered_incomplete_window(paged_gtex):
    research, state = paged_gtex
    state["pages"]["/association/singleTissueEqtl"] = {0: page([], size=2)}
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool("get", arguments("eqtl", tissue_id="Thyroid"))).data
    assert result["outcome"] == "empty", result
    assert result["next_actions"] == []
    assert result["sections"]["eqtl"]["data"]["coverage"]["accessible_window_exhausted"]


async def test_provider_page_window_exhaustion_is_not_unrecoverable_absence(paged_gtex):
    research, state = paged_gtex
    state["pages"]["/expression/medianGeneExpression"] = {
        100000: page([expression()], total=100002, size=1, index=100000),
    }
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool_mcp("get", arguments(page=100000, limit=1))).structured_content
    assert result["outcome"] == "partial"
    assert result["next_actions"] == []
    data = result["sections"]["expression"]["data"]
    assert len(data["data"]) == 1 and len(result["provenance"]) == 1
    assert data["coverage"]["continuation_reason"] == "supported_page_range_exceeded"
    assert data["coverage"]["accessible_window_exhausted"] is False
    assert data["coverage"]["next_page"] is None


async def test_smaller_provider_cap_is_preserved_as_the_continuation_page_width(paged_gtex):
    research, state = paged_gtex
    endpoint = "/expression/medianGeneExpression"
    state["pages"][endpoint] = {
        0: page([expression()], total=2, size=1),
        1: page([expression(tissue="Liver")], total=2, size=1, index=1),
    }
    async with Client(create_server(service=research)) as client:
        first = (await client.call_tool("get", arguments(limit=2))).data
        action = first["next_actions"][0]
        assert action["arguments"]["section_parameters"]["expression"]["limit"] == 1
        last = (await client.call_tool(action["tool"], action["arguments"])).data
    assert last["outcome"] == "data", last
    assert [r.url.params["itemsPerPage"] for r in state["requests"] if r.url.path.endswith(endpoint)] == [
        "2",
        "1",
    ]


@pytest.mark.parametrize(
    "section,endpoint",
    [
        ("eqtl", "/association/singleTissueEqtl"),
        ("sqtl", "/association/singleTissueSqtl"),
        ("transcripts", "/reference/transcript"),
        ("exons", "/reference/exon"),
    ],
)
async def test_page_limit_keeps_source_values_and_coverage(paged_gtex, section, endpoint):
    from gtex_helpers import annotation

    research, state = paged_gtex
    record = (
        annotation()
        if section == "transcripts"
        else annotation(exon=True)
        if section == "exons"
        else association(splicing=section == "sqtl")
    )
    state["pages"][endpoint] = {100000: page([record], total=100002, size=1, index=100000)}
    parameters = {"tissue_id": "Thyroid"} if section in {"eqtl", "sqtl"} else {}
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool("get", arguments(section, page=100000, limit=1, **parameters))
        ).structured_content
    assert result["outcome"] == "partial" and result["next_actions"] == []
    data = result["sections"][section]["data"]
    assert len(data["data"]) == 1
    key = "transcriptId" if section == "transcripts" else "exonId" if section == "exons" else "pValue"
    assert data["data"][0][key] == record[key]
    assert data["coverage"]["continuation_reason"] == "supported_page_range_exceeded"
    assert data["coverage"]["accessible_window_exhausted"] is False
    assert len(result["provenance"]) == 1
