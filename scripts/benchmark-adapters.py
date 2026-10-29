#!/usr/bin/env python3
"""Provider-free adapter orchestration benchmark; never a production SLO."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import jsonschema
from fastmcp import Client, FastMCP
from pydantic import BaseModel, ConfigDict

from biomedmcp.adapters import SourceAdapters
from biomedmcp.decoding import decode_tool_result
from biomedmcp.runtime import digest


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int


async def fixture(value: int):
    return {"value": value, "doubled": value * 2}


async def measure(function, iterations, repeats):
    for _ in range(10):
        await function()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            await function()
        samples.append((time.perf_counter_ns() - started) / iterations / 1_000_000)
    return {
        "milliseconds_per_call": samples,
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


async def benchmark(iterations=200, repeats=5):
    async def forbidden(*args, **kwargs):
        raise AssertionError("The orchestration benchmark must not make provider HTTP requests.")

    with patch.object(httpx.AsyncClient, "request", forbidden):
        return await _benchmark(iterations, repeats)


async def _benchmark(iterations, repeats):
    # Exercise actual retained discovery/schema construction without reading
    # scientific providers. The comparison reproduces the prior validate path.
    adapters = SourceAdapters()
    source, operation = "gtex", "query_expression"
    params = {"query_type": "gene_median", "gene_id": "BRAF", "dataset_id": "gtex_v10", "limit": 25}
    server = await adapters._server(source)

    async def legacy_validate():
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
        schema = dict(tools[operation].input_schema)
        schema.setdefault("additionalProperties", False)
        jsonschema.validate(params, schema)

    async def cached_validate():
        await adapters.validate(source, operation, params)

    started = time.perf_counter_ns()
    await cached_validate()
    cold_ms = (time.perf_counter_ns() - started) / 1_000_000
    catalog = await adapters.catalog(source)
    validation = {
        "legacy_discovery_and_schema_check": await measure(legacy_validate, iterations, repeats),
        "cached_catalog_and_compiled_validator": await measure(cached_validate, iterations, repeats),
        "cold_catalog_and_all_validator_compilation_ms": cold_ms,
        "source": source,
        "operation": operation,
        "arguments": params,
        "catalog_sha256": digest(catalog),
        "catalog_tools": len(catalog),
        "catalog_utf8_bytes": len(json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()),
    }
    synthetic = FastMCP("orchestration-benchmark", version="synthetic-1")
    synthetic.add_tool(fixture)
    args, expected = {"value": 7}, {"value": 7, "doubled": 14}

    async def fresh_session():
        async with Client(synthetic) as client:
            result = decode_tool_result(await client.call_tool("fixture", args))
        assert result == expected

    async def typed_direct():
        request = Input.model_validate(args)
        assert await fixture(request.value) == expected

    async with Client(synthetic) as client:

        async def reused_session():
            assert decode_tool_result(await client.call_tool("fixture", args)) == expected

        sessions = {
            "fresh_mcp_session": await measure(fresh_session, iterations, repeats),
            "reused_mcp_session": await measure(reused_session, iterations, repeats),
            "direct_typed_function": await measure(typed_direct, iterations, repeats),
        }
    return {
        "schema_version": 1,
        "measured_at": datetime.now(UTC).isoformat(),
        "hardware": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "python": platform.python_version(),
        },
        "dependencies": {
            name: importlib.metadata.version(name) for name in ("fastmcp", "pydantic", "jsonschema")
        },
        "inputs_sha256": {
            name: hashlib.sha256((Path(__file__).parents[1] / name).read_bytes()).hexdigest()
            for name in ("src/biomedmcp/adapters.py", "scripts/benchmark-adapters.py", "uv.lock")
        },
        "workload": {
            "iterations_per_repeat": iterations,
            "repeats": repeats,
            "warmup_calls_per_mode": 10,
            "provider_requests": 0,
            "provider_latency_ms": 0,
            "fixture_arguments": args,
            "fixture_result_sha256": digest(expected),
        },
        "validation": validation,
        "session_comparison": sessions,
        "decision": "Keep the retained MCP execution boundary. Cache discovery and compiled validators; session reuse/direct calls remain benchmark-only alternatives requiring lifecycle, middleware, error and cancellation parity before adoption.",
        "limitations": [
            "Local orchestration timing only; scientific HTTP, provider pacing and network latency are excluded.",
            "GTEx schema validation and one tiny typed synthetic operation do not represent all provider payloads or real agent tasks.",
            "Cold compilation is measured separately; warm samples are sequential repeated-call averages, not request-latency percentiles.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args(argv)
    if not 1 <= args.iterations <= 10000 or not 1 <= args.repeats <= 20:
        parser.error("iterations must be 1–10000 and repeats 1–20")
    report = asyncio.run(benchmark(args.iterations, args.repeats))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "validation_medians_ms": {
                    key: value["median_ms"]
                    for key, value in report["validation"].items()
                    if isinstance(value, dict) and "median_ms" in value
                },
                "session_medians_ms": {
                    key: value["median_ms"] for key, value in report["session_comparison"].items()
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
