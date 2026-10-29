#!/usr/bin/env python3
"""Declare an already installed, reviewed public release; never downloads or extracts."""

import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--release", required=True)
parser.add_argument("--source-url", required=True)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument(
    "--mutation-coverage",
    type=Path,
    help="Reviewed JSON with samples array and genes array (or explicit all); required for mutation denominators",
)
args = parser.parse_args()
root = args.directory.resolve()
if not args.source_url.startswith("https://") or not (root / "meta_study.txt").is_file():
    parser.error("Use a reviewed HTTPS source and an installed cBioPortal study")
files = {}
for file in sorted(root.rglob("*")):
    if file.is_symlink():
        parser.error("Symlinks are forbidden")
    if file.is_file():
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        files[str(file.relative_to(root))] = digest.hexdigest()
entry = {
    "id": root.name,
    "enabled": True,
    "release": args.release,
    "source_url": args.source_url,
    "files": files,
    "sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
}
if args.mutation_coverage:
    entry["mutation_coverage"] = json.loads(args.mutation_coverage.read_text())
existing = json.loads(args.output.read_text()) if args.output.exists() else {"studies": []}
existing["studies"] = [e for e in existing["studies"] if e["id"] != entry["id"]] + [entry]
args.output.write_text(json.dumps(existing, indent=2) + "\n")
