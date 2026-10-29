"""Leased, measured study payloads; no analysis is run under the cache lock."""

import csv
import hashlib
import json
import sys
import threading
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType

from ..errors import ResearchError

MIB = 1024 * 1024
PAYLOAD_BUDGET = 256 * MIB
PARSER_RESERVATION = 32 * MIB
ANALYSIS_RESERVATION = 32 * MIB
MAX_LINE = 2 * MIB
MAX_COLUMNS = 50_000
MAX_SAMPLES = 10_000
MAX_ENTRIES = 64
MAX_RESULT_BYTES = 8 * MIB


def budget_error():
    return ResearchError(
        "study_budget_exceeded",
        "Interactive study resource budget exceeded; use platform analytics for larger work.",
    )


def payload_bytes(value):
    """Conservative Python payload size: aliases are deliberately charged again.

    Immutable proxies include an upper allowance for their backing dictionary.
    This is an admission metric, not process RSS or native allocator accounting.
    The acyclic payload format avoids a large auxiliary visited-object set.
    """
    if isinstance(value, MappingProxyType):
        size = sys.getsizeof(value) + 224 + 80 * len(value)
        return size + sum(payload_bytes(k) + payload_bytes(v) for k, v in value.items())
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(payload_bytes(k) + payload_bytes(v) for k, v in value.items())
    if isinstance(value, (tuple, list, frozenset, set)):
        return sys.getsizeof(value) + sum(payload_bytes(item) for item in value)
    return sys.getsizeof(value)


@dataclass
class Entry:
    value: object
    size: int
    pins: int = 0


class Reservation:
    def __init__(self, cache, size):
        self.cache, self.size = cache, size

    def grow(self, amount):
        with self.cache.lock:
            self.cache._make_room(amount)
            self.cache.used += amount
            self.size += amount
            self.cache.peak = max(self.cache.peak, self.cache.used)

    def close(self):
        with self.cache.lock:
            self.cache.used -= self.size
            self.size = 0


class StudyCache:
    def __init__(self, budget=PAYLOAD_BUDGET, max_entries=MAX_ENTRIES):
        self.budget, self.max_entries = budget, max_entries
        self.entries, self.building = OrderedDict(), {}
        self.lock = threading.Lock()
        self.used = self.peak = 0

    def _make_room(self, amount):
        if amount > self.budget:
            raise budget_error()
        for key in list(self.entries):
            if self.used + amount <= self.budget:
                break
            entry = self.entries[key]
            if entry.pins == 0:
                self.used -= entry.size
                del self.entries[key]
        if self.used + amount > self.budget:
            raise budget_error()

    @contextmanager
    def reserve(self, size):
        with self.lock:
            self._make_room(size)
            self.used += size
            self.peak = max(self.peak, self.used)
        ticket = Reservation(self, size)
        try:
            yield ticket
        finally:
            ticket.close()

    @contextmanager
    def lease(self, key, builder):
        # Single-flight initialization: wait without holding the cache lock.
        while True:
            with self.lock:
                entry = self.entries.get(key)
                if entry is not None:
                    entry.pins += 1
                    self.entries.move_to_end(key)
                    break
                event = self.building.get(key)
                if event is None:
                    while len(self.entries) + len(self.building) >= self.max_entries:
                        victim = next((k for k, e in self.entries.items() if not e.pins), None)
                        if victim is None:
                            raise budget_error()
                        self.used -= self.entries.pop(victim).size
                    event = threading.Event()
                    self.building[key] = event
                    creator = True
                else:
                    creator = False
            if not creator:
                event.wait()
                continue
            try:
                with self.reserve(PARSER_RESERVATION) as ticket:
                    value = builder(ticket)
                    size = payload_bytes(value)
                    if size > ticket.size - PARSER_RESERVATION:
                        ticket.grow(size - (ticket.size - PARSER_RESERVATION))
                    with self.lock:
                        # Transfer the retained allocation to the pinned entry.
                        self.used -= ticket.size - size
                        ticket.size = 0
                        entry = Entry(value, size, 1)
                        self.entries[key] = entry
                break
            finally:
                with self.lock:
                    self.building.pop(key)
                    event.set()
        try:
            yield entry.value
        finally:
            with self.lock:
                entry.pins -= 1

    def snapshot(self):
        with self.lock:
            return {
                "budget_bytes": self.budget,
                "accounted_bytes": self.used,
                "peak_accounted_bytes": self.peak,
                "retained_bytes": sum(e.size for e in self.entries.values()),
                "pinned_entries": sum(e.pins > 0 for e in self.entries.values()),
                "entries": len(self.entries),
                "building": len(self.building),
            }


