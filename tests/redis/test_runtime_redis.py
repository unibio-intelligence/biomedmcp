"""Required container qualification against real Redis, with no provider traffic."""

import asyncio
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from redis.asyncio import Redis

from biomedmcp.contracts import SearchRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.pagination import page_payload
from biomedmcp.runtime import ProviderRuntime, digest, operation_deadline

pytestmark = pytest.mark.redis
SIGNING_KEY = b"r" * 32


@pytest.mark.parametrize("nested", [False, True])
async def test_actual_pair_continuation_crosses_real_redis_workers(workers, monkeypatch, nested):
    from fastmcp import Client
    from opentargets_mcp import queries
    from test_opentargets_pair_evidence import ADVANCED, ARGS, TOKEN, PairProvider

    from biomedmcp.mcp.server import create_server
    from biomedmcp.native.opentargets_pair_evidence import PairContinuation

    p = PairProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    monkeypatch.setenv("UBI_PROFILE", "local")
    services = [ResearchService(runtime=r) for r in workers.runtimes]
    async with Client(create_server(service=services[0])) as c:
        first = (await c.call_tool("query_source", ADVANCED if nested else ARGS)).data
    action = first["next_actions"][0]
    key = (
        "biomedmcp:result:"
        + PairContinuation.cache_prefix
        + digest(action["arguments"]["params"]["evidence_cursor"])
    )
    assert 0 < await workers.clients[1].pttl(key) <= 3600000
    async with Client(create_server(service=services[1])) as c:
        second = (await c.call_tool(action["tool"], action["arguments"])).data
    assert second["sections"]["opentargets"]["data"]["evidence"][0]["id"] == "pair-1"
    assert second["next_actions"] == [] and len(p.calls) == (7 if nested else 4)
    assert TOKEN not in json.dumps([first, second])


@pytest.mark.parametrize("failure", ["expiry", "unavailable"])
async def test_pair_redis_state_loss_rejects_before_http(workers, monkeypatch, failure):
    from opentargets_mcp import queries
    from redis.exceptions import ConnectionError
    from test_opentargets_pair_evidence import PARAMS, PairProvider

    from biomedmcp.native.opentargets_pair_evidence import PairContinuation

    p = PairProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: p)
    first, second = [ResearchService(runtime=r) for r in workers.runtimes]
    result = await first.source("opentargets", "analyze_association", PARAMS, scope=workers.scope)
    params = result.next_actions[0]["arguments"]["params"]
    key = "biomedmcp:result:" + PairContinuation.cache_prefix + digest(params["evidence_cursor"])
    if failure == "expiry":
        await workers.clients[0].delete(key)
    else:
        original = workers.clients[1].get

        async def fail_cursor_read(name):
            if name == key:
                raise ConnectionError("SYNTHETIC_PRIVATE_REDIS_FAILURE")
            return await original(name)

        monkeypatch.setattr(workers.clients[1], "get", fail_cursor_read)
    with pytest.raises(ResearchError) as error:
        await second.source("opentargets", "analyze_association", params, scope=workers.scope)
    assert error.value.code == ("expired_cursor" if failure == "expiry" else "cache_unavailable")
    assert "PRIVATE_REDIS" not in str(error.value) and len(p.calls) == 2


async def test_actual_variant_evidence_continuation_crosses_real_redis_workers(workers, monkeypatch):
    from fastmcp import Client
    from opentargets_mcp import queries
    from test_opentargets_variant_evidence import ARGS, TOKEN, VariantProvider

    from biomedmcp.mcp.server import create_server

    provider = VariantProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    monkeypatch.setenv("UBI_PROFILE", "local")
    services = [ResearchService(runtime=runtime) for runtime in workers.runtimes]
    async with Client(create_server(service=services[0])) as first:
        result = (await first.call_tool("query_source", ARGS)).data
    action = result["next_actions"][0]
    key = "biomedmcp:result:opentargets-variant-page:" + digest(
        action["arguments"]["params"]["evidence_cursor"]
    )
    assert 0 < await workers.clients[1].pttl(key) <= 3600000
    async with Client(create_server(service=services[1])) as second:
        continued = (await second.call_tool(action["tool"], action["arguments"])).data
    assert (
        continued["sections"]["opentargets"]["data"]["evidences"]["variant"]["evidences"]["rows"][0]["id"]
        == "synthetic-evidence-1"
    )
    assert continued["next_actions"] == [] and len(provider.calls) == 4
    assert TOKEN not in json.dumps(result) + json.dumps(continued)


