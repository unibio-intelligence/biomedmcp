"""Retries exercise the actual public httpcore boundary without provider traffic."""

import asyncio
import json
import socket
import ssl
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpcore
import pytest

from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.native.http import ProviderHTTP
from biomedmcp.runtime import ProviderBudget, ProviderRuntime, operation_deadline

SENTINEL = "provider-credential-query-body-sentinel"


class Stream:
    def __init__(self, body=b'{"records":[{"id":"confirmed"}]}'):
        self.body = body
        self.closed = False

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        self.closed = True


class Pool:
    def __init__(self, outcomes, body=b'{"records":[{"id":"confirmed"}]}'):
        self.outcomes, self.requests, self.streams = outcomes, [], []
        self.body = body

    async def handle_async_request(self, request):
        self.requests.append(request)
        item = self.outcomes[min(len(self.requests) - 1, len(self.outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, [])
        stream = Stream(self.body)
        self.streams.append(stream)
        return httpcore.Response(status, headers=headers, content=stream)


@pytest.fixture
def retry_boundary(monkeypatch):
    public = transport.PublicTransport()
    admissions = []

    async def admit(url):
        transport.validate_url(url)
        admissions.append(url)

    monkeypatch.setattr(transport, "admit", admit)
    monkeypatch.setattr(transport, "_transport", public)
    return public, admissions


@pytest.mark.parametrize(
    "failure",
    [
        429,
        502,
        503,
        504,
        httpcore.ConnectError(SENTINEL),
        httpcore.ConnectTimeout(SENTINEL),
        httpcore.ReadTimeout(SENTINEL),
        httpcore.RemoteProtocolError(SENTINEL),
    ],
)
async def test_replay_safe_get_recovers_and_every_attempt_is_paced(retry_boundary, failure):
    public, admissions = retry_boundary
    pool = public.pool = Pool([failure, 200])
    value = await ProviderHTTP().get("https://mygene.info/v3/query", params={"q": SENTINEL})
    assert value == {"records": [{"id": "confirmed"}]}
    assert len(pool.requests) == len(admissions) == 2
    if not isinstance(failure, Exception):
        assert pool.streams[0].closed


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500, 501])
async def test_nontransient_status_is_not_automatically_retried(retry_boundary, status):
    public, admissions = retry_boundary
    pool = public.pool = Pool([status, 200])
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert len(pool.requests) == len(admissions) == 1
    assert SENTINEL not in str(caught.value)


@pytest.mark.parametrize(
    "method,body",
    [("POST", b"{}"), ("PUT", b"{}"), ("DELETE", b""), ("GET", b"content"), ("HEAD", b"content")],
)
async def test_unqualified_or_unreplayable_requests_are_never_retried(retry_boundary, method, body):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503, 200])
    async with transport.AsyncClient() as client:
        value = await client.request(method, "https://mygene.info/v3/query", content=body)
    assert value.status_code == 503 and len(pool.requests) == len(admissions) == 1


@pytest.mark.parametrize("failure", [429, 503, httpcore.ConnectError(SENTINEL)])
async def test_persistent_failure_has_one_bounded_automatic_retry(retry_boundary, failure, caplog, capsys):
    public, admissions = retry_boundary
    pool = public.pool = Pool([failure])
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://mygene.info/v3/query", params={"q": SENTINEL})
    assert len(pool.requests) == len(admissions) == 2
    assert caught.value.code == ("source_rate_limited" if failure == 429 else "source_unavailable")
    output = capsys.readouterr()
    assert SENTINEL not in str(caught.value) + caplog.text + output.out + output.err


async def test_retry_after_delay_seconds_and_http_date_are_not_shortened(retry_boundary, monkeypatch):
    public, admissions = retry_boundary
    observed = []

    async def sleep(delay):
        observed.append(delay)

    monkeypatch.setattr(transport.asyncio, "sleep", sleep)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(transport, "time", lambda: now.timestamp())
    for header in (b"2", format_datetime(now + timedelta(seconds=3), usegmt=True).encode()):
        public.pool = Pool([(503, [(b"retry-after", header)]), 200])
        assert await ProviderHTTP().get("https://mygene.info/v3/query")
    assert len(admissions) == 4 and observed == [2, 3]


