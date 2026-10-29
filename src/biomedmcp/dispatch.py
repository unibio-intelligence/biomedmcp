"""One validated operation contract for CLI, MCP and embedded callers."""

from __future__ import annotations

import asyncio
import time

from pydantic import ValidationError

from .content_boundary import mark_source_data
from .errors import ResearchError, error_result, invalid_parameters
from .output_contracts import batch_outcome, validate_output
from .public_catalog import ADAPTERS, native_request, public_capabilities, validated_action
from .receipts import attach_receipt, participating_sources
from .request_telemetry import phase, request_trace
from .runtime import operation_deadline, remaining_budget
from .utility_contracts import validate_utility

REQUEST_TIMEOUT = 75
COMPOSED_TIMEOUT = 120


async def finalize(service, result, *, scope, operation, arguments):
    actions = [validated_action(action) for action in result.next_actions]
    for action in actions:
        try:
            # Verify source-specific contracts and ownership without acquiring
            # evidence or executing the suggested request.
            await prepare(service, action["tool"], action["arguments"], scope=scope)
        except ResearchError:
            raise ResearchError(
                "invalid_output", "The service generated an invalid follow-up request."
            ) from None
    result.next_actions = actions
    mark_source_data(result)
    # Retain exact merged/computed rows, not merely their constituent source
    # windows. Receipt and recovery metadata also count toward the byte budget.
    from .evidence import retain_composed_recovery

    await retain_composed_recovery(
        result, store=getattr(service, "evidence", None), scope=scope, operation=operation
    )
    # Revalidate mutated output, including its response byte budget.
    from .contracts import ResearchResult

    bounded = ResearchResult.model_validate(result.model_dump(mode="json"))
    return attach_receipt(bounded, operation, arguments)


async def prepare(service, operation, arguments, *, scope):
    try:
        model = ADAPTERS[operation].validate_python(arguments)
        operation, model = native_request(operation, model)
    except ValidationError as exc:
        error = invalid_parameters(exc)
        if (
            operation == "get"
            and isinstance(arguments, dict)
            and arguments.get("entity") == "gene"
            and isinstance(arguments.get("sections"), list)
            and "annotations" in arguments["sections"]
        ):
            error.correction = 'Gene ontology annotations use get(entity="gene",id=...,sections=["go"]). Other gene sections are listed by capabilities(entity="gene").'
        raise error from None
    except KeyError:
        raise invalid_parameters() from None
    if operation in {"search", "get"}:
        function = getattr(service, operation)
        await function(model, scope=scope, _plan_only=True)
        return lambda: function(model, scope=scope)
    function = service.source if operation == "query_source" else getattr(service, operation)
    params = model.model_dump(exclude_none=True)
    if operation == "query_source":
        await service.source(model.source, model.operation, model.params, scope=scope, _plan_only=True)
    else:
        await function(**params, scope=scope, _plan_only=True)
    return lambda: function(**params, scope=scope)


async def execute(service, operation, arguments, *, scope):
    with request_trace(operation, "embedded") as observation, phase("dispatch"):
        value = await _bounded_execute(service, operation, arguments, scope=scope)
        observation.complete(value, output_state="scientific_result_constructed")
        return value


async def _bounded_execute(service, operation, arguments, *, scope):
    budget = remaining_budget(COMPOSED_TIMEOUT if operation in {"batch", "research"} else REQUEST_TIMEOUT)
    deadline = time.monotonic() + budget
    token = operation_deadline.set(deadline)
    try:
        async with asyncio.timeout_at(deadline):
            return await _execute(service, operation, arguments, scope=scope)
    except TimeoutError:
        raise ResearchError(
            "operation_timeout",
            "The complete request deadline elapsed; no absence can be inferred.",
            retryable=True,
        ) from None
    finally:
        operation_deadline.reset(token)


async def _execute(service, operation, arguments, *, scope):
    utility = validate_utility(operation, arguments)
    if operation == "quota":
        return {
            "schema_version": "1.0",
            "enabled": False,
            "profile": "local",
            "message": "Hosted quota requires --url.",
        }
    if operation == "capabilities":
        if utility.diagnose:
            if utility.entity is not None:
                raise invalid_parameters()
            from .diagnostics import diagnose

            return public_capabilities(await diagnose(service, source=utility.source))
        return public_capabilities(await service.capabilities(source=utility.source, entity=utility.entity))
    if operation == "batch":
        prepared = []
        # Every request is validated before any provider is contacted.
        for index, request in enumerate(utility.calls):
            try:
                prepared.append(await prepare(service, request.operation, request.arguments, scope=scope))
            except ResearchError as exc:
                for field in exc.details:
                    field["path"] = f"$.calls[{index}].arguments" + field["path"][1:]
                raise

        async def one(fn, request):
            receipt_token = participating_sources.set(set())
            try:
                result = await fn()
                result = await finalize(
                    service,
                    result,
                    scope=scope,
                    operation=request.operation,
                    arguments=request.arguments,
                )
                value = result.model_dump(mode="json")
                validate_output(request.operation, value)
                return value
            except (ResearchError, TimeoutError) as exc:
                return error_result(
                    exc
                    if isinstance(exc, ResearchError)
                    else ResearchError(
                        "source_timeout",
                        "Source deadline elapsed; no absence can be inferred.",
                        retryable=True,
                    )
                )
            except Exception:  # noqa: BLE001 -- one failed item must preserve successful peer evidence
                return error_result(
                    ResearchError("internal_error", "The public operation could not complete.")
                )
            finally:
                participating_sources.reset(receipt_token)

        results = await asyncio.gather(
            *(one(fn, call) for fn, call in zip(prepared, utility.calls, strict=True))
        )
        return {"schema_version": "1.0", "outcome": batch_outcome(results), "results": results}
    receipt_token = participating_sources.set(set())
    try:
        result = await (await prepare(service, operation, arguments, scope=scope))()
        return await finalize(service, result, scope=scope, operation=operation, arguments=arguments)
    finally:
        participating_sources.reset(receipt_token)
