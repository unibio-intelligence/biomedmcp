#!/usr/bin/env python3
"""Read-only offline CI gates for generated public contracts and local links."""

import argparse
import asyncio
import hashlib
import json
import re
import runpy
import tomllib
from contextlib import ExitStack, contextmanager
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from biomedmcp.adapters import PROVIDERS
from biomedmcp.diagnostics import import_probe, offline_evidence
from biomedmcp.native import REVISION
from biomedmcp.onboarding import investigations_markdown, matrix_markdown
from biomedmcp.source_licensing import check_inventory
from biomedmcp.source_licensing import matrix_markdown as license_markdown
from biomedmcp.source_policy import policy, source_names

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "__pycache__", "build", "dist", "vendor", ".cache", "reports"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


@contextmanager
def no_network():
    def denied(*args, **kwargs):
        raise RuntimeError("Governance checks cannot contact providers or external links")

    with ExitStack() as stack:
        for target in (
            "socket.create_connection",
            "socket.getaddrinfo",
            "socket.socket.connect",
            "socket.socket.connect_ex",
            "socket.socket.sendto",
        ):
            stack.enter_context(patch(target, denied))
        yield


def lock_inventory(root):
    raw = (root / "uv.lock").read_bytes()
    lock = tomllib.loads(raw.decode())
    packages = [
        {
            key: package[key]
            for key in ("name", "version", "source", "sdist", "wheels", "resolution-markers")
            if key in package
        }
        for package in lock["package"]
    ]
    packages.sort(
        key=lambda package: (
            package["name"],
            package["version"],
            json.dumps(package["source"], sort_keys=True),
        )
    )
    return {
        "schema_version": 1,
        "uv_lock_sha256": sha(raw),
        "lock_version": lock["version"],
        "requires_python": lock["requires-python"],
        "packages": packages,
        "scope": "All frozen lock nodes and artifact hashes, including platform alternatives and dev tools. Installed/runtime subsets and source licenses require their own evidence.",
    }


async def generated(root):
    check_inventory(source_names())
    scripts = Path(__file__).resolve().parent
    with no_network():
        catalog = runpy.run_path(str(scripts / "catalog.py"))
        outputs = await catalog["artifacts"](root)
        adapter = runpy.run_path(str(scripts / "adapter-catalog.py"))
        report = await adapter["snapshot"]()
    outputs.update(
        {
            "docs/adapter-catalog.json": (json.dumps(report, indent=2) + "\n").encode(),
            "docs/investigations.md": investigations_markdown().encode(),
            "docs/source-access.md": matrix_markdown().encode(),
            "docs/source-licenses.md": license_markdown().encode(),
            "docs/locked-dependencies.json": (json.dumps(lock_inventory(root), indent=2) + "\n").encode(),
        }
    )
    return outputs


def compare_generated(root, expected):
    errors = []
    for name, data in expected.items():
        path = root / name
        if not path.is_file() or path.is_symlink():
            errors.append(name)
            continue
        actual = path.read_bytes()
        if name == "docs/mcp-catalog-budget.json":
            try:
                old, new = json.loads(actual), json.loads(data)
                # Token counts depend on optional tokenizer installation, not schema identity.
                for value in (old, new):
                    if not isinstance(value, dict) or not {"tokens", "tokenizer"} <= value.keys():
                        raise ValueError("Missing token measurement fields")
                    if not (
                        value["tokens"] is None
                        and value["tokenizer"] is None
                        or type(value["tokens"]) is int
                        and value["tokens"] > 0
                        and value["tokenizer"] == "cl100k_base"
                    ):
                        raise ValueError("Invalid token measurement")
                    value.pop("tokens", None)
                    value.pop("tokenizer", None)
                same = old == new
            except (ValueError, AttributeError):
                same = False
        else:
            same = actual == data
        if not same:
            errors.append(name)
    return errors


class HTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(values[key])
        for key in ("id", "name"):
            if values.get(key):
                self.ids.add(values[key])


def markdown(text):
    links, anchors, counts = [], set(), {}
    tokens = MarkdownIt("commonmark", {"html": True}).parse(text)
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            children = tokens[index + 1].children or []
            title = "".join(child.content for child in children if child.type in ("text", "code_inline"))
            base = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
            count = counts.get(base, 0)
            counts[base] = count + 1
            anchors.add(base if not count else f"{base}-{count}")
        for child in token.children or []:
            if child.type in ("link_open", "image"):
                target = child.attrGet("href" if child.type == "link_open" else "src")
                if target:
                    links.append(target)
            elif child.type == "html_inline":
                parser = HTML()
                parser.feed(child.content)
                links.extend(parser.links)
                anchors.update(parser.ids)
        if token.type == "html_block":
            parser = HTML()
            parser.feed(token.content)
            links.extend(parser.links)
            anchors.update(parser.ids)
    return links, anchors


