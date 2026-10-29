"""Create-only checksummed public releases; never downloads or changes a live pointer."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .content_boundary import safe_link
from .errors import ResearchError
from .source_licensing import ACCEPTED_DATA_LICENSES
from .studies import MAX_MEMBER_BYTES, _verify_studies
from .study_metadata import manifest_entries

PERMITTED_DATA_LICENSES = frozenset(ACCEPTED_DATA_LICENSES)


def require_data_rights(entry):
    rights = entry.get("data_rights")
    if (
        not isinstance(rights, dict)
        or set(rights) != {"license", "evidence_url", "scope"}
        or rights.get("license") not in PERMITTED_DATA_LICENSES
        or rights.get("scope") != "all_declared_files"
        or not safe_link(rights.get("evidence_url"))
        or not rights["evidence_url"].startswith("https://")
    ):
        raise ResearchError(
            "source_license_unreleased",
            "Every installed study needs reviewed permissive rights covering all declared files.",
        )


def install_release(manifest, source_root, destination):
    """Verify a reviewed release and atomically publish a content-addressed directory.

    Eligibility is a recorded operator review, not a license inferred from a
    source URL, API key, code license or the cBioPortal file format.
    """
    manifest, source_root, destination = map(Path, (manifest, source_root, destination))
    if manifest.is_symlink() or source_root.is_symlink() or destination.is_symlink():
        raise ResearchError("invalid_study_manifest", "Linked study installation paths are forbidden.")
    if manifest.stat().st_size > 1_000_000:
        raise ResearchError("invalid_study_manifest", "Study manifest exceeds its metadata budget.")
    raw = manifest.read_bytes()
    entries = manifest_entries(raw)
    enabled = [entry for entry in entries if entry.get("enabled")]
    if not enabled:
        raise ResearchError("invalid_study_manifest", "Installation requires an enabled reviewed release.")
    for entry in enabled:
        require_data_rights(entry)
    _verify_studies(manifest, source_root)
    identity = hashlib.sha256(raw).hexdigest()
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / identity

    def existing():
        if final.is_symlink() or not final.is_dir():
            raise ResearchError(
                "study_version_changed", "Installed release identity conflicts with its directory."
            )
        release = final / "release"
        if not release.is_dir():
            raise ResearchError(
                "provider_busy",
                "Study installation is incomplete; reconcile it before retrying.",
                retryable=True,
            )
        published_manifest = release / "manifest.json"
        if published_manifest.is_symlink() or published_manifest.read_bytes() != raw:
            raise ResearchError(
                "study_version_changed", "Installed release metadata conflicts with its identity."
            )
        _verify_studies(published_manifest, release / "studies")

    if final.exists() or final.is_symlink():
        existing()
        return {"status": "verified_existing", "identity": identity, "directory": str(final / "release")}
    try:
        final.mkdir(mode=0o700)
    except FileExistsError:
        existing()
        return {"status": "verified_existing", "identity": identity, "directory": str(final / "release")}
    stage = Path(tempfile.mkdtemp(prefix=".study-stage-", dir=destination))
    try:
        (stage / "manifest.json").write_bytes(raw)
        for entry in enabled:
            study = stage / "studies" / entry["id"]
            study.mkdir(parents=True)
            for relative, expected in entry["files"].items():
                source = source_root / entry["id"] / relative
                target = study / relative
                if not target.resolve().is_relative_to(study.resolve()):
                    raise ResearchError(
                        "invalid_study_manifest", "Study member escapes its release directory."
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                # Refuse links at open time, including a swap after verification.
                fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                total, digest = 0, hashlib.sha256()
                with os.fdopen(fd, "rb") as reader, target.open("xb") as writer:
                    for block in iter(lambda: reader.read(1024 * 1024), b""):
                        total += len(block)
                        if total > MAX_MEMBER_BYTES:
                            raise ResearchError(
                                "study_version_changed", "Study member exceeds its installation budget."
                            )
                        digest.update(block)
                        writer.write(block)
                    writer.flush()
                    os.fsync(writer.fileno())
                if digest.hexdigest() != expected:
                    raise ResearchError(
                        "study_version_changed", "Study changed while installing its release."
                    )
        _verify_studies(stage / "manifest.json", stage / "studies")
        for path in stage.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        # macOS requires a writable source directory for this directory move.
        # Files and children are read-only; harden the root immediately after it.
        stage.chmod(0o755)
        # This identity directory is reserved with exclusive mkdir above.
        # Readers see either no release or the fully verified release directory.
        stage.rename(final / "release")
        (final / "release").chmod(0o555)
        final.chmod(0o555)
        return {"status": "installed", "identity": identity, "directory": str(final / "release")}
    finally:
        if stage.exists():
            for path in stage.rglob("*"):
                if path.is_dir():
                    path.chmod(0o700)
            stage.chmod(0o700)
            shutil.rmtree(stage)
        if final.exists() and not (final / "release").exists():
            final.rmdir()


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = install_release(args.manifest, args.root, args.destination)
    except ResearchError as exc:
        print(json.dumps({"error": exc.as_dict()}))
        return 1
    except OSError:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "local_io_error",
                        "message": "Study installation filesystem operation failed.",
                        "retryable": False,
                    }
                }
            )
        )
        return 1
    print(json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
