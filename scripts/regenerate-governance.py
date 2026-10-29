#!/usr/bin/env python3
"""Refresh generated contracts; manual readiness claims remain review-owned."""

import asyncio
import json
import runpy
from pathlib import Path


async def main():
    root = Path(__file__).resolve().parents[1]
    checks = runpy.run_path(str(root / "scripts/check-governance.py"))
    outputs = await checks["generated"](root)
    inventory = runpy.run_path(str(root / "scripts/python-inventory.py"))
    outputs["docs/python-dependency-inventory.json"] = (
        json.dumps(inventory["snapshot"](root), indent=2) + "\n"
    ).encode()
    for name, data in outputs.items():
        (root / name).write_bytes(data)
    print(json.dumps({"regenerated": sorted(outputs), "manual_readiness": "review separately"}))


if __name__ == "__main__":
    asyncio.run(main())