@pytest.mark.parametrize("header", [b"86400", b"-1", b"NaN", b"0.1", b"invalid-date", b"9" * 500])
async def test_unhonorable_retry_after_preserves_failure_without_early_retry(retry_boundary, header):
    public, admissions = retry_boundary
    pool = public.pool = Pool([(429, [(b"retry-after", header)]), 200])
    token = operation_deadline.set(time.monotonic() + 0.05)
    try:
        with pytest.raises(ResearchError) as caught:
            await ProviderHTTP().get("https://mygene.info/v3/query")
        assert caught.value.code == "source_rate_limited"
        assert len(pool.requests) == len(admissions) == 1
    finally:
        operation_deadline.reset(token)


async def test_cancelled_backoff_closes_response_and_makes_no_further_attempt(retry_boundary, monkeypatch):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503, 200])
    sleeping = asyncio.Event()

    async def wait(delay):
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transport.asyncio, "sleep", wait)
    task = asyncio.create_task(ProviderHTTP().get("https://mygene.info/v3/query"))
    try:
        await asyncio.wait_for(sleeping.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.streams[0].closed and len(pool.requests) == len(admissions) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_retry_cannot_bypass_lost_distributed_admission(retry_boundary, monkeypatch):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503, 200])

    class BrokenRedis:
        async def eval(self, *args):
            raise ConnectionError(SENTINEL)

    budget = ProviderBudget(BrokenRedis())

    async def admit(url):
        admissions.append(url)
        if len(admissions) > 1:
            await budget.acquire("mygene")

    monkeypatch.setattr(transport, "admit", admit)
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert caught.value.code == "provider_budget_unavailable"
    assert len(pool.requests) == 1 and len(admissions) == 2


async def test_retry_failure_keeps_successful_peer_evidence(retry_boundary):
    public, _ = retry_boundary
    public.pool = Pool([503])
    runtime = ProviderRuntime()

    async def good():
        return {"records": [{"id": "retained"}]}

    failed, successful = await asyncio.gather(
        runtime.invoke(
            "failed", {}, lambda: ProviderHTTP().get("https://mygene.info/v3/query"), scope="local"
        ),
        runtime.invoke("good", {}, good, scope="local"),
        return_exceptions=True,
    )
    assert isinstance(failed, ResearchError) and failed.code == "source_unavailable"
    assert successful[0]["payload"] == {"records": [{"id": "retained"}]}
    assert runtime.flights == {}


@pytest.mark.parametrize("host,path", sorted(transport.READ_POST_ROUTES))
async def test_qualified_read_post_replays_identical_bounded_bytes(retry_boundary, host, path):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503, 200])
    key = "criteria" if host == "api.reporter.nih.gov" else "q" if path.endswith("/query") else "ids"
    payload = {key: {} if key == "criteria" else ["672", "673"]}
    async with transport.AsyncClient() as client:
        response = await client.post(f"https://{host}{path}", json=payload)
    assert response.status_code == 200 and len(admissions) == 2
    bodies = [b"".join([part async for part in request.stream]) for request in pool.requests]
    assert bodies[0] == bodies[1] and json.loads(bodies[0]) == payload


@pytest.mark.parametrize("parameter", ["scroll_id", "_scroll_id", "fetch_all"])
async def test_stateful_scrolling_is_not_replayed_in_get_or_post(retry_boundary, parameter):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503])
    async with transport.AsyncClient() as client:
        assert (
            await client.get("https://mygene.info/v3/query", params={parameter: "token"})
        ).status_code == 503
        assert (
            await client.post("https://mygene.info/v3/query", data={"q": "TP53", parameter: "token"})
        ).status_code == 503
    assert len(pool.requests) == len(admissions) == 2


async def test_streaming_request_body_and_oversized_post_are_not_replayed(retry_boundary):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503])

    async def content():
        yield b"{}"

    async with transport.AsyncClient() as client:
        assert (await client.post("https://mygene.info/v3/query", content=content())).status_code == 503
        assert (await client.post("https://mygene.info/v3/query", json={"q": "x" * 65536})).status_code == 503
    assert len(pool.requests) == len(admissions) == 2


async def test_invalid_json_and_application_errors_are_not_retried(retry_boundary):
    public, admissions = retry_boundary
    for body, code in (
        (b"not-json", "invalid_source_response"),
        (b'{"error":"unavailable"}', "upstream_error"),
    ):
        public.pool = Pool([200], body=body)
        with pytest.raises(ResearchError) as caught:
            await ProviderHTTP().get("https://mygene.info/v3/query")
        assert caught.value.code == code
    assert len(admissions) == 2


