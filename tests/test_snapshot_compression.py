"""Lossless compressed evidence, hostile framing and bounded worker lifecycle."""

import asyncio
import base64
import hashlib
import json
import threading
import time
import zlib

import pytest

from biomedmcp import recovery, snapshot_codec
from biomedmcp.contracts import Provenance
from biomedmcp.errors import ResearchError
from biomedmcp.recovery import EvidenceStore, Omissions, parse_uri, resource_uri
from biomedmcp.runtime import ResultCache, digest
from biomedmcp.snapshot_codec import VALUE_BYTES, VALUE_NODES
from biomedmcp.study_workers import StudyWorkers


def proof():
    return Provenance(evidence_id="ev_compression", source="protein-atlas", content_hash=digest("synthetic"))


async def publish(value, *, cache=None):
    from biomedmcp.evidence import bound

    store = EvidenceStore(cache or ResultCache())
    omitted = Omissions()
    bound(value, omissions=omitted)
    metadata = await store.publish(value, proof(), omitted.metadata(), scope="scope")
    assert metadata["snapshot_status"] == "available", metadata
    handle = parse_uri(metadata["uri"])[0]
    return store, metadata, store.key("scope", handle)


async def test_large_unicode_and_escaped_strings_round_trip_without_type_or_pointer_changes():
    text = 'αβ\\"🙂\n' * 80000
    original = {" spaced/~ ": text, "empty": [], "zero": 0, "missing": None}
    store, metadata, key = await publish(original)
    stored = await store.cache.get(key)
    assert stored["encoding"] == "zlib-json" and stored["value"] is None
    assert len(json.dumps(stored).encode()) <= recovery.SNAPSHOT_BYTES
    value = await store.read(metadata["omissions"][0]["uri"], scope="scope")
    assert value["pointer"] == "/ spaced~1~0 " and value["value"] == text[4000:8000]
    assert value["range"]["total"] == len(text) and value["evidence_ids"] == [proof().evidence_id]
    root = await store.read(metadata["uri"], scope="scope")
    assert root["value"]["empty"] == [] and root["value"]["zero"] == 0 and root["value"]["missing"] is None
    assert root["snapshot_sha256"] == stored["snapshot_sha256"]
    assert (
        root["value_sha256"]
        == hashlib.sha256(
            json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert root["value_sha256"] == metadata["value_sha256"]


async def test_compression_does_not_enlarge_storage_or_decoding_grants():
    store, _, key = await publish({"text": "x" * 2_000_000})
    stored = await store.cache.get(key)
    assert stored["value_utf8_bytes"] > recovery.SNAPSHOT_BYTES
    assert len(json.dumps(stored).encode()) < recovery.SNAPSHOT_BYTES
    too_large = await store.publish({"text": "x" * VALUE_BYTES}, proof(), {}, scope="scope")
    assert too_large["reason"] == "snapshot_decoded_byte_budget" and "uri" not in too_large
    import random

    random_text = random.Random(493).randbytes(1_100_000).hex()
    incompressible = await store.publish({"text": random_text}, proof(), {}, scope="scope")
    assert incompressible["reason"] == "snapshot_byte_budget" and "uri" not in incompressible
    small, _, small_key = await publish({"text": "fixture"})
    assert (await small.cache.get(small_key))["encoding"] == "json"


@pytest.mark.parametrize(
    "attack",
    [
        "base64",
        "zlib",
        "truncated",
        "trailing",
        "concatenated",
        "decoded_size",
        "decoded_hash",
        "bomb",
        "deep_json",
        "many_nodes",
        "duplicate_keys",
        "nonfinite",
        "dual_encoding",
    ],
)
async def test_corrupt_or_hostile_compressed_snapshots_fail_with_controlled_errors(attack):
    store, metadata, key = await publish({"text": "x" * 500000})
    stored = await store.cache.get(key)
    packed = base64.b64decode(stored["encoded_value"])
    raw = zlib.decompress(packed)
    if attack == "base64":
        stored["encoded_value"] = "invalid*base64-synthetic-sentinel"
    elif attack == "zlib":
        stored["encoded_value"] = base64.b64encode(b"synthetic-untrusted-sentinel").decode()
    elif attack in {"truncated", "trailing", "concatenated"}:
        packed = (
            packed[:-1] if attack == "truncated" else packed + (b"tail" if attack == "trailing" else packed)
        )
        stored["encoded_value"] = base64.b64encode(packed).decode()
    elif attack == "decoded_size":
        stored["value_utf8_bytes"] -= 1
    elif attack == "decoded_hash":
        stored["value_sha256"] = "0" * 64
    elif attack == "dual_encoding":
        stored["value"] = {"text": "different data"}
    else:
        raw = {
            "bomb": b'"' + b"x" * (VALUE_BYTES + 1) + b'"',
            "deep_json": b"[" * 2000 + b"0" + b"]" * 2000,
            "many_nodes": b"[" + b"0," * (VALUE_NODES * 3) + b"0]",
            "duplicate_keys": b'{"x":1,"x":2}',
            "nonfinite": b'{"x":NaN}',
        }[attack]
        stored["encoded_value"] = base64.b64encode(zlib.compress(raw)).decode()
        stored["value_utf8_bytes"] = min(len(raw), VALUE_BYTES)
        stored["value_sha256"] = hashlib.sha256(raw).hexdigest()
    # Rehash the envelope to exercise inner framing/hash/resource guards too.
    stored["snapshot_sha256"] = digest({k: v for k, v in stored.items() if k != "snapshot_sha256"})
    await store.cache.put(key, stored, 60)
    with pytest.raises(ResearchError) as caught:
        await store.read(metadata["uri"], scope="scope")
    assert caught.value.code == "evidence_invalid_data"
    assert "synthetic-untrusted-sentinel" not in str(caught.value)


async def test_compressed_snapshot_sanitation_precedes_storage_and_source_access_precedes_decode(monkeypatch):
    monkeypatch.setenv("NCI_API_KEY", "synthetic-compressed-credential")
    store, metadata, _ = await publish(
        {
            "text": "x" * 500000 + "synthetic-compressed-credential",
            "password": "another-credential",
            "url": "file:///private/key",
        }
    )
    assert metadata["redacted"]
    root = await store.read(metadata["uri"], scope="scope")
    assert "synthetic-compressed-credential" not in json.dumps(root)
    assert root["value"]["url"] is None and root["value"]["password"] == "[REDACTED]"
    selected = await store.read(
        resource_uri(parse_uri(metadata["uri"])[0], "/text", 500000, 4000), scope="scope"
    )
    assert selected["value"] == "[REDACTED]"

    def forbidden(_):
        pytest.fail("Unavailable source was decompressed")

    monkeypatch.setattr(recovery, "unpack", forbidden)
    with pytest.raises(ResearchError) as caught:
        await store.read(metadata["uri"], scope="scope", availability=lambda _: (False, "disabled"))
    assert caught.value.code == "source_access_denied"
    with pytest.raises(ResearchError) as caught:
        await store.read(metadata["uri"], scope="different")
    assert caught.value.code == "evidence_unavailable"


async def test_snapshot_worker_cancellation_keeps_permit_until_real_completion(monkeypatch):
    pool = StudyWorkers(workers=1, max_pending=1, thread_name="ubi-evidence-test")
    entered, release = threading.Event(), threading.Event()
    original = recovery.pack

    def blocked(value):
        entered.set()
        assert release.wait(3)
        return original(value)

    monkeypatch.setattr(recovery, "workers", pool)
    monkeypatch.setattr(recovery, "pack", blocked)
    store = EvidenceStore(ResultCache())
    task = asyncio.create_task(store.publish({"text": "x" * 500000}, proof(), {}, scope="scope"))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.pending == 1
        busy = await store.publish({"text": "other"}, proof(), {}, scope="scope")
        assert busy["reason"] == "snapshot_worker_unavailable"
    finally:
        release.set()
        await asyncio.to_thread(pool.close)
    assert pool.pending == 0


async def test_expiry_during_decoding_is_enforced(monkeypatch):
    store, metadata, _ = await publish({"text": "x" * 500000})
    original = recovery.unpack

    def expired(snapshot):
        value = original(snapshot)
        snapshot.expires_at = time.time() - 1
        return value

    monkeypatch.setattr(recovery, "unpack", expired)
    with pytest.raises(ResearchError) as caught:
        await store.read(metadata["uri"], scope="scope")
    assert caught.value.code == "evidence_unavailable"


async def test_closed_codec_pool_is_a_recovery_failure_without_destroying_scientific_evidence(monkeypatch):
    store, metadata, _ = await publish({"text": "x" * 500000})
    pool = StudyWorkers(workers=1, thread_name="ubi-evidence-closed")
    pool.close()
    monkeypatch.setattr(recovery, "workers", pool)
    failed = await store.publish({"text": "new evidence"}, proof(), {}, scope="scope")
    assert failed["reason"] == "snapshot_worker_unavailable" and "uri" not in failed
    with pytest.raises(ResearchError) as caught:
        await store.read(metadata["uri"], scope="scope")
    assert caught.value.code == "evidence_unavailable" and caught.value.retryable


def test_encoded_json_guard_checks_structure_before_json_allocation(monkeypatch):
    for raw in [b"[" * 2000, b"[" + b"0," * (VALUE_NODES * 3) + b"0]"]:
        with pytest.raises(ValueError):
            snapshot_codec.json_shape(raw)
    # Source prose can contain brackets/quotes without consuming structural grants.
    snapshot_codec.json_shape(json.dumps({"text": '[]{}\\"' * 200000}).encode())