async def test_variant_evidence_cursor_state_expiry_rejects_before_http(workers, monkeypatch):
    from opentargets_mcp import queries
    from test_opentargets_variant_evidence import PARAMS, VariantProvider

    provider = VariantProvider()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: provider)
    first, second = [ResearchService(runtime=runtime) for runtime in workers.runtimes]
    result = await first.source("opentargets", "query_genetics", PARAMS, scope=workers.scope)
    params = result.next_actions[0]["arguments"]["params"]
    key = "biomedmcp:result:opentargets-variant-page:" + digest(params["evidence_cursor"])
    await workers.clients[0].delete(key)
    with pytest.raises(ResearchError) as caught:
        await second.source("opentargets", "query_genetics", params, scope=workers.scope)
    assert caught.value.code == "expired_cursor" and len(provider.calls) == 2


async def test_evidence_recovery_uses_the_same_snapshot_across_independent_real_redis_runtimes(workers):
    primary = ResearchService(runtime=workers.runtimes[0])
    peer = ResearchService(runtime=workers.runtimes[1])
    calls = []

    async def provider():
        calls.append(1)
        return {"rows": list(range(40))}

    section, proof = await primary._invoke("europepmc", "fixture_recovery", {}, provider, scope=workers.scope)
    uri = section.recovery["omissions"][0]["uri"]
    result = await peer.read_evidence(uri, scope=workers.scope)
    assert result["value"] == list(range(25, 40))
    assert result["evidence_ids"] == [proof.evidence_id] and calls == [1]
    with pytest.raises(ResearchError) as error:
        await peer.read_evidence(uri, scope=workers.scope + "-different")
    assert error.value.code == "evidence_unavailable"


async def test_evidence_snapshot_expiry_uses_actual_redis_ttl(workers):
    from biomedmcp.contracts import Provenance
    from biomedmcp.recovery import TTL, EvidenceStore, parse_uri

    store = EvidenceStore(workers.runtimes[0].cache)
    metadata = await store.publish(
        {"text": "fixture"},
        Provenance(evidence_id="ev_fixture", source="europepmc", content_hash=digest("fixture")),
        {},
        scope=workers.scope,
    )
    handle = parse_uri(metadata["uri"])[0]
    key = "biomedmcp:result:" + store.key(workers.scope, handle)
    assert TTL * 1000 - 10000 <= await workers.clients[0].pttl(key) <= TTL * 1000
    await workers.clients[0].pexpire(key, 1)
    await asyncio.sleep(0.02)
    with pytest.raises(ResearchError) as error:
        await store.read(metadata["uri"], scope=workers.scope)
    assert error.value.code == "evidence_unavailable"


async def test_compressed_large_evidence_is_exact_across_real_redis_replicas(workers):
    from biomedmcp.recovery import SNAPSHOT_BYTES, parse_uri, resource_uri

    primary = ResearchService(runtime=workers.runtimes[0])
    peer = ResearchService(runtime=workers.runtimes[1])
    calls = []
    text = "αβγδ" * 300000

    async def provider():
        calls.append(1)
        return {"text": text}

    section, proof = await primary._invoke(
        "protein-atlas", "fixture_compression", {}, provider, scope=workers.scope
    )
    assert section.recovery["snapshot_status"] == "available"
    handle = parse_uri(section.recovery["uri"])[0]
    key = "biomedmcp:result:" + primary.evidence.key(workers.scope, handle)
    encoded = await workers.clients[0].get(key)
    assert len(encoded) <= SNAPSHOT_BYTES and json.loads(encoded)["encoding"] == "zlib-json"
    uri = resource_uri(handle, "/text", 1_100_000, 4000)
    value = await peer.read_evidence(uri, scope=workers.scope)
    assert value["value"] == text[1_100_000:1_104_000]
    assert value["range"]["total"] == len(text) and value["evidence_ids"] == [proof.evidence_id]
    assert calls == [1]
    with pytest.raises(ResearchError) as caught:
        await peer.read_evidence(uri, scope=workers.scope + "other")
    assert caught.value.code == "evidence_unavailable"


async def test_evidence_snapshot_admission_is_atomic_and_bounded_across_real_redis_replicas(
    workers, monkeypatch
):
    from biomedmcp import recovery
    from biomedmcp.contracts import Provenance

    monkeypatch.setattr(recovery, "MAX_SNAPSHOTS", 8)
    stores = [recovery.EvidenceStore(runtime.cache) for runtime in workers.runtimes]
    proof = Provenance(evidence_id="ev_fixture", source="europepmc", content_hash=digest("fixture"))
    # Qualify atomic storage/eviction within the codec's four-pending grant.
    # Worker saturation and cancellation have their own admission regressions.
    values = []
    for offset in range(0, 24, 4):
        values.extend(
            await asyncio.gather(
                *(
                    stores[i % 2].publish({"index": i}, proof, {}, scope=workers.scope)
                    for i in range(offset, offset + 4)
                )
            )
        )
    index = "biomedmcp:evidence:{evidence}:index"
    keys = await workers.clients[0].zrange(index, 0, -1)
    assert len(keys) == 8
    assert all(await asyncio.gather(*(workers.clients[0].exists(key) for key in keys)))
    assert all(
        len(body) <= recovery.SNAPSHOT_BYTES
        for body in await asyncio.gather(*(workers.clients[0].get(key) for key in keys))
    )
    assert sum(value["snapshot_status"] == "available" for value in values) >= 8


