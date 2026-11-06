"""Only credential-free public predictor acquisitions share cache/coalescing."""

import asyncio
import time
from contextlib import nullcontext

import pytest
from biomedmcp.provider_credentials import RequestCredentials, credential_context
from biomedmcp.runtime import ProviderRuntime, anonymous_pagination


@pytest.mark.parametrize("source,operation", [("alphamissense", "get:predictions"), ("eve", "get:eve")])
async def test_cookie_free_callers_reuse_public_result_without_provider_egress(source, operation):
    runtime = ProviderRuntime()
    calls = []

    async def fetch():
        calls.append(1)
        return {"records": [{"score": 0.5}]}

    results = []
    for scope in ["anonymous:first", "anonymous:second"]:
        with anonymous_pagination(scope=scope, resource="https://service/mcp"):
            results.append(
                await runtime.invoke(source, {"operation": operation, "id": "BRAF V2E"}, fetch, scope=scope)
            )
    assert calls == [1] and results[0][1] is False and results[1][1] is True
    assert results[0][0] == results[1][0]


@pytest.mark.parametrize(
    "boundary",
    ["no_trusted_context", "account", "resource", "credential", "source", "operation", "identifier", "fresh"],
)
async def test_private_or_different_acquisitions_never_reuse_public_predictor_cache(boundary):
    runtime = ProviderRuntime()
    calls = []

    async def fetch():
        calls.append(1)
        return {"records": [{"score": len(calls) / 10}]}

    for i in range(2):
        scope = f"anonymous:guest{i}" if boundary != "account" else f"account:{i}"
        resource = f"https://service/{i if boundary == 'resource' else 'mcp'}"
        source = "alphamissense" if boundary != "source" else "uniprot"
        params = {
            "operation": "get:predictions" if boundary != "operation" else "private:save",
            "id": f"BRAF V{2 + i if boundary == 'identifier' else 2}E",
        }
        credential = RequestCredentials(
            partition=f"account:{i}",
            deadline=time.monotonic() + 60,
            values={},
            pacing={"ncbi": "ncbi", "openfda": "openfda"},
        )
        with (
            anonymous_pagination(scope=scope, resource=resource)
            if boundary != "no_trusted_context"
            else nullcontext()
        ):
            with credential_context(credential) if boundary == "credential" else nullcontext():
                _, cached = await runtime.invoke(
                    source,
                    params,
                    fetch,
                    scope=scope,
                    freshness="fresh" if boundary == "fresh" else "cached_if_fresh",
                )
                assert not cached
    assert len(calls) == 2


async def test_public_predictor_flights_coalesce_across_cookie_free_callers():
    runtime = ProviderRuntime()
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = []

    async def fetch():
        calls.append(1)
        started.set()
        await finish.wait()
        return {"records": [{"score": 0.5}]}

    def submit(scope):
        with anonymous_pagination(scope=scope, resource="https://service/mcp"):
            return asyncio.create_task(
                runtime.invoke(
                    "alphamissense", {"operation": "get:predictions", "id": "BRAF V2E"}, fetch, scope=scope
                )
            )

    first = submit("anonymous:a")
    await started.wait()
    second = submit("anonymous:b")
    await asyncio.sleep(0)
    finish.set()
    a, b = await asyncio.gather(first, second)
    assert calls == [1] and a[0] == b[0]


async def test_mismatched_trusted_scope_cannot_promote_a_private_request():
    runtime = ProviderRuntime()
    calls = []

    async def fetch():
        calls.append(1)
        return {"records": [{"score": 0.5}]}

    for i in range(2):
        with anonymous_pagination(scope="anonymous:other", resource="https://service/mcp"):
            await runtime.invoke(
                "alphamissense", {"operation": "get:predictions"}, fetch, scope=f"anonymous:{i}"
            )
    assert len(calls) == 2
