"""Local BYOK is origin-bound wire configuration, never scientific input or a rights grant."""

import json

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.native.http import ProviderHTTP


@pytest.mark.parametrize(
    "url,setting",
    [
        ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", "NCBI_API_KEY"),
        ("https://api.fda.gov/drug/event.json", "OPENFDA_API_KEY"),
    ],
)
async def test_native_source_keys_are_added_only_to_wire_copies(monkeypatch, url, setting):
    sentinel = "synthetic-native-byok-sentinel"
    monkeypatch.setenv(setting, sentinel)
    observed = []

    def handler(request):
        observed.append(request)
        assert request.url.params["api_key"] == sentinel
        return httpx.Response(200, json={"records": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    params = {"term": "BRAF"}
    result = await ProviderHTTP().get(url, params=params)
    assert params == {"term": "BRAF"}
    assert len(observed) == 1
    assert sentinel not in json.dumps(result)


@pytest.mark.parametrize(
    "url",
    [
        "https://eutils.ncbi.nlm.nih.gov.evil.invalid/entrez/eutils/esearch.fcgi",
        "https://api.fda.gov.evil.invalid/drug/event.json",
        "https://eutils.ncbi.nlm.nih.gov/other/path",
        "https://example.org/entrez/eutils/esearch.fcgi",
        "http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        "https://user@api.fda.gov/drug/event.json",
    ],
)
async def test_keys_are_never_injected_into_unqualified_origins_or_paths(monkeypatch, url):
    monkeypatch.setenv("NCBI_API_KEY", "synthetic-ncbi-origin-sentinel")
    monkeypatch.setenv("OPENFDA_API_KEY", "synthetic-fda-origin-sentinel")

    def handler(request):
        assert "api_key" not in request.url.params
        assert "sentinel" not in str(request.url) + str(request.headers)
        return httpx.Response(200, json={"records": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    await ProviderHTTP().get(url)


@pytest.mark.parametrize(
    "setting,url",
    [
        ("NCBI_API_KEY", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"),
        ("OPENFDA_API_KEY", "https://api.fda.gov/drug/event.json"),
    ],
)
async def test_native_byok_failure_does_not_expose_credentials(monkeypatch, caplog, capsys, setting, url):
    sentinel = "synthetic-local-failure-sentinel"
    monkeypatch.setenv(setting, sentinel)

    def handler(request):
        assert request.url.params["api_key"] == sentinel
        raise httpx.ConnectError(str(request.url), request=request)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ResearchError) as error:
        await ProviderHTTP().get(url)
    assert error.value.code == "source_unavailable"
    captured = capsys.readouterr()
    assert sentinel not in str(error.value) + caplog.text + captured.out + captured.err
