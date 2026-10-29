#!/usr/bin/env python3
"""Measure the real loopback HTTP path in an isolated provider-free process.

Uses public scientific dispatch with synthetic Europe PMC responses. Measures
server RSS/heap separately from the client and records workload and tolerances.
No provider traffic, credentials, deployment or production SLO claim.
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import resource
import socket
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route

from biomedmcp.mcp.http_security import (
    BODY_TIMEOUT_SECONDS,
    HTTP_CONNECTIONS,
    JSON_DEPTH,
    REQUEST_BYTES,
    REQUEST_CONCURRENCY,
    RequestBudget,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from ingress_helpers import assert_batch, create_app, maximum_batch


def rss():
    if sys.platform == "linux":
        lines = Path("/proc/self/status").read_text().splitlines()
        current = int(next(line for line in lines if line.startswith("VmRSS:")).split()[1]) * 1024
    elif sys.platform == "darwin":
        current = (
            int(subprocess.check_output(["/bin/ps", "-o", "rss=", "-p", str(os.getpid())], text=True)) * 1024
        )
    else:
        raise RuntimeError("RSS qualification supports Linux and macOS")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return current, int(peak if sys.platform == "darwin" else peak * 1024)


async def serve(fd):
    os.environ["UBI_PROFILE"] = "local"
    app, provider = create_app()
    tracemalloc.start()

    async def state(request):
        node = app.middleware_stack
        while not isinstance(node, RequestBudget):
            node = node.app
        current, peak = rss()
        heap, heap_peak = tracemalloc.get_traced_memory()
        return JSONResponse(
            {
                "rss_bytes": current,
                "peak_rss_bytes": peak,
                "heap_bytes": heap,
                "peak_heap_bytes": heap_peak,
                "active": node.active,
                "provider_calls": provider.calls,
            }
        )

    app.router.routes.append(Route("/__qualification_state", state))
    listener = socket.socket(fileno=fd)
    runner = uvicorn.Server(
        uvicorn.Config(
            app,
            access_log=False,
            log_level="error",
            limit_concurrency=HTTP_CONNECTIONS,
            timeout_graceful_shutdown=5,
        )
    )
    await runner.serve(sockets=[listener])


class RejectionProtocol(asyncio.Protocol):
    """Complete HTTP responses remain valid if the peer subsequently resets."""

    def __init__(self):
        self.response = asyncio.get_running_loop().create_future()
        self.buffer = bytearray()

    def data_received(self, data):
        if self.response.done():
            return
        self.buffer.extend(data)
        if len(self.buffer) > 4096:
            self.response.set_exception(RuntimeError("Rejected response exceeded its budget"))
            return
        if b"\r\n\r\n" not in self.buffer:
            return
        head, body = bytes(self.buffer).split(b"\r\n\r\n", 1)
        lengths = [
            int(line.split(b":", 1)[1])
            for line in head.split(b"\r\n")[1:]
            if line.lower().startswith(b"content-length:")
        ]
        if len(lengths) != 1:
            self.response.set_exception(RuntimeError("Rejected response lacks an explicit length"))
        elif len(body) >= lengths[0]:
            self.response.set_result((head, body[: lengths[0]]))

    def connection_lost(self, exc):
        if not self.response.done():
            self.response.set_exception(RuntimeError("Connection ended before a complete rejection response"))


async def rejected(port, kind, intended_bytes):
    transport, protocol = await asyncio.get_running_loop().create_connection(
        RejectionProtocol, "127.0.0.1", port
    )
    framing = f"Content-Length: {intended_bytes}" if kind == "declared" else "Transfer-Encoding: chunked"
    headers = f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nContent-Type: application/json\r\n{framing}\r\n\r\n"
    transport.write(headers.encode())
    sent = 0
    response = protocol.response
    try:
        if kind == "chunked":
            chunk = b"credential-sentinel-" + b"x" * (16_384 - 20)
            while sent < min(intended_bytes, REQUEST_BYTES + 16_384) and not response.done():
                piece = chunk[: min(len(chunk), intended_bytes - sent)]
                transport.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                sent += len(piece)
                await asyncio.sleep(0.001)
            if sent == intended_bytes and not response.done():
                transport.write(b"0\r\n\r\n")
        head, body = await asyncio.wait_for(response, 5)
        status = int(head.split(b" ", 2)[1])
        assert status in {413, 503}, status
        assert b"credential-sentinel" not in head + body
        return {"status": status, "sent_body_bytes": sent}
    finally:
        response.cancel()
        transport.close()


async def incomplete(port):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    body = b"x" * (REQUEST_BYTES - 1)
    writer.write(
        f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n{len(body):x}\r\n".encode()
        + body
        + b"\r\n"
    )
    await writer.drain()
    return reader, writer


async def measure(port):
    url = f"http://127.0.0.1:{port}"
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-11-25",
    }
    samples, scenarios = [], []
    async with httpx.AsyncClient(base_url=url, timeout=15) as client:
        for _ in range(200):
            try:
                if (await client.get("/readyz")).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("Qualification server did not start")
        for _ in range(2):
            response = await client.post("/mcp", content=maximum_batch(), headers=headers)
            assert response.status_code == 200
            assert_batch(response.json())
        baseline = (await client.get("/__qualification_state")).json()
        samples.append(baseline)
        for kind, size, concurrency in [
            ("declared", 1_048_576, 16),
            ("declared", 1_073_741_824, 96),
            ("chunked", 131_072, 16),
            ("chunked", 8_388_608, 32),
            ("chunked", 67_108_864, 96),
        ]:
            started = time.monotonic()
            results = await asyncio.gather(*(rejected(port, kind, size) for _ in range(concurrency)))
            sample = (await client.get("/__qualification_state")).json()
            samples.append(sample)
            assert sample["active"] == 0
            scenarios.append(
                {
                    "kind": kind,
                    "intended_body_bytes": size,
                    "concurrency": concurrency,
                    "elapsed_seconds": time.monotonic() - started,
                    "status_counts": {
                        str(code): sum(row["status"] == code for row in results) for code in (413, 503)
                    },
                    "max_sent_body_bytes": max(row["sent_body_bytes"] for row in results),
                    "server": sample,
                }
            )
        held = await asyncio.gather(*(incomplete(port) for _ in range(REQUEST_CONCURRENCY)))
        try:
            for _ in range(100):
                sample = (await client.get("/__qualification_state")).json()
                if sample["active"] == REQUEST_CONCURRENCY:
                    break
                await asyncio.sleep(0.01)
            assert sample["active"] == REQUEST_CONCURRENCY
            samples.append(sample)
            started = time.monotonic()
            rejected_requests = await asyncio.gather(*(rejected(port, "declared", 10) for _ in range(64)))
            assert all(row["status"] == 503 for row in rejected_requests)
            health = await client.get("/readyz")
            assert health.status_code == 200
            scenarios.append(
                {
                    "kind": "incomplete_bodies_and_overload",
                    "held": REQUEST_CONCURRENCY,
                    "held_body_bytes": REQUEST_BYTES - 1,
                    "excess_requests": 64,
                    "status": 503,
                    "health_status": health.status_code,
                    "elapsed_seconds": time.monotonic() - started,
                    "server": sample,
                }
            )
        finally:
            for _, writer in held:
                writer.close()
            await asyncio.gather(*(writer.wait_closed() for _, writer in held), return_exceptions=True)
        for _ in range(100):
            sample = (await client.get("/__qualification_state")).json()
            if sample["active"] == 0:
                break
            await asyncio.sleep(0.01)
        assert sample["active"] == 0
        reader, writer = await incomplete(port)
        started = time.monotonic()
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), BODY_TIMEOUT_SECONDS + 3)
            assert head.startswith(b"HTTP/1.1 408")
            scenarios.append(
                {
                    "kind": "real_slow_body_deadline",
                    "status": 408,
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
        finally:
            writer.close()
            await writer.wait_closed()
        response = await client.post("/mcp", content=maximum_batch(), headers=headers)
        assert response.status_code == 200
        assert_batch(response.json())
        final = (await client.get("/__qualification_state")).json()
        assert final["active"] == 0 and final["provider_calls"] == 10
        samples.append(final)
        rss_growth = max(row["rss_bytes"] for row in samples) - baseline["rss_bytes"]
        rss_peak_growth = max(row["peak_rss_bytes"] for row in samples) - baseline["peak_rss_bytes"]
        heap_peak_growth = max(row["peak_heap_bytes"] for row in samples) - baseline["peak_heap_bytes"]
        assert rss_growth <= 32 * 1024**2 and rss_peak_growth <= 32 * 1024**2
        assert heap_peak_growth <= 24 * 1024**2
        return {
            "result": "passed",
            "limits": {
                "request_bytes": REQUEST_BYTES,
                "json_depth": JSON_DEPTH,
                "active_requests_per_worker": REQUEST_CONCURRENCY,
                "body_timeout_seconds": BODY_TIMEOUT_SECONDS,
                "builtin_http_concurrency": HTTP_CONNECTIONS,
            },
            "max_batch": {
                "calls": 10,
                "body_bytes": REQUEST_BYTES,
                "per_query_characters": 512,
                "filter_lists_per_call": 4,
                "items_per_list": 5,
                "characters_per_item": 256,
                "outcome": "data",
                "provenance": "europepmc synthetic fixture",
            },
            "baseline": baseline,
            "final": final,
            "scenarios": scenarios,
            "memory": {
                "rss_growth_bytes": max(0, rss_growth),
                "peak_rss_growth_bytes": max(0, rss_peak_growth),
                "peak_python_heap_growth_bytes": max(0, heap_peak_growth),
                "rss_growth_budget_bytes": 32 * 1024**2,
                "heap_growth_budget_bytes": 24 * 1024**2,
            },
            "interpretation": "One isolated worker and fixed rejected-request workloads, with real loopback TCP/HTTP and provider-free scientific dispatch. RSS includes Python/native/server allocations; traced heap excludes kernel/client memory. Budgets are qualification thresholds, not production SLOs or a claim about arbitrary ASGI hosts/proxies.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve-fd", type=int)
    args = parser.parse_args()
    if args.serve_fd is not None:
        asyncio.run(serve(args.serve_fd))
        return
    if args.output is None:
        parser.error("--output is required")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    paths = [
        Path(__file__).resolve(),
        ROOT / "tests/ingress_helpers.py",
        ROOT / "src/biomedmcp/mcp/http_security.py",
        ROOT / "uv.lock",
    ]
    inputs = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with tempfile.TemporaryFile(mode="w+b") as logs:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve-fd", str(listener.fileno())],
            pass_fds=(listener.fileno(),),
            stdout=logs,
            stderr=logs,
        )
        listener.close()
        try:
            report = asyncio.run(measure(port))
            report["qualified_at"] = datetime.now(UTC).isoformat()
            report["environment"] = {
                "python": platform.python_version(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "cpu_count": os.cpu_count(),
            }
            assert inputs == {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
            }, "Qualification inputs changed during execution"
            report["input_sha256"] = inputs
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(
                json.dumps(
                    {"result": report["result"], "memory": report["memory"], "report": str(args.output)}
                )
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
