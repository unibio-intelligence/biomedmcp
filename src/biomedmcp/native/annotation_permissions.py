"""Exclude explicitly restricted embedded fields without treating omission as absence."""

from copy import deepcopy

HELD_FIELDS = {"mychem": {"sider", "umls"}, "mydisease": {"umls"}}


def projection(source, value):
    """Run at acquisition before either provider or public caches can retain data."""
    held = HELD_FIELDS.get(source, set())

    def visit(item):
        if isinstance(item, dict):
            return {key: visit(child) for key, child in item.items() if key.split(".", 1)[0].lower() not in held}
        if isinstance(item, list):
            return [visit(child) for child in item]
        return deepcopy(item)

    return visit(value)
