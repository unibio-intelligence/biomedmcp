import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 429, 503, "json", "connect"])
async def test_openfda_credentials_absent_from_response_and_framework_logs(
    monkeypatch, caplog, capsys, failure
):
    from openfda_mcp import server

    sentinel = "synthetic-openfda-credential-sentinel"
    monkeypatch.setenv("OPENFDA_API_KEY", sentinel)

    def handler(request):
        assert request.url.params["api_key"] == sentinel
        if failure == "connect":
            raise httpx.ConnectError(str(request.url), request=request)
        if failure == "json":
            return httpx.Response(200, text=sentinel)
        return httpx.Response(failure, json={"error": sentinel})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_drug_info", {"query": "test"}, raise_on_error=False)
    assert result.is_error
    assert sentinel not in str(result)
    assert sentinel not in caplog.text
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err


def test_log_redaction_covers_args_tracebacks_and_encoded_credentials(monkeypatch, caplog):
    import logging
    from urllib.parse import quote

    from biomedmcp.logging_safety import install_log_redaction

    sentinel = "synthetic-secret-with/a+space value"
    monkeypatch.setenv("OPENFDA_API_KEY", sentinel)
    install_log_redaction()
    logger = logging.getLogger("ubi.provider.security-test")
    try:
        raise ValueError(sentinel)
    except ValueError:
        logger.exception("provider failure %s", quote(sentinel, safe=""))
    assert sentinel not in caplog.text
    assert quote(sentinel, safe="") not in caplog.text
    assert "ValueError" in caplog.text
    assert "[REDACTED]" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["bio-ontology", "ncbi", "native-ncbi"])
@pytest.mark.parametrize("failure", [401, 429, 503, "json", "connect"])
async def test_other_credential_provider_boundaries_are_safe(monkeypatch, caplog, capsys, source, failure):
    import traceback

    from fastmcp.exceptions import ToolError

    from biomedmcp.errors import ResearchError
    from biomedmcp.native.http import ProviderHTTP

    sentinel = "synthetic-other-provider-credential-sentinel"
    monkeypatch.setenv("NCBI_API_KEY", sentinel)
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", sentinel)

    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError(str(request.url) + sentinel, request=request)
        if failure == "json":
            return httpx.Response(200, text=sentinel)
        return httpx.Response(failure, json={"error": sentinel})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    with pytest.raises((ToolError, ResearchError)) as caught:
        if source == "bio-ontology":
            from bio_ontology_mcp import server

            monkeypatch.setattr(server, "BIOONTOLOGY_API_KEY", sentinel)
            await server.make_request("/search", {"q": "test"})
        elif source == "ncbi":
            from ncbi_mcp import server

            monkeypatch.setattr(server, "API_KEY", sentinel)
            await server.api_request("GET", "gene")
        else:
            await ProviderHTTP().get("https://eutils.ncbi.nlm.nih.gov/test", params={"api_key": sentinel})
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert sentinel not in caplog.text
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
