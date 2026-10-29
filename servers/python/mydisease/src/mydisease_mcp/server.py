"""FastMCP-backed server for MyDisease MCP tools."""
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
from .client import MyDiseaseClient
from .tools import (
    AnnotationApi,
    BatchApi,
    ClinicalApi,
    DrugApi,
    EpidemiologyApi,
    ExportApi,
    GeneAssociationApi,
    GWASApi,
    MappingApi,
    MetadataApi,
    OntologyApi,
    PathwayApi,
    PhenotypeApi,
    QueryApi,
    VariantApi,
)

__all__ = [
    "mcp",
    "get_client",
    "main",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _bool_from_env(value: str, default: bool) -> bool:
    try:
        return value.lower() in {"1", "true", "yes", "on"}
    except AttributeError:
        return default


def _load_client_config() -> Dict[str, Any]:
    return {
        "base_url": os.environ.get("MYDISEASE_BASE_URL", "https://mydisease.info/v1"),
        "cache_enabled": _bool_from_env("false", True),
        "cache_ttl": int(os.environ.get("MYDISEASE_CACHE_TTL", "3600")),
        "rate_limit": int(os.environ.get("MYDISEASE_RATE_LIMIT", "10")),
        "timeout": float(os.environ.get("MYDISEASE_TIMEOUT", "30.0")),
    }


# Initialize client at module load time for use in composition
_client_config = _load_client_config()
logger.info(
    "Initializing MyDisease client with cache_enabled=%s cache_ttl=%s rate_limit=%s timeout=%s",
    _client_config["cache_enabled"],
    _client_config["cache_ttl"],
    _client_config["rate_limit"],
    _client_config["timeout"],
)

_client = MyDiseaseClient(
    base_url=_client_config["base_url"],
    timeout=_client_config["timeout"],
    cache_enabled=_client_config["cache_enabled"],
    cache_ttl=_client_config["cache_ttl"],
    rate_limit=_client_config["rate_limit"],
)


def get_client() -> MyDiseaseClient:
    return _client


mcp = FastMCP(
    name="mydisease-mcp",
    version=package_version,
)

_query_api = QueryApi()
_annotation_api = AnnotationApi()
_batch_api = BatchApi()
_gene_association_api = GeneAssociationApi()
_variant_api = VariantApi()
_phenotype_api = PhenotypeApi()
_clinical_api = ClinicalApi()
_ontology_api = OntologyApi()
_gwas_api = GWASApi()
_pathway_api = PathwayApi()
_drug_api = DrugApi()
_epidemiology_api = EpidemiologyApi()
_export_api = ExportApi()
_mapping_api = MappingApi()
_metadata_api = MetadataApi()


def _make_tool_wrapper(method: Callable[..., Any]) -> Callable[..., Any]:
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
            title="Query MyDisease.info",
            read_only_hint=True,
            open_world_hint=True,
        )
    except ImportError:
        read_only_annotations = None
    
    api_instances: Tuple[Any, ...] = (
        _query_api,
        _annotation_api,
        _batch_api,
        _gene_association_api,
        _variant_api,
        _phenotype_api,
        _clinical_api,
        _ontology_api,
        _gwas_api,
        _pathway_api,
        _drug_api,
        _epidemiology_api,
        _export_api,
        _mapping_api,
        _metadata_api,
    )

    for api in api_instances:
        for name in dir(api):
            if name.startswith("_"):
                continue
            method = getattr(api, name)
            if not inspect.iscoroutinefunction(method):
                continue
            wrapper = _make_tool_wrapper(method)
            mcp.tool(name=name, annotations=read_only_annotations)(wrapper)
            logger.debug("Registered tool: %s", name)


register_all_api_methods()


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


@mcp.custom_route("/.well-known/mcp.json", methods=["GET"], include_in_schema=False)
async def discovery_endpoint(request: Request) -> JSONResponse:
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
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/sse", methods=["POST"], include_in_schema=False)
async def sse_message_fallback(_: Request) -> Response:
    return Response(status_code=204)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="MyDisease MCP Server",
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
        "Starting MyDisease MCP server (transport=%s, host=%s, port=%s)",
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
