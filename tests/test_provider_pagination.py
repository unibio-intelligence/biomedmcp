"""Continuation must describe provider coverage, independently of visible rows."""

from unittest.mock import AsyncMock

import pytest
from clinical_trials_helpers import study
from native_helpers import HTTP as NativeHTTP

from biomedmcp.contracts import SearchRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.runtime import ProviderRuntime


class HTTP(NativeHTTP):
    def __init__(self, *responses):
        converted = []
        for row in responses:
            if isinstance(row, dict) and "data" in row:
                values = [{"source": "MED", "id": p.get("pmid", p["id"]),
                           "pmid": p.get("pmid", p["id"]),
                           "doi": p.get("doi"), "title": p.get("title")}
                          for p in row["data"]]
                item = {"resultList": {"result": values}}
                if "total" in row: item["hitCount"] = row["total"]
                if "next" in row: item["nextCursorMark"] = str(row["next"])
                converted.append(item)
            else: converted.append(row)
        super().__init__(*converted)


def paper(n):
    return {"id": str(n), "title": f"BRAF {n}"}


def request(entity="article", source="europepmc", **kwargs):
    return SearchRequest(entity=entity, query="BRAF", limit=2, filters={"source": source}, **kwargs)






async def test_duplicate_only_window_does_not_end_provider_coverage():
    http = HTTP(
        {"data": [paper(0), paper(1)], "next": 2, "total": 6},
        {"data": [paper(0), paper(1)], "next": 4, "total": 6},
        {"data": [paper(4), paper(5)], "total": 6},
    )
    service = ResearchService(http=http)
    req = request()
    first = await service.search(req, scope="test")
    second = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert {r["pmid"] for r in second.records} == {"4", "5"}
    assert second.next_cursor is None


async def test_ctgov_opaque_token_resumes_without_prefix_replay():
    service = ResearchService()
    service.providers.adapter = AsyncMock(
        side_effect=[
            {
                "studies": [
                    {"id": identifier, **study(identifier)} for identifier in ["NCT00000001", "NCT00000002"]
                ],
                "nextPageToken": "OPAQUE/+=",
                "totalCount": 3,
            },
            {"studies": [{"id": "NCT00000003", **study("NCT00000003")}], "totalCount": 3},
        ]
    )
    req = request("trial", "clinical-trials")
    first = await service.search(req, scope="test")
    second = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert second.records[0]["id"] == "NCT00000003" and second.next_cursor is None
    assert second.records[0]["record_type"] == "trial"
    supporting = set(second.records[0]["evidence_ids"])
    assert supporting <= {proof.evidence_id for proof in second.provenance}
    assert supporting.isdisjoint({proof.evidence_id for proof in first.provenance})
    calls = service.providers.adapter.call_args_list
    assert len(calls) == 2 and calls[1].kwargs["page_token"] == "OPAQUE/+="
    assert "OPAQUE" not in first.model_dump_json()


async def test_europepmc_resumes_returned_cursor_with_fixed_page_size():
    http = HTTP(
        {
            "resultList": {"result": [{"source": "MED", "id": str(n)} for n in (0, 1)]},
            "hitCount": 3,
            "nextCursorMark": "OPAQUE/+=",
            "request": {"cursorMark": "*"},
        },
        {"resultList": {"result": [{"source": "MED", "id": "2"}]}, "hitCount": 3},
    )
    service = ResearchService(http=http)
    req = request(source="europepmc")
    first = await service.search(req, scope="test")
    second = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert second.records[0]["pmid"] == "2" and second.next_cursor is None
    assert [c[2]["params"]["pageSize"] for c in http.calls] == [2, 2]
    assert http.calls[1][2]["params"]["cursorMark"] == "OPAQUE/+="


async def test_federated_overflow_is_retained_with_original_evidence():
    service = ResearchService(runtime=ProviderRuntime(cursor_key=b"p" * 32))

    async def search(entity, source, query, filters, limit, offset):
        return (
            [{"pmid": f"{source}-{offset + n}", "title": "BRAF"} for n in range(limit)] if not offset else []
        )

    service.providers.search = search
    req = SearchRequest(entity="article", query="BRAF", limit=2)
    all_rows, evidence = [], set()
    cursor = None
    for _ in range(6):
        result = await service.search(req.model_copy(update={"cursor": cursor}), scope="test")
        all_rows.extend(r["pmid"] for r in result.records)
        evidence.update(p.evidence_id for p in result.provenance)
        assert all(set(r["evidence_ids"]) <= evidence for r in result.records)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert len(all_rows) == len(set(all_rows)) == 6
    assert cursor is None