def check_links(root):
    root = root.resolve()
    errors = []
    documents = sorted(
        path for path in root.rglob("*.md") if not any(part in SKIP for part in path.relative_to(root).parts)
    )
    safe_documents = []
    for path in documents:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            errors.append(f"{path.relative_to(root).as_posix()}: nonpublic documentation path")
        else:
            safe_documents.append(path)
    parsed = {path: markdown(path.read_text()) for path in safe_documents}
    for path, (links, _) in parsed.items():
        name = path.relative_to(root).as_posix()
        for link in links:
            target = urlsplit(link)
            if target.scheme or target.netloc:
                # No external requests; this gate qualifies local targets/anchors only.
                continue
            local = unquote(target.path)
            destination = (
                root / local.lstrip("/") if local.startswith("/") else path.parent / local
            ).resolve()
            if not local:
                destination = path
            if (
                not destination.is_relative_to(root)
                or not destination.exists()
                or (destination.suffix.lower() == ".md" and destination not in parsed)
            ):
                errors.append(f"{name}: missing or nonpublic local target")
            elif target.fragment and destination.is_file() and destination.suffix.lower() == ".md":
                anchors = parsed[destination][1]
                if unquote(target.fragment) not in anchors:
                    errors.append(f"{name}: missing local heading anchor")
    return sorted(set(errors))


def check_readiness(root):
    try:
        report = json.loads((root / "docs/capability-readiness.json").read_text())
        if report.get("implementation") != REVISION:
            return ["docs/capability-readiness.json: stale implementation revision"]
        rows = report["rows"]
        if len(rows) != 42 or {row["id"] for row in rows} != {f"C{i:02}" for i in range(1, 43)}:
            return ["docs/capability-readiness.json: incomplete or duplicate capability rows"]
        for row in rows:
            platform = int(row["id"][1:]) >= 38
            if row["owner"] != ("platform" if platform else "public_science") or row["status"] != (
                "platform_owned" if platform else "implemented_not_exhaustively_qualified"
            ):
                return ["docs/capability-readiness.json: unsupported readiness or ownership claim"]
            for evidence in row["evidence"]:
                if evidence.startswith(("docs/", "tests/")):
                    path = (root / evidence).resolve()
                    if not path.is_relative_to(root.resolve()) or not path.is_file():
                        return ["docs/capability-readiness.json: missing public evidence"]
        for key in ("source_schemas", "architecture", "live_observations"):
            path = (root / "docs" / report[key]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                return ["docs/capability-readiness.json: missing public evidence index"]
        inventory = json.loads((root / "docs/python-dependency-inventory.json").read_text())
        if inventory["uv_lock_sha256"] != sha((root / "uv.lock").read_bytes()):
            return ["docs/python-dependency-inventory.json: stale lockfile identity"]
        locked = {
            (package_name(package["name"]), package["version"])
            for package in lock_inventory(root)["packages"]
        }
        installed = [(package_name(row["name"]), row["version"]) for row in inventory["packages"]]
        if not installed or len(set(installed)) != len(installed) or not set(installed) <= locked:
            return [
                "docs/python-dependency-inventory.json: installed package is outside the frozen inventory"
            ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ["Public readiness/dependency evidence is malformed or missing"]
    return []


def check_receipt(root):
    try:
        report = json.loads((root / "src/biomedmcp/offline-qualification.json").read_text())
        names = source_names()
        probe = import_probe({name: policy(name)["module"] for name in names})
        if not all(row["importable"] for row in probe["sources"].values()):
            return ["Offline source inventory is not completely importable"]
        for name in report["sources"]:
            if name not in names or offline_evidence(probe, name, report)["status"] not in (
                "passed",
                "inventory_only",
            ):
                return ["Bundled offline qualification is stale or malformed"]
        expected = {
            str(path.relative_to(root)): sha(path.read_bytes())
            for path in sorted((root / "tests").rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
        }
        if report["test_inputs_sha256"] != expected or report["runner_sha256"] != sha(
            (root / "scripts/qualify-readiness.py").read_bytes()
        ):
            return ["Bundled offline qualification test/runner inputs are stale"]
        retained = {name for name in PROVIDERS if name != "depmap"}
        if not retained <= report["sources"].keys():
            return ["Bundled offline retained-source evidence is incomplete"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ["Bundled offline qualification is missing or invalid"]
    return []


async def check(root, *, receipt=True):
    expected = await generated(root)
    errors = [name + ": generated artifact drift" for name in compare_generated(root, expected)]
    errors += check_links(root) + check_readiness(root)
    if receipt:
        errors += check_receipt(root)
    return sorted(set(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--generated-only",
        action="store_true",
        help="Check artifacts/links before refreshing full test evidence",
    )
    args = parser.parse_args()
    try:
        errors = asyncio.run(check(args.root.resolve(), receipt=not args.generated_only))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
        # Provider exceptions or malformed document values must not expose their contents.
        errors = ["Governance inputs could not be evaluated; inspect the public checkout and generators"]
    print(
        json.dumps(
            {
                "result": "failed" if errors else "passed",
                "errors": errors,
                "provider_requests": 0,
                "external_links": "not_requested; local target/anchor validation only",
            },
            sort_keys=True,
        )
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
