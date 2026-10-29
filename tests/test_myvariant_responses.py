"""MyVariant response contracts before exact-identity filtering; offline only."""

from copy import deepcopy

import httpx
import pytest
from native_helpers import BRAF, HTTP

from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.native.variants import Variants


async def query(client, mode):
    if mode == "search":
        return await client.search("BRAF", {}, 10)
    return await client.resolve(
        {"protein": "BRAF V600E", "rsid": "rs1", "hgvs": "NM_004333.6:c.1799T>A"}[mode]
    )


@pytest.mark.parametrize("mode", ["search", "protein", "rsid", "hgvs"])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"hits": None},
        {"hits": [{}], "total": 1},
        {"hits": [None], "total": 1},
        {"hits": [], "total": True},
        {"hits": [], "total": -1},
        {"hits": [], "total": "0"},
        {"hits": [], "total": 1.5},
        {"hits": [BRAF], "total": 0},
        {"hits": [], "total": 0, "error": "credential-sentinel"},
        {"hits": [], "total": 0, "errors": ["credential-sentinel"]},
        {"hits": []},
    ],
)
async def test_invalid_query_cannot_be_empty_or_exact(mode, payload, caplog):
    with pytest.raises(ResearchError) as caught:
        await query(Variants(HTTP(payload)), mode)
    assert caught.value.code == "invalid_source_response"
    assert "credential-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        [None],
        [{}],
        {"notfound": "true"},
        {"notfound": True},
        {"_id": None},
        {"_id": 123},
        {"_id": ""},
        {"_id": "credential-sentinel", "error": "failed"},
    ],
)
async def test_invalid_direct_lookup_cannot_be_empty(payload):
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(payload)).resolve("chr7:140453136:A:T", "grch37")
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "field,value",
    [
        ("snpeff", []),
        ("snpeff", {"ann": "broken"}),
        ("snpeff", {"ann": [None]}),
        ("snpeff", {"ann": [{"genename": 123, "hgvs_p": "p.Val600Glu"}]}),
        ("snpeff", {"ann": [{"genename": "BRAF", "hgvs_p": []}]}),
        ("snpeff", {"ann": [{"feature_id": 123}]}),
        ("dbnsfp", []),
        ("dbnsfp", {"genename": [None]}),
        ("dbnsfp", {"genename": "BRAF", "hgvsp": 600}),
        ("dbsnp", []),
        ("dbsnp", {"rsid": [123]}),
        ("hg38", {"start": True}),
        ("hg38", {"start": -1}),
        ("hg38", {"start": 2, "end": 1}),
        ("hg38", [None]),
        ("clinvar", "broken"),
        ("cadd", []),
        ("cosmic", [None]),
        ("gnomad_exome", "broken"),
        ("dbscsnv", None),
    ],
)
async def test_partial_nested_records_fail_before_filtering(field, value):
    hit = {**deepcopy(BRAF), field: value}
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP({"hits": [hit], "total": 1})).search("BRAF", {}, 10)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("mode", ["search", "protein", "rsid", "hgvs"])
async def test_explicit_valid_empty_query_is_distinct_from_failure(mode):
    result = await query(Variants(HTTP({"hits": [], "total": 0})), mode)
    assert result.get("resolution") == "empty" if mode != "search" else result["hits"] == []


@pytest.mark.parametrize("payload", [BRAF, [BRAF]])
async def test_valid_direct_record_and_allele_list_preserve_identity(payload):
    result = await Variants(HTTP(payload)).resolve("chr7:140453136:A:T", "grch37")
    assert result["id"] == BRAF["_id"] and result["assembly"] == "grch37"


@pytest.mark.parametrize("mode", ["protein", "rsid", "hgvs"])
async def test_incomplete_candidate_window_cannot_claim_unique_identity_or_absence(mode):
    hit = {**deepcopy(BRAF), "dbsnp": {"rsid": "rs1"}}
    result = await query(Variants(HTTP({"hits": [hit], "total": 26})), mode)
    assert result["resolution"] == "ambiguous"
    assert result["candidate_window"]["complete"] is False
    assert result["candidate_window"]["total"] == 26
    assert result["candidates"]


async def test_no_exact_match_in_incomplete_window_is_still_unresolved():
    result = await Variants(HTTP({"hits": [{**BRAF, "dbsnp": {"rsid": "rs2"}}], "total": 26})).resolve("rs1")
    assert result["resolution"] == "ambiguous" and result["candidates"] == []