@pytest.mark.parametrize("change", ["account", "query", "tamper"])
async def test_scoped_cursor_rejects_changes_before_provider_io(change):
    http = HTTP({"data": [paper(0), paper(1)], "next": 2, "total": 4})
    service = ResearchService(http=http)
    req = request()
    first = await service.search(req, scope="test")
    cursor = first.next_cursor
    if change == "tamper":
        cursor = ("a" if cursor[0] != "a" else "b") + cursor[1:]
    with pytest.raises(ResearchError, match="Cursor"):
        await service.search(
            req.model_copy(update={"cursor": cursor, "query": "TP53" if change == "query" else "BRAF"}),
            scope="other" if change == "account" else "test",
        )
    assert len(http.calls) == 1




async def test_gwas_p_value_filter_preserves_raw_page_continuation():
    from gwas_helpers import page, row

    http = HTTP(
        page(
            [
                row(1, p_value=0.1, pvalue_mantissa=1, pvalue_exponent=-1),
                row(2, p_value=0.2, pvalue_mantissa=2, pvalue_exponent=-1),
            ],
            total=4,
            size=2,
        ),
        page(
            [
                row(3, p_value=1e-10, pvalue_mantissa=1, pvalue_exponent=-10),
                row(4, p_value=1e-12, pvalue_mantissa=1, pvalue_exponent=-12),
            ],
            total=4,
            size=2,
            number=1,
        ),
    )
    result = await ResearchService(http=http).search(
        SearchRequest(entity="gwas", query="BRAF", limit=2, filters={"p_value": 1e-8}), scope="test"
    )
    assert {r["id"] for r in result.records} == {"3", "4"}
    assert result.next_cursor is None
    assert [c[2]["params"]["page"] for c in http.calls] == [0, 1]
    page = result.query["execution"]["source_pagination"]["gwas"]
    assert page["raw_rows_scanned"] == 4 and page["filtered_rows"] == 2


async def test_exact_variant_filter_preserves_raw_page_continuation():
    def hit(n, gene):
        return {"_id": str(n), "snpeff": {"ann": {"genename": gene, "hgvs_p": "p.Val600Glu"}}}

    http = HTTP(
        {"hits": [hit(0, "OTHER"), hit(1, "OTHER")], "total": 4},
        {"hits": [hit(2, "BRAF"), hit(3, "BRAF")], "total": 4},
    )
    result = await ResearchService(http=http).search(
        SearchRequest(entity="variant", query="BRAF", limit=2, filters={"gene": "BRAF", "hgvsp": "V600E"}),
        scope="test",
    )
    assert {r["_id"] for r in result.records} == {"2", "3"}
    assert result.next_cursor is None
    assert [c[2]["params"]["from"] for c in http.calls] == [0, 2]


@pytest.mark.parametrize("token", ["X" * 6000, "OPAQUE"])
async def test_provider_tokens_are_preserved_before_visible_string_bounds(token):
    service = ResearchService()
    service.providers.adapter = AsyncMock(
        side_effect=[
            {
                "studies": [
                    {"id": identifier, **study(identifier)} for identifier in ["NCT00000001", "NCT00000002"]
                ],
                "nextPageToken": token,
            },
            {"studies": []},
        ]
    )
    req = request("trial", "clinical-trials")
    first = await service.search(req, scope="test")
    await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert service.providers.adapter.call_args_list[1].kwargs["page_token"] == token
    assert token not in first.model_dump_json()


@pytest.mark.parametrize("token", ["X" * 8193, "", [], 42])
async def test_invalid_opaque_tokens_fail_closed(token):
    service = ResearchService()
    service.providers.adapter = AsyncMock(return_value={"studies": [], "nextPageToken": token})
    result = await service.search(request("trial", "clinical-trials"), scope="test")
    assert result.outcome == "error" and result.next_cursor is None
    assert result.sections["clinical-trials"].error["code"] == "invalid_source_response"


async def test_nonadvancing_numeric_continuation_fails_closed():
    from biomedmcp.pagination import page_payload

    service = ResearchService()
    service.providers.search = AsyncMock(return_value=page_payload([], raw_count=0, total=20,
                                                                   exhausted=False, next_offset=0))
    result = await service.search(request(), scope="test")
    assert result.outcome == "error" and result.next_cursor is None


async def test_provider_failure_does_not_erase_earlier_window_or_peer_evidence():
    service = ResearchService()
    from biomedmcp.pagination import page_payload

    async def search(entity, source, query, filters, limit, offset):
        if source == "europepmc":
            if offset == 0:
                return page_payload([{"pmid": "0"}], raw_count=2, exhausted=False, next_offset=2)
            raise ResearchError("source_unavailable", "Provider unavailable.")
        return page_payload([], raw_count=0, exhausted=True)

    service.providers.search = search
    result = await service.search(SearchRequest(entity="article", query="BRAF", limit=2), scope="test")
    assert result.records[0]["pmid"] == "0"
    assert result.outcome == "partial" and result.next_cursor
    assert result.sections["europepmc"].error["code"] == "source_unavailable"
    assert result.sections["pubmed"].outcome == "empty"


