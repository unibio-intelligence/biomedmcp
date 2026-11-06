"""Authenticated read-only schemas complement the compact scientific tool catalog."""

import json
from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.record_schemas import FAMILIES, record_schema


@pytest.mark.parametrize("family", FAMILIES)
def test_families_are_self_contained_and_not_permission_overrides(family):
    schema = record_schema(family)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"] == f"biomedmcp://schemas/records/{family}"
    assert "does not" in schema["x-ubi-qualification"]

    def refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/")
            for child in value.values():
                refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)

    refs(schema)
    changed = deepcopy(schema)
    changed["$id"] = "mutated"
    assert record_schema(family)["$id"] != changed["$id"]


@pytest.mark.parametrize("family", ["unknown", "../../private", "variant?api_key=sentinel"])
def test_unknown_schema_family_is_safe_error(family):
    with pytest.raises(ResearchError) as caught:
        record_schema(family)
    assert caught.value.code == "invalid_parameters" and family not in str(caught.value)


@pytest.mark.parametrize("family", FAMILIES)
async def test_actual_mcp_can_read_each_schema_without_provider_traffic(monkeypatch, family):
    monkeypatch.setenv("UBI_PROFILE", "local")

    def forbidden(*args, **kwargs):
        raise AssertionError("Schema reads must not acquire provider data")

    monkeypatch.setattr(transport, "AsyncClient", forbidden)
    async with Client(create_server()) as client:
        resources = await client.read_resource(f"biomedmcp://schemas/records/{family}")
    schema = json.loads(resources[0].text)
    assert schema == record_schema(family)
    jsonschema.Draft202012Validator.check_schema(schema)
