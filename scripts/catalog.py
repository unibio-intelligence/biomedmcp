#!/usr/bin/env python3
"""Generate ownership/schema evidence from the live public catalog."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client

from biomedmcp.examples import ADAPTER_READMES, adapter_readme, guide_examples, readme_examples
from biomedmcp.mcp.server import create_server
from biomedmcp.output_contracts import CATALOG_BYTE_BUDGET
from biomedmcp.public_catalog import operation_map


async def artifacts(root):
    os.environ["UBI_PROFILE"] = "local"
    async with Client(create_server()) as client:
        tools = [tool.model_dump(mode="json", exclude_none=True) for tool in await client.list_tools()]
    raw = json.dumps(tools, separators=(",", ":"), sort_keys=True).encode()
    report = {
        "tools": tools,
        "tool_count": len(tools),
        "utf8_bytes": len(raw),
        "tokens": None,
        "tokenizer": None,
        "measurement": "live tools/list",
        "byte_budget": CATALOG_BYTE_BUDGET,
        "budget_decision": "96 KiB bounds the 13-tool catalog with self-contained evidence-receipt schemas. Client/model token and task impact remains unqualified. Selected literature and trial registry metadata is typed; other inner scientific record coverage remains open. Equivalent nullable shorthand and omission of redundant annotations preserve constraints. FastMCP retains self-contained local definitions, with no external schema references.",
    }
    if len(raw) > CATALOG_BYTE_BUDGET:
        raise RuntimeError(
            f"The live catalog ({len(raw)} bytes) exceeds the {CATALOG_BYTE_BUDGET}-byte discovery budget"
        )
    try:
        import tiktoken

        report.update(
            tokens=len(tiktoken.get_encoding("cl100k_base").encode(raw.decode())), tokenizer="cl100k_base"
        )
    except ImportError:
        pass
    outputs = {
        "docs/mcp-catalog-budget.json": json.dumps(report, indent=2) + "\n",
        "docs/operation-ownership.json": json.dumps(operation_map(), indent=2) + "\n",
        "docs/examples.md": (
            "# Public call examples\n\nGenerated from biomedmcp.examples; run scripts/catalog.py to refresh. Examples demonstrate synthetic adapter contracts. Check [source release eligibility](source-licenses.md) before execution; unreleased integrations cannot be enabled by adding keys.\n\n"
            + guide_examples()
        ),
    }
    readme = root / "README.md"
    text = readme.read_text()
    start_marker, end_marker = "<!-- public-call-examples:start -->", "<!-- public-call-examples:end -->"
    start, end = text.index(start_marker) + len(start_marker), text.index(end_marker)
    text = text[:start] + "\n```sh\n" + readme_examples() + "\n```\n" + text[end:]
    outputs["README.md"] = text
    for package in ADAPTER_READMES:
        outputs[f"servers/python/{package}/README.md"] = adapter_readme(package)
    return {name: text.encode() for name, text in outputs.items()}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    outputs = await artifacts(args.root)
    for name, data in outputs.items():
        (args.root / name).write_bytes(data)
    report = json.loads(outputs["docs/mcp-catalog-budget.json"])
    print(json.dumps({k: v for k, v in report.items() if k != "tools"}))


if __name__ == "__main__":
    asyncio.run(main())
