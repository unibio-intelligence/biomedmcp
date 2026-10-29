#!/usr/bin/env python3
"""Capture current source operation schemas with explicit offline configuration."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from biomedmcp.adapters import PROVIDERS
from biomedmcp.domain import ResearchService
from biomedmcp.source_licensing import review


async def snapshot():
    # The same schema must be generated in CI and on a configured operator host.
    # These fixture values authorize no source read and are never tool parameters.
    settings = {
        name: "schema-discovery-fixture"
        for provider in PROVIDERS.values()
        for name in provider.get("required_env", [])
    }
    settings.update(
        UBI_PROFILE="local", UBI_LICENSED_SOURCES="antibody-registry", UBI_PUBLIC_STUDY_MANIFEST=""
    )
    with tempfile.TemporaryDirectory(prefix="ubi-schema-discovery-") as temporary:
        settings["UBI_PUBLIC_STUDY_DIR"] = temporary
        with patch.dict(os.environ, settings, clear=True):
            service = ResearchService()
            rows = []
            for name in sorted(set(PROVIDERS) | service.extensions.sources):
                permission = review(name)
                capability = (
                    await service.capabilities(source=name)
                    if permission["release_status"] == "eligible"
                    else {
                        "configured": False,
                        "operations": [],
                        "reason": "Source integration is unreleased under the source license policy.",
                    }
                )
                operations = capability["operations"]
                rows.append(
                    {
                        "source": name,
                        "schema_available": capability["configured"],
                        "health": "not_probed",
                        "reason": capability["reason"],
                        "license_review": permission,
                        "operation_count": len(operations),
                        "operations": operations,
                    }
                )
    return {
        "sources": rows,
        "operation_count": sum(row["operation_count"] for row in rows),
        "configuration_mode": "Synthetic credential/access settings and an empty study directory; schemas only, no source calls.",
        "meaning": "Only source-permission-eligible operations are exposed. Offline schema discovery is not configured operator access or live source qualification; retained unexposed adapter tests use synthetic fixtures, not real data-use grants.",
    }


async def main():
    report = await snapshot()
    root = Path(__file__).resolve().parents[1]
    (root / "docs/adapter-catalog.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
