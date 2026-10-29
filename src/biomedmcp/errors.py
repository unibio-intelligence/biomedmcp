"""Public research errors do not require hosted Ubi packages."""

from contextlib import contextmanager
from functools import cache, wraps


def correction_for(code: str) -> str:
    if code in {"accounting_unresolved", "request_in_progress", "reservation_reconciled"}:
        return "Retain the original request key and ask the operator to inspect accounting status before retrying; do not submit a new idempotency key."
    if code == "replay_denied":
        return "Use the original authorized client and account; do not reuse another caller's request key."
    if code in {"evidence_unavailable", "evidence_invalid_data"}:
        return "Repeat the original public request to obtain a new scoped evidence snapshot; retain saved evidence and do not infer absence."
    if code == "invalid_resource":
        return (
            "Use the exact evidence URI returned by this service; do not construct a file or network locator."
        )
    if code in {"evidence_resource_budget", "output_metadata_budget"}:
        return "Select a provided child-field resource or request fewer scientific sections/a narrower source window."
    if code in {"internal_error", "invalid_output", "invalid_adapter_schema"}:
        return (
            "Report the operation and error code to the maintainer, without credentials or sensitive input."
        )
    if code == "invalid_source_response":
        return "Select another qualified source or report the source/error code; do not treat this as empty evidence."
    if code == "source_contract_changed":
        return "Report the source and operation to the maintainer for current-contract reconciliation; do not infer absence."
    if code == "source_connection_rejected":
        return "Check provider DNS/TLS policy with the operator or select another qualified source."
    if code in {"invalid_cursor", "expired_cursor", "missing_page_state"}:
        return "Restart the same query without a cursor."
    if code.startswith(("invalid_", "unknown_", "unsupported_")):
        return "Inspect tools/list and capabilities, then correct the arguments before retrying."
    if "ambiguous" in code:
        return "Resolve the identifier with its species, namespace and assembly before joining evidence."
    if "rate_limit" in code or code == "provider_busy":
        return "Wait before retrying; reduce concurrent requests and inspect quota."
    if "authentication" in code or "access_denied" in code:
        return "Check the configured access permissions; keep credentials in client secret storage."
    if code in {"local_io_error", "invalid_local_state"}:
        return "Check the local input file or private state directory and its permissions."
    return "Retry later or select another qualified source; do not infer absence from this failure."


class ResearchError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        correction: str | None = None,
        details: list[dict] | None = None,
    ):
        super().__init__(message)
        self.code, self.retryable = code, retryable
        self.correction = correction or correction_for(code)
        self.details = details or []

    def as_dict(self):
        from .logging_safety import redact

        return {
            "code": self.code,
            "message": redact(str(self)),
            "retryable": self.retryable,
            "correction": self.correction,
            **({"fields": {f["path"]: f["constraint"] for f in self.details}} if self.details else {}),
        }


@cache
def _parameter_field_names():
    """The public input contract is fixed for this implementation revision."""
    from .public_catalog import MODELS, schema
    from .utility_contracts import UTILITY_MODELS

    names = set()

    def collect(value):
        if isinstance(value, dict):
            names.update(value.get("properties", {}))
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for operation in (*MODELS, *UTILITY_MODELS):
        collect(schema(operation))
    return frozenset(names)


def invalid_parameters(error=None, *, prefix=()) -> ResearchError:
    # Only schema-owned field names and array indices leave this boundary.
    # Never return submitted values, unknown keys, validator messages or ctx.
    details = []
    if error is not None and hasattr(error, "errors"):
        names = _parameter_field_names()
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:8]:
            location = (*prefix, *item["loc"])
            path = "$" + "".join(
                f"[{part}]" if type(part) is int else "." + (part if part in names else "<unknown>")
                for part in location
            )
            details.append({"path": path, "constraint": item["type"]})
    return ResearchError(
        "invalid_parameters", "The operation arguments do not match the input contract.", details=details
    )


def error_result(error: ResearchError) -> dict:
    return {"schema_version": "1.0", "outcome": "error", "error": error.as_dict()}


@contextmanager
def provider_boundary(source: str):
    """Convert expected retained-provider failures before FastMCP logs them."""
    import json

    import httpx
    import structlog
    from fastmcp.exceptions import ToolError

    from .transport import RejectedConnection

    try:
        yield
    except (httpx.HTTPError, ValueError, ResearchError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        if isinstance(exc, ResearchError):
            code, retryable = exc.code, exc.retryable
        elif isinstance(exc, RejectedConnection):
            code, retryable = "source_connection_rejected", False
        elif isinstance(exc, ValueError):
            code, retryable = "invalid_source_response", False
        else:
            code = {
                401: "source_authentication_failed",
                403: "source_access_denied",
                404: "source_not_found",
                429: "source_rate_limited",
            }.get(status, "source_unavailable")
            retryable = status is None or status == 429 or status >= 500
        error = {"code": code, "message": f"{source} could not complete the request.", "retryable": retryable}
        structlog.get_logger(__name__).warning(
            "provider_failure", source=source, code=code, retryable=retryable, status=status
        )
        # ToolError is expected by the framework; never attach the raw cause.
        raise ToolError(json.dumps(error)) from None


def provider_tool_boundary(source: str):
    """Sanitize acquisition and subsequent validation before adapter SDK logging."""

    def decorate(function):
        @wraps(function)
        async def controlled(*args, **kwargs):
            with provider_boundary(source):
                from .source_licensing import require_operation

                require_operation(source, function.__name__)
                return await function(*args, **kwargs)

        return controlled

    return decorate
