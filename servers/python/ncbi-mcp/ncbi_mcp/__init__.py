"""NCBI Datasets MCP Server.

Optimized Python implementation providing access to NCBI Datasets API.
Reduced from 31 TypeScript tools to 15 composite Python tools (51.6% reduction).
"""

from .server import mcp

__all__ = ["mcp"]
__version__ = "2.0.0"