async def test_dns_policy_rejection_makes_zero_connections_and_no_retry(retry_boundary, monkeypatch):
    public, admissions = retry_boundary
    lookups = []

    async def lookup(*args, **kwargs):
        lookups.append(True)
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ]

    class DNSPool:
        async def handle_async_request(self, request):
            await transport.PublicNetworkBackend().connect_tcp("mygene.info", 443)

    public.pool = DNSPool()
    monkeypatch.setattr(transport.anyio, "getaddrinfo", lookup)
    with pytest.raises(ResearchError):
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert len(lookups) == len(admissions) == 1


async def test_validated_ip_failover_uses_one_dns_answer_and_shared_timeout(monkeypatch):
    lookups, calls = [], []

    async def lookup(*args, **kwargs):
        lookups.append(True)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("93.184.216.34", "1.1.1.1")]

    async def connect(self, host, port, timeout, local_address, socket_options):
        calls.append((host, port, timeout))
        if len(calls) == 1:
            raise httpcore.ConnectError(SENTINEL)
        return "connected"

    monkeypatch.setattr(transport.anyio, "getaddrinfo", lookup)
    monkeypatch.setattr(transport.AutoBackend, "connect_tcp", connect)
    assert await transport.PublicNetworkBackend().connect_tcp("mygene.info", 443, timeout=4) == "connected"
    assert len(lookups) == 1 and [row[0] for row in calls] == ["93.184.216.34", "1.1.1.1"]
    assert 0 < calls[0][2] <= 2 and 0 < calls[1][2] <= 4


async def test_tls_verification_failure_is_never_retried(retry_boundary):
    public, admissions = retry_boundary
    failure = httpcore.ConnectError(SENTINEL)
    failure.__cause__ = ssl.SSLCertVerificationError(SENTINEL)
    pool = public.pool = Pool([failure, 200])
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert caught.value.code == "source_connection_rejected" and not caught.value.retryable
    assert len(pool.requests) == len(admissions) == 1


async def test_retry_consumes_the_original_deadline_and_clamps_attempt_timeouts(retry_boundary, monkeypatch):
    public, admissions = retry_boundary
    pool = public.pool = Pool([503, 200])
    monkeypatch.setattr(transport, "retry_delay", lambda headers: 0.025)
    token = operation_deadline.set(time.monotonic() + 0.1)
    try:
        assert await ProviderHTTP().get("https://mygene.info/v3/query")
    finally:
        operation_deadline.reset(token)
    assert len(admissions) == 2
    timeouts = [request.extensions["timeout"]["read"] for request in pool.requests]
    assert 0 < timeouts[1] < timeouts[0] <= 0.1


async def test_response_body_deadline_closes_upstream_without_replay(retry_boundary):
    public, admissions = retry_boundary
    entered = asyncio.Event()

    class SlowStream(Stream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"{}"

    stream = SlowStream()

    class SlowPool:
        async def handle_async_request(self, request):
            return httpcore.Response(200, content=stream)

    public.pool = SlowPool()
    token = operation_deadline.set(time.monotonic() + 0.04)
    try:
        with pytest.raises(ResearchError):
            await asyncio.wait_for(ProviderHTTP().get("https://mygene.info/v3/query"), 0.3)
    finally:
        operation_deadline.reset(token)
    assert entered.is_set() and stream.closed and len(admissions) == 1


async def test_actual_retained_mapping_retry_preserves_public_identity_and_provenance(
    retry_boundary, monkeypatch
):
    from fastmcp import Client

    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    public, admissions = retry_boundary
    payload = [
        {
            "query": "BRAF",
            "_id": "673",
            "symbol": "BRAF",
            "taxid": 9606,
            "entrezgene": 673,
            "ensembl": {"gene": "ENSG00000157764"},
            "HGNC": "1097",
        }
    ]
    pool = public.pool = Pool([503, 200], body=json.dumps(payload).encode())
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "mygene",
                    "operation": "map_gene_ids",
                    "params": {"gene_ids": ["BRAF"], "input_namespace": "symbol"},
                },
            )
        ).data
    assert result["outcome"] == "data" and result["provenance"][0]["source"] == "mygene"
    assert "ENSG00000157764" in json.dumps(result["sections"]["mygene"]["data"])
    assert len(admissions) == len(pool.requests) == 2