async def test_corrupt_real_redis_snapshot_index_cannot_create_orphan_payloads(workers):
    from biomedmcp.contracts import Provenance
    from biomedmcp.recovery import EvidenceStore

    client = workers.clients[0]
    index = "biomedmcp:evidence:{evidence}:index"
    previous = await client.zrange(index, 0, -1, withscores=True)
    before = {key async for key in client.scan_iter(match="biomedmcp:result:{evidence}:*")}
    try:
        await client.delete(index)
        await client.set(index, "synthetic-index-sentinel")
        metadata = await EvidenceStore(workers.runtimes[1].cache).publish(
            {"text": "fixture"},
            Provenance(evidence_id="ev_fixture", source="europepmc", content_hash=digest("fixture")),
            {},
            scope=workers.scope,
        )
        assert metadata["snapshot_status"] == "unavailable" and "uri" not in metadata
        assert "synthetic-index-sentinel" not in json.dumps(metadata)
        assert {key async for key in client.scan_iter(match="biomedmcp:result:{evidence}:*")} == before
    finally:
        await client.delete(index)
        if previous:
            await client.zadd(index, dict(previous))


async def test_civic_continuation_resumes_on_independent_real_redis_runtime(workers):
    from civic_helpers import EVIDENCE, connection, response
    from native_helpers import HTTP

    from biomedmcp.contracts import GetRequest

    data = response((), ())
    data["data"]["evidenceItems"] = connection([EVIDENCE], total=2, more=True, cursor="raw-civic-next")
    primary = ResearchService(runtime=workers.runtimes[0], http=HTTP(data))
    peer_http = HTTP({"data": {"evidenceItems": connection([EVIDENCE], total=2)}})
    peer = ResearchService(runtime=workers.runtimes[1], http=peer_http)
    request = GetRequest(
        entity="variant", id="BRAF V600E", sections=["civic"], section_parameters={"civic": {"limit": 1}}
    )
    first = await primary.get(request, scope=workers.scope)
    assert first.outcome == "partial" and len(first.next_actions) == 1
    arguments = first.next_actions[0]["arguments"]
    result = await peer.get(GetRequest.model_validate(arguments), scope=workers.scope)
    assert result.outcome == "data" and not result.next_actions
    assert peer_http.calls[0][2]["body"]["variables"]["after"] == "raw-civic-next"
    cached = await primary.get(GetRequest.model_validate(arguments), scope=workers.scope)
    assert cached.provenance[0].cached and len(peer_http.calls) == 1


async def test_civic_expired_real_redis_state_fails_before_provider_io(workers):
    from civic_helpers import EVIDENCE, connection, response
    from native_helpers import HTTP

    from biomedmcp.contracts import GetRequest

    data = response((), ())
    data["data"]["assertions"] = connection([], total=0)
    data["data"]["evidenceItems"] = connection([EVIDENCE], total=2, more=True, cursor="raw-civic-next")
    primary = ResearchService(runtime=workers.runtimes[0], http=HTTP(data))
    peer_http = HTTP()
    peer = ResearchService(runtime=workers.runtimes[1], http=peer_http)
    first = await primary.get(
        GetRequest(
            entity="variant", id="BRAF V600E", sections=["civic"], section_parameters={"civic": {"limit": 1}}
        ),
        scope=workers.scope,
    )
    arguments = first.next_actions[0]["arguments"]
    cursor = arguments["section_parameters"]["civic"]["cursor"]
    key = "biomedmcp:result:civic-page:" + digest(cursor)
    ttl = await workers.clients[0].ttl(key)
    assert 3590 <= ttl <= 3600
    assert await workers.clients[0].delete(key) == 1
    with pytest.raises(ResearchError) as caught:
        await peer.get(GetRequest.model_validate(arguments), scope=workers.scope)
    assert caught.value.code == "expired_cursor" and not peer_http.calls


async def test_http_retry_reenters_real_redis_pacing_and_keeps_shared_result(workers, monkeypatch):
    import httpcore

    from biomedmcp import transport
    from biomedmcp.native.http import ProviderHTTP
    from biomedmcp.runtime import ProviderBudget

    source = "retry-" + uuid.uuid4().hex
    budget = ProviderBudget(workers.clients[0])
    calls = []

    class Stream:
        async def __aiter__(self):
            yield b'{"records":[{"id":"retained"}]}'

        async def aclose(self):
            pass

    class Pool:
        async def handle_async_request(self, request):
            calls.append(time.monotonic())
            return httpcore.Response(503 if len(calls) == 1 else 200, content=Stream())

    public = transport.PublicTransport()
    public.pool = Pool()

    async def admit(url):
        transport.validate_url(url)
        await budget.acquire(source, requests_per_second=10)

    monkeypatch.setattr(transport, "admit", admit)
    monkeypatch.setattr(transport, "_transport", public)
    monkeypatch.setattr(transport, "retry_delay", lambda headers: 0)
    runtime, peer = workers.runtimes

    async def read():
        return await ProviderHTTP().get("https://mygene.info/v3/query")

    value, cached = await runtime.invoke(source, {}, read, scope=workers.scope)
    assert not cached and value["payload"] == {"records": [{"id": "retained"}]}
    assert len(calls) == 2 and calls[1] - calls[0] >= 0.08
    assert (await peer.invoke(source, {}, read, scope=workers.scope)) == (value, True)
    assert len(calls) == 2


