#!/usr/bin/env python3
"""Record installed dependency versions/licenses from the locked environment."""

import hashlib
import importlib.metadata
import json
import re
from pathlib import Path


def snapshot(root, distributions=None):
    rows = {}
    for dist in importlib.metadata.distributions() if distributions is None else distributions:
        row = {
            "name": dist.metadata["Name"],
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or (dist.metadata.get("License") or "").split("\n")[0][:200]
            or "See installed distribution license files",
            "license_files": dist.metadata.get_all("License-File") or [],
        }
        name = re.sub(r"[-_.]+", "-", row["name"]).lower()
        # Editable installs can expose identical egg-info and dist-info metadata.
        # Conflicting versions/licenses are not resolved by silently choosing one.
        if name in rows and row != rows[name]:
            raise ValueError("Conflicting installed distribution metadata")
        rows[name] = row
    return {
        "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "packages": sorted(rows.values(), key=lambda r: r["name"].lower()),
    }


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "docs/python-dependency-inventory.json").write_text(json.dumps(snapshot(root), indent=2) + "\n")


if __name__ == "__main__":
    main()
