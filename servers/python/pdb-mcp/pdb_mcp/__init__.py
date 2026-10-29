"""PDB (Protein Data Bank) MCP Server.

Python implementation providing access to RCSB Protein Data Bank.
5 focused tools - no reduction needed from TypeScript.
"""

from .server import mcp

__all__ = ["mcp"]
__version__ = "2.0.0"
