"""GTEx reference acquisition and QTL joins preserve release-qualified identities."""

from copy import deepcopy

import httpx
import jsonschema
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from gtex_helpers import GENCODE, VARIANT, annotation, association, dynamic, gene, page, variant
from gtex_mcp import server as gtex
from gtex_mcp.contracts import CONTRACT
from gtex_mcp.gtex_client import GTExClient

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.mcp.server import create_server
from biomedmcp.public_catalog import schema


@pytest.fixture
async def references(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    state = {"requests": [], "responses": {}, "release": "gtex_v10"}

    def handler(request):
        assert request.url.host == "gtexportal.org"
        state["requests"].append(request)
        path = request.url.path.removeprefix("/api/v2")
        index = int(request.url.params.get("page", 0))
        size = int(request.url.params.get("itemsPerPage", 25))
        payload = state["responses"].get((path, index))
        if payload is None:
            rows = {
                "/reference/gene": [gene()],
                "/reference/transcript": [annotation()],
                "/reference/exon": [annotation(exon=True)],
                "/dataset/variant": [variant()],
                "/association/singleTissueEqtl": [association()],
                "/association/singleTissueSqtl": [association(splicing=True)],
            }
            payload = (
                dynamic(splicing=path.endswith("dynsqtl")) if "/dyn" in path else page(rows[path], size=size)
            )
        if isinstance(payload, int):
            return httpx.Response(payload, text="synthetic-reference-secret")
        return httpx.Response(200, json=deepcopy(payload))

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    await gtex.client.close()
    monkeypatch.setattr(gtex.client, "_rate_limit_delay", 0)
    yield ResearchService(), state
    await gtex.client.close()


def request(section, **params):
    return {
        "entity": "gene",
        "id": "BRAF",
        "species": 9606,
        "sections": [section],
        "sources": ["gtex"],
        "source_versions": {"gtex": "gtex_v10"},
        "section_parameters": {section: {"limit": 2, **params}},
    }


@pytest.mark.parametrize(
    "section,endpoint", [("transcripts", "/reference/transcript"), ("exons", "/reference/exon")]
)
async def test_canonical_annotation_windows_execute_and_resume(references, section, endpoint):
    research, state = references
    rows = [annotation(exon=section == "exons"), annotation(exon=section == "exons")]
    rows[1]["transcriptId"] = "ENST00000496384.7"
    state["responses"][(endpoint, 0)] = page(rows[:1], size=1, total=2)
    state["responses"][(endpoint, 1)] = page(rows[1:], size=1, total=2, index=1)
    async with Client(create_server(service=research)) as client:
        first = (await client.call_tool("get", request(section, limit=1))).data
        assert first["outcome"] == "data", first
        assert first["sections"][section]["data"]["data"] == rows[:1]
        assert first["provenance"][0]["source_version"] == "gtex_v10"
        identity = first["sections"][section]["data"]["gene_identity"]
        assert identity["gencode_id"] == GENCODE
        action = first["next_actions"][0]
        jsonschema.validate(action["arguments"], schema("get"))
        assert action["arguments"]["id"] == GENCODE
        assert action["arguments"]["source_versions"] == {"gtex": "gtex_v10"}
        last = (await client.call_tool("get", action["arguments"])).data
    assert last["sections"][section]["data"]["data"] == rows[1:]
    assert last["next_actions"] == []
    reads = [r for r in state["requests"] if r.url.path.endswith(endpoint)]
    assert all(r.url.params["gencodeId"] == GENCODE for r in reads)
    assert all("transcriptId" not in r.url.params and "exonId" not in r.url.params for r in reads)
    if section == "transcripts":
        assert all(
            r.url.params["gencodeVersion"] == "v39" and r.url.params["genomeBuild"] == "GRCh38/hg38"
            for r in reads
        )
    else:
        assert all(r.url.params["datasetId"] == "gtex_v10" for r in reads)


@pytest.mark.parametrize(
    "method,endpoint",
    [("get_transcript_info", "/reference/transcript"), ("get_exon_info", "/reference/exon")],
)
async def test_client_uses_documented_gene_and_annotation_release(references, method, endpoint):
    _, state = references
    client = GTExClient()
    client._rate_limit_delay = 0
    try:
        await getattr(client, method)(GENCODE, "gtex_v10", page=0, limit=2)
    finally:
        await client.close()
    params = state["requests"][0].url.params
    assert params["gencodeId"] == GENCODE
    if endpoint.endswith("transcript"):
        assert params["gencodeVersion"] == "v39"
        assert params["genomeBuild"] == "GRCh38/hg38"
        assert "datasetId" not in params
    else:
        assert params["datasetId"] == "gtex_v10"
        assert "gencodeVersion" not in params and "genomeBuild" not in params


@pytest.mark.parametrize(
    "section,field,value",
    [
        (section, field, value)
        for section in ("transcripts", "exons")
        for field, value in (
            ("gencodeId", "ENSG00000012048.22"),
            ("gencodeVersion", "v26"),
            ("genomeBuild", "GRCh37/hg19"),
            ("transcriptId", "ENSG00000157764.14"),
            ("start", 0),
            ("featureType", "gene"),
        )
    ],
)
async def test_wrong_annotation_identity_or_coordinate_semantics_fail(references, section, field, value):
    research, state = references
    endpoint = "/reference/transcript" if section == "transcripts" else "/reference/exon"
    state["responses"][(endpoint, 0)] = page([{**annotation(exon=section == "exons"), field: value}], size=2)
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool_mcp("get", request(section))).structured_content
    assert result["outcome"] == "error", result
    assert result["provenance"] == [] and result["next_actions"] == []


