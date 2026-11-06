import httpcore
import httpx
import pytest

from biomedmcp import transport

FAILURES = [
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
    (httpcore.ProxyError, httpx.ProxyError),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("core_error,client_error", FAILURES)
@pytest.mark.parametrize("streaming", [False, True])
async def test_core_failures_map_without_sensitive_context(monkeypatch, core_error, client_error, streaming):
    async def admit(url):
        pass

    class Stream:
        async def __aiter__(self):
            raise core_error("credential-sentinel provider-body-sentinel")
            yield b""

        async def aclose(self):
            pass

    class Pool:
        async def handle_async_request(self, request):
            if not streaming:
                raise core_error("credential-sentinel provider-body-sentinel")
            return httpcore.Response(200, content=Stream())

    monkeypatch.setattr(transport, "admit", admit)
    public = transport.PublicTransport()
    public.pool = Pool()
    request_url = "https://provider.example?api_key=credential-sentinel"
    with pytest.raises(client_error) as caught:
        async with httpx.AsyncClient(transport=public) as client:
            await client.get(request_url)
    import traceback

    rendered = "".join(traceback.format_exception(caught.value))
    assert "credential-sentinel" not in rendered
    assert "provider-body-sentinel" not in rendered


@pytest.mark.asyncio
async def test_failed_transport_preserves_successful_federated_evidence(monkeypatch):
    from biomedmcp.contracts import SearchRequest
    from biomedmcp.domain import ResearchService
    from biomedmcp.native.http import ProviderHTTP

    async def admit(url):
        pass

    class Pool:
        async def handle_async_request(self, request):
            raise httpcore.ConnectError("credential-sentinel")

    monkeypatch.setattr(transport, "admit", admit)
    public = transport.PublicTransport()
    public.pool = Pool()
    monkeypatch.setattr(transport, "AsyncClient", lambda **kw: httpx.AsyncClient(transport=public))
    service = ResearchService()

    async def search(entity, source, query, filters, limit, offset):
        if source == "pubmed":
            return await ProviderHTTP().get("https://provider.example")
        return [{"pmid": "123", "title": "BRAF sentinel evidence", "sources": [source]}]

    monkeypatch.setattr(service.providers, "search", search)
    result = await service.search(
        SearchRequest(entity="article", query="BRAF", filters={}), scope="local"
    )
    assert result.outcome == "partial"
    assert result.records[0]["pmid"] == "123"
    assert result.sections["pubmed"].outcome == "unavailable"
    assert result.provenance[0].source == "europepmc"
    assert "credential-sentinel" not in result.model_dump_json()
