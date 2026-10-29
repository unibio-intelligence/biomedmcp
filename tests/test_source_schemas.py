"""Validate checked-in Open Targets queries against a dated provider schema."""

import ast
import json
from pathlib import Path

import pytest
from graphql import build_client_schema, parse, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = build_client_schema(
    json.loads((ROOT / "src/biomedmcp/native/opentargets_contract.json").read_text())["introspection"]
)


def queries():
    found = []
    for path in (ROOT / "servers/python/opentargets/src").rglob("*.py"):
        tree = ast.parse(path.read_text())
        fragments = {
            id(child)
            for joined in ast.walk(tree)
            if isinstance(joined, ast.JoinedStr)
            for child in joined.values
        }
        for node in ast.walk(tree):
            if id(node) in fragments:
                continue
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value.strip()
            if value.startswith(("query ", "query{", "query {")):
                found.append(pytest.param(value, id=f"{path.name}:{node.lineno}"))
    return found


@pytest.mark.parametrize("query", queries())
def test_provider_graphql_schema(query):
    assert not validate(SCHEMA, parse(query))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["target", "disease"])
async def test_dynamic_composite_queries(kind):
    from opentargets_mcp.tools.composite import CompositeTools

    class Client:
        calls = 0

        async def _query(self, query, variables=None):
            errors = validate(SCHEMA, parse(query))
            assert not errors, [str(e) for e in errors]
            self.calls += 1
            return {}

    client = Client()
    if kind == "target":
        await CompositeTools().get_target_profile(
            client,
            "ENSG00000157764",
            sections=["identity", "biology", "safety", "tractability", "interactions"],
        )
    else:
        await CompositeTools().get_disease_profile(
            client, "EFO_0000305", sections=["identity", "targets", "phenotypes", "otar_projects"]
        )
    assert client.calls
