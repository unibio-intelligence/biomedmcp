#!/usr/bin/env python3
"""Offline executable GitHub fixture, never a publication client."""

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

state_file = Path(os.environ["UBI_RELEASE_TEST_STATE"])
state = json.loads(state_file.read_text())
args = sys.argv[1:]


def emit(value, status=200):
    print(f"HTTP/2.0 {status} Fixture\n\n" + json.dumps(value))
    sys.exit(0 if status < 300 else 1)


def mutate(operation):
    state["mutations"].append(operation)
    fail = state.get("fail") == operation
    if fail:
        state["fail"] = None
    state_file.write_text(json.dumps(state))
    if fail:
        print("synthetic-release-credential-sentinel", file=sys.stderr)
        emit({}, 502)


if args[:2] == ["attestation", "verify"]:
    assert args[args.index("--hostname") + 1] == "github.com"
    assert args[args.index("--repo") + 1] == "unibio-intelligence/biomedmcp"
    assert (
        args[args.index("--signer-workflow") + 1]
        == "unibio-intelligence/biomedmcp/.github/workflows/release.yml"
    )
    assert args[args.index("--source-digest") + 1] == args[args.index("--signer-digest") + 1]
    assert "--deny-self-hosted-runners" in args
    path = Path(args[2])
    kind = args[args.index("--predicate-type") + 1]
    statement = {
        "subject": [{"name": path.name, "digest": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}],
        "predicateType": kind,
        "predicate": state["sbom"] if kind == "https://cyclonedx.org/bom" else {},
    }
    print(json.dumps([{"verificationResult": {"statement": statement}}]))
    sys.exit(0)

if args[:2] == ["release", "upload"]:
    assert "--clobber" not in args
    assert args[args.index("--repo") + 1] == "github.com/unibio-intelligence/biomedmcp"
    asset_path = Path(args[3])
    assert asset_path.name not in {a["name"] for a in state["assets"]}
    data = asset_path.read_bytes()
    asset_id = len(state["assets"]) + 100
    state["assets"].append({"id": asset_id, "name": asset_path.name, "size": len(data), "state": "uploaded"})
    state["contents"][str(asset_id)] = base64.b64encode(data).decode()
    mutate("upload:" + asset_path.name)
    sys.exit(0)

assert args[0] == "api" and args[args.index("--hostname") + 1] == "github.com"
if "--include" not in args:
    assert args[-1] == "Accept: application/octet-stream"
    asset_id = args[3].rsplit("/", 1)[-1]
    sys.stdout.buffer.write(base64.b64decode(state["contents"][asset_id]))
    sys.exit(0)
method = args[args.index("--method") + 1]
path = args[args.index("--method") + 2]
prefix = "repos/unibio-intelligence/biomedmcp"
payload = json.load(sys.stdin) if "--input" in args else None
if path == prefix:
    emit({"full_name": prefix.removeprefix("repos/"), "private": False, "permissions": {"push": True}})
if path.startswith(prefix + "/releases?"):
    emit(state["releases"])
if path.endswith("/git/ref/tags/v0.2.0"):
    if state["tag"] is None:
        emit({}, 404)
    emit({"object": {"type": "commit", "sha": state["tag"]}})
if "/git/commits/" in path:
    emit({"sha": path.rsplit("/", 1)[-1]})
if path.endswith("/git/refs"):
    assert method == "POST" and state["tag"] is None
    state["tag"] = payload["sha"]
    mutate("tag")
    emit({"object": {"type": "commit", "sha": state["tag"]}}, 201)
if path == prefix + "/releases":
    assert method == "POST" and not state["releases"]
    state["releases"].append({"id": 1, **payload})
    mutate("draft")
    emit(state["releases"][0], 201)
if path.startswith(prefix + "/releases/1/assets?"):
    emit(state["assets"])
if path == prefix + "/releases/1":
    if method == "PATCH":
        assert payload == {"draft": False}
        state["releases"][0]["draft"] = False
        mutate("publish")
    emit(state["releases"][0])
raise AssertionError(f"Unsupported fixture call {method} {path}")
