"""CI must reject stale generated contracts and broken public documentation."""

import importlib.util
import json
import socket
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-governance.py"


@pytest.fixture
def governance():
    assert SCRIPT.is_file(), "Governance check is missing"
    spec = importlib.util.spec_from_file_location("governance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name", ["docs/operation-ownership.json", "docs/mcp-catalog-budget.json", "docs/source-access.md"]
)
def test_stale_generated_artifact_fails_without_rewriting(governance, tmp_path, name):
    target = tmp_path / name
    target.parent.mkdir(parents=True)
    target.write_text("stale sentinel")
    assert governance.compare_generated(tmp_path, {name: b"current generated contract\n"}) == [name]
    assert target.read_text() == "stale sentinel"


@pytest.mark.parametrize("destination", ["missing.md", "../private.md", "guide.md#missing-heading"])
def test_broken_or_private_local_link_fails(governance, tmp_path, destination):
    (tmp_path / "README.md").write_text(f"[link]({destination})\n")
    (tmp_path / "guide.md").write_text("# Existing heading\n")
    errors = governance.check_links(tmp_path)
    assert errors and all("README.md" in error for error in errors)


def test_code_examples_do_not_become_false_document_links(governance, tmp_path):
    (tmp_path / "README.md").write_text("```md\n[example](does-not-exist.md)\n```\n")
    assert governance.check_links(tmp_path) == []


def test_reference_links_and_duplicate_heading_anchors_are_checked(governance, tmp_path):
    (tmp_path / "README.md").write_text("[Good][guide]\n\n[guide]: guide.md#same-heading-1\n")
    (tmp_path / "guide.md").write_text("# Same heading\n\n# Same heading\n")
    assert governance.check_links(tmp_path) == []
    (tmp_path / "README.md").write_text("[Bad][guide]\n\n[guide]: guide.md#same-heading-2\n")
    assert governance.check_links(tmp_path)


