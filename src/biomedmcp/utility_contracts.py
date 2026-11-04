"""Utility and protocol request validation before sessions or provider I/O."""

from typing import Any

from pydantic import Field, ValidationError

from .contracts import BatchCall, Entity, StrictModel
from .errors import invalid_parameters


class NoArguments(StrictModel):
    pass


class BatchRequest(StrictModel):
    calls: list[BatchCall] = Field(min_length=1, max_length=10)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Reuse when retrying so quota is charged once.",
    )


class CapabilityRequest(StrictModel):
    source: str | None = Field(default=None, min_length=1, max_length=128)
    entity: Entity | None = None
    diagnose: bool = Field(default=False, strict=True, description="Probe live source health (slower).")


class DiagnosisRequest(StrictModel):
    source: str | None = Field(default=None, min_length=1, max_length=128)


class ReadResourceRequest(StrictModel):
    uri: str = Field(min_length=1, max_length=2048)


class GetPromptRequest(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, str] = Field(default_factory=dict, max_length=16)


UTILITY_MODELS = {"run_batch": BatchRequest, "get_capabilities": CapabilityRequest, "get_quota": NoArguments}
PROTOCOL_MODELS = {
    "tools": NoArguments,
    "resources": NoArguments,
    "prompts": NoArguments,
    "read-resource": ReadResourceRequest,
    "get-prompt": GetPromptRequest,
}


def validate_utility(operation: str, arguments: Any):
    model = {**UTILITY_MODELS, **PROTOCOL_MODELS, "diagnose": DiagnosisRequest}.get(operation)
    if model is None:
        return None
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise invalid_parameters(exc) from None
