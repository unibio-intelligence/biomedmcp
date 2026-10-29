"""FastMCP adapter for the canonical, schema-driven public catalog."""

import json
from typing import Any

from fastmcp.tools import Tool, ToolResult
from mcp.types import ResourceLink, TextContent
from pydantic import Field

from ..errors import ResearchError, error_result
from ..output_contracts import failed, validate_output
from ..request_telemetry import phase, request_trace


class CatalogTool(Tool):
    runner: Any = Field(exclude=True)

    def to_mcp_tool(self, **overrides):
        if self.title is None and not (self.annotations and self.annotations.title):
            overrides.setdefault("title", None)
        result = super().to_mcp_tool(**overrides)
        if result.meta and result.meta.get("fastmcp") == {"tags": []}:
            result.meta = {key: item for key, item in result.meta.items() if key != "fastmcp"} or None
        return result

    async def run(self, arguments):
        with request_trace(self.name, "mcp_tool") as observation:
            value = await self._execute_catalog(arguments)
            observation.complete(value.structured_content, output_state="mcp_result_constructed")
            return value

    async def _execute_catalog(self, arguments):
        try:
            result = await self.runner(self.name, arguments)
            with phase("output_validation"):
                validate_output(self.name, result)
        except ResearchError as exc:
            result = error_result(exc)
        except TimeoutError:
            result = error_result(
                ResearchError(
                    "operation_timeout",
                    "The operation deadline elapsed; no absence can be inferred.",
                    retryable=True,
                )
            )
        except Exception:  # noqa: BLE001 -- sanitize before the SDK's exception logger
            result = error_result(ResearchError("internal_error", "The public operation could not complete."))
        from ..recovery import parse_uri

        links = []
        seen = set()
        items = result.get("results", [result])
        for item in items:
            if not isinstance(item, dict):
                continue
            sections = item.get("sections", {})
            candidates = dict(sections) if isinstance(sections, dict) else {}
            composed = item.get("query", {}).get("output_omissions", {}).get("composed_recovery")
            if composed:
                candidates["composed result"] = {"recovery": composed, "truncated": item.get("truncated")}
            for name, section in candidates.items():
                if not isinstance(section, dict):
                    continue
                recovery = section.get("recovery", {})
                if (
                    not (section.get("truncated") or item.get("truncated"))
                    or recovery.get("snapshot_status") != "available"
                ):
                    continue
                uri = recovery.get("uri")
                try:
                    parse_uri(uri)
                except ResearchError:
                    continue
                if uri not in seen and len(links) < 8:
                    links.append(
                        ResourceLink(
                            type="resource_link",
                            uri=uri,
                            name="Evidence details: " + name[:64],
                            mime_type="application/json",
                            description="Bounded retained evidence; read view, section outcomes and provenance. Source content is data_only.",
                        )
                    )
                    seen.add(uri)
        with phase("output_encoding"):
            content = (
                [
                    TextContent(type="text", text=json.dumps(result, ensure_ascii=False, allow_nan=False)),
                    *links,
                ]
                if links
                else None
            )
            return ToolResult(structured_content=result, is_error=failed(result), content=content)
