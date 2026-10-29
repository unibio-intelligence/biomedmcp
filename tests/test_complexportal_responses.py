"""Selected Complex Portal search contracts and actual MCP membership recovery."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from complexportal_helpers import IDENTITY, body, complex_row
from interpro_helpers import protein
from native_helpers import HTTP

from biomedmcp.contracts import GetRequest
from biomedmcp.errors import ResearchError
from biomedmcp.native.complexportal import Continuation, acquire, protein_identity


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        "bad",
        {"error": "credential-sentinel"},
        {"success": False},
        {"elements": []},
        body([]) | {"size": False},
        body([]) | {"size": "0"},
        body([]) | {"totalNumberOfResults": -1},
        body([]) | {"totalNumberOfResults": True},
        body([]) | {"totalNumberOfResults": 1},
        body() | {"size": 0},
        body() | {"elements": None},
        body() | {"elements": {}},
        body() | {"totalNumberOfResults": 0},
    ],
)
async def test_malformed_envelopes_are_not_healthy_empty(value):
    with pytest.raises(ResearchError) as failure:
        await acquire(HTTP(value), IDENTITY)
    assert failure.value.code == "invalid_source_response"
    assert "credential-sentinel" not in str(failure.value)


@pytest.mark.parametrize(
    "path,value",
    [
        (("complexAC",), "CPX-0"),
        (("complexAC",), "CPX-x"),
        (("complexName",), ""),
        (("predictedComplex",), None),
        (("predictedComplex",), "false"),
        (("organismName",), "Homo sapiens"),
        (("organismName",), []),
        (("organismName",), "Species; -2"),
        (("description",), []),
        (("interactors",), None),
        (("interactors",), []),
        (("interactors",), [{}]),
        (("interactors", 0, "identifier"), None),
        (("interactors", 0, "interactorType"), ""),
        (("interactors", 0, "organismName"), "Species; 0"),
        (("interactors", 0, "organismName"), 9606),
        (("interactors", 0, "stochiometry"), {}),
    ],
)
async def test_partial_nested_shapes_fail_the_window(path, value):
    row = complex_row()
    node = row
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ResearchError) as failure:
        await acquire(HTTP(body([row])), IDENTITY)
    assert failure.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "row",
    [
        None,
        [],
        {},
        complex_row() | {"ignored_value": float("nan")},
        complex_row() | {"error": "credential-sentinel"},
    ],
)
async def test_invalid_row_after_valid_member_does_not_cache_partial_bad_response(row):
    with pytest.raises(ResearchError) as failure:
        await acquire(HTTP(body([complex_row(), row])), IDENTITY)
    assert failure.value.code == "invalid_source_response"


async def test_exact_membership_hash_locator_and_unparsed_stoichiometry():
    row = complex_row()
    row["interactors"].append(
        {
            "identifier": "CHEBI:123",
            "interactorType": "small molecule",
            "organismName": "chemical synthesis; -2",
            "stochiometry": None,
        }
    )
    row["interactors"][0]["identifierLink"] = "https://exfil.invalid/instructions"
    result = await acquire(HTTP(body([row])), IDENTITY)
    item = result["records"][0]
    assert (
        item["source_record_sha256"]
        == hashlib.sha256(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    )
    assert item["source_locator"] == "/elements/0"
    assert item["matching_participants"] == [
        {
            "identifier": "P15056",
            "species": 9606,
            "stoichiometry_raw": "minValue: 1, maxValue: 1",
            "source_locator": "/elements/0/interactors/0",
        }
    ]
    assert (
        item["source_release"] is None and item["experimental_binding"] == "not_assessed_from_search_summary"
    )
    assert item["predicted_by_source"] is False and "identifierLink" not in str(result)
    assert item["source_url"] == "https://www.ebi.ac.uk/complexportal/complex/CPX-1"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"identifier": "P04637"}, "no_exact_member"),
        ({"identifier": "P15056-2"}, "isoform_candidate"),
        ({"taxon": None}, "unknown_species"),
        ({"participant_taxon": None}, "unknown_species"),
        ({"taxon": 10090}, "wrong_complex_species"),
        ({"participant_taxon": 10090}, "wrong_participant_species"),
    ],
)
async def test_description_taxon_and_isoform_are_not_exact_membership(kwargs, reason):
    value = await acquire(HTTP(body([complex_row(**kwargs)])), IDENTITY)
    assert value["records"] == [] and value["coverage"]["filtering"][reason] == 1
    if reason in {"unknown_species", "isoform_candidate"}:
        assert value["section_outcomes"]["complexportal"]["outcome"] == "partial"
        assert value["unqualified_candidates"][0]["reason"] == reason


async def test_explicit_empty_requires_valid_source_counts():
    result = await acquire(HTTP(body([])), IDENTITY)
    assert result["records"] == [] and result["protein_identity"] == IDENTITY
    assert result["_provider_page"]["exhausted"] is True
    assert result["coverage"]["source_query_total"] == 0


async def test_filtered_duplicate_windows_preserve_raw_offsets_and_later_membership():
    http = HTTP(
        body([complex_row(identifier="P04637")], total=3),
        body([complex_row(identifier="P04637")], total=3),
        body([complex_row(complex_id="CPX-2")], total=3),
    )
    state = None
    windows = []
    for _ in range(3):
        value = await acquire(http, IDENTITY, limit=1, state=state)
        windows.append(value)
        state = value["_complexportal_state"]
    assert [call[2]["params"] for call in http.calls] == [{"first": i, "number": 1} for i in range(3)]
    assert windows[0]["records"] == windows[1]["records"] == []
    assert windows[1]["coverage"]["filtering"]["duplicates"] == 1
    assert windows[2]["records"][0]["complex_id"] == "CPX-2"
    assert windows[2]["section_outcomes"]["complexportal"]["outcome"] == "partial"
    assert windows[2]["_provider_page"]["exhausted"] is True


async def test_source_total_and_sequence_drift_require_restart():
    initial = await acquire(HTTP(body(total=3)), IDENTITY)
    with pytest.raises(ResearchError) as failure:
        await acquire(
            HTTP(body([complex_row(complex_id="CPX-2")], total=4)),
            IDENTITY,
            state=initial["_complexportal_state"],
        )
    assert failure.value.code == "source_version_changed"
    http = HTTP()
    with pytest.raises(ResearchError) as failure:
        await acquire(http, IDENTITY | {"sequence_sha256": "b" * 64}, state=initial["_complexportal_state"])
    assert failure.value.code == "identity_mismatch" and http.calls == []


@pytest.mark.parametrize(
    "change", ["empty", "many", "accession", "species", "taxon_type", "sequence", "length"]
)
def test_unverified_uniprot_identity_cannot_anchor_absence(change):
    row = protein()
    value = {"results": [row]}
    if change == "empty":
        value["results"] = []
    if change == "many":
        value["results"] = [row, row]
    if change == "accession":
        row["primaryAccession"] = "P04637"
    if change == "species":
        row["organism"]["taxonId"] = 10090
    if change == "taxon_type":
        row["organism"]["taxonId"] = "9606"
    if change == "sequence":
        row["sequence"]["value"] = ""
    if change == "length":
        row["sequence"]["length"] -= 1
    with pytest.raises(ResearchError):
        protein_identity(value, "P15056", 9606)


async def test_retained_cc0_observation_excludes_six_description_only_hits():
    raw = (Path(__file__).parent / "fixtures/complexportal-p15056-2026-10-11.json").read_bytes()
    manifest = json.loads(
        (Path(__file__).parent / "fixtures/complexportal-observation-2026-10-11.json").read_text()
    )
    assert hashlib.sha256(raw).hexdigest() == manifest["sha256"]
    value = await acquire(HTTP(json.loads(raw)), IDENTITY)
    assert value["coverage"]["source_query_total"] == 18
    assert value["coverage"]["filtering"]["no_exact_member"] == 6
    assert len(value["records"]) == 12 and all(x["species"] == 9606 for x in value["records"])
    assert "CPX-26353" not in {x["complex_id"] for x in value["records"]}
    assert "CPX-12671" in {x["complex_id"] for x in value["records"]}
    assert all(x["experimental_binding"] == "not_assessed_from_search_summary" for x in value["records"])


@pytest.fixture
async def mcp_boundary(monkeypatch):
    import httpx
    from fastmcp import Client

    from biomedmcp import transport
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    responses, calls = [], []
    current_protein = protein()

    def handler(request):
        calls.append(request)
        if request.url.host == "rest.uniprot.org":
            return httpx.Response(
                200,
                json=deepcopy(current_protein)
                if request.url.path.endswith("P15056")
                else {"results": [deepcopy(current_protein)]},
            )
        assert request.url.host == "www.ebi.ac.uk"
        assert request.url.path == "/intact/complex-ws/search/P15056"
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        yield client, responses, calls, service, current_protein


GET = {
    "entity": "protein",
    "id": "P15056",
    "sections": ["complexes"],
    "sources": ["complexportal", "uniprot"],
}


async def test_actual_mcp_invalid_source_uncached_valid_source_cached(mcp_boundary):
    client, responses, calls, _, _ = mcp_boundary
    responses.extend([{}, body()])
    failed = (await client.call_tool_mcp("get", GET)).structured_content
    assert (
        failed["sections"]["complexes"]["error"]["code"] == "invalid_source_response"
        and failed["provenance"] == []
    )
    good = (await client.call_tool_mcp("get", GET)).structured_content
    assert good["outcome"] == "data" and good["provenance"][0]["sources"] == ["complexportal", "uniprot"]
    assert good["sections"]["complexes"]["data"]["records"][0]["record_type"] == "complex_membership"
    assert "_complexportal_state" not in str(good)
    cached = (await client.call_tool_mcp("get", GET)).structured_content
    assert cached["provenance"][0]["cached"] is True
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 2


async def test_actual_mcp_filtered_and_duplicate_pages_are_executable(mcp_boundary):
    client, responses, calls, service, _ = mcp_boundary
    responses.extend(
        [
            body([complex_row(identifier="P04637")], total=3),
            body([complex_row(identifier="P04637")], total=3),
            body([complex_row(complex_id="CPX-2")], total=3),
        ]
    )
    request = GET | {"section_parameters": {"complexes": {"limit": 1}}}
    first = (await client.call_tool_mcp("get", request)).structured_content
    assert first["outcome"] == "partial" and first["sections"]["complexes"]["data"]["records"] == []
    action = first["next_actions"][0]
    for change in [
        {"id": "P04637"},
        {"species": 10090},
        {"freshness": "fresh"},
        {
            "section_parameters": {
                "complexes": {
                    "limit": 2,
                    "cursor": action["arguments"]["section_parameters"]["complexes"]["cursor"],
                }
            }
        },
    ]:
        with pytest.raises(ResearchError):
            await service.get(GetRequest(**(action["arguments"] | change)), scope="local")
    with pytest.raises(ResearchError):
        await service.get(GetRequest(**action["arguments"]), scope="other")
    second = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert second["outcome"] == "partial" and second["next_actions"]
    last = second["next_actions"][0]
    third = (await client.call_tool_mcp(last["tool"], last["arguments"])).structured_content
    assert third["next_actions"] == [] and third["outcome"] == "partial"
    assert third["sections"]["complexes"]["data"]["records"][0]["complex_id"] == "CPX-2"
    assert [int(r.url.params["first"]) for r in calls if r.url.host == "www.ebi.ac.uk"] == [0, 1, 2]


@pytest.mark.parametrize("failure", ["connect", "json", 401, 403, 404, 429, 503, "shape"])
async def test_actual_mcp_source_failure_retains_successful_peer_and_is_not_cached(mcp_boundary, failure):
    import httpx

    client, responses, calls, _, _ = mcp_boundary
    bad = (
        {}
        if failure == "shape"
        else httpx.ConnectError("credential-sentinel")
        if failure == "connect"
        else httpx.Response(200 if failure == "json" else failure, text="credential-sentinel")
    )
    responses.extend([bad, bad])
    for _ in range(2):
        value = (
            await client.call_tool_mcp("get", GET | {"sections": ["record", "complexes"]})
        ).structured_content
        assert value["outcome"] == "partial" and value["sections"]["record"]["outcome"] == "data"
        assert value["sections"]["complexes"]["outcome"] in {"error", "unavailable"}
        assert len(value["provenance"]) == 1 and value["provenance"][0]["sources"] == ["uniprot"]
        assert "credential-sentinel" not in str(value)
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 2


@pytest.mark.parametrize("mutation", ["missing", "offset", "total", "seen", "duplicate", "sequence", "extra"])
async def test_actual_mcp_invalid_or_expired_cursor_state_fails_before_http(mcp_boundary, mutation):
    from biomedmcp.runtime import digest

    client, responses, calls, service, _ = mcp_boundary
    responses.append(body(total=3))
    first = (await client.call_tool_mcp("get", GET)).structured_content
    action = first["next_actions"][0]
    cursor = action["arguments"]["section_parameters"]["complexes"]["cursor"]
    key = "complexportal-page:" + digest(cursor)
    state = await service.runtime.cache.get(key)
    if mutation == "missing":
        service.runtime.cache.values.pop(key)
    else:
        if mutation == "offset":
            state["offset"] = True
        if mutation == "total":
            state["total"] = 1
        if mutation == "seen":
            state["seen"] = [{}]
        if mutation == "duplicate":
            state["seen"] = ["CPX-1", "CPX-1"]
        if mutation == "sequence":
            state["sequence_sha256"] = "bad"
        if mutation == "extra":
            state["extra"] = 2
        await service.runtime.cache.put(key, state, 3600)
    before = len(calls)
    value = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert value["outcome"] == "error" and value["error"]["code"] == (
        "expired_cursor" if mutation == "missing" else "cache_invalid_data"
    )
    assert len(calls) == before


async def test_actual_mcp_mouse_membership_and_action_preserve_species(mcp_boundary):
    client, responses, _, _, current_protein = mcp_boundary
    current_protein["organism"]["taxonId"] = 10090
    responses.extend(
        [
            body([complex_row(taxon=10090, participant_taxon=10090)], total=2),
            body([complex_row(complex_id="CPX-2", taxon=10090, participant_taxon=10090)], total=2),
        ]
    )
    value = (await client.call_tool_mcp("get", GET | {"species": 10090})).structured_content
    assert (
        value["outcome"] == "partial"
        and value["sections"]["complexes"]["data"]["records"][0]["species"] == 10090
    )
    action = value["next_actions"][0]
    assert action["arguments"]["species"] == 10090
    resumed = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert resumed["sections"]["complexes"]["data"]["protein_identity"]["species"] == 10090


@pytest.mark.parametrize(
    "arguments",
    [
        GET | {"id": "BRAF"},
        GET | {"id": "P15056-2"},
        GET | {"sources": ["complexportal"]},
        GET | {"section_parameters": {"complexes": {"limit": True}}},
        GET | {"section_parameters": {"complexes": {"limit": 26}}},
        GET | {"section_parameters": {"complexes": {"page": 1}}},
    ],
)
async def test_actual_mcp_invalid_plan_fails_before_provider_io(mcp_boundary, arguments):
    client, _, calls, _, _ = mcp_boundary
    value = (await client.call_tool_mcp("get", arguments)).structured_content
    assert value["outcome"] == "error" and calls == []


async def test_actual_mcp_final_scan_window_preserves_unassessed_remainder(mcp_boundary):
    from biomedmcp.runtime import digest

    client, responses, calls, service, _ = mcp_boundary
    request = GetRequest(**GET)
    cursor = service.runtime.cursors.encode(
        query=Continuation.binding(request, 25), scope="local", offset=999
    )
    await service.runtime.cache.put(
        "complexportal-page:" + digest(cursor),
        {"offset": 999, "seen": ["CPX-1"], "total": 1001, "sequence_sha256": IDENTITY["sequence_sha256"]},
        3600,
    )
    responses.append(body([complex_row(complex_id="CPX-2")], total=1001))
    value = (
        await client.call_tool_mcp("get", GET | {"section_parameters": {"complexes": {"cursor": cursor}}})
    ).structured_content
    data = value["sections"]["complexes"]["data"]
    assert value["outcome"] == "partial" and value["next_actions"] == []
    assert data["coverage"]["continuation_status"] == "scan_limit" and data["records"]
    assert calls[-1].url.params["first"] == "999" and calls[-1].url.params["number"] == "1"


async def test_actual_mcp_state_write_failure_keeps_evidence_and_partial_coverage(mcp_boundary, monkeypatch):
    client, responses, _, service, _ = mcp_boundary
    original = service.runtime.cache.put

    async def put(key, value, ttl):
        if key.startswith("complexportal-page:"):
            raise ResearchError("cache_unavailable", "Storage unavailable")
        return await original(key, value, ttl)

    monkeypatch.setattr(service.runtime.cache, "put", put)
    responses.append(body(total=2))
    value = (await client.call_tool_mcp("get", GET)).structured_content
    assert value["outcome"] == "partial" and value["next_actions"] == []
    assert value["sections"]["complexes"]["data"]["records"]
    assert value["sections"]["complexes"]["data"]["coverage"]["continuation_status"] == "storage_unavailable"


def test_actual_cli_complex_cursor_survives_process_restart(tmp_path):
    import os
    import subprocess
    import sys

    from synthetic_permissions import BOOTSTRAP

    script = tmp_path / "complex_cli.py"
    log = tmp_path / "calls.jsonl"
    script.write_text(
        BOOTSTRAP
        + "\nimport httpx, json, os\nfrom biomedmcp import transport\noriginal=httpx.AsyncClient\nprotein="
        + repr(protein())
        + "\nrows="
        + repr([complex_row(identifier="P04637"), complex_row(complex_id="CPX-2")])
        + """
