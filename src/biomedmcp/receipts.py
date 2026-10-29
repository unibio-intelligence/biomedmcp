"""Bound public evidence to a validated task without claiming live replay.

Hashes use runtime.digest: SHA-256 of sorted, compact, ASCII-escaped JSON.
The result hash excludes only receipt.result_sha256, avoiding a self-reference. Source
participation observes service provider boundaries (including cached/failing
ones); it never promotes provider-supplied source strings into this inventory.
"""

from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from .content_boundary import SECRET_FIELD
from .contracts import EvidenceReceipt, ResearchResult
from .errors import ResearchError
from .logging_safety import redactor
from .native import REVISION
from .runtime import digest

participating_sources: ContextVar[set[str] | None] = ContextVar("ubi_receipt_sources", default=None)
REQUEST_BYTES = 8192


def observe_source(source: str) -> None:
    current = participating_sources.get()
    if current is not None:
        current.add(source)


def result_digest(value: dict) -> str:
    content = dict(value)
    receipt = dict(content["receipt"])
    receipt.pop("result_sha256", None)
    content["receipt"] = receipt
    return digest(content)


def _safe_request(value: Any, *, _redact=None) -> tuple[Any, bool]:
    redact = _redact if _redact is not None else redactor()
    if isinstance(value, str):
        safe = redact(value)
        return safe, safe != value
    if isinstance(value, dict):
        result, changed = {}, False
        for key, item in value.items():
            safe_key = redact(key)
            if SECRET_FIELD.fullmatch(key):
                safe, cut = "[REDACTED]", True
            else:
                safe, cut = _safe_request(item, _redact=redact)
            result[safe_key] = safe
            changed |= cut or safe_key != key
        return result, changed
    if isinstance(value, list):
        values = [_safe_request(item, _redact=redact) for item in value]
        return [item for item, _ in values], any(changed for _, changed in values)
    return value, False


def attach_receipt(result: ResearchResult, operation: str, arguments: dict) -> ResearchResult:
    import json

    from .public_catalog import ADAPTERS

    # Preserve the public scientific task, not its internal search/get alias.
    normalized = ADAPTERS[operation].validate_python(arguments).model_dump(mode="json", exclude_none=True)
    request, redacted = _safe_request(normalized)
    omitted = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode()) > REQUEST_BYTES
    observed = participating_sources.get() or set()
    # Provenance sources are service-issued boundary owners. Its nested
    # `sources` values may include provider claims and are intentionally excluded.
    sources = sorted(observed | {proof.source for proof in result.provenance})
    result.receipt = EvidenceReceipt(
        implementation=REVISION,
        operation=operation,
        request=None if omitted else request,
        request_sha256=digest(request),
        result_sha256="0" * 64,
        sources=sources,
        completed_at=datetime.now(UTC).isoformat(),
        request_redacted=redacted,
        request_omitted=omitted,
        # Dataset release labels alone do not prove immutable endpoint replay.
        time_dependent=bool(sources),
    )
    # Receipt bytes count toward the same scientific response budget. Hash the
    # actual final payload after any omission, link sanitation and action checks.
    bounded = ResearchResult.model_validate(result.model_dump(mode="json"))
    bounded.receipt.result_sha256 = result_digest(bounded.model_dump(mode="json"))
    return bounded


def verify_receipt(value: dict, *, normalized_request: dict | None = None) -> bool:
    """Detect saved-payload/request drift; this is integrity, not authenticity.

    An omitted request can only be checked against a separately saved normalized
    request. This function verifies the complete supplied receipt contract and
    result hash, and the request hash whenever the request is present.
    """
    try:
        from .output_contracts import validate_output

        receipt = EvidenceReceipt.model_validate(value.get("receipt"))
        validate_output(receipt.operation, value)
        if result_digest(value) != receipt.result_sha256:
            return False
        if receipt.request_omitted != (receipt.request is None):
            return False
        if normalized_request is not None and digest(normalized_request) != receipt.request_sha256:
            return False
        return receipt.request is None or digest(receipt.request) == receipt.request_sha256
    except (ValidationError, ValueError, TypeError, AttributeError, KeyError, ResearchError):
        return False
