"""Decode structured in-process MCP adapter responses."""

import json
from typing import Any

from .errors import ResearchError


def decode_tool_result(result: Any, *, public_operation: str | None = None) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        value = structured
    else:
        value = getattr(result, "data", None)
        if not isinstance(value, (dict, list)):
            texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
            text = "\n".join(texts)
            if len(text.encode()) > 2_000_000:
                raise ResearchError("response_too_large", "The source exceeded its response budget.")
            try:
                value = json.loads(text)
            except ValueError:
                value = None
    is_error = getattr(result, "is_error", False)
    if public_operation:
        from .output_contracts import validate_output

        validate_output(public_operation, value)
        if "error" in value:
            error = value["error"]
            raise ResearchError(
                error["code"],
                error["message"],
                retryable=error["retryable"],
                correction=error["correction"],
            ) from None
        return value  # Scientific failures retain their sections/provenance, also when isError is true.
    if is_error:
        # Retained provider output is untrusted. Preserve only the controlled
        # provider-boundary classifications; never echo arbitrary error text.
        codes = {
            "source_unavailable",
            "source_rate_limited",
            "source_authentication_failed",
            "source_access_denied",
            "source_not_found",
            "invalid_source_response",
            "identity_mismatch",
            "ambiguous_identity",
            "source_contract_changed",
            "source_connection_rejected",
            "source_response_budget",
        }
        code = value.get("code") if isinstance(value, dict) else None
        raise ResearchError(
            code if code in codes else "upstream_error",
            "The source operation failed; no negative evidence can be inferred.",
            retryable=value.get("retryable") is True if code in codes else True,
        ) from None
    if value is None:
        raise ResearchError("invalid_source_response", "Expected structured JSON from the source.")
    return value
