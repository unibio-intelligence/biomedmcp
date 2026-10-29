"""Install the synthetic public fixture in a new directory; never downloads data."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def install(destination):
    if destination.exists():
        raise ValueError("Choose a new empty destination; the demo never overwrites an existing release")
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/studies/ubi_synthetic"
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("The synthetic input contains a linked member")
    directory = destination / "studies/ubi_synthetic"
    shutil.copytree(source, directory)
    files = {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    study = {
        "id": "ubi_synthetic",
        "enabled": True,
        "release": "synthetic-v1",
        "source_url": "https://example.org/synthetic",
        "files": files,
        "sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "mutation_coverage": {"samples": ["S1", "S2", "S3", "S4"], "genes": "all"},
    }
    manifest = destination / "manifest.json"
    manifest.write_text(json.dumps({"studies": [study]}, indent=2) + "\n")
    return {
        "study_root": str(destination / "studies"),
        "manifest": str(manifest),
        "id": study["id"],
        "release": study["release"],
        "synthetic": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.destination.resolve())))


if __name__ == "__main__":
    main()
