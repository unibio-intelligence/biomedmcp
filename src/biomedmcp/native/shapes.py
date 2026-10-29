"""Endpoint-specific minimum shapes: absent collections never mean no matches."""

from ..errors import ResearchError


def invalid_shape():
    raise ResearchError(
        "invalid_source_response", "Provider response does not match the required scientific response shape."
    )


def collection(value, *paths, element=dict):
    """Require one explicit collection path, including its typed ancestors."""
    for path in paths:
        node = value
        missing = False
        for key in path:
            if not isinstance(node, dict) or node.get("error") or node.get("errors"):
                invalid_shape()
            if key not in node:
                missing = True
                break
            node = node[key]
        if missing:
            continue
        if not isinstance(node, list):
            invalid_shape()
        if any(not isinstance(item, element) or not item for item in node):
            invalid_shape()
        return node
    invalid_shape()
