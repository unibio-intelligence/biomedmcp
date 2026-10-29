"""Registry descriptions must start the actual MCP server, not the JSON CLI."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

from biomedmcp import cli
from biomedmcp.mcp import server

ROOT = Path(__file__).resolve().parents[1]


def test_registry_python_arguments_dispatch_to_server(monkeypatch):
    document = json.loads((ROOT / "server.json").read_text())
    package = next(p for p in document["packages"] if p["registryType"] == "pypi")
    arguments = []
    for item in package["packageArguments"]:
        if item["type"] == "named":
            arguments.append(item["name"])
        arguments.append(item["value"])
    run = Mock()
    monkeypatch.setattr(server, "main", run)
    monkeypatch.setattr(sys, "argv", ["biomedmcp", *arguments])
    cli.main()
    run.assert_called_once_with(["--transport", "stdio"])


def test_mcp_mode_preserves_stdio_and_local_http_loopback(monkeypatch):
    service = Mock()
    monkeypatch.setattr(server, "create_server", lambda: service)
    monkeypatch.setenv("UBI_PROFILE", "local")
    server.main(["--transport", "stdio"])
    service.run.assert_called_once_with(transport="stdio")


def test_package_ownership_metadata_and_version_match():
    import tomllib
    document = json.loads((ROOT / "server.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert document["version"] == project["version"]
    assert "mcp-name: " + document["name"] in (ROOT / "README.md").read_text()
    assert "io.modelcontextprotocol.server.name=\"" + document["name"] + "\"" in (ROOT / "Dockerfile").read_text()
    assert {p["registryType"] for p in document["packages"]} == {"pypi", "oci"}
    assert document["packages"][0]["version"] == project["version"]
    assert document["packages"][1]["identifier"].endswith(":" + project["version"])


def test_front_page_examples_use_the_research_notebook_theme():
    from biomedmcp.examples import EXAMPLES
    content = (ROOT / "README.md").read_text()
    assert "evidence notebook" in content
    assert "BRAF" not in content and "melanoma" not in content
    assert not any("BRAF" in item.arguments_json or "V600E" in item.arguments_json for item in EXAMPLES)
