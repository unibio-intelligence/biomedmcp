"""Explicit subprocess science-fixture permissions; never installed runtime code."""

BOOTSTRAP = """
from biomedmcp import source_licensing as _fixture_permissions
from biomedmcp.source_policy import source_names as _fixture_names
_fixture_sources = set(_fixture_names())
_fixture_permissions.availability = lambda source: (True, None) if source in _fixture_sources else (False, 'Unknown synthetic source')
_fixture_permissions.operation_allowed = lambda source, operation: source in _fixture_sources
"""
