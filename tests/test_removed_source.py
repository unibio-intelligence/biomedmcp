"""Removed integrations cannot be advertised or reactivated with credentials."""

import json

import pytest
from fastmcp import Client
from native_helpers import HTTP

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.catalog import SEARCH_SOURCES, SECTIONS
from biomedmcp.native.literature import Literature, article_id, plan_sources
from biomedmcp.source_policy import source_names

pytestmark = pytest.mark.source_permissions


def test_removed_source_and_tldr_are_absent_from_public_ownership():
    assert "semanticscholar" not in source_names()
    assert "tldr" not in SECTIONS["article"]
    assert SEARCH_SOURCES["author"] == ["openalex"]


@pytest.mark.parametrize("identifier", ["a" * 40, "s2:1234"])
def test_removed_source_identifiers_do_not_become_other_article_namespaces(identifier):
    with pytest.raises(ResearchError):
        article_id(identifier)


async def test_keys_do_not_restore_a_removed_source_or_trigger_network(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "synthetic-removed-source-key")
    http = HTTP()
    with pytest.raises(ResearchError) as error:
        await Literature(http).search_source("semanticscholar", "BRAF", {}, 2)
    assert error.value.code == "unsupported_source"
    with pytest.raises(ResearchError):
        plan_sources({"source": "semanticscholar"})
    with pytest.raises(ResearchError):
        await ResearchService(http=http).capabilities(source="semanticscholar")
    assert http.calls == []


async def test_mcp_catalog_has_no_tldr_section_and_discovery_has_no_removed_source(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        tools = await client.list_tools()
        discovery = (await client.call_tool("capabilities", {"entity": "article"})).data
    assert "tldr" not in json.dumps([t.input_schema for t in tools])
    assert "semanticscholar" not in json.dumps(discovery)


async def test_removed_author_ids_do_not_acquire_openalex_data():
    http = HTTP()
    result = await execute(
        ResearchService(http=http), "get", {"entity": "author", "id": "s2:1234"}, scope="test"
    )
    assert result.outcome == "error"
    assert result.sections["record"].error["code"] == "invalid_identifier"
    assert http.calls == []
