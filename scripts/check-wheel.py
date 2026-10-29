#!/usr/bin/env python3
"""Check the complete public wheel without resolving adapter distribution names."""

import argparse
import json
import re
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(root, wheels):
    project = tomllib.loads((root / "pyproject.toml").read_text())
    metadata = project["project"]
    adapter_names = {
        normalize(tomllib.loads(path.read_text())["project"]["name"])
        for path in (root / "servers/python").glob("*/pyproject.toml")
    }
    paths = sorted(wheels.glob("*.whl"))
    require(len(paths) == 1, "Release exactly one biomedmcp wheel, with adapters bundled inside.")
    requirements = {Requirement(value) for value in metadata["dependencies"]}
    require(
        all(normalize(item.name) not in adapter_names and item.url is None for item in requirements),
        "Adapter distribution names and direct-source dependencies must not enter public metadata.",
    )
    with zipfile.ZipFile(paths[0]) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)) and wheel.testzip() is None, "Invalid wheel members.")
        records = [name for name in names if name.endswith(".dist-info/METADATA")]
        prefix = f"biomedmcp-{metadata['version']}.dist-info/"
        require(records == [prefix + "METADATA"], "Wheel distribution identity differs from source.")
        actual = Parser().parsestr(wheel.read(records[0]).decode())
        require(actual["Name"] == "biomedmcp", "Only biomedmcp may be released.")
        require(actual["Version"] == metadata["version"], "Wheel version differs from source.")
        require(actual["Requires-Python"] == metadata["requires-python"], "Python requirement differs.")
        require(
            {Requirement(value) for value in actual.get_all("Requires-Dist", [])} == requirements,
            "Wheel dependencies differ from the reviewed runtime requirements.",
        )
        checked = 0
        packages = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
        require(len(packages) == len(adapter_names) + 1, "Adapter module inventory is incomplete.")
        for package in packages:
            directory = root / package
            require((directory / "__init__.py").is_file(), "Bundled package is missing.")
            for path in sorted(directory.rglob("*")):
                if path.suffix not in {".py", ".json"} or "__pycache__" in path.parts:
                    continue
                name = directory.name + "/" + path.relative_to(directory).as_posix()
                require(name in names and wheel.read(name) == path.read_bytes(), "Bundled module/data differs.")
                checked += 1
        for pattern in metadata["license-files"]:
            for path in root.glob(pattern):
                if path.is_file():
                    name = prefix + "licenses/" + path.relative_to(root).as_posix()
                    require(name in names and wheel.read(name) == path.read_bytes(), "Bundled license differs.")
    return {"result": "passed", "distribution": "biomedmcp", "bundled_adapters": len(adapter_names),
            "adapter_index_dependencies": 0, "module_files_checked": checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--wheels", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check(args.root, args.wheels)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