def handler(request):
    if request.url.host == "rest.uniprot.org":
        return httpx.Response(200, json=protein if request.url.path.endswith("P15056") else {"results":[protein]})
    assert request.url.host == "www.ebi.ac.uk"
    offset=int(request.url.params["first"])
    with open(os.environ["COMPLEX_CALL_LOG"], "a") as stream:
        stream.write(json.dumps({"first":offset,"number":int(request.url.params["number"])}) + "\\n")
    return httpx.Response(200, json={"size":1,"totalNumberOfResults":2,"elements":[rows[offset]]})
transport.AsyncClient=lambda **kw: original(transport=httpx.MockTransport(handler))
from biomedmcp.cli import main
main()
"""
    )
    env = dict(
        os.environ,
        UBI_PROFILE="local",
        UBI_LOCAL_STATE_DIR=str(tmp_path / "state"),
        COMPLEX_CALL_LOG=str(log),
    )
    env.pop("UBI_CURSOR_KEY", None)

    def run(arguments):
        result = subprocess.run(
            [sys.executable, str(script), "get", json.dumps(arguments)],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    first = run(GET | {"section_parameters": {"complexes": {"limit": 1}}})
    assert first["sections"]["complexes"]["data"]["records"] == []
    second = run(first["next_actions"][0]["arguments"])
    assert second["sections"]["complexes"]["data"]["records"][0]["complex_id"] == "CPX-2"
    assert second["next_actions"] == []
    assert [json.loads(x) for x in log.read_text().splitlines()] == [
        {"first": 0, "number": 1},
        {"first": 1, "number": 1},
    ]


@pytest.mark.parametrize("change", ["sequence", "total"])
async def test_actual_mcp_continuation_drift_requires_restart(mcp_boundary, change):
    client, responses, calls, _, current_protein = mcp_boundary
    responses.append(body(total=3))
    first = (await client.call_tool_mcp("get", GET)).structured_content
    action = first["next_actions"][0]
    if change == "sequence":
        current_protein["sequence"]["value"] = "A" * 766
    else:
        responses.append(body([complex_row(complex_id="CPX-2")], total=4))
    before = len([r for r in calls if r.url.host == "www.ebi.ac.uk"])
    value = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert value["sections"]["complexes"]["error"]["code"] == (
        "identity_mismatch" if change == "sequence" else "source_version_changed"
    )
    assert value["provenance"] == []
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == before + (change == "total")


@pytest.mark.parametrize("taxon", [9606, None])
async def test_actual_mcp_empty_and_unknown_membership_have_distinct_outcomes(mcp_boundary, taxon):
    client, responses, _, _, _ = mcp_boundary
    responses.append(body([]) if taxon == 9606 else body([complex_row(taxon=None)]))
    value = (await client.call_tool_mcp("get", GET)).structured_content
    assert value["outcome"] == ("empty" if taxon == 9606 else "partial")
    assert value["sections"]["complexes"]["data"]["records"] == []
    assert value["provenance"][0]["sources"] == ["complexportal", "uniprot"]
