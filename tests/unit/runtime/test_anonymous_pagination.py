"""Public continuation grants a query page, never a guest/account identity."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from biomedmcp.contracts import SearchRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.provider_credentials import RequestCredentials, credential_context
from biomedmcp.runtime import CursorCodec, anonymous_pagination

RESOURCE = "https://public.example/mcp"
ALICE = "anonymous:alice:" + RESOURCE
BOB = "anonymous:bob:" + RESOURCE


def issue(codec, scope=ALICE, resource=RESOURCE, query="BRAF"):
    with anonymous_pagination(scope=scope, resource=resource):
        return codec.encode(query=query, scope=scope, offset=2)


def test_cookie_free_query_cursor_resumes_without_restoring_identity():
    codec = CursorCodec(b"x" * 32)
    cursor = issue(codec)
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        assert codec.decode(cursor, query="BRAF", scope=BOB) == 2
    with pytest.raises(ResearchError, match="Cursor"):
        codec.decode(cursor, query="BRAF", scope=BOB)


@pytest.mark.parametrize("change", ["query", "resource", "account", "scope", "signature", "expiry"])
def test_public_cursor_cannot_cross_other_boundaries(change, monkeypatch):
    from biomedmcp import runtime

    codec = CursorCodec(b"x" * 32)
    cursor = issue(codec)
    query, resource, scope = "BRAF", RESOURCE, BOB
    if change == "query":
        query = "BRCA1"
    elif change == "resource":
        resource = "https://other.example/mcp"
    elif change == "account":
        scope = "account:alice"
    elif change == "signature":
        cursor = ("A" if cursor[0] != "A" else "B") + cursor[1:]
    elif change == "expiry":
        now = runtime.time.time()
        monkeypatch.setattr(runtime.time, "time", lambda: now + 3601)
    with anonymous_pagination(scope=BOB, resource=resource):
        with pytest.raises(ResearchError, match="Cursor"):
            codec.decode(cursor, query=query, scope="anonymous:other" if change == "scope" else scope)


def test_authenticated_and_personal_key_cursors_remain_owner_bound():
    import time

    codec = CursorCodec(b"x" * 32)
    private = codec.encode(query="BRAF", scope="account:alice", offset=2)
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        with pytest.raises(ResearchError):
            codec.decode(private, query="BRAF", scope=BOB)
    context = RequestCredentials(partition="account-alice-v1", deadline=time.monotonic() + 60,
                                 values={}, pacing={"ncbi": "ncbi", "openfda": "openfda"})
    with credential_context(context):
        cursor = issue(codec)
        with anonymous_pagination(scope=BOB, resource=RESOURCE):
            with pytest.raises(ResearchError):
                codec.decode(cursor, query="BRAF", scope=BOB)


async def test_parallel_anonymous_contexts_do_not_leak_into_private_work():
    codec = CursorCodec(b"x" * 32)
    cursor = issue(codec)

    async def public():
        with anonymous_pagination(scope=BOB, resource=RESOURCE):
            await asyncio.sleep(0)
            assert codec.decode(cursor, query="BRAF", scope=BOB) == 2

    async def private():
        await asyncio.sleep(0)
        with pytest.raises(ResearchError):
            codec.decode(cursor, query="BRAF", scope=BOB)

    await asyncio.gather(public(), private())


async def test_real_search_keeps_overflow_and_evidence_private_across_cookie_free_pages():
    service = ResearchService()
    service.providers.search = AsyncMock(side_effect=[
        {"records": [{"id": str(n)} for n in range(3)], "_provider_page": {
            "raw_count": 3, "exhausted": True, "exhaustion_basis": "bounded_snapshot"}},
    ])
    request = SearchRequest(entity="gene", query="BRAF", limit=2)
    with anonymous_pagination(scope=ALICE, resource=RESOURCE):
        first = await service.search(request, scope=ALICE)
    assert first.next_cursor and len(first.records) == 2
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        second = await service.search(request.model_copy(update={"cursor": first.next_cursor}), scope=BOB)
    assert [r["id"] for r in second.records] == ["2"]
    assert not second.next_cursor
    assert service.providers.search.await_count == 1
    recovery = await service.evidence.publish({"rows": first.records}, first.provenance[0], {}, scope=ALICE)
    uri = recovery["uri"]
    with pytest.raises(ResearchError, match="scope"):
        await service.read_evidence(uri, scope=BOB)


async def test_continuation_rechecks_source_permissions_before_cached_overflow(monkeypatch):
    from biomedmcp import source_licensing

    service = ResearchService()
    service.providers.search = AsyncMock(return_value={
        "records": [{"id": str(n)} for n in range(3)], "_provider_page": {
            "raw_count": 3, "exhausted": True, "exhaustion_basis": "bounded_snapshot"}})
    request = SearchRequest(entity="gene", query="BRAF", limit=2)
    with anonymous_pagination(scope=ALICE, resource=RESOURCE):
        first = await service.search(request, scope=ALICE)
    monkeypatch.setattr(source_licensing, "availability", lambda source: (False, "Source now held"))
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        with pytest.raises(ResearchError) as error:
            await service.search(request.model_copy(update={"cursor": first.next_cursor}), scope=BOB)
    assert error.value.code == "source_license_unreleased"
    assert service.providers.search.await_count == 1
