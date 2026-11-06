"""Recovery capabilities cannot recover guest identity, private snapshots or keys."""

import asyncio
import logging
import time

import pytest

from biomedmcp.contracts import Provenance
from biomedmcp.errors import ResearchError
from biomedmcp.provider_credentials import RequestCredentials, credential_context
from biomedmcp.recovery import EvidenceStore, parse_uri, resource_uri
from biomedmcp.runtime import ResultCache, anonymous_pagination, digest

RESOURCE = "https://public.example/mcp"
ALICE, BOB = "anonymous:alice", "anonymous:bob"


def store(cache=None, key=b"x" * 32):
    return EvidenceStore(cache or ResultCache(), signing_key=key)


async def issue(s, scope=ALICE):
    with anonymous_pagination(scope=scope, resource=RESOURCE):
        return await s.publish(
            {"rows": list(range(35)), "text": "α" * 4500},
            Provenance(evidence_id="ev_fixture", source="europepmc", content_hash=digest("fixture")),
            {},
            scope=scope,
        )


async def test_grant_recovers_exact_public_snapshot_without_cookie_and_retains_children():
    s = store()
    recovery = await issue(s)
    assert parse_uri(recovery["uri"])[0].startswith("public_")
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        root = await s.read(recovery["uri"], scope=BOB)
        rows = next(x["uri"] for x in root["children"] if x["field"] == "rows")
        result = await s.read(rows, scope=BOB)
        assert result["value"] == list(range(25))
        final = await s.read(result["next_uri"], scope=BOB)
        assert final["value"] == list(range(25, 35))
        text = next(x["uri"] for x in root["children"] if x["field"] == "text")
        part = await s.read(text, scope=BOB)
        rest = await s.read(part["next_uri"], scope=BOB)
        assert part["value"] + rest["value"] == "α" * 4500
    assert root["snapshot_sha256"] == recovery["snapshot_sha256"]
    assert "alice" not in recovery["uri"]


@pytest.mark.parametrize(
    "boundary", ["no_context", "resource", "account", "scope", "key", "signature", "expiry", "source"]
)
async def test_grant_boundaries_fail_closed(boundary, monkeypatch):
    from biomedmcp import recovery as module

    s = store()
    rec = await issue(s)
    uri, scope, resource = rec["uri"], BOB, RESOURCE
    if boundary == "resource":
        resource = "https://other.example/mcp"
    elif boundary == "account":
        scope = "account:alice"
    elif boundary == "scope":
        scope = "anonymous:outside-active-context"
    elif boundary == "key":
        s = store(s.cache, b"y" * 32)
    elif boundary == "signature":
        handle, pointer, start, count = parse_uri(uri)
        uri = resource_uri(handle[:-1] + ("a" if handle[-1] != "a" else "b"), pointer, start, count)
    elif boundary == "expiry":
        now = time.time()
        monkeypatch.setattr(module.time, "time", lambda: now + 601)
    availability = (lambda source: (False, "held")) if boundary == "source" else None
    if boundary == "no_context":
        with pytest.raises(ResearchError):
            await s.read(uri, scope=scope)
    else:
        with (
            anonymous_pagination(scope=BOB if boundary == "scope" else scope, resource=resource),
            pytest.raises(ResearchError),
        ):
            await s.read(uri, scope=scope, availability=availability)


async def test_private_and_byok_evidence_never_acquires_public_grant():
    s = store()
    private = await issue(s, "account:alice")
    assert not parse_uri(private["uri"])[0].startswith("public_")
    creds = RequestCredentials(
        partition="fixture",
        deadline=time.monotonic() + 30,
        values={},
        pacing={"ncbi": "ncbi", "openfda": "openfda"},
    )
    with credential_context(creds):
        byok = await issue(s)
    assert not parse_uri(byok["uri"])[0].startswith("public_")
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        for rec in (private, byok):
            with pytest.raises(ResearchError):
                await s.read(rec["uri"], scope=BOB)
    assert (await s.read(private["uri"], scope="account:alice"))["value"]["rows"] == list(range(25))


async def test_parallel_requests_and_replicas_keep_public_and_private_scopes_separate():
    cache = ResultCache()
    a, b = store(cache), store(cache)
    public, private = await asyncio.gather(issue(a), issue(a, "account:alice"))
    with anonymous_pagination(scope=BOB, resource=RESOURCE):
        assert (await b.read(public["uri"], scope=BOB))["value"]["rows"] == list(range(25))
        with pytest.raises(ResearchError):
            await b.read(private["uri"], scope=BOB)


def test_capability_is_redacted_in_logs_but_scientific_uris_remain_executable():
    from biomedmcp.logging_safety import install_log_redaction, redact_event

    grant = "public_" + "a" * 32 + "_" + "b" * 64
    assert grant not in str(redact_event(None, None, {"uri": resource_uri(grant)}))
    install_log_redaction()
    record = logging.getLogRecordFactory()(
        "test", logging.ERROR, __file__, 1, "%s", (resource_uri(grant),), None
    )
    assert grant not in record.getMessage()
    assert parse_uri(resource_uri(grant))[0] == grant
