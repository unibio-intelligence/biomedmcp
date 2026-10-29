import pytest

from bio_ontology_mcp import server


@pytest.mark.asyncio
async def test_make_request_fails_fast_without_api_key(monkeypatch):
    monkeypatch.setattr(server, "BIOONTOLOGY_API_KEY", "")

    with pytest.raises(RuntimeError, match="BIOONTOLOGY_API_KEY is not configured"):
        await server.make_request("/search", {"q": "BRCA1"})