@pytest.mark.parametrize("selector,key", [("rs113488022", "snpId"), (VARIANT, "variantId")])
async def test_variant_reference_selects_the_correct_namespace(references, selector, key):
    _, state = references
    result = await gtex.client.get_variant_info(selector, limit=2)
    assert result["data"] == [variant()]
    assert state["requests"][0].url.params[key] == selector
    assert ("variantId" if key == "snpId" else "snpId") not in state["requests"][0].url.params


@pytest.mark.parametrize(
    "section,mode",
    [("eqtl", "gene_associations"), ("sqtl", "gene_associations"), ("eqtl", "dynamic"), ("sqtl", "dynamic")],
)
async def test_rsid_is_qualified_before_qtl_join(references, section, mode):
    research, state = references
    params = {"tissue_id": "Thyroid", "variant_id": "rs113488022", "analysis_mode": mode}
    if section == "sqtl" and mode == "dynamic":
        params["phenotype_id"] = "chr7:100:200:clu_1"
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool("get", request(section, **params))).data
    assert result["outcome"] == "data", result
    identity = result["sections"][section]["data"]["variant_identity"]
    assert identity["variant_id"] == VARIANT and identity["snp_id"] == "rs113488022"
    assert identity["dataset_id"] == "gtex_v10" and identity["genome_build"] == "GRCh38/hg38"
    ref = next(r for r in state["requests"] if r.url.path.endswith("/dataset/variant"))
    assert ref.url.params["snpId"] == "rs113488022"
    qtls = [r for r in state["requests"] if "/association/" in r.url.path]
    assert qtls and all(r.url.params["variantId"] == VARIANT for r in qtls)


@pytest.mark.parametrize(
    "payload",
    [
        page([]),
        page([variant(), {**variant(), "variantId": "chr7_140753336_A_C_b38", "alt": "C"}]),
        page([variant()], total=26),
        page([{**variant(), "snpId": "rs999"}]),
        503,
    ],
)
async def test_unavailable_ambiguous_incomplete_or_failed_variant_stops_join(
    references, payload, caplog, capsys
):
    research, state = references
    state["responses"][("/dataset/variant", 0)] = payload
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool_mcp("get", request("eqtl", tissue_id="Thyroid", variant_id="rs113488022"))
        ).structured_content
    assert result["outcome"] == "error", result
    assert not any("/association/" in r.url.path for r in state["requests"])
    assert "synthetic-reference-secret" not in str(result) + caplog.text + capsys.readouterr().err