@pytest.fixture
async def workers():
    url = os.environ.get("UBI_TEST_REDIS_URL")
    if not url:
        pytest.fail("The required Redis integration group needs isolated UBI_TEST_REDIS_URL; no skip.")
    clients = [Redis.from_url(url, socket_connect_timeout=0.3, socket_timeout=0.3) for _ in range(2)]
    try:
        assert all(await asyncio.gather(*(client.ping() for client in clients)))
        assert clients[0].connection_pool is not clients[1].connection_pool
        yield SimpleNamespace(
            clients=clients,
            runtimes=[ProviderRuntime(redis=client, cursor_key=SIGNING_KEY) for client in clients],
            scope="redis-fixture-" + uuid.uuid4().hex,
            url=url,
        )
    finally:
        for client in clients:
            await client.aclose()


class RedisRelay:
    """Forward real Redis packets; controlled pauses/disconnects are worker faults."""

    def __init__(self, url):
        self.upstream = urlsplit(url)
        if self.upstream.scheme != "redis":
            raise ValueError("Use the isolated plain Redis qualification container.")
        self.connections = set()
        self.tasks = set()
        self.enabled = True
        self.gate = asyncio.Event()
        self.gate.set()

    async def serve(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream_writer = None
        try:
            if not self.enabled:
                return
            upstream_reader, upstream_writer = await asyncio.open_connection(
                self.upstream.hostname,
                self.upstream.port or 6379,
            )
            self.connections.update((writer, upstream_writer))

            async def forward(source, target):
                while chunk := await source.read(65536):
                    await self.gate.wait()
                    target.write(chunk)
                    await target.drain()

            async with asyncio.TaskGroup() as group:
                first = group.create_task(forward(reader, upstream_writer))
                second = group.create_task(forward(upstream_reader, writer))
                await asyncio.wait((first, second), return_when=asyncio.FIRST_COMPLETED)
                first.cancel()
                second.cancel()
        except (ConnectionError, OSError):
            pass
        finally:
            for connection in (writer, upstream_writer):
                if connection is not None:
                    self.connections.discard(connection)
                    connection.close()
                    await connection.wait_closed()
            self.tasks.discard(task)

    async def disconnect(self):
        self.enabled = False
        self.gate.set()
        for writer in list(self.connections):
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)


async def idle(runtime):
    deadline = time.monotonic() + 0.3
    while runtime.flights:
        assert time.monotonic() < deadline, "Cancelled Redis work retained admission"
        await asyncio.sleep(0.005)
    assert not runtime.source_slots


@asynccontextmanager
async def relay_client(workers):
    relay = RedisRelay(workers.url)
    server = await asyncio.start_server(relay.serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    # Redis still parses the original database/auth options; only TCP routing changes.
    client = Redis.from_url(workers.url, socket_connect_timeout=0.2, socket_timeout=0.2)
    client.connection_pool.connection_kwargs.update(host="127.0.0.1", port=port)
    try:
        assert await client.ping()
        yield relay, client
    finally:
        await relay.disconnect()
        server.close()
        await server.wait_closed()
        await client.aclose()


async def test_shared_result_cache_isolated_by_scope_query_and_source(workers):
    first, second = workers.runtimes
    calls = []

    async def acquire():
        calls.append(True)
        return {"records": [{"id": "α", "measured": 0, "missing": None}], "units": "nM"}

    original, hit = await first.invoke("fixture", {"query": "BRAF"}, acquire, scope=workers.scope)
    assert not hit
    shared, hit = await second.invoke("fixture", {"query": "BRAF"}, acquire, scope=workers.scope)
    assert hit and shared == original and len(calls) == 1
    shared["payload"]["records"][0]["measured"] = 99
    assert (await first.invoke("fixture", {"query": "BRAF"}, acquire, scope=workers.scope))[0] == original
    for source, params, scope in (
        ("fixture", {"query": "TP53"}, workers.scope),
        ("other", {"query": "BRAF"}, workers.scope),
        ("fixture", {"query": "BRAF"}, workers.scope + "-other"),
    ):
        assert not (await second.invoke(source, params, acquire, scope=scope))[1]
    assert len(calls) == 4


async def test_result_ttl_expires_and_fresh_bypasses_peer_cache(workers):
    first, second = workers.runtimes
    calls = []

    async def acquire():
        calls.append(True)
        return {"sequence": len(calls)}

    params = {"fixture": workers.scope}
    await first.invoke("fixture", params, acquire, scope=workers.scope, ttl=1)
    key = "biomedmcp:result:" + digest({"source": "fixture", "params": params, "scope": workers.scope})
    assert 0 < await workers.clients[1].pttl(key) <= 1000
    assert (await second.invoke("fixture", params, acquire, scope=workers.scope))[1]
    fresh, hit = await second.invoke(
        "fixture", params, acquire, scope=workers.scope, freshness="fresh", ttl=1
    )
    assert not hit and fresh["payload"]["sequence"] == 2
    deadline = time.monotonic() + 2
    while await workers.clients[0].exists(key):
        assert time.monotonic() < deadline
        await asyncio.sleep(0.02)
    record, hit = await first.invoke("fixture", params, acquire, scope=workers.scope)
    assert not hit and record["payload"]["sequence"] == 3


@pytest.mark.parametrize(
    "data",
    [
        b"{broken",
        b"\xff",
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e999}',
        b'{"value":-1e999}',
    ],
)
async def test_corrupt_serialized_cache_fails_safely(workers, data):
    key = "corrupt-" + workers.scope
    await workers.clients[0].set("biomedmcp:result:" + key, data, ex=10)
    with pytest.raises(ResearchError) as caught:
        await workers.runtimes[1].cache.get(key)
    assert caught.value.code == "cache_invalid_data"
    assert "broken" not in str(caught.value)


