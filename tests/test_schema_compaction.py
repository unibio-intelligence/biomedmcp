"""Equivalent validation survives nullable/default metadata compaction."""

from copy import deepcopy

import jsonschema
import pytest

from biomedmcp.schema_utils import compact_nullable

LEAVES = [
    {"type": "string", "minLength": 1, "maxLength": 4, "pattern": "^a"},
    {"type": "integer", "minimum": 0, "maximum": 2},
    {"type": "number", "exclusiveMinimum": 0, "multipleOf": 0.5},
    {"type": "boolean"},
    {"type": "string", "enum": ["a", "b"]},
    {"const": "a"},
    {"enum": [0, False, "a"]},
    {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    {
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
        "additionalProperties": False,
    },
]
VALUES = [
    None,
    True,
    False,
    -1,
    0,
    0.5,
    1,
    2,
    3,
    "",
    "a",
    "ab",
    "b",
    [],
    [1],
    ["a"],
    {},
    {"count": 1},
    {"count": "1"},
    {"count": 1, "extra": 2},
]


@pytest.mark.parametrize("leaf", LEAVES)
def test_nullable_shorthand_preserves_validation_for_boundary_values(leaf):
    schema = {"anyOf": [leaf, {"type": "null"}], "default": None, "description": "Retain this annotation"}
    original = deepcopy(schema)
    compact = compact_nullable(schema, omit_null_defaults=True)
    jsonschema.Draft202012Validator.check_schema(compact)
    assert schema == original and compact["description"] == schema["description"]
    assert "default" not in compact
    for value in VALUES:
        assert jsonschema.Draft202012Validator(schema).is_valid(value) == jsonschema.Draft202012Validator(
            compact
        ).is_valid(value), value


@pytest.mark.parametrize(
    "schema",
    [
        {"anyOf": [{"const": "a", "enum": ["b"]}, {"type": "null"}]},
        {"anyOf": [{"const": "a"}, {"type": "null"}], "enum": ["a"]},
        {"anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}], "minimum": 1},
        {"anyOf": [{"type": "null"}, {"type": "null"}]},
        {"anyOf": [{"type": ["string", "integer"]}, {"type": "null"}]},
    ],
)
def test_intersecting_siblings_and_unhandled_branches_are_not_broadened(schema):
    compact = compact_nullable(schema)
    for value in VALUES:
        assert jsonschema.Draft202012Validator(schema).is_valid(value) == jsonschema.Draft202012Validator(
            compact
        ).is_valid(value)


def test_property_names_literal_defaults_and_non_null_defaults_survive():
    literal = {"anyOf": [{"type": "string"}, {"type": "null"}], "additionalProperties": True}
    schema = {
        "type": "object",
        "properties": {
            "additionalProperties": True,
            "default": {"type": "integer", "default": 10},
            "title": {"type": "string"},
        },
        "additionalProperties": False,
        "default": literal,
        "examples": [literal],
        "const": literal,
    }
    compact = compact_nullable(schema, omit_null_defaults=True)
    assert compact["properties"] == schema["properties"]
    assert compact["default"] == compact["const"] == literal
    assert compact["examples"] == [literal]
    assert compact["additionalProperties"] is False


@pytest.mark.parametrize("values", [["free", "pro", "enterprise", "admin"], ["immediate"]])
def test_output_nullable_enum_recompaction_preserves_domain(values):
    from biomedmcp.output_contracts import _compact

    schema = {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}
    compact = _compact(compact_nullable(schema))
    for value in [*VALUES, *values, "unknown"]:
        assert jsonschema.Draft202012Validator(schema).is_valid(value) == jsonschema.Draft202012Validator(
            compact
        ).is_valid(value)


@pytest.mark.parametrize("title", [None, "Registry evidence"])
def test_catalog_compaction_preserves_explicit_titles_and_metadata(title):
    from mcp.types import ToolAnnotations

    from biomedmcp.mcp.catalog_tool import CatalogTool

    tool = CatalogTool(
        name="get",
        title=title,
        description="Retrieve evidence",
        parameters={"type": "object"},
        runner=object(),
        meta={"security": {"scope": "public"}},
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    public = tool.to_mcp_tool()
    assert public.title == title
    assert public.meta == {"security": {"scope": "public"}}
    assert public.annotations.read_only_hint is True
    assert tool.to_mcp_tool(title="Explicit override").title == "Explicit override"
    tool.tags = {"registry"}
    assert tool.to_mcp_tool().meta["fastmcp"]["tags"] == ["registry"]
