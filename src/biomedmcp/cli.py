"""JSON CLI over exactly the same application services as MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from .domain import ResearchService
from .errors import ResearchError, error_result
from .output_contracts import failed, validate_output
from .public_catalog import MODELS
from .request_telemetry import phase, request_trace
from .utility_contracts import PROTOCOL_MODELS, validate_utility


async def execute(operation, params, *, url=None, login=False, state_dir=None):
    with request_trace(operation, "cli") as observation:
        value = await _execute(operation, params, url=url, login=login, state_dir=state_dir)
        observation.complete(value, output_state="cli_value_constructed")
        return value


async def _execute(operation, params, *, url=None, login=False, state_dir=None):
    validate_utility(operation, params)
    if operation == "diagnose":
        if state_dir is not None:
            raise ResearchError("invalid_parameters", "Read-only diagnosis does not use a state directory.")
        params = {**params, "diagnose": True}
        operation = "capabilities"
    if operation == "capabilities" and params.get("diagnose") is True and not url:
        if state_dir is not None:
            raise ResearchError("invalid_parameters", "Read-only diagnosis does not use a state directory.")
        from .dispatch import execute as dispatch

        return await dispatch(ResearchService(), operation, params, scope="diagnosis")
    if state_dir is not None and url:
        raise ResearchError("invalid_parameters", "--state-dir applies to local execution only.")
    if operation == "read-resource" and not url and params["uri"].startswith("biomedmcp://evidence/"):
        from mcp.types import TextResourceContents

        from .local_state import LocalState
        from .recovery import parse_uri
        from .runtime import ProviderRuntime

        parse_uri(params["uri"])

        async with asyncio.timeout(75):
            state = await LocalState.open(state_dir)
            service = ResearchService(runtime=ProviderRuntime(cache=state, cursor_key=state.signing_key))
            value = await service.read_evidence(params["uri"], scope=state.scope)
            return [
                TextResourceContents(
                    uri=params["uri"],
                    mime_type="application/json",
                    text=json.dumps(value, ensure_ascii=False, allow_nan=False),
                ).model_dump(mode="json")
            ]
    if url or operation in {"resources", "read-resource", "prompts", "get-prompt", "tools"}:
        import os

        from fastmcp import Client

        target = url
        auth = os.getenv("UBI_PUBLIC_TOKEN") if url else None
        if target is None:
            if os.getenv("UBI_PROFILE") != "local":
                raise ValueError("Local MCP inspection requires UBI_PROFILE=local")
            from .mcp.server import create_server

            target = create_server()
        elif login:
            from urllib.parse import urlsplit

            from fastmcp.client.transports import StreamableHttpTransport

            from .oauth import BioMedOAuth

            endpoint = urlsplit(url)
            if endpoint.scheme != "https" or endpoint.username or endpoint.password:
                raise ResearchError("invalid_parameters", "Hosted OAuth requires a credential-free HTTPS URL.")
            identity = f"https://{endpoint.netloc}/.well-known/biomedmcp-cli-client.json"
            auth = auth or BioMedOAuth(
                client_name="BioMed MCP", client_id=identity, client_metadata_url=identity,
                callback_host="127.0.0.1", callback_port=8765,
                additional_client_metadata={"application_type": "native", "token_endpoint_auth_method": "none"},
            )
            target = StreamableHttpTransport(url, headers={"X-Biomedmcp-Require-Login": "1"})
        elif not os.getenv("UBI_PUBLIC_TOKEN"):
            from .remote_guest import transport

            target = await transport(url)
        async with Client(target, auth=auth) as client:
            primitive = await protocol_call(client, operation, params)
            if primitive is not None:
                return primitive
            result = await client.call_tool_mcp(operation, params)
            from .decoding import decode_tool_result

            return decode_tool_result(result, public_operation=operation)
    from . import transport
    from .dispatch import COMPOSED_TIMEOUT, REQUEST_TIMEOUT
    from .dispatch import execute as dispatch
    from .local_state import LocalState
    from .runtime import ProviderRuntime, operation_deadline, remaining_budget

    transport.configure()
    deadline = time.monotonic() + remaining_budget(
        COMPOSED_TIMEOUT if operation in {"batch", "research"} else REQUEST_TIMEOUT
    )
    token = operation_deadline.set(deadline)
    try:
        async with asyncio.timeout_at(deadline):
            state = await LocalState.open(state_dir)
            runtime = ProviderRuntime(cache=state, cursor_key=state.signing_key)
            value = await dispatch(ResearchService(runtime=runtime), operation, params, scope=state.scope)
            result = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            with phase("output_validation"):
                validate_output(operation, result)
            return result
    except TimeoutError:
        raise ResearchError(
            "operation_timeout",
            "The complete local request deadline elapsed; no absence can be inferred.",
            retryable=True,
        ) from None
    finally:
        operation_deadline.reset(token)
        await transport.shutdown()


def cli_error(exc: Exception) -> ResearchError:
    import httpx
    from mcp import MCPError

    if isinstance(exc, ResearchError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        return cli_error(exc.exceptions[0])
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        return ResearchError("authentication_failed", "The remote service denied access.")
    if isinstance(exc, (httpx.HTTPError, ConnectionError, TimeoutError)):
        return ResearchError("remote_unavailable", "The remote service could not be reached.", retryable=True)
    if isinstance(exc, MCPError):
        code = "invalid_parameters" if exc.error.code == -32602 else "remote_protocol_error"
        return ResearchError(code, "The remote MCP request could not complete.")
    if isinstance(exc, OSError):
        return ResearchError("local_io_error", "The local input or state could not be accessed.")
    if isinstance(exc, (ValueError, TypeError)):
        return ResearchError("invalid_request", "The CLI request is invalid; use a bounded JSON object.")
    return ResearchError("internal_error", "The public CLI operation could not complete.")


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ResearchError("invalid_request", "Invalid CLI options; use --help to inspect the command.")


def main():
    parser = JSONArgumentParser(description="biomedmcp biomedical research")
    parser.add_argument(
        "operation",
        choices=[
            "resources",
            "read-resource",
            "prompts",
            "get-prompt",
            "tools",
            *MODELS,
            "capabilities",
            "batch",
            "quota",
            "diagnose",
        ],
    )
    parser.add_argument("arguments", nargs="?", default="{}", help="JSON, @file.json, or - for stdin")
    parser.add_argument("--url", help="Hosted biomedmcp MCP endpoint; otherwise execute locally")
    parser.add_argument(
        "--state-dir",
        help="Absolute private local cursor/cache directory (default: UBI_LOCAL_STATE_DIR or XDG state directory)",
    )
    parser.add_argument(
        "--login", action="store_true", help="Use the client OAuth login flow for hosted calls"
    )
    try:
        args = parser.parse_args()
        if args.arguments == "-":
            raw = sys.stdin.buffer.read(65537).decode("utf-8")
        elif args.arguments.startswith("@"):
            with Path(args.arguments[1:]).open("rb") as stream:
                raw = stream.read(65537).decode("utf-8")
        else:
            raw = args.arguments
        if len(raw.encode("utf-8")) > 65536:
            raise ValueError("Arguments exceed 64 KiB")
        params = json.loads(raw)
        if not isinstance(params, dict):
            raise ValueError("Arguments must be a JSON object")  # noqa: TRY004 -- user input contract
        value = asyncio.run(
            execute(args.operation, params, url=args.url, login=args.login, state_dir=args.state_dir)
        )
        failure = isinstance(value, dict) and failed(value)
        print(json.dumps(value, allow_nan=False), file=sys.stderr if failure else sys.stdout)
        if failure:
            raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001 -- all CLI failures have a safe JSON/exit contract
        print(json.dumps(error_result(cli_error(exc))), file=sys.stderr)
        raise SystemExit(2)


async def protocol_call(client, operation, params):
    if operation in PROTOCOL_MODELS:
        params = validate_utility(operation, params).model_dump()

    def serial(value):
        if isinstance(value, list):
            return [serial(item) for item in value]
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    if operation == "resources":
        return serial(await client.list_resources())
    if operation == "read-resource":
        return serial(await client.read_resource(params["uri"]))
    if operation == "prompts":
        return serial(await client.list_prompts())
    if operation == "get-prompt":
        return serial(await client.get_prompt(params["name"], params.get("arguments", {})))
    if operation == "tools":
        return serial(await client.list_tools())
    return None