def test_stale_readiness_revision_is_rejected(governance, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/capability-readiness.json").write_text(json.dumps({"implementation": "biomedmcp/0.1.0"}))
    assert governance.check_readiness(tmp_path)


@pytest.mark.parametrize("target", ["/guide%20book.md#heading", "guide%20book.md#heading", "assets/"])
def test_encoded_root_links_and_directory_targets_resolve(governance, tmp_path, target):
    (tmp_path / "README.md").write_text(f"[link]({target})\n")
    (tmp_path / "guide book.md").write_text("# Heading\n")
    (tmp_path / "assets").mkdir()
    assert governance.check_links(tmp_path) == []


@pytest.mark.parametrize(
    "text", ['<a href="missing.md">link</a>', "![image](missing.png)", "[link](%2e%2e/private.md)"]
)
def test_html_images_and_encoded_traversal_are_checked(governance, tmp_path, text):
    (tmp_path / "README.md").write_text(text)
    assert governance.check_links(tmp_path)


def test_symlink_document_is_rejected_before_reading(governance, tmp_path, monkeypatch):
    secret = tmp_path.parent / f"{tmp_path.name}-private.md"
    secret.write_text("private sentinel")
    (tmp_path / "private.md").symlink_to(secret)
    (tmp_path / "README.md").write_text("[link](private.md)\n")
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.resolve() != secret, "Checker read a private symlink target"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    assert governance.check_links(tmp_path)


@pytest.mark.parametrize(
    "tokens,tokenizer", [(None, "cl100k_base"), (True, "cl100k_base"), (-1, "cl100k_base"), (1, None)]
)
def test_optional_token_measurement_must_be_well_formed(governance, tmp_path, tokens, tokenizer):
    name = "docs/mcp-catalog-budget.json"
    target = tmp_path / name
    target.parent.mkdir()
    target.write_text(json.dumps({"tokens": tokens, "tokenizer": tokenizer, "tool_count": 13}))
    expected = json.dumps({"tokens": None, "tokenizer": None, "tool_count": 13}).encode()
    assert governance.compare_generated(tmp_path, {name: expected}) == [name]


def test_tokenizer_installation_does_not_change_catalog_identity(governance, tmp_path):
    name = "docs/mcp-catalog-budget.json"
    target = tmp_path / name
    target.parent.mkdir()
    target.write_text(json.dumps({"tokens": 100, "tokenizer": "cl100k_base", "tool_count": 13}))
    expected = json.dumps({"tokens": None, "tokenizer": None, "tool_count": 13}).encode()
    assert governance.compare_generated(tmp_path, {name: expected}) == []
    target.write_text(json.dumps({"tokens": 100, "tokenizer": "cl100k_base", "tool_count": 12}))
    assert governance.compare_generated(tmp_path, {name: expected}) == [name]


@pytest.fixture
def readiness_tree(tmp_path):
    report = json.loads((ROOT / "docs/capability-readiness.json").read_text())
    for name in {item for row in report["rows"] for item in row["evidence"]}:
        if name.startswith(("docs/", "tests/")):
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture evidence")
    for key in ("source_schemas", "architecture", "live_observations"):
        (tmp_path / "docs" / report[key]).write_text("fixture index")
    for name in ("docs/capability-readiness.json", "docs/python-dependency-inventory.json", "uv.lock"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


def test_current_readiness_and_pep503_dependency_names_are_accepted(governance, readiness_tree):
    assert governance.package_name("Jaraco.Classes") == "jaraco-classes"
    assert governance.check_readiness(readiness_tree) == []


@pytest.mark.parametrize("mutation", ["owner", "status", "duplicate", "evidence", "index"])
def test_readiness_does_not_promote_or_drop_evidence(governance, readiness_tree, mutation):
    target = readiness_tree / "docs/capability-readiness.json"
    report = json.loads(target.read_text())
    if mutation == "duplicate":
        report["rows"][1] = report["rows"][0]
    elif mutation == "evidence":
        report["rows"][0]["evidence"] = ["tests/missing.py"]
    elif mutation == "index":
        report["architecture"] = "missing.md"
    else:
        report["rows"][0][mutation] = "platform" if mutation == "owner" else "live_qualified"
    target.write_text(json.dumps(report))
    assert governance.check_readiness(readiness_tree)


@pytest.mark.parametrize("mutation", ["lock", "version", "empty", "duplicate"])
def test_dependency_snapshot_rejects_unbound_inputs(governance, readiness_tree, mutation):
    target = readiness_tree / "docs/python-dependency-inventory.json"
    report = json.loads(target.read_text())
    if mutation == "lock":
        report["uv_lock_sha256"] = "0" * 64
    elif mutation == "version":
        report["packages"][0]["version"] = "999999"
    elif mutation == "empty":
        report["packages"] = []
    else:
        report["packages"].append(report["packages"][0])
    target.write_text(json.dumps(report))
    assert governance.check_readiness(readiness_tree)


def test_governance_denies_network_even_for_external_document_links(governance, tmp_path):
    (tmp_path / "README.md").write_text("[external](https://example.invalid/missing)\n")
    with governance.no_network():
        assert governance.check_links(tmp_path) == []
        with pytest.raises(RuntimeError, match="cannot contact"):
            socket.create_connection(("example.invalid", 443))


def test_shared_qualifier_enforces_read_only_gates_before_contracts():
    script = (ROOT / "scripts/test-local.sh").read_text()
    for command in ("ruff check src/biomedmcp scripts", "python scripts/check-governance.py"):
        assert command in script and script.index(command) < script.index("pytest tests -q")
    assert "--generated-only" not in script
    assert "uv run --frozen --no-sync python scripts/check-governance.py" in script
    assert "uv run --frozen --no-sync ruff check" in script
    for command in ("ruff", "python scripts/check-governance.py"):
        assert any("--network none" in line and command in line for line in script.splitlines())
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "./scripts/test-local.sh" in workflow and "contents: read" in workflow


@pytest.mark.parametrize("conflict", [None, "Version", "License"])
def test_installed_inventory_deduplicates_only_identical_editable_metadata(tmp_path, conflict):
    spec = importlib.util.spec_from_file_location("inventory", ROOT / "scripts/python-inventory.py")
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    (tmp_path / "uv.lock").write_text("fixture frozen lock")
    distributions = []
    for number in range(2):
        metadata = Message()
        metadata["Name"] = "fixture-package"
        metadata["Version"] = "1.0" if conflict != "Version" or number == 0 else "2.0"
        metadata["License"] = "MIT" if conflict != "License" or number == 0 else "Apache-2.0"
        distributions.append(SimpleNamespace(metadata=metadata, version=metadata["Version"]))
    if conflict:
        with pytest.raises(ValueError, match="Conflicting"):
            inventory.snapshot(tmp_path, distributions)
    else:
        assert len(inventory.snapshot(tmp_path, distributions)["packages"]) == 1


@pytest.mark.parametrize("mutation", ["test", "runner", "source", "dependency", "missing-source", "revision"])
def test_receipt_rejects_changed_qualified_inputs(governance, tmp_path, monkeypatch, mutation):
    # Preserve genuine source fingerprints while changing one bound input.
    # The synthetic receipt is a validator fixture, never written to the distribution.
    report = json.loads((ROOT / "src/biomedmcp/offline-qualification.json").read_text())
    # A validator fixture must be initially valid even before source requalification.
    report["implementation"] = governance.REVISION
    names = governance.source_names()
    probe = {
        "core_sha256": report["core_sha256"],
        "dependencies": report["dependencies"],
        "sources": {
            name: {
                "importable": True,
                "implementation_sha256": report["sources"].get(name, {}).get("implementation_sha256"),
            }
            for name in names
        },
    }
    monkeypatch.setattr(governance, "import_probe", lambda _: probe)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/fixture.py").write_text("fixture")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/qualify-readiness.py").write_text("runner fixture")
    report["test_inputs_sha256"] = {"tests/fixture.py": governance.sha(b"fixture")}
    report["runner_sha256"] = governance.sha(b"runner fixture")
    path = tmp_path / "src/biomedmcp/offline-qualification.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report))
    assert governance.check_receipt(tmp_path) == []
    if mutation == "test":
        (tmp_path / "tests/fixture.py").write_text("changed")
    elif mutation == "runner":
        (tmp_path / "scripts/qualify-readiness.py").write_text("changed")
    else:
        if mutation == "source":
            report["sources"]["gtex"]["implementation_sha256"] = "0" * 64
        elif mutation == "dependency":
            report["dependencies"] = {}
        elif mutation == "revision":
            report["implementation"] = "biomedmcp/stale"
        else:
            report["sources"].pop("gtex")
        path.write_text(json.dumps(report))
    assert governance.check_receipt(tmp_path)