@pytest.mark.parametrize(
    "field,value",
    [
        ("pos", 140753337),
        ("ref", "G"),
        ("alt", "C"),
        ("chromosome", "chr8"),
        ("variantId", "chr7_140753336_A_T_b37"),
        ("snpIdUpper", "RS999"),
    ],
)
async def test_inconsistent_variant_coordinates_fail(references, field, value):
    _, state = references
    state["responses"][("/dataset/variant", 0)] = page([{**variant(), field: value}])
    with pytest.raises(ToolError, match="invalid_source_response"):
        await gtex.client.get_variant_info("rs113488022")


@pytest.mark.parametrize(
    "identifier",
    [
        "rs",
        "rs0001",
        "rs-1",
        "chr7_140453136_A_T_b37",
        "chr7_0_A_T_b38",
        "7_140753336_A_T",
        "synthetic-reference-secret",
    ],
)
async def test_invalid_or_wrong_build_qtl_identifier_fails_preflight_without_io(references, identifier):
    research, state = references
    async with Client(create_server(service=research)) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get", request("eqtl", tissue_id="Thyroid", variant_id=identifier))
    assert state["requests"] == []


@pytest.mark.parametrize("section", ["transcripts", "exons"])
async def test_annotation_missingness_failure_and_nonhuman_scope(references, section):
    research, state = references
    endpoint = "/reference/transcript" if section == "transcripts" else "/reference/exon"
    server = create_server(service=research)
    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get", {**request(section), "species": 10090})
        assert state["requests"] == []
        state["responses"][(endpoint, 0)] = 503
        failed = (await client.call_tool_mcp("get", request(section))).structured_content
        assert failed["outcome"] == "error"
        state["responses"][(endpoint, 0)] = page([], size=2)
        empty = (await client.call_tool_mcp("get", request(section))).structured_content
        assert empty["outcome"] == "empty"
        assert empty["next_actions"] == []


@pytest.mark.parametrize("section", ["transcripts", "exons"])
async def test_annotation_release_v8_is_pinned_even_when_provider_defaults_to_v10(references, section):
    research, state = references
    state["responses"][("/reference/gene", 0)] = page(
        [{**gene(identifier="ENSG00000157764.13"), "gencodeVersion": "v26"}]
    )
    endpoint = "/reference/transcript" if section == "transcripts" else "/reference/exon"
    state["responses"][(endpoint, 0)] = page(
        [{**annotation(exon=section == "exons"), "gencodeId": "ENSG00000157764.13", "gencodeVersion": "v26"}],
        size=2,
    )
    arguments = {**request(section), "source_versions": {"gtex": "gtex_v8"}}
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool("get", arguments)).data
    assert result["outcome"] == "data", result
    assert result["provenance"][0]["source_version"] == "gtex_v8"
    read = state["requests"][-1]
    assert read.url.params["gencodeId"] == "ENSG00000157764.13"
    assert (
        read.url.params["gencodeVersion"] == "v26"
        if section == "transcripts"
        else read.url.params["datasetId"] == "gtex_v8"
    )


async def test_rsid_recovery_uses_qualified_coordinate_and_preserves_filters(references):
    research, state = references
    endpoint = "/association/singleTissueEqtl"
    state["responses"][(endpoint, 0)] = page([association()], size=1, total=2)
    state["responses"][(endpoint, 1)] = page([association()], size=1, total=2, index=1)
    arguments = request(
        "eqtl", tissue_id="Thyroid", variant_id="rs113488022", limit=1, p_value_threshold=0.05
    )
    async with Client(create_server(service=research)) as client:
        first = (await client.call_tool("get", arguments)).data
        count = len(state["requests"])
        cached = (await client.call_tool("get", arguments)).data
        assert len(state["requests"]) == count
        assert cached["provenance"][0]["cached"]
        action = cached["next_actions"][0]
        assert action == first["next_actions"][0]
        jsonschema.validate(action["arguments"], schema("get"))
        assert action["arguments"]["section_parameters"]["eqtl"] == {
            "tissue_id": "Thyroid",
            "analysis_mode": "gene_associations",
            "variant_id": VARIANT,
            "p_value_threshold": 0.05,
            "limit": 1,
            "page": 1,
        }
    async with Client(create_server(service=research)) as client:
        last = (await client.call_tool("get", action["arguments"])).data
    assert last["outcome"] == "data" and last["next_actions"] == []
    references_read = [r for r in state["requests"] if r.url.path.endswith("/dataset/variant")]
    assert references_read[0].url.params["snpId"] == "rs113488022"
    assert references_read[-1].url.params["variantId"] == VARIANT