study_cache = StudyCache()


def validate_sample_ids(samples):
    ids = [row["SAMPLE_ID"] for row in samples]
    sample_ids = frozenset(ids)
    if len(ids) != len(sample_ids):
        raise ResearchError("invalid_study", "Duplicate sample identifiers in the study release.")
    return sample_ids


def validate_mutation_samples(mutations, sample_ids):
    if any(row.get("Tumor_Sample_Barcode") not in sample_ids for row in mutations):
        raise ResearchError("invalid_study", "Mutation references an undeclared sample.")


def verified_members(manifest, study, metadata_sha256):
    """Bind private member hashes to the registry's exact verified declaration."""
    if manifest.stat().st_size > 1_000_000:
        raise ResearchError("invalid_study_manifest", "Study manifest exceeds its metadata budget.")
    for entry in json.loads(manifest.read_text())["studies"]:
        if entry.get("id") == study:
            digest = hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode())
            if digest.hexdigest() == metadata_sha256:
                return entry["files"]
    raise ResearchError("study_version_changed", "Study declaration changed before analysis.")


def parsed_lines(path):
    """Bound physical records; multiline fields are explicitly unsupported."""
    if path.stat().st_size > 200_000_000:
        raise budget_error()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            offset = handle.tell()
            raw = handle.readline(MAX_LINE + 1)
            if not raw:
                break
            if len(raw) > MAX_LINE:
                raise budget_error()
            digest.update(raw)
            if raw.startswith(b"#") or not raw.strip():
                continue
            try:
                fields = next(csv.reader([raw.decode("utf-8")], delimiter="\t", strict=True))
            except (UnicodeError, csv.Error):
                raise ResearchError(
                    "invalid_study", "Invalid UTF-8 or unsupported multiline table record."
                ) from None
            if len(fields) > MAX_COLUMNS:
                raise budget_error()
            yield offset, raw, fields
    yield None, digest.hexdigest(), None


