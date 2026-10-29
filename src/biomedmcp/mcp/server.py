"""The single public MCP boundary."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager, nullcontext

from mcp.types import Icon, ToolAnnotations
from pydantic import BaseModel
from starlette.responses import JSONResponse

from .. import local_boundary
from ..auth_branding import DISPLAY_NAME, LOGO_URL
from ..content_boundary import SOURCE_POLICY
from ..dispatch import execute as dispatch
from ..domain import ResearchService
from ..errors import ResearchError
from ..examples import by_id, guide_examples
from ..examples import description as example_description
from ..request_telemetry import phase, request_trace
from ..runtime import ProviderRuntime
from .http_security import PublicMCP, trust_policy

READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
LOCAL_READ = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

# Hosted probes include fresh TLS/accounting setup. Keep the aggregate deadline
# below the container (3s) and load-balancer (5s) health-check timeouts.
DEPENDENCY_PROBE_TIMEOUT = 2


def create_server(*, service=None, settings=None, ledger=None, boundary=None, credential_context=None):
    from ..logging_safety import install_log_redaction

    install_log_redaction()
    boundary = boundary or local_boundary
    AuthSettings = boundary.AuthSettings
    build_auth, build_ledger = boundary.build_auth, boundary.build_ledger
    current_context, accounted = boundary.current_context, boundary.accounted
    dependencies_ready, close_auth = boundary.dependencies_ready, boundary.close_auth
    close_ledger = getattr(boundary, "close_ledger", None)
    ServiceError = boundary.ServiceError
    settings = settings or AuthSettings.from_env(default_url="https://biomedmcp.unibiointelligence.com")
    ledger = ledger or build_ledger(settings.profile)
    state = {"service": service, "ready": False}
    readiness_gate = asyncio.Lock()
    if settings.profile == "hosted" and len(os.getenv("UBI_CURSOR_KEY", "")) < 32:
        raise ValueError("UBI_CURSOR_KEY is required in hosted mode and must have at least 32 characters")

    @asynccontextmanager
    async def lifespan(server):
        if service is not None:
            state["ready"] = True
            try:
                yield
            finally:
                state["ready"] = False
            return
        redis = None
        from .. import transport

        transport_started = False
        try:
            async with asyncio.timeout(DEPENDENCY_PROBE_TIMEOUT):
                await dependencies_ready(settings, ledger)
                if settings.redis_url:
                    from redis.asyncio import Redis

                    redis = Redis.from_url(settings.redis_url)
                runtime = ProviderRuntime(redis=redis)
                await runtime.check_dependencies()
                transport.configure(redis=redis)
                transport_started = True
                state["service"] = ResearchService(runtime=runtime)
                state["ready"] = True
            yield
        finally:
            state["ready"] = False
            try:
                if transport_started:
                    await transport.shutdown()
            finally:
                try:
                    if redis is not None:
                        await redis.aclose()
                finally:
                    try:
                        await close_auth(server.auth)
                    finally:
                        if close_ledger is not None:
                            await close_ledger(ledger)

    server = PublicMCP(
        DISPLAY_NAME,
        icons=[Icon(src=LOGO_URL, mime_type="image/svg+xml")],
        version="0.2.1",
        dereference_schemas=False,
        auth=build_auth(settings),
        lifespan=lifespan,
        instructions="Public biomedical research. Use literature_search, trial_search, variant_evidence and study_analysis for their scientific tasks. Use search/get for remaining records, research for declared dossiers, and capabilities for distinct advanced source schemas. Preserve source, species, release and section outcomes. A provider failure is not evidence of absence. Private lake, project imports, durable compute and modeling belong to Ubi platform. "
        + SOURCE_POLICY,
    )
    server.http_trusted_hosts, server.http_trusted_origins = trust_policy(settings)

    def research_service():
        if state["service"] is None:
            raise ResearchError(
                "source_unavailable", "The public research service is not ready.", retryable=True
            )
        return state["service"]

    async def run(name, params, fn, *, key=None, cost=1):
        async def operation():
            with phase("operation"):
                value = await fn(context.cache_scope)
            return value.model_dump(mode="json") if isinstance(value, BaseModel) else value

        context = current_context(settings.resource)
        manager = (
            credential_context(context)
            if credential_context is not None and name != "evidence_read" and not getattr(context, "anonymous", False)
            else nullcontext()
        )
        async with manager:
            from ..provider_credentials import active_credentials

            credentials = active_credentials.get()
            accounting_params = (
                params
                if credentials is None
                else {"operation_params": params, "provider_credential_partition": credentials.partition}
            )
            with phase("accounting"):
                return await accounted(
                    ledger, context, "public." + name, accounting_params, operation, key=key, cost=cost
                )

    from ..output_contracts import output_schema
    from ..public_catalog import DESCRIPTIONS, MODELS, schema
    from ..utility_contracts import UTILITY_MODELS, validate_utility
    from .catalog_tool import CatalogTool

    async def invoke_catalog(name, arguments):
        try:
            return await invoke_public(name, arguments)
        except ServiceError as exc:
            raise ResearchError(
                getattr(exc, "code", "access_denied"),
                "The hosted access or accounting operation could not complete.",
                retryable=getattr(exc, "retryable", False),
            ) from None

    async def invoke_public(name, arguments):
        utility = validate_utility(name, arguments)
        if name == "quota":
            value = await ledger.snapshot(current_context(settings.resource).account_id)
            return {**value, "schema_version": "1.0"}
        if name == "capabilities":
            context = current_context(settings.resource)
            admission = getattr(boundary, "admit_public_read", None)
            if admission is not None:
                await admission(context)
            return await dispatch(research_service(), name, arguments, scope=context.cache_scope)
        if name == "batch":
            calls = [call.model_dump(mode="json") for call in utility.calls]
            return await run(
                name,
                calls,
                lambda scope: dispatch(research_service(), name, {"calls": calls}, scope=scope),
                key=utility.idempotency_key,
                cost=len(calls),
            )
        return await run(
            name,
            arguments,
            lambda scope: dispatch(research_service(), name, arguments, scope=scope),
        )

    utility_descriptions = {
        "batch": "Execute up to ten independent read operations with one atomic quota reservation.",
        "capabilities": "Inspect enabled sources, workflows, sections or an advanced operation's exact schema.",
        "quota": "Inspect current research allowance and reset times; sign in for higher limits.",
    }
    for name in (*MODELS, *UTILITY_MODELS):
        server.add_tool(
            CatalogTool(
                name=name,
                description=DESCRIPTIONS[name]
                if name in MODELS
                else example_description(utility_descriptions[name], name),
                parameters=schema(name),
                output_schema=output_schema(name),
                annotations=LOCAL_READ if name in {"capabilities", "quota"} else READ,
                runner=invoke_catalog,
            )
        )

    def static_output(operation, build, *, boundary_name="mcp_resource"):
        with request_trace(operation, boundary_name) as observation:
            with phase("authentication"):
                current_context(settings.resource)
            with phase("output_encoding"):
                value = build()
            observation.complete(value, output_state="static_output_constructed")
            return value

    def guide_text():
        return (
            "Use the named scientific task tools for papers, trials, variant evidence and study analysis; search/get cover remaining records. Resolve ambiguity before joining biological records. For deeper source functionality inspect capabilities. Research bundles preserve partial failures. Use Ubi platform for curated lake joins, projects, imports, jobs and modeling.\n\n"
            + SOURCE_POLICY
            + "\n\nSelected typed scientific records have optional schemas at biomedmcp://schemas/records/{family}, where family is literature, trial, variant, expression or study. Read a schema when validating those records; schema availability does not grant source permissions or establish provider health."
            + "\n\n"
            + guide_examples()
        )

    @server.resource("biomedmcp://guide")
    async def guide() -> str:
        return static_output("resource_guide", guide_text)

    @server.resource("biomedmcp://schemas/result")
    async def result_schema() -> dict:
        return static_output("resource_result_schema", lambda: output_schema("get"))

    @server.resource("biomedmcp://schemas/evidence")
    async def evidence_schema() -> dict:
        from ..recovery import EvidenceResponse

        return static_output("resource_evidence_schema", EvidenceResponse.model_json_schema)

    @server.resource("biomedmcp://schemas/records/{family}")
    async def scientific_record_schema(family: str) -> dict:
        from ..record_schemas import record_schema

        return static_output("resource_record_schema", lambda: record_schema(family))

    from ..recovery import TEMPLATE

    @server.resource(TEMPLATE, mime_type="application/json")
    async def evidence_range(handle: str, selector: str, start: str, count: str) -> str:
        with request_trace("evidence_read", "mcp_resource") as observation:
            value = await read_range(handle, selector, start, count)
            observation.complete(json.loads(value), output_state="resource_json_constructed")
            return value

    async def read_range(handle: str, selector: str, start: str, count: str) -> str:
        from ..recovery import PREFIX, parse_uri

        uri = f"{PREFIX}{handle}/{selector}/{start}/{count}"
        parse_uri(uri)
        try:
            value = await run(
                "evidence_read",
                {"uri": uri},
                lambda scope: research_service().read_evidence(uri, scope=scope),
            )
        except ServiceError as exc:
            raise ResearchError(
                getattr(exc, "code", "access_denied"),
                "The hosted evidence access or accounting operation could not complete.",
                retryable=getattr(exc, "retryable", False),
            ) from None
        except ResearchError:
            raise
        except Exception:  # noqa: BLE001 -- sanitize before the resource SDK logs
            raise ResearchError("internal_error", "The evidence resource could not be read.") from None
        with phase("output_encoding"):
            return json.dumps(value, ensure_ascii=False, allow_nan=False)

    @server.prompt()
    async def target_research(gene: str) -> str:
        def build():
            arguments = by_id("target-dossier").arguments
            arguments["focus"] = gene
            return (
                "Call research with arguments "
                + json.dumps(arguments)
                + "; distinguish curated assertions, predictions, observational evidence and unavailable sources."
            )

        return static_output("prompt_target_research", build, boundary_name="mcp_prompt")

    @server.custom_route("/health", methods=["GET"])
    async def health(request):
        return JSONResponse({"status": "alive", "product": "biomedmcp"})

    @server.custom_route("/readyz", methods=["GET"])
    async def ready(request):
        healthy = state["ready"]
        if healthy:
            try:
                # Bound both gate admission and all dependency work. Readiness
                # cannot stack unbounded probes or stall the liveness route.
                async with asyncio.timeout(DEPENDENCY_PROBE_TIMEOUT), readiness_gate:
                    await dependencies_ready(settings, ledger)
                    runtime = getattr(state["service"], "runtime", None)
                    if runtime is not None:
                        await runtime.check_dependencies()
            except Exception:  # noqa: BLE001 -- readiness must return a sanitized unavailable status
                healthy = False
        return JSONResponse({"ready": healthy, "auth": settings.profile}, status_code=200 if healthy else 503)

    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default=os.getenv("MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.getenv("FASTMCP_SERVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FASTMCP_SERVER_PORT", "8000")))
    args = parser.parse_args()
    if (
        os.getenv("UBI_PROFILE") == "local"
        and args.transport == "http"
        and args.host not in {"127.0.0.1", "localhost", "::1"}
        and os.getenv("UBI_LOCAL_CONTAINER") != "1"
    ):
        parser.error("Anonymous local HTTP must bind loopback; use a hosted profile for remote access.")
    server = create_server()
    server.run(
        transport=args.transport,
        **(
            {"host": args.host, "port": args.port, "stateless_http": True} if args.transport == "http" else {}
        ),
    )
