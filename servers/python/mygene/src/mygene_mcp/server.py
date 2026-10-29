"""FastMCP-backed server for MyGene MCP tools."""
from __future__ import annotations

import anyio
import functools
import inspect
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, Optional, Tuple

import mcp.types as mcp_types
from fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__ as package_version
from .client import MyGeneClient
from .tools import (
    AdvancedQueryApi,
    AnnotationApi,
    BatchApi,
    ChemicalApi,
    DiseaseApi,
    ExportApi,
    ExpressionApi,
    GOApi,
    HomologyApi,
    IntervalApi,
    MetadataApi,
    PathwayApi,
    QueryApi,
    VariantApi,
    UnifiedTools,
)

__all__ = [
    "mcp",
    "get_client",
    "main",
]

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client lifecycle management
# ---------------------------------------------------------------------------
def _load_client_config() -> Dict[str, Any]:
    """Load client configuration from environment variables."""
    return {
        "base_url": os.getenv("MYGENE_BASE_URL", "https://mygene.info/v3"),
        "timeout": float(os.getenv("MYGENE_TIMEOUT", "30.0")),
    }


# Initialize client at module load time for use in composition
_config = _load_client_config()
logger.info(
    "Initializing MyGene client with base_url=%s timeout=%s",
    _config["base_url"],
    _config["timeout"],
)

_client = MyGeneClient(
    base_url=_config["base_url"],
    timeout=_config["timeout"],
)


def get_client() -> MyGeneClient:
    """Return the active MyGeneClient."""
    return _client


# ---------------------------------------------------------------------------
# FastMCP initialisation
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="mygene-mcp",
    version=package_version,
)

# Initialize unified tools API
_unified_api = UnifiedTools()


def _make_tool_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an API coroutine so the shared client is injected automatically."""

    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        client = get_client()
        return await method(client, *args, **kwargs)

    signature = inspect.signature(method)
    params = list(signature.parameters.values())[1:]
    wrapper.__signature__ = signature.replace(parameters=params)  # type: ignore[attr-defined]
    return wrapper


def register_all_api_methods() -> None:
    """Register every coroutine defined on the API classes as FastMCP tools."""
    
    # Import ToolAnnotations for Anthropic compliance
    try:
        from mcp.types import ToolAnnotations
        read_only_annotations = ToolAnnotations(
            title="Query MyGene.info",
            read_only_hint=True,
            open_world_hint=True,
        )
    except ImportError:
        read_only_annotations = None
    
    # List of unified tool methods
    unified_tools = [
        "query_genes",
        "get_gene",
        "analyze_gene_context",
        "compare_genes",
        "map_gene_ids",
        "batch_operations",
    ]

    for tool_name in unified_tools:
        method = getattr(_unified_api, tool_name)
        if not inspect.iscoroutinefunction(method):
            logger.warning("Method %s is not a coroutine, skipping", tool_name)
            continue

        wrapper = _make_tool_wrapper(method)
        mcp.tool(name=tool_name, annotations=read_only_annotations)(wrapper)
        logger.info("Registered unified tool: %s", tool_name)


register_all_api_methods()


# ---------------------------------------------------------------------------
# Deprecated module-level guidance
# ---------------------------------------------------------------------------

def __getattr__(name: str) -> Any:  # pragma: no cover - guidance only
    if name == "ALL_TOOLS":
        raise AttributeError(
            "ALL_TOOLS has been removed in v0.3.0. Use FastMCP list_tools instead."
        )
    if name == "API_CLASS_MAP":
        raise AttributeError(
            "API_CLASS_MAP has been removed in v0.3.0. Tool dispatch is handled by FastMCP."
        )
    raise AttributeError(name)


# ---------------------------------------------------------------------------
# Discovery endpoints for HTTP/SSE transports
# ---------------------------------------------------------------------------


@mcp.custom_route("/.well-known/mcp.json", methods=["GET"], include_in_schema=False)
async def discovery_endpoint(request: Request) -> JSONResponse:
    """Expose MCP discovery metadata for HTTP/SSE clients."""

    base_url = str(request.base_url).rstrip("/")
    sse_path = "sse"
    message_path = "messages/"
    http_path = "mcp"

    capabilities = mcp._mcp_server.get_capabilities(
        NotificationOptions(),
        experimental_capabilities={}
    )

    transports: Dict[str, Dict[str, str]] = {
        "sse": {
            "url": f"{base_url}/{sse_path}",
            "messageUrl": f"{base_url}/{message_path}",
        }
    }

    transports["http"] = {
        "url": f"{base_url}/{http_path}",
    }

    discovery = {
        "protocolVersion": mcp_types.LATEST_PROTOCOL_VERSION,
        "server": {
            "name": mcp._mcp_server.name,
            "version": mcp._mcp_server.version,
            "instructions": mcp._mcp_server.instructions,
        },
        "capabilities": capabilities.model_dump(mode="json"),
        "transports": transports,
    }

    return JSONResponse(discovery)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def root_health(_: Request) -> JSONResponse:
    """Simple health check endpoint."""

    return JSONResponse({"status": "ok"})


@mcp.custom_route("/sse", methods=["POST"], include_in_schema=False)
async def sse_message_fallback(_: Request) -> Response:
    """Gracefully handle clients that POST to the SSE endpoint."""

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MyGene MCP Server",
        epilog="Environment overrides: MCP_TRANSPORT, FASTMCP_SERVER_HOST, FASTMCP_SERVER_PORT",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="Transport protocol to expose (stdio, sse, or http)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("FASTMCP_SERVER_HOST", "0.0.0.0"),
        help="Host for SSE transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("FASTMCP_SERVER_PORT", "8000")),
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG level) logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.transport in {"sse", "http"}:
        os.environ["FASTMCP_SERVER_HOST"] = args.host
        os.environ["FASTMCP_SERVER_PORT"] = str(args.port)
        if hasattr(mcp, "settings"):
            mcp.settings.host = args.host  # type: ignore[attr-defined]
            mcp.settings.port = args.port  # type: ignore[attr-defined]
        logger.info("Configured %s host=%s port=%s", args.transport.upper(), args.host, args.port)

    logger.info(
        "Starting MyGene MCP server (transport=%s, host=%s, port=%s)",
        args.transport,
        args.host,
        args.port,
    )

    try:
        if args.transport == "http":
            async def run_http() -> None:
                await mcp.run_http_async(host=args.host, port=args.port)

            anyio.run(run_http)
        else:
            mcp.run(transport=args.transport)
    except KeyboardInterrupt:  # pragma: no cover - user interaction
        logger.info("Server interrupted by user")
    except Exception:  # pragma: no cover - unexpected runtime failure
        logger.exception("Server encountered an unrecoverable error")
        raise


if __name__ == "__main__":  # pragma: no cover
    main()