async def test_oversized_and_nonfinite_cache_writes_do_not_create_shared_entries(workers):
    cache = workers.runtimes[0].cache
    key = "bounded-" + workers.scope
    assert await cache.put(key, {"value": "é" * 500000}, 10) is False
    assert await workers.runtimes[1].cache.get(key) is None
    with pytest.raises(ValueError):
        await cache.put(key, {"value": float("nan")}, 10)
    assert await workers.runtimes[1].cache.get(key) is None


async def test_independent_workers_share_atomic_provider_pacing(workers):
    source = "fixture-" + workers.scope
    admitted = []

    async def acquire(worker):
        await worker.budget.acquire(source, requests_per_second=4)
        admitted.append(time.monotonic())

    await asyncio.wait_for(asyncio.gather(*(acquire(workers.runtimes[index % 2]) for index in range(6))), 5)
    gaps = [later - earlier for earlier, later in zip(sorted(admitted), sorted(admitted)[1:])]
    assert min(gaps) >= 0.21, gaps  # 250ms policy; 40ms observation tolerance.
    assert await workers.clients[0].pttl("biomedmcp:budget:" + source) > 0


async def test_admission_uses_redis_clock_and_request_deadline(workers, monkeypatch):
    source = "fixture-" + workers.scope
    await workers.runtimes[0].budget.acquire(source, requests_per_second=4)
    monkeypatch.setattr("biomedmcp.runtime.time.time", lambda: 0)
    token = operation_deadline.set(time.monotonic() + 0.03)
    try:
        with pytest.raises(ResearchError) as caught:
            await workers.runtimes[1].budget.acquire(source, requests_per_second=4)
        assert caught.value.code == "provider_busy" and caught.value.retryable
    finally:
        operation_deadline.reset(token)


def page_services(workers, client=None):
    services = [ResearchService(runtime=runtime) for runtime in workers.runtimes]
    if client is not None:
        services[1] = ResearchService(runtime=ProviderRuntime(redis=client, cursor_key=SIGNING_KEY))
    calls = []

    async def acquire(entity, source, query, filters, limit, offset, continuation=None):
        calls.append((offset, continuation))
        if offset == 0:
            return page_payload(
                [{"pmid": "1", "title": "BRAF"}, {"pmid": "2", "title": "BRAF"}],
                raw_count=2,
                exhausted=False,
                next_offset=2,
                continuation="OPAQUE/+=" + workers.scope,
            )
        assert offset == 2 and continuation == "OPAQUE/+=" + workers.scope
        return page_payload(
            [{"pmid": "2", "title": "BRAF"}, {"pmid": "3", "title": "BRAF"}],
            raw_count=2,
            exhausted=True,
        )

    for service in services:
        service.providers.search = acquire
    request = SearchRequest(
        entity="article", query="BRAF " + workers.scope, limit=2, filters={"source": "europepmc"}
    )
    return services, request, calls


