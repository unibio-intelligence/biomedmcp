"""Observed unknown coordinates remain unknown through validation and recovery."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from uniprot_mcp.shapes import feature, protein

from biomedmcp import transport
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt

FIXTURE = Path(__file__).parent / "fixtures/uniprot-P02751-projected-2026-10-12.json"


def observed():
    raw = FIXTURE.read_bytes()
    provenance = json.loads(FIXTURE.with_name(FIXTURE.stem + "-provenance.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == provenance["fixture_sha256"]
    assert provenance["license"] == "CC-BY-4.0"
    return json.loads(raw)


def test_observed_projection_accepts_null_unknown_without_fabricating_a_coordinate():
    row = observed()
    before = deepcopy(row)
    protein(row, expected="P02751", require_sequence=True)
    assert row == before
    assert row["features"][5]["location"]["end"] == {"value": None, "modifier": "UNKNOWN"}
    assert len(row["features"]) == 444
    assert len(row["sequence"]["value"]) == row["sequence"]["length"] == 2477


@pytest.mark.parametrize("side", ["start", "end"])
@pytest.mark.parametrize("point", [{"modifier": "UNKNOWN"}, {"value": None, "modifier": "UNKNOWN"}])
def test_unknown_endpoint_encodings_are_preserved(side, point):
    row = {"type": "Chain", "location": {"start": {"value": 1}, "end": {"value": 10}}}
    row["location"][side] = point
    before = deepcopy(row)
    feature(row)
    assert row == before


@pytest.mark.parametrize(
    "point",
    [
        {"value": None, "modifier": "EXACT"}, {"value": None},
        {"value": 0, "modifier": "EXACT"}, {"value": True, "modifier": "EXACT"},
        {"value": "723", "modifier": "EXACT"}, {"modifier": "EXACT"},
        {"value": [], "modifier": "UNKNOWN"}, {},
    ],
)
def test_missing_or_malformed_known_positions_are_still_invalid(point):
    with pytest.raises(ResearchError) as caught:
        feature({"type": "Chain", "location": {"start": {"value": 1}, "end": point}})
    assert caught.value.code == "invalid_source_response"


async def test_actual_public_mcp_recovers_all_observed_features_from_one_acquisition(monkeypatch):
    payload = observed()
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "rest.uniprot.org" and request.url.path == "/uniprotkb/P02751"
        assert "sequence" in request.url.params["fields"].split(",")
        return httpx.Response(200, json=payload, headers={"x-uniprot-release": "2026_03"})

    monkeypatch.setattr(transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService())) as client:
        response = await client.call_tool_mcp(
            "get", {"entity": "protein", "id": "P02751", "sections": ["record"], "sources": ["uniprot"]}
        )
        assert not response.is_error
        result = response.structured_content
        assert verify_receipt(result)
        section = result["sections"]["record"]
        assert section["data"]["sequence"] == payload["sequence"]
        assert len(section["data"]["features"]) == 25
        omission = next(o for o in section["recovery"]["omissions"] if o["pointer"] == "/features")
        complete = list(section["data"]["features"])
        uri = omission["uri"]
        reads = 0
        while uri:
            recovered = json.loads((await client.read_resource(uri))[0].text)
            assert recovered["evidence_ids"] == section["evidence_ids"]
            complete.extend(recovered["value"])
            uri = recovered["next_uri"]
            reads += 1
            assert reads < 30
    assert complete == payload["features"]
    assert complete[5]["location"]["end"]["value"] is None
    assert len(calls) == 1 and 0 < reads < 17


async def test_bad_known_endpoint_is_not_cached_as_empty_and_valid_source_can_retry(monkeypatch):
    valid = observed()
    invalid = deepcopy(valid)
    invalid["features"][5]["location"]["end"]["modifier"] = "EXACT"
    state = {"payload": invalid, "calls": 0}
    original = httpx.AsyncClient

    def handler(request):
        state["calls"] += 1
        return httpx.Response(200, json=state["payload"], headers={"x-uniprot-release": "2026_03"})

    monkeypatch.setattr(transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("UBI_PROFILE", "local")
    arguments = {"entity": "protein", "id": "P02751", "sections": ["record"], "sources": ["uniprot"]}
    async with Client(create_server(service=ResearchService())) as client:
        failed = await client.call_tool_mcp("get", arguments)
        assert failed.is_error
        assert failed.structured_content["sections"]["record"]["error"]["code"] == "invalid_source_response"
        assert failed.structured_content["outcome"] == "error" and not failed.structured_content["provenance"]
        state["payload"] = valid
        repaired = await client.call_tool_mcp("get", arguments)
        assert not repaired.is_error and repaired.structured_content["sections"]["record"]["data"]
        cached = await client.call_tool_mcp("get", arguments)
        assert not cached.is_error
    assert state["calls"] == 2
