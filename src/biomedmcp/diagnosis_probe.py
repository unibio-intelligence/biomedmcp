"""Isolated import probe: no provider reads, no bytecode writes, no raw logs."""

import contextlib
import hashlib
import importlib
import importlib.metadata
import io
import json
import sys
from pathlib import Path


def fingerprint(module):
    root = Path(importlib.import_module(module.__name__.split(".")[0]).__file__).parent
    paths = sorted({*root.rglob("*.py"), *root.rglob("*.json")})
    digest = hashlib.sha256()
    for path in paths:
        if "__pycache__" in path.parts or path.name == "offline-qualification.json":
            continue
        digest.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def main():
    specifications = json.loads(sys.stdin.read(65536))
    results = {}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import socket

        import httpx

        def blocked(*args, **kwargs):
            raise RuntimeError("diagnosis_network_blocked")

        async def async_blocked(*args, **kwargs):
            blocked()

        socket.create_connection = blocked
        socket.getaddrinfo = blocked
        socket.socket.connect = blocked
        socket.socket.connect_ex = blocked
        socket.socket.sendto = blocked
        httpx.Client.request = blocked
        httpx.AsyncClient.request = async_blocked
        from . import transport

        transport.AsyncClient.request = async_blocked
        for source, name in specifications.items():
            try:
                module = importlib.import_module(name)
                results[source] = {"importable": True, "implementation_sha256": fingerprint(module)}
            except Exception:  # noqa: BLE001 -- raw import exceptions may contain credentials
                results[source] = {"importable": False, "code": "adapter_import_failed"}
        core_sha256 = fingerprint(importlib.import_module("biomedmcp"))
    dependencies = {
        name: importlib.metadata.version(name) for name in ("fastmcp", "pydantic", "httpx", "jsonschema")
    }
    print(json.dumps({"sources": results, "dependencies": dependencies, "core_sha256": core_sha256}))


if __name__ == "__main__":
    main()