async def test_continuation_resumes_on_independent_worker_with_original_provenance(workers):
    services, request, calls = page_services(workers)
    first = await services[0].search(request, scope=workers.scope)
    assert {row["pmid"] for row in first.records} == {"1", "2"} and first.next_cursor
    key = "biomedmcp:result:page:" + digest(first.next_cursor)
    assert 0 < await workers.clients[1].pttl(key) <= 3600000
    second = await services[1].search(
        request.model_copy(update={"cursor": first.next_cursor}), scope=workers.scope
    )
    assert [row["pmid"] for row in second.records] == ["3"] and second.next_cursor is None
    assert calls == [(0, None), (2, "OPAQUE/+=" + workers.scope)]
    assert {proof.evidence_id for proof in first.provenance} <= {
        proof.evidence_id for proof in second.provenance
    }
    assert "OPAQUE" not in second.model_dump_json()


async def test_actual_mcp_continuation_moves_between_redis_workers(workers, monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    services, request, calls = page_services(workers)
    params = {"query": request.query, "limit": 2, "filters": {"source": "europepmc"}}
    async with Client(create_server(service=services[0])) as first:
        result = (await first.call_tool("literature_search", params)).data
    async with Client(create_server(service=services[1])) as second:
        continued = (
            await second.call_tool(
                "literature_search",
                {
                    **params,
                    "cursor": result["next_cursor"],
                },
            )
        ).data
    assert [row["pmid"] for row in continued["records"]] == ["3"]
    assert continued["next_cursor"] is None
    assert calls == [(0, None), (2, "OPAQUE/+=" + workers.scope)]


@pytest.mark.parametrize("change", ["query", "account", "key", "tamper"])
async def test_peer_cursor_rejects_rebinding_before_provider_io(workers, change):
    services, request, calls = page_services(workers)
    first = await services[0].search(request, scope=workers.scope)
    cursor = first.next_cursor
    if change == "key":
        services[1].runtime = ProviderRuntime(redis=workers.clients[1], cursor_key=b"x" * 32)
    if change == "tamper":
        cursor = ("a" if cursor[0] != "a" else "b") + cursor[1:]
    with pytest.raises(ResearchError) as caught:
        await services[1].search(
            request.model_copy(
                update={"cursor": cursor, "query": "TP53" if change == "query" else request.query}
            ),
            scope=workers.scope + "-other" if change == "account" else workers.scope,
        )
    assert caught.value.code == "invalid_cursor" and calls == [(0, None)]


async def test_page_state_expiry_is_distinct_from_evidence_absence(workers):
    services, request, calls = page_services(workers)
    first = await services[0].search(request, scope=workers.scope)
    key = "biomedmcp:result:page:" + digest(first.next_cursor)
    assert await workers.clients[0].pexpire(key, 20)
    await asyncio.sleep(0.04)
    with pytest.raises(ResearchError) as caught:
        await services[1].search(
            request.model_copy(update={"cursor": first.next_cursor}), scope=workers.scope
        )
    assert caught.value.code == "expired_cursor" and calls == [(0, None)]


async def test_restart_process_reads_shared_result_and_scoped_cursor(workers):
    runtime = workers.runtimes[0]
    query = {"query": "BRAF", "fixture": workers.scope}
    cursor = runtime.cursors.encode(query=query, scope=workers.scope, offset=2)
    key = "page:" + digest(cursor)
    await runtime.cache.put(key, {"seen": ["1", "2"], "continuation": "OPAQUE"}, 60)
    code = """
import asyncio,json,os,sys
from redis.asyncio import Redis
from biomedmcp.runtime import ProviderRuntime
async def main():
    value=json.loads(sys.stdin.read())
    async with Redis.from_url(os.environ['UBI_TEST_REDIS_URL']) as redis:
        runtime=ProviderRuntime(redis=redis,cursor_key=b'r'*32)
        state=await runtime.cache.get(value['key'])
        offset=runtime.cursors.decode(value['cursor'],query=value['query'],scope=value['scope'])
        print(json.dumps({'state':state,'offset':offset}))
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(
                json.dumps(
                    {
                        "key": key,
                        "cursor": cursor,
                        "query": query,
                        "scope": workers.scope,
                    }
                ).encode()
            ),
            10,
        )
        assert process.returncode == 0, stderr.decode()
        assert json.loads(stdout) == {"state": {"seen": ["1", "2"], "continuation": "OPAQUE"}, "offset": 2}
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def test_connection_pool_reconnect_preserves_shared_state(workers):
    key = "reconnect-" + workers.scope
    await workers.runtimes[0].cache.put(key, {"measured": 0}, 60)
    await workers.clients[1].connection_pool.disconnect()
    assert await workers.runtimes[1].cache.get(key) == {"measured": 0}


@pytest.mark.parametrize("stage", ["cache_read", "cache_write", "budget"])
async def test_real_connection_loss_fails_closed_and_recovers(workers, stage):
    async with relay_client(workers) as (relay, client):
        runtime = ProviderRuntime(redis=client, cursor_key=SIGNING_KEY)
        called = []

        async def acquire():
            called.append(True)
            if stage == "cache_write":
                await relay.disconnect()
            return {"records": []}

        if stage != "cache_write":
            await relay.disconnect()
        with pytest.raises(ResearchError) as caught:
            if stage == "budget":
                await runtime.budget.acquire("fixture-" + workers.scope)
            else:
                await runtime.invoke("fixture", {}, acquire, scope=workers.scope)
        assert caught.value.code == (
            "provider_budget_unavailable" if stage == "budget" else "cache_unavailable"
        )
        assert caught.value.retryable
        assert len(called) == (1 if stage == "cache_write" else 0)
        relay.enabled = True
        assert await client.ping()
        if stage == "budget":
            await runtime.budget.acquire("fixture-" + workers.scope)
            assert await workers.clients[1].pttl("biomedmcp:budget:fixture-" + workers.scope) > 0
        recovered, hit = await runtime.invoke(
            "fixture", {}, lambda: asyncio.sleep(0, result={"recovered": True}), scope=workers.scope
        )
        assert not hit and recovered["payload"] == {"recovered": True}
        assert not runtime.flights


async def test_continuation_cache_loss_is_a_safe_retryable_error(workers):
    async with relay_client(workers) as (relay, client):
        services, request, calls = page_services(workers, client)
        first = await services[0].search(request, scope=workers.scope)
        await relay.disconnect()
        with pytest.raises(ResearchError) as caught:
            await services[1].search(
                request.model_copy(update={"cursor": first.next_cursor}), scope=workers.scope
            )
        assert caught.value.code == "cache_unavailable" and caught.value.retryable
        assert calls == [(0, None)]


async def test_continuation_state_write_loss_does_not_advertise_a_broken_cursor(workers, monkeypatch):
    async with relay_client(workers) as (relay, client):
        service = page_services(workers)[0][0]
        service.runtime = ProviderRuntime(redis=client, cursor_key=SIGNING_KEY)
        _, request, _ = page_services(workers)
        put = service.runtime.cache.put

        async def store(key, value, ttl):
            if key.startswith("page:"):
                await relay.disconnect()
            return await put(key, value, ttl)

        monkeypatch.setattr(service.runtime.cache, "put", store)
        with pytest.raises(ResearchError) as caught:
            await service.search(request, scope=workers.scope)
        assert caught.value.code == "cache_unavailable" and caught.value.retryable


async def test_delayed_distributed_admission_fails_within_request_deadline(workers):
    async with relay_client(workers) as (relay, client):
        runtime = ProviderRuntime(redis=client)
        relay.gate.clear()
        token = operation_deadline.set(time.monotonic() + 0.06)
        started = time.monotonic()
        try:
            with pytest.raises(ResearchError) as caught:
                await asyncio.wait_for(runtime.budget.acquire("fixture-" + workers.scope), 0.4)
            assert caught.value.code == "provider_budget_unavailable" and caught.value.retryable
            assert time.monotonic() - started < 0.3
        finally:
            operation_deadline.reset(token)


async def test_real_redis_delay_stays_inside_operation_deadline(workers):
    async with relay_client(workers) as (relay, client):
        runtime = ProviderRuntime(redis=client, operation_timeout=0.06)
        relay.gate.clear()
        called = []

        async def acquire():
            called.append(True)
            return {"records": []}

        started = time.monotonic()
        with pytest.raises(ResearchError) as caught:
            await asyncio.wait_for(runtime.invoke("fixture", {}, acquire, scope=workers.scope), 0.4)
        assert caught.value.code == "operation_timeout"
        assert time.monotonic() - started < 0.3 and not called
        await idle(runtime)


async def test_coalesced_cancellation_keeps_peer_and_shared_cache(workers):
    first, second = workers.runtimes
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def acquire():
        calls.append(True)
        entered.set()
        await release.wait()
        return {"records": [{"measured": 0}]}

    tasks = [asyncio.create_task(first.invoke("fixture", {}, acquire, scope=workers.scope)) for _ in range(8)]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for task in tasks[:7]:
            task.cancel()
        cancelled = await asyncio.gather(*tasks[:7], return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in cancelled)
        release.set()
        await tasks[7]
        record, hit = await second.invoke("fixture", {}, acquire, scope=workers.scope)
        assert hit and record["payload"]["records"][0]["measured"] == 0 and len(calls) == 1
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert not first.flights and not second.flights


async def test_all_cancelled_callers_release_admission_without_caching_absence(workers):
    runtime = workers.runtimes[0]
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def acquire():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    tasks = [
        asyncio.create_task(runtime.invoke("fixture", {}, acquire, scope=workers.scope)) for _ in range(8)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.sleep(0)
        assert not runtime.flights and not runtime.source_slots
        record, hit = await runtime.invoke(
            "fixture", {}, lambda: asyncio.sleep(0, result={"recovered": True}), scope=workers.scope
        )
        assert not hit and record["payload"]["recovered"]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_real_redis_readiness_loss_and_recovery_preserve_liveness(workers, monkeypatch):
    from test_infrastructure_readiness import client_for

    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setenv("UBI_MCP_BASE_URL", "http://localhost")
    async with (
        relay_client(workers) as (relay, redis),
        client_for(ProviderRuntime(redis=redis)) as client,
    ):
        assert (await client.get("/readyz")).status_code == 200
        await relay.disconnect()
        ready, live = await client.get("/readyz"), await client.get("/health")
        assert ready.status_code == 503 and ready.json()["ready"] is False
        assert live.status_code == 200 and live.json()["status"] == "alive"
        relay.enabled = True
        assert (await client.get("/readyz")).status_code == 200


@pytest.mark.parametrize("denied", ["get", "set", "eval"])
async def test_real_redis_acl_loss_is_unready_even_when_ping_works(workers, monkeypatch, denied):
    from test_infrastructure_readiness import SENTINEL, client_for

    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setenv("UBI_MCP_BASE_URL", "http://localhost")
    user = "readiness-" + uuid.uuid4().hex
    admin = workers.clients[0]
    await admin.execute_command(
        "ACL",
        "SETUSER",
        user,
        "reset",
        "on",
        ">" + SENTINEL,
        "~biomedmcp:*",
        "+ping",
        "+select",
        "+get",
        "+set",
        "+eval",
        "+time",
        "-" + denied,
    )
    redis = Redis.from_url(
        workers.url, username=user, password=SENTINEL, socket_connect_timeout=0.3, socket_timeout=0.3
    )
    try:
        assert await redis.ping()
        async with client_for(ProviderRuntime(redis=redis)) as client:
            ready = await client.get("/readyz")
            assert ready.status_code == 503 and SENTINEL not in ready.text
            assert (await client.get("/health")).status_code == 200
            await admin.execute_command("ACL", "SETUSER", user, "+" + denied)
            assert (await client.get("/readyz")).status_code == 200
    finally:
        await redis.aclose()
        assert await admin.acl_deluser(user) == 1


async def test_real_readiness_probe_keys_expire_without_consuming_provider_quota(workers, monkeypatch):
    from test_infrastructure_readiness import client_for

    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.setenv("UBI_MCP_BASE_URL", "http://localhost")
    redis = workers.clients[0]
    prefixes = ["biomedmcp:result:readiness:*", "biomedmcp:budget:readiness-*"]
    before = {key for pattern in prefixes async for key in redis.scan_iter(match=pattern)}
    source = "probe-control-" + uuid.uuid4().hex
    quota = "biomedmcp:budget:" + source
    await redis.set(quota, "123456", ex=10)
    async with client_for(ProviderRuntime(redis=redis)) as client:
        assert (await client.get("/readyz")).status_code == 200
    after = {key for pattern in prefixes async for key in redis.scan_iter(match=pattern)}
    created = after - before
    assert len(created) == 2
    assert all([0 < await redis.pttl(key) <= 2000 for key in created])
    assert await redis.get(quota) == b"123456"
    end = time.monotonic() + 3
    while any([await redis.exists(key) for key in created]):
        assert time.monotonic() < end
        await asyncio.sleep(0.05)
    await redis.delete(quota)


async def test_actual_complex_continuation_crosses_real_redis_workers(workers, monkeypatch):
    import httpx
    from complexportal_helpers import body, complex_row
    from fastmcp import Client
    from interpro_helpers import protein

    from biomedmcp import transport
    from biomedmcp.mcp.server import create_server

    original = httpx.AsyncClient
    calls = []
    responses = [
        body([complex_row(identifier="P04637")], total=2),
        body([complex_row(complex_id="CPX-2")], total=2),
    ]

    def handler(request):
        if request.url.host == "rest.uniprot.org":
            return httpx.Response(
                200, json=protein() if request.url.path.endswith("P15056") else {"results": [protein()]}
            )
        assert request.url.host == "www.ebi.ac.uk" and request.url.path == "/intact/complex-ws/search/P15056"
        calls.append(request)
        return httpx.Response(200, json=responses.pop(0))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setenv("UBI_PROFILE", "local")
    services = [ResearchService(runtime=r) for r in workers.runtimes]
    args = {
        "entity": "protein",
        "id": "P15056",
        "sections": ["complexes"],
        "sources": ["complexportal", "uniprot"],
        "section_parameters": {"complexes": {"limit": 1}},
    }
    async with Client(create_server(service=services[0])) as c:
        first = (await c.call_tool_mcp("get", args)).structured_content
    action = first["next_actions"][0]
    key = "biomedmcp:result:complexportal-page:" + digest(
        action["arguments"]["section_parameters"]["complexes"]["cursor"]
    )
    assert 0 < await workers.clients[1].pttl(key) <= 3600000
    async with Client(create_server(service=services[1])) as c:
        second = (await c.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert second["sections"]["complexes"]["data"]["records"][0]["complex_id"] == "CPX-2"
    assert second["next_actions"] == [] and [int(r.url.params["first"]) for r in calls] == [0, 1]
