"""Release metadata must keep every adapter inside one distribution."""

import importlib.util
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_wheel", ROOT / "scripts/check-wheel.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture
def distribution(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "pyproject.toml").write_text('''[project]
name = "biomedmcp"
version = "0.2.1"
requires-python = ">=3.13"
dependencies = ["httpx==0.28.1"]
license-files = ["LICENSE", "servers/python/**/LICENSE"]
[tool.hatch.build.targets.wheel]
packages = ["src/biomedmcp", "servers/python/ncbi/ncbi_mcp", "servers/python/pdb/pdb_mcp"]
''')
    (root / "LICENSE").write_text("Synthetic root license")
    for adapter in ("ncbi", "pdb"):
        folder = root / "servers/python" / adapter
        folder.mkdir(parents=True)
        (folder / "pyproject.toml").write_text(f'[project]\nname = "{adapter}-mcp"\n')
        (folder / "LICENSE").write_text(f"Synthetic {adapter} license")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    files = {
        "biomedmcp-0.2.1.dist-info/METADATA":
            b"Metadata-Version: 2.4\nName: biomedmcp\nVersion: 0.2.1\nRequires-Python: >=3.13\n"
            b"Requires-Dist: httpx==0.28.1\n\n",
    }
    for package in project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]:
        folder = root / package
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in (("__init__.py", b""), ("contracts.json", b'{"contract":"synthetic"}')):
            (folder / name).write_bytes(data)
            files[folder.name + "/" + name] = data
    for pattern in project["project"]["license-files"]:
        for path in root.glob(pattern):
            files["biomedmcp-0.2.1.dist-info/licenses/" + path.relative_to(root).as_posix()] = path.read_bytes()
    wheels = tmp_path / "wheels"
    wheels.mkdir()

    def write():
        with zipfile.ZipFile(wheels / "biomedmcp-0.2.1-py3-none-any.whl", "w") as wheel:
            for name, data in files.items():
                wheel.writestr(name, data)

    return root, wheels, files, write


def test_complete_single_distribution_preserves_modules_data_and_licenses(distribution):
    root, wheels, _, write = distribution
    write()
    result = checker.check(root, wheels)
    assert result["bundled_adapters"] == 2 and result["adapter_index_dependencies"] == 0
    assert result["module_files_checked"] == 6


@pytest.mark.parametrize("dependency", ["ncbi-mcp", "ncbi-mcp==0.0.1", "pdb_mcp>=0.0.1"])
def test_adapter_dependencies_are_rejected_even_with_versions(distribution, dependency):
    root, wheels, _, write = distribution
    path = root / "pyproject.toml"
    path.write_text(path.read_text().replace('"httpx==0.28.1"', json.dumps(dependency)))
    write()
    with pytest.raises(ValueError, match="Adapter distribution names"):
        checker.check(root, wheels)


@pytest.mark.parametrize("name", ["ncbi_mcp/__init__.py", "pdb_mcp/contracts.json",
                                     "biomedmcp-0.2.1.dist-info/licenses/servers/python/ncbi/LICENSE"])
def test_missing_module_data_or_license_stops_release(distribution, name):
    root, wheels, files, write = distribution
    files.pop(name)
    write()
    with pytest.raises(ValueError, match="Bundled"):
        checker.check(root, wheels)


def test_unreviewed_wheel_dependency_stops_release(distribution):
    root, wheels, files, write = distribution
    name = "biomedmcp-0.2.1.dist-info/METADATA"
    files[name] = files[name].replace(b"Requires-Dist: httpx==0.28.1", b"Requires-Dist: pdb-mcp")
    write()
    with pytest.raises(ValueError, match="dependencies differ"):
        checker.check(root, wheels)


def test_extra_adapter_wheel_stops_release(distribution):
    root, wheels, _, write = distribution
    write()
    (wheels / "pdb_mcp-999.0-py3-none-any.whl").write_bytes(b"not a reviewed release")
    with pytest.raises(ValueError, match="exactly one"):
        checker.check(root, wheels)


def test_workflow_checks_the_single_wheel_before_bundling():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    assert "uv build --all-packages" not in text
    assert text.index("uv build --wheel") < text.index("scripts/check-wheel.py")
    assert text.index("scripts/check-wheel.py") < text.index("release-artifacts.py bundle")