async def test_valid_rsid_array_and_noncoding_annotations_remain_usable():
    hit = {**deepcopy(BRAF), "dbsnp": {"rsid": ["rs1", "rs2"]}}
    hit["snpeff"]["ann"].append({"genename": "BRAF", "hgvs_p": None})
    result = await Variants(HTTP({"hits": [hit], "total": 1})).resolve("rs1")
    assert result["resolution"] == "exact" and result["annotation"] == hit


async def test_duplicate_provider_rows_are_not_two_independent_candidates():
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP({"hits": [BRAF, BRAF], "total": 2})).resolve("BRAF V600E")
    assert caught.value.code == "invalid_source_response"


async def test_query_page_past_total_is_valid_but_gap_inside_total_is_not():
    result = await Variants(HTTP({"hits": [], "total": 2})).search("BRAF", {}, 10, offset=2)
    assert result["_provider_page"]["exhausted"]
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP({"hits": [], "total": 2})).search("BRAF", {}, 10, offset=1)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("mode", ["protein", "rsid", "hgvs", "filtered_search"])
@pytest.mark.parametrize(
    "hit", [{"_id": BRAF["_id"]}, {"_id": BRAF["_id"], "snpeff": {"ann": [{"effect": "missense_variant"}]}}]
)
async def test_identity_evidence_missing_from_hit_is_not_absence(mode, hit):
    client = Variants(HTTP({"hits": [hit], "total": 1}))
    with pytest.raises(ResearchError) as caught:
        if mode == "filtered_search":
            await client.search("BRAF", {"gene": "BRAF", "hgvsp": "V600E"}, 10)
        else:
            await query(client, mode)
    assert caught.value.code == "invalid_source_response"


async def test_parallel_unjoined_protein_annotations_cannot_be_negative_evidence():
    hit = {
        "_id": BRAF["_id"],
        "dbnsfp": {"genename": ["BRAF", "OTHER"], "hgvsp": ["p.Val600Glu", "p.Val600Lys"]},
    }
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP({"hits": [hit], "total": 1})).resolve("BRAF V600E")
    assert caught.value.code == "ambiguous_identifier"


async def test_direct_wrong_identity_is_failure_not_absence():
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP({"_id": "chr7:g.140453136A>C"})).resolve("chr7:140453136:A:T", "grch37")
    assert caught.value.code == "identity_mismatch"


@pytest.mark.parametrize(
    "case,code",
    [
        (401, "source_authentication_failed"),
        (429, "source_rate_limited"),
        (503, "source_unavailable"),
        ("json", "invalid_source_response"),
        ("connect", "source_unavailable"),
        ("application", "upstream_error"),
    ],
)
async def test_real_http_failures_are_safe_and_never_absence(monkeypatch, case, code, caplog):
    original = httpx.AsyncClient

    def handler(request):
        if case == "connect":
            raise httpx.ConnectError("credential-sentinel", request=request)
        if case == "json":
            return httpx.Response(200, content=b"credential-sentinel")
        return httpx.Response(case if isinstance(case, int) else 200, json={"error": "credential-sentinel"})

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ResearchError) as caught:
        await Variants().resolve("BRAF V600E")
    assert caught.value.code == code
    assert "credential-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("mode", ["search", "variant_evidence"])
async def test_actual_mcp_failure_is_uncached_and_recovery_retains_provenance(monkeypatch, mode):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        payload = {} if len(calls) == 1 else {"hits": [BRAF], "total": 1}
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    params = (
        {"entity": "variant", "query": "BRAF"}
        if mode == "search"
        else {"id": "BRAF V600E", "sections": ["record"]}
    )
    async with Client(create_server(service=ResearchService())) as client:
        first = (await client.call_tool(mode, params, raise_on_error=False)).structured_content
        second = (await client.call_tool(mode, params)).data
        third = (await client.call_tool(mode, params)).data
    assert first["outcome"] == "error" and not first["provenance"]
    assert next(iter(first["sections"].values()))["error"]["code"] == "invalid_source_response"
    assert second["outcome"] == third["outcome"] == "data"
    assert second["provenance"][0]["source"] == "myvariant"
    assert third["provenance"][0]["cached"] and len(calls) == 2