def read_table(path, expected, ticket, kind, sample_ids=None):
    rows, header = [], None
    for offset, raw, fields in parsed_lines(path):
        if offset is None:
            if raw != expected:
                raise ResearchError(
                    "study_version_changed", "Parsed table differs from the verified release."
                )
            break
        if header is None:
            header = fields
            if len(set(header)) != len(header):
                raise ResearchError("invalid_study", "Duplicate study table columns.")
            required = {
                "samples": {"SAMPLE_ID"},
                "patients": {"PATIENT_ID"},
                "mutations": {"Hugo_Symbol", "Tumor_Sample_Barcode"},
                "sv": {"Site1_Hugo_Symbol", "Site2_Hugo_Symbol", "Sample_Id"},
            }[kind]
            if not required <= set(header):
                raise ResearchError("invalid_study", "Study table lacks required columns.")
            ticket.grow(payload_bytes(header))
            continue
        if len(fields) != len(header):
            raise ResearchError("invalid_study", "Study table row does not match its header.")
        row = dict(zip(header, fields, strict=True))
        if kind == "mutations":
            row = {
                key: row[key]
                for key in ("Hugo_Symbol", "Tumor_Sample_Barcode", "Variant_Classification")
                if key in row
            }
        identity = {
            "samples": "SAMPLE_ID",
            "patients": "PATIENT_ID",
            "mutations": "Hugo_Symbol",
            "sv": "Sample_Id",
        }[kind]
        if not row.get(identity) or len(row[identity]) > 256:
            raise ResearchError("invalid_study", "Study table requires bounded nonempty identifiers.")
        if kind == "samples" and len(row.get("PATIENT_ID", "")) > 256:
            raise ResearchError("invalid_study", "Study table requires bounded patient identifiers.")
        if kind == "sv" and any(len(row[key]) > 256 for key in ("Site1_Hugo_Symbol", "Site2_Hugo_Symbol")):
            raise ResearchError("invalid_study", "Study table requires bounded gene identifiers.")
        row = MappingProxyType(row)
        # Includes list/index growth and repeated references in the size metric.
        ticket.grow(2 * payload_bytes(row) + 1024)
        rows.append(row)
        if len(rows) > (MAX_SAMPLES if kind == "samples" else 1_000_000):
            raise budget_error()
    if header is None:
        raise ResearchError("invalid_study", "Study table has no header.")
    if kind == "samples":
        sample_ids = validate_sample_ids(rows)
        return MappingProxyType(
            {
                "rows": MappingProxyType({row["SAMPLE_ID"]: row for row in rows}),
                "sample_ids": sample_ids,
            }
        )
    if kind == "patients":
        if len({row["PATIENT_ID"] for row in rows}) != len(rows):
            raise ResearchError("invalid_study", "Duplicate patient identifiers.")
        return MappingProxyType({row["PATIENT_ID"]: row for row in rows})
    if kind == "mutations":
        validate_mutation_samples(rows, sample_ids)
        genes, counts = defaultdict(list), defaultdict(int)
        for row in rows:
            genes[row["Hugo_Symbol"]].append(row)
            counts[row["Tumor_Sample_Barcode"]] += 1
        return MappingProxyType(
            {
                "rows": tuple(rows),
                "genes": MappingProxyType({g: tuple(r) for g, r in genes.items()}),
                "sample_counts": MappingProxyType(dict(counts)),
            }
        )
    if kind == "sv" and any(row["Sample_Id"] not in sample_ids for row in rows):
        raise ResearchError("invalid_study", "Structural variants reference unknown clinical samples.")
    return tuple(rows)


def matrix_index(path, expected, ticket):
    header, genes, count = None, {}, 0
    for offset, raw, fields in parsed_lines(path):
        if offset is None:
            if raw != expected:
                raise ResearchError(
                    "study_version_changed", "Indexed matrix differs from the verified release."
                )
            break
        if header is None:
            if "Hugo_Symbol" not in fields or len(set(fields)) != len(fields):
                raise ResearchError("invalid_study", "Matrix requires unique columns and a gene identifier.")
            header = tuple(fields)
            gene_column = header.index("Hugo_Symbol")
            ticket.grow(payload_bytes(header))
            continue
        if len(fields) != len(header) or not fields[gene_column] or len(fields[gene_column]) > 256:
            raise ResearchError("invalid_study", "Matrix row does not match its declared columns/identity.")
        gene = fields[gene_column]
        if gene in genes:
            genes[gene] = None  # A duplicate is never silently selected.
        else:
            ticket.grow(sys.getsizeof(gene) + 1024)
            genes[gene] = (offset, len(raw), hashlib.sha256(raw).digest())
        count += 1
        if count > 1_000_000:
            raise budget_error()
    if header is None:
        raise ResearchError("invalid_study", "Matrix has no header.")
    return MappingProxyType({"header": header, "genes": MappingProxyType(genes)})


def matrix_row(path, index, gene, ticket):
    if gene not in index["genes"]:
        raise ResearchError("study_gene_unavailable", "The assay has no measured row for the requested gene.")
    locator = index["genes"][gene]
    if locator is None:
        raise ResearchError(
            "ambiguous_gene", "Multiple matrix rows match this gene; release needs unambiguous identifiers."
        )
    offset, size, expected = locator
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read(size)
    if hashlib.sha256(raw).digest() != expected:
        raise ResearchError("study_version_changed", "Requested matrix row differs from the verified index.")
    fields = next(csv.reader([raw.decode("utf-8")], delimiter="\t", strict=True))
    row = MappingProxyType(dict(zip(index["header"], fields, strict=True)))
    ticket.grow(payload_bytes(row))
    return row
