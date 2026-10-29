"""Verify declared public study releases before native analysis."""

import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path
from stat import S_ISDIR, S_ISREG

from .errors import ResearchError
from .study_metadata import manifest_entries

ASSAY_FILES = {
    "mutations": ("data_mutations.txt", "mutation_event"),
    "cna": ("data_cna.txt", "discrete_copy_number_call"),
    "expression": ("data_mrna_seq_v2_rsem_zscores_ref_all_samples.txt", "z_score"),
    "sv": ("data_sv.txt", "structural_variant_event"),
}
MAX_MEMBER_BYTES = 2_000_000_000
_verified = OrderedDict()
_verification_lock = threading.Lock()
_verification_pending = {}


def release_fingerprint(manifest, root, *, include_content=True):
    """Content change detector; filesystem timestamps alone are insufficient."""
    path = Path(manifest)
    if path.stat().st_size > 1_000_000:
        raise ResearchError("invalid_study_manifest", "Study manifest exceeds its metadata budget.")
    raw = path.read_bytes()
    entries = manifest_entries(raw)
    signature = [hashlib.sha256(raw).hexdigest()]
    for entry in entries:
        if not isinstance(entry, dict):
            raise ResearchError("invalid_study_manifest", "Invalid study release entry.")
        if not entry.get("enabled"):
            continue
        if not isinstance(entry.get("id"), str):
            raise ResearchError("invalid_study_manifest", "Study release requires an identifier.")
        directory = (Path(root).resolve() / entry["id"]).resolve()
        if not directory.is_relative_to(Path(root).resolve()) or directory == Path(root).resolve():
            raise ResearchError("invalid_study_manifest", "Study directory is outside its public root.")
        signature.append((entry["id"], directory.is_dir()))
        for file in sorted(directory.rglob("*")):
            stat = file.lstat()
            content = None
            if S_ISREG(stat.st_mode) and include_content:
                if stat.st_size > MAX_MEMBER_BYTES:
                    raise ResearchError("invalid_study_manifest", "Invalid managed study member.")
                digest, total = hashlib.sha256(), 0
                with file.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        total += len(block)
                        if total > MAX_MEMBER_BYTES:
                            raise ResearchError("invalid_study_manifest", "Invalid managed study member.")
                        digest.update(block)
                content = digest.hexdigest()
            signature.append(
                (
                    str(file.relative_to(directory)),
                    stat.st_mode,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    content,
                )
            )
            if len(signature) > 10_000:
                raise ResearchError(
                    "invalid_study_manifest", "Study member inventory exceeds its supported budget."
                )
    return signature


def load_studies() -> dict:
    """Explicitly recheck every declared member, including unchanged metadata."""
    return _registry(recheck=True)


def study_registry() -> dict:
    """Share initialization; analyses separately checksum their consumed members.

    Inventory metadata detects ordinary changes across the installed tree. It
    is never the content proof for a scientific input, including a cache hit.
    An explicit load_studies() also rechecks bytes of unconsumed members.
    """
    return _registry(recheck=False)


def study_paths():
    manifest = os.getenv("UBI_PUBLIC_STUDY_MANIFEST")
    root = os.getenv("UBI_PUBLIC_STUDY_DIR")
    if not manifest and not root:
        bundle = Path(__file__).parent / "data" / "demo"
        manifest, root = str(bundle / "manifest.json"), str(bundle / "studies")
    elif not manifest or not root:
        raise ResearchError("invalid_study_manifest", "Configure both the study manifest and root directory.")
    return Path(manifest), Path(root)


def _registry(*, recheck):
    manifest, root = study_paths()
    key = (str(Path(manifest).resolve()), str(Path(root).resolve()))
    while True:
        before = release_fingerprint(manifest, root, include_content=False)
        with _verification_lock:
            cached = _verified.get(key)
            if not recheck and cached and cached[0] == before:
                _verified.move_to_end(key)
                encoded = cached[1]
                break
            refresh = not recheck and cached and cached[0][0] == before[0]
            pending = _verification_pending.get(key)
            if pending is None:
                if len(_verification_pending) >= 4:
                    raise ResearchError(
                        "provider_busy", "Study verification is busy; retry later.", retryable=True
                    )
                pending = _verification_pending[key] = threading.Event()
                creator = True
            else:
                creator = False
        if not creator:
            pending.wait()
            continue
        try:
            if refresh:
                _verify_changed_members(manifest, root, cached[0], before)
                encoded = cached[1]
            else:
                registry = _verify_studies(manifest, root)
                encoded = json.dumps(registry, sort_keys=True)
            if release_fingerprint(manifest, root, include_content=False) != before:
                raise ResearchError("study_version_changed", "Study release changed during verification.")
            with _verification_lock:
                _verified[key] = (before, encoded)
                _verified.move_to_end(key)
                while len(_verified) > 4:
                    _verified.popitem(last=False)
            break
        finally:
            with _verification_lock:
                _verification_pending.pop(key)
                pending.set()
    return json.loads(encoded)