async def test_new_alias_for_delivered_article_is_suppressed_on_later_pages():
    http = HTTP(
        {"data": [{**paper(0), "pmid": "1"}, paper(1001)], "next": 2},
        {"data": [{**paper(2), "pmid": "1", "doi": "10.1234/x"}, paper(1003)], "next": 4},
        {"data": [{**paper(4), "doi": "10.1234/x"}, paper(1005)]},
    )
    service = ResearchService(http=http)
    req = request()
    first = await service.search(req, scope="test")
    second = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert {r["pmid"] for r in second.records} == {"1003", "1005"}
    assert second.next_cursor is None


def test_independent_cursor_snapshots_cannot_collide_within_same_second(monkeypatch):
    from biomedmcp import runtime

    monkeypatch.setattr(runtime.time, "time", lambda: 100)
    codec = runtime.CursorCodec(b"s" * 32)
    a = codec.encode(query={}, scope="a", offset=2)
    b = codec.encode(query={}, scope="a", offset=2)
    assert a != b
    assert codec.decode(a, query={}, scope="a") == codec.decode(b, query={}, scope="a") == 2


async def test_expired_page_state_fails_before_provider_io():
    http = HTTP({"data": [paper(0), paper(1)], "next": 2})
    service = ResearchService(http=http)
    req = request()
    first = await service.search(req, scope="test")
    service.runtime.cache.values.clear()
    with pytest.raises(ResearchError) as caught:
        await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert caught.value.code == "expired_cursor" and len(http.calls) == 1


async def test_local_reranking_scope_is_reported_as_window():
    result = await ResearchService(http=HTTP({"data": [paper(0)]})).search(request(), scope="test")
    assert result.query["execution"]["sort_scope"] == "window"


async def test_sorted_federation_uses_only_qualified_provider_routes():
    service = ResearchService()
    service.providers.search = AsyncMock(return_value=[])
    result = await service.search(
        SearchRequest(entity="article", query="BRAF", filters={"sort": "date"}), scope="test"
    )
    assert result.query["execution"]["sources"] == ["pubmed", "europepmc"]
    assert result.query["execution"]["sort_scope"] == "federated_windows"
    assert "globally exhaustive" in result.warnings[0]


async def test_actual_mcp_literature_continuation_retains_eligible_records(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP(
        {"data": [paper(0), paper(1)], "next": 2},
        {"data": [paper(0), paper(1)], "next": 4},
        {"data": [paper(4), paper(5)]},
    )
    async with Client(create_server(service=ResearchService(http=http))) as client:
        params = {"query": "BRAF", "limit": 2, "filters": {"source": "europepmc"}}
        first = (await client.call_tool("literature_search", params)).data
        second = (
            await client.call_tool("literature_search", {**params, "cursor": first["next_cursor"]})
        ).data
        assert {r["pmid"] for r in second["records"]} == {"4", "5"}
        assert second["next_cursor"] is None


async def test_storage_budget_does_not_advertise_an_unrecoverable_cursor(monkeypatch):
    service = ResearchService(http=HTTP({"data": [paper(0), paper(1)], "next": 2}))
    cache_put = service.runtime.cache.put

    async def put(key, value, ttl):
        return False if key.startswith("page:") else await cache_put(key, value, ttl)

    monkeypatch.setattr(service.runtime.cache, "put", put)
    result = await service.search(request(), scope="test")
    assert result.next_cursor is None
    assert any("storage budget" in warning for warning in result.warnings)


async def test_bounded_source_limit_is_not_reported_as_exhaustive_absence():
    from biomedmcp.runtime import digest

    service = ResearchService(http=HTTP({"data": [paper(0), paper(1)], "next": 2}))
    req = request()
    first = await service.search(req, scope="test")
    key = "page:" + digest(first.next_cursor)
    state = await service.runtime.cache.get(key)
    state["providers"]["europepmc"]["offset"] = 1000
    await service.runtime.cache.put(key, state, 3600)
    result = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    assert not result.records and result.next_cursor is None
    assert result.outcome == "partial" and result.truncated
    assert any("coverage is incomplete" in warning.lower() for warning in result.warnings)


async def test_provider_route_limit_is_disclosed_when_total_is_larger():
    result = await ResearchService(http=HTTP({"data": [paper(0)], "total": 10000})).search(
        request(), scope="test"
    )
    assert result.next_cursor is None
    assert any("Coverage is incomplete" in warning for warning in result.warnings)
    assert result.query["execution"]["source_pagination"]["europepmc"]["total"] == 10000


async def test_retained_source_statuses_have_provenance_on_overflow_pages():
    service = ResearchService()
    service.providers.search = AsyncMock(
        side_effect=lambda entity, source, *args: [{"pmid": f"{source}-{n}"} for n in range(2)]
    )
    req = SearchRequest(entity="article", query="BRAF", limit=2)
    first = await service.search(req, scope="test")
    second = await service.search(req.model_copy(update={"cursor": first.next_cursor}), scope="test")
    ids = {p.evidence_id for p in second.provenance}
    assert all(set(section.evidence_ids) <= ids for section in second.sections.values())
    assert all(set(row["evidence_ids"]) <= ids for row in second.records)
