"""Neutral hosting contract with synthetic wire keys; no provider traffic."""
import asyncio
import logging
import time

import httpcore
import httpx
import pytest

from biomedmcp import provider_credentials as credentials
from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.logging_safety import install_log_redaction, redact
from biomedmcp.runtime import ProviderRuntime, ResultCache

SECRET = "synthetic-wire-key-sentinel"


def snapshot(partition="alice-v1", values=None, **kwargs):
    return credentials.RequestCredentials(
        partition=partition, deadline=time.monotonic()+60,
        values=values if values is not None else {"ncbi":SECRET,"openfda":SECRET},
        pacing={"ncbi":partition+":ncbi","openfda":partition+":openfda"}, **kwargs)


@pytest.fixture
def eligible(monkeypatch):
    monkeypatch.setattr(credentials, "availability", lambda _: (True,None))


@pytest.mark.parametrize("url,query,header", [
    ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene",True,False),
    ("https://api.ncbi.nlm.nih.gov/datasets/v2/gene/id/1",False,True),
    ("https://api.fda.gov/drug/event.json?limit=1",True,False)])
async def test_keys_exist_only_at_core_boundary(eligible, monkeypatch, url, query, header):
    seen = []
    class Stream:
        async def __aiter__(self):
            yield b'{"fixture":true}'
        async def aclose(self):pass
    class Pool:
        async def handle_async_request(self, request):
            seen.append(request)
            return httpcore.Response(200, content=Stream())
    async def admit(url):
        assert SECRET not in url
    monkeypatch.setattr(transport,"admit",admit)
    public = transport.PublicTransport()
    await public.pool.aclose()
    public.pool = Pool()
    with credentials.credential_context(snapshot()):
        async with httpx.AsyncClient(transport=public) as client:
            result = await client.get(url)
            assert SECRET not in str(result.request.url) + str(result.request.headers)
    assert (SECRET.encode() in seen[0].url.target) is query
    assert any(k==b"api-key" and v==SECRET.encode() for k,v in seen[0].headers) is header
    assert credentials.active_credentials.get() is None


@pytest.mark.parametrize("url", ["https://api.fda.gov.evil/drug/event.json",
    "https://eutils.ncbi.nlm.nih.gov.evil/entrez/eutils/esearch.fcgi",
    "https://example.org/drug/event.json"])
def test_other_hosts_never_receive_user_keys(eligible,url):
    request = httpx.Request("GET",url)
    with credentials.credential_context(snapshot()):
        wire_url,headers = credentials.wire_parts(request)
    assert SECRET not in str(wire_url)+str(headers)


@pytest.mark.parametrize("url,method", [
    ("http://api.fda.gov/drug/event.json","GET"),
    ("https://api.fda.gov:444/drug/event.json","GET"),
    ("https://api.fda.gov/unknown","GET"),
    ("https://api.ncbi.nlm.nih.gov/variation/v0/refsnp/1","GET"),
    ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi","POST")])
def test_unqualified_routes_fail_before_wire(eligible,url,method):
    with credentials.credential_context(snapshot()), pytest.raises(ResearchError,match="qualified wire route"):
        credentials.wire_parts(httpx.Request(method,url))


def test_operator_keys_replaced_only_in_request_and_missing_user_key_is_anonymous(eligible):
    request = httpx.Request("GET","https://api.fda.gov/drug/event.json?api_key=operator-key&limit=1",
                            headers={"api-key":"operator-key","Authorization":"operator-key"})
    with credentials.credential_context(snapshot(values={})):
        url, headers = credentials.wire_parts(request)
    assert "operator-key" not in str(url)+str(headers)+str(request.url)+str(request.headers)
    assert url.params["limit"] == "1"


def test_policy_withdrawal_cannot_be_overridden_by_keys(monkeypatch):
    monkeypatch.setattr(credentials, "availability", lambda _: (False, "Permission withdrawn"))
    with credentials.credential_context(snapshot()), pytest.raises(ResearchError) as caught:
        credentials.wire_parts(httpx.Request("GET","https://api.fda.gov/drug/event.json"))
    assert caught.value.code == "source_unreleased"


async def test_cache_flights_partition_versions_while_evidence_stays_owned():
    cache, runtime = ResultCache(), ProviderRuntime()
    with credentials.credential_context(snapshot("alice-v1")):
        await cache.put("page:opaque",{"window":1},60)
        await cache.put("{evidence}:owner:handle",{"acquired":True},60)
    with credentials.credential_context(snapshot("alice-v2")):
        assert await cache.get("page:opaque") is None
        assert await cache.get("{evidence}:owner:handle") == {"acquired":True}
    calls = []
    async def invoke(partition):
        with credentials.credential_context(snapshot(partition)):
            async def provider():
                calls.append(partition)
                await asyncio.sleep(0.01)
                return {"fixture":partition}
            result,_ = await runtime.invoke("fixture",{},provider,scope="same-account")
            return result["payload"]
    results = await asyncio.gather(invoke("alice-v1"),invoke("alice-v1"),invoke("alice-v2"))
    assert results == [{"fixture":"alice-v1"},{"fixture":"alice-v1"},{"fixture":"alice-v2"}]
    assert calls.count("alice-v1") == calls.count("alice-v2") == 1
    assert not runtime.flights


async def test_private_pacing_precedes_global_pacing(eligible,monkeypatch):
    calls=[]
    class Budget:
        async def acquire(self,source,**kwargs):calls.append(source)
    monkeypatch.setattr(transport,"_budget",Budget())
    with credentials.credential_context(snapshot()):
        await transport.admit("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
    assert calls == ["alice-v1:ncbi","ncbi"]


@pytest.mark.parametrize("split",[1,8,len(SECRET)-1])
async def test_chunked_echo_never_releases_a_secret_prefix(split):
    yielded=[]
    class Stream:
        async def __aiter__(self):
            yield SECRET[:split].encode()
            yield SECRET[split:].encode()
        async def aclose(self):pass
    with pytest.raises(ResearchError) as caught:
        async for chunk in transport.BoundedStream(Stream(),patterns=(SECRET.encode(),)):
            yielded.append(chunk)
    assert caught.value.code == "source_unavailable" and yielded == []
    assert SECRET not in str(caught.value)


async def test_benign_chunk_boundaries_preserve_complete_content():
    class Stream:
        async def __aiter__(self):
            yield b'{"fixture":'
            yield b'true}'
        async def aclose(self):pass
    result=b"".join([c async for c in transport.BoundedStream(Stream(),patterns=(SECRET.encode(),))])
    assert result==b'{"fixture":true}'


def test_dynamic_log_redaction_is_request_local(caplog):
    install_log_redaction()
    with credentials.credential_context(snapshot()):
        logging.getLogger("credential-fixture").warning("%s",SECRET)
        assert SECRET not in redact("header value "+SECRET)
    assert SECRET not in caplog.text
    assert redact(SECRET)==SECRET


def test_expired_context_cannot_enter_cache_or_wire():
    value=snapshot()
    value.deadline=time.monotonic()-1
    with pytest.raises(ResearchError), credentials.credential_context(value):pass


@pytest.mark.parametrize("change",[{"partition":"bad/value"},{"deadline":float("nan")},
    {"values":{"other":SECRET}},{"values":{"ncbi":"\n"}},{"pacing":{}},{"blocked":{"other"}}])
def test_invalid_internal_context_rejected(change):
    values={"partition":"p","deadline":time.monotonic()+60,"values":{},
            "pacing":{"ncbi":"p:n","openfda":"p:f"}}
    values.update(change)
    with pytest.raises(ValueError):credentials.RequestCredentials(**values)