@pytest.mark.parametrize(
    "endpoint,params",
    [
        ("/reference/transcript", {"transcriptId": "ENST00000288602.10", "datasetId": "gtex_v10"}),
        ("/reference/exon", {"exonId": "ENSE00001484009.1", "datasetId": "gtex_v10"}),
        ("/association/dyneqtl", {"geneId": GENCODE, "variantId": VARIANT, "tissueSiteDetailId": "Thyroid"}),
        ("/association/egene", {"pValueThreshold": 0.05}),
        ("/dataset/sample", {"sampleId": "GTEX-FIXTURE"}),
    ],
)
async def test_retired_or_malformed_provider_queries_fail_before_http(references, endpoint, params):
    _, state = references
    with pytest.raises(ToolError, match="invalid_provider_request"):
        await gtex.client._make_request(endpoint, params=params)
    assert state["requests"] == []


@pytest.mark.parametrize("endpoint", CONTRACT["requests"])
async def test_unknown_request_parameters_are_rejected_without_provider_io(references, endpoint):
    _, state = references
    with pytest.raises(ToolError, match="invalid_provider_request"):
        await gtex.client._make_request(
            endpoint, params={"unsupportedSecretField": "synthetic-reference-secret"}
        )
    assert state["requests"] == []


async def test_metasoft_uses_the_cohort_variant_mapping(references):
    research, state = references
    state["responses"][("/association/metasoft", 0)] = page(
        [{"gencodeId": GENCODE, "datasetId": "gtex_v10", "variantId": VARIANT, "metaP": 0.01, "tissues": {}}],
        size=2,
    )
    async with Client(create_server(service=research)) as client:
        result = (
            await client.call_tool(
                "get",
                request("eqtl", tissue_id="Thyroid", analysis_mode="metasoft", variant_id="rs113488022"),
            )
        ).data
    assert result["outcome"] == "data", result
    assert state["requests"][-1].url.params["variantId"] == VARIANT


@pytest.mark.parametrize(
    "field,value", [("exonId", "ENST00000288602.10"), ("exonNumber", "0"), ("exonNumber", "1.5")]
)
async def test_exon_identity_and_transcript_ordinals_are_validated(references, field, value):
    research, state = references
    state["responses"][("/reference/exon", 0)] = page([{**annotation(exon=True), field: value}], size=2)
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool_mcp("get", request("exons"))).structured_content
    assert result["outcome"] == "error", result


@pytest.mark.parametrize("section", ["transcripts", "exons"])
async def test_annotation_reads_share_gene_identity_and_preserve_primary_record_on_failure(
    references, section, monkeypatch
):
    research, state = references
    calls = []

    async def gene_record(identifier, species):
        calls.append((identifier, species))
        return {
            "id": "673",
            "ensembl_id": GENCODE.split(".")[0],
            "symbol": "BRAF",
            "qualified_identity": {"symbol": "BRAF", "tax_id": 9606},
        }

    monkeypatch.setattr(research.providers, "gene", gene_record)
    endpoint = "/reference/transcript" if section == "transcripts" else "/reference/exon"
    state["responses"][(endpoint, 0)] = 503
    arguments = {
        **request(section),
        "id": "673",
        "sections": ["record", section],
        "sources": ["mygene", "gtex"],
    }
    async with Client(create_server(service=research)) as client:
        result = (await client.call_tool_mcp("get", arguments)).structured_content
    assert result["outcome"] == "partial", result
    assert result["sections"]["record"]["outcome"] == "data"
    assert result["sections"][section]["outcome"] == "unavailable"
    assert calls == [("673", 9606)]
    assert state["requests"][0].url.params["geneId"] == GENCODE.split(".")[0]