def _verify_changed_members(manifest, root, previous, current):
    def members(signature):
        result, study = {}, None
        for item in signature[1:]:
            if len(item) == 2:
                study = item[0]
                if not item[1]:
                    raise ResearchError("study_version_changed", "Study directory is unavailable.")
            else:
                result[(study, item[0])] = item[1:]
        return result

    old, new = members(previous), members(current)
    if old.keys() != new.keys():
        raise ResearchError("study_version_changed", "Study inventory changed since release verification.")
    entries = {entry["id"]: entry for entry in json.loads(Path(manifest).read_bytes())["studies"]}
    for (study, relative), identity in new.items():
        if old[(study, relative)] == identity:
            continue
        if S_ISDIR(identity[0]) and S_ISDIR(old[(study, relative)][0]):
            continue
        expected = entries[study]["files"].get(relative)
        if expected is None:
            raise ResearchError(
                "study_version_changed", "Study inventory changed since release verification."
            )
        verify_study_member(Path(root) / study / relative, expected)


def verify_study_member(path, expected):
    """Checksum consumed bytes even when the immutable parsed payload is cached."""
    before = path.lstat()
    if not S_ISREG(before.st_mode) or before.st_size > MAX_MEMBER_BYTES:
        raise ResearchError("study_version_changed", "Invalid managed study member.")
    digest, total = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(block)
            if total > MAX_MEMBER_BYTES:
                raise ResearchError("study_version_changed", "Invalid managed study member.")
            digest.update(block)
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if digest.hexdigest() != expected or any(
        getattr(after, name) != getattr(before, name) for name in fields
    ):
        raise ResearchError(
            "study_version_changed", "A consumed study member differs from the declared release."
        )


def _verify_studies(manifest, root) -> dict:
    root = Path(root).resolve()
    registry = {}
    for entry in manifest_entries(Path(manifest).read_bytes()):
        if not entry.get("enabled"):
            continue
        required = {"id", "release", "sha256", "files", "source_url"}
        if not required <= entry.keys() or not entry["files"]:
            raise ResearchError(
                "invalid_study_manifest", "An enabled study requires a version and checksummed files."
            )
        directory = (root / entry["id"]).resolve()
        if not directory.is_relative_to(root) or directory == root or not directory.is_dir():
            raise ResearchError("invalid_study_manifest", "Study directory is outside its public root.")
        members = {
            str(path.relative_to(directory))
            for path in directory.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        if members != set(entry["files"]) or any(path.is_symlink() for path in directory.rglob("*")):
            raise ResearchError(
                "invalid_study_manifest", "The managed study inventory contains undeclared or linked members."
            )
        for relative, expected in entry["files"].items():
            file = (directory / relative).resolve()
            if (
                not file.is_relative_to(directory)
                or not file.is_file()
                or file.stat().st_size > MAX_MEMBER_BYTES
            ):
                raise ResearchError("invalid_study_manifest", "Invalid managed study member.")
            verify_study_member(file, expected)
        canonical = json.dumps(entry["files"], sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(canonical.encode()).hexdigest() != entry["sha256"]:
            raise ResearchError("invalid_study_manifest", "The study manifest digest is invalid.")
        assays = {}
        declarations = entry.get("assays", {})
        if not isinstance(declarations, dict):
            raise ResearchError("invalid_study_manifest", "Assay declarations must be an object.")
        for kind, (filename, units) in ASSAY_FILES.items():
            declared = declarations.get(kind, {})
            if not isinstance(declared, dict) or not isinstance(declared.get("units", units), str):
                raise ResearchError("invalid_study_manifest", "Invalid declared assay units.")
            assays[kind] = {
                "available": filename in entry["files"],
                "file": filename,
                "sha256": entry["files"].get(filename),
                "units": declared.get("units", units),
                "units_basis": "manifest declaration"
                if "units" in declared
                else "managed cBioPortal file format",
                "sample_coverage": "finite values per gene"
                if kind in {"cna", "expression"}
                else "release-declared assay coverage",
                "gene_coverage": "verified matrix rows"
                if kind in {"cna", "expression"}
                else "release-declared assay coverage",
            }
        registry[entry["id"]] = {
            **{k: v for k, v in entry.items() if k != "files"},
            "assays": assays,
            "metadata_sha256": hashlib.sha256(
                json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    return registry
