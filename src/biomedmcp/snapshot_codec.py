"""Bounded lossless evidence storage; compression never expands storage grants.

Hashes bind canonical UTF-8 JSON after sanitation. Stored snapshots retain the
same one-MB ceiling; decoding is separately limited before JSON allocation.
"""

import base64
import hashlib
import json
import re
import zlib

from .content_boundary import source_links
from .receipts import _safe_request
from .study_workers import StudyWorkers

VALUE_BYTES = 8_000_000
VALUE_DEPTH = 64
VALUE_NODES = 100_000
workers = StudyWorkers(thread_name="ubi-evidence", busy_message="Evidence workers are busy; retry later.")


class PackingError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def shape(value):
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > VALUE_NODES:
            raise PackingError("snapshot_node_budget")
        if depth > VALUE_DEPTH:
            raise PackingError("snapshot_depth_budget")
        if isinstance(item, (dict, list)):
            if len(item) > VALUE_NODES - count:
                raise PackingError("snapshot_node_budget")
            if isinstance(item, dict):
                if any(not isinstance(k, str) for k in item):
                    raise PackingError("snapshot_invalid_data")
                if any(len(k) > VALUE_BYTES for k in item):
                    raise PackingError("snapshot_decoded_byte_budget")
                children = item.values()
            else:
                children = item
            pending.extend((child, depth + 1) for child in children)
        elif isinstance(item, str):
            if len(item) > VALUE_BYTES:
                raise PackingError("snapshot_decoded_byte_budget")
        elif item is not None and not isinstance(item, (int, float, bool)):
            raise PackingError("snapshot_invalid_data")


def encoded_value(value):
    pieces, total = [], 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    for piece in encoder.iterencode(value):
        part = piece.encode("utf-8")
        total += len(part)
        if total > VALUE_BYTES:
            raise PackingError("snapshot_decoded_byte_budget")
        pieces.append(part)
    return b"".join(pieces)


def pack(value):
    shape(value)
    rejected = {}
    safe, redacted = _safe_request(source_links(value, "", rejected))
    raw = encoded_value(safe)
    result = {
        "encoding": "json",
        "value": safe,
        "encoded_value": None,
        "value_utf8_bytes": len(raw),
        "value_sha256": hashlib.sha256(raw).hexdigest(),
    }
    if len(raw) > 250_000:
        packed = base64.b64encode(zlib.compress(raw, level=6)).decode("ascii")
        # Random/incompressible data must still use a smaller plain snapshot.
        if len(packed) + 128 < len(raw):
            result.update(encoding="zlib-json", value=None, encoded_value=packed)
    return result, safe, redacted or bool(rejected)


DELIMITER = re.compile(rb'[\[\]{}:," \t\r\n]')


def json_shape(raw):
    """Reject excessive nesting/tokens before parsing untrusted stored JSON.

    Skip complete quoted spans with C-backed searches, so multi-MiB source
    prose is not walked character-by-character on every bounded resource read.
    The standard decoder subsequently checks actual JSON syntax and shapes.
    """
    index = depth = tokens = 0
    while index < len(raw):
        char = raw[index]
        if char == 34:
            end = index
            while True:
                end = raw.find(b'"', end + 1)
                if end < 0:
                    raise ValueError("Invalid encoded snapshot")
                back, slashes = end - 1, 0
                while back >= index and raw[back] == 92:
                    back -= 1
                    slashes += 1
                if slashes % 2 == 0:
                    break
            index = end + 1
            tokens += 1
        elif char in (91, 123):
            depth += 1
            tokens += 1
            if depth > VALUE_DEPTH + 1:
                raise ValueError("Encoded snapshot exceeds depth budget")
            index += 1
        elif char in (93, 125):
            depth -= 1
            if depth < 0:
                raise ValueError("Invalid encoded snapshot")
            index += 1
        elif char in (58, 44, 32, 9, 13, 10):
            index += 1
        else:
            end = DELIMITER.search(raw, index)
            index = end.start() if end else len(raw)
            tokens += 1
        # Keys are tokens too; a legal object can have one per value node.
        if tokens > VALUE_NODES * 2:
            raise ValueError("Encoded snapshot exceeds node budget")


def unpack(snapshot):
    if snapshot.encoding == "json":
        shape(snapshot.value)
        raw = encoded_value(snapshot.value)
        value = snapshot.value
    else:
        packed = base64.b64decode(snapshot.encoded_value, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, VALUE_BYTES + 1)
        if len(raw) > VALUE_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("Encoded snapshot exceeds byte budget or has invalid framing")
        json_shape(raw)
        value = json.loads(raw)
        shape(value)
        if encoded_value(value) != raw:
            raise ValueError("Encoded snapshot is not canonical JSON")
    if len(raw) != snapshot.value_utf8_bytes or hashlib.sha256(raw).hexdigest() != snapshot.value_sha256:
        raise ValueError("Decoded snapshot failed integrity validation")
    return value
