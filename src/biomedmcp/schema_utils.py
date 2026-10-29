"""Lossless shorthand for nullable JSON Schema branches."""

from copy import deepcopy

# Each of these assertions ignores instances outside its applicable type.
TYPE_ASSERTIONS = {
    "type",
    "enum",
    "const",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "properties",
    "required",
    "additionalProperties",
    "minProperties",
    "maxProperties",
}


def compact_nullable(value, *, omit_null_defaults=False):
    if isinstance(value, list):
        return [compact_nullable(item, omit_null_defaults=omit_null_defaults) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: {
            name: compact_nullable(child, omit_null_defaults=omit_null_defaults)
            for name, child in item.items()
        }
        if key in {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
        and isinstance(item, dict)
        else deepcopy(item)
        if key in {"const", "enum", "default", "examples"}
        else compact_nullable(item, omit_null_defaults=omit_null_defaults)
        for key, item in value.items()
        if not (omit_null_defaults and key == "default" and item is None)
        and not (key == "additionalProperties" and item is True)
    }
    branches = result.get("anyOf")
    if not isinstance(branches, list) or len(branches) != 2 or {"type": "null"} not in branches:
        return result
    branch = next((item for item in branches if item != {"type": "null"}), None)
    if not isinstance(branch, dict) or not set(branch) <= TYPE_ASSERTIONS or not branch:
        return result
    if set(branch) & (set(result) - {"anyOf"}):
        return result
    if branch.get("type") not in (None, "string", "boolean", "integer", "number", "array", "object"):
        return result
    if "enum" in branch and "const" in branch:
        return result
    # Enum/const already close their value domain, including after unioning null.
    if "const" in branch:
        replacement = {**branch, "enum": [branch["const"], None]}
        replacement.pop("const")
    elif "enum" in branch:
        replacement = {**branch, "enum": [*branch["enum"], None]}
    elif "type" in branch:
        replacement = {**branch, "type": [branch["type"], "null"]}
    else:
        return result
    if "type" in replacement and ("const" in branch or "enum" in branch):
        replacement["type"] = [branch["type"], "null"]
    if set(replacement) & (set(result) - {"anyOf"}):
        return result
    result.pop("anyOf")
    return {**result, **replacement}