@pytest.mark.parametrize(
    "first,last,code,retryable",
    [
        (429, 403, "source_access_denied", False),
        (503, 404, "source_not_found", False),
        (503, 429, "source_rate_limited", True),
    ],
)
async def test_exhausted_retry_preserves_final_status_classification(
    retry_boundary, first, last, code, retryable
):
    public, admissions = retry_boundary
    public.pool = Pool([first, last])
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert caught.value.code == code and caught.value.retryable == retryable and len(admissions) == 2


async def test_retries_reenter_actual_shared_rate_pacing(retry_boundary, monkeypatch):
    public, _ = retry_boundary
    calls = []

    class TimedPool(Pool):
        async def handle_async_request(self, request):
            calls.append(time.monotonic())
            return await super().handle_async_request(request)

    budget = ProviderBudget()
    public.pool = TimedPool([503, 200])

    async def admit(url):
        transport.validate_url(url)
        await budget.acquire("mygene", requests_per_second=20)

    monkeypatch.setattr(transport, "admit", admit)
    monkeypatch.setattr(transport, "retry_delay", lambda headers: 0)
    assert await ProviderHTTP().get("https://mygene.info/v3/query")
    assert len(calls) == 2 and calls[1] - calls[0] >= 0.045


@pytest.mark.parametrize(
    "payload", [{"q": {}}, {"q": None}, {"q": []}, {"q": True}, {"q": [False]}, {"q": ""}]
)
async def test_invalid_qualified_post_shape_does_not_retry(retry_boundary, payload):
    public, admissions = retry_boundary
    public.pool = Pool([503, 200])
    async with transport.AsyncClient() as client:
        value = await client.post("https://mygene.info/v3/query", json=payload)
    assert value.status_code == 503 and len(admissions) == 1


@pytest.mark.parametrize(
    "failure",
    [
        httpcore.WriteTimeout(SENTINEL),
        httpcore.ReadError(SENTINEL),
        httpcore.LocalProtocolError(SENTINEL),
        httpcore.ProxyError(SENTINEL),
        httpcore.PoolTimeout(SENTINEL),
    ],
)
async def test_unqualified_transport_failures_are_not_retried(retry_boundary, failure):
    public, admissions = retry_boundary
    pool = public.pool = Pool([failure, 200])
    with pytest.raises(ResearchError):
        await ProviderHTTP().get("https://mygene.info/v3/query")
    assert len(pool.requests) == len(admissions) == 1


async def test_real_httpcore_connection_keeps_original_tls_hostname_during_ip_pinning(monkeypatch):
    connected, tls_names, writes = [], [], []

    class NetworkStream:
        async def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"

        async def write(self, buffer, timeout=None):
            writes.append(buffer)

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_names.append(server_hostname)
            return self

        def get_extra_info(self, info):
            return None

    async def connect(self, host, port, timeout, local_address, socket_options):
        connected.append(host)
        return NetworkStream()

    async def lookup(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    async def admit(url):
        transport.validate_url(url)

    monkeypatch.setattr(transport.AutoBackend, "connect_tcp", connect)
    monkeypatch.setattr(transport.anyio, "getaddrinfo", lookup)
    monkeypatch.setattr(transport, "admit", admit)
    public = transport.PublicTransport()
    try:
        import httpx

        async with httpx.AsyncClient(transport=public) as client:
            assert (await client.get("https://mygene.info/v3/query")).status_code == 200
    finally:
        await public.shutdown()
    assert connected == ["93.184.216.34"] and tls_names == ["mygene.info"]
    assert b"Host: mygene.info" in b"".join(writes)


async def test_expired_parent_deadline_and_zero_http_budget_make_no_provider_attempt(retry_boundary):
    public, admissions = retry_boundary
    pool = public.pool = Pool([200])
    token = operation_deadline.set(time.monotonic() - 1)
    try:
        with pytest.raises(ResearchError) as caught:
            await ProviderHTTP().get("https://mygene.info/v3/query")
        assert caught.value.code == "operation_timeout"
    finally:
        operation_deadline.reset(token)
    async with transport.AsyncClient(timeout=0) as client:
        with pytest.raises(ResearchError) as caught:
            await client.get("https://mygene.info/v3/query")
        assert caught.value.code == "operation_timeout"
    assert admissions == [] and pool.requests == []
