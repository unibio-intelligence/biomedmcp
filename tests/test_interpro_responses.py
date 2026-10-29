"""Selected InterPro response contracts, source identity and residue semantics."""

from copy import deepcopy

import pytest
from interpro_helpers import IDENTITY, body, entry, response
from native_helpers import HTTP

from biomedmcp.errors import ResearchError
from biomedmcp.native.interpro import acquire, overlaps


@pytest.mark.parametrize(
    "value",
    [
        {},
        None,
        [],
        "broken",
        {"error": "interpro-secret-sentinel"},
        {"results": []},
        {"count": 0, "results": None, "next": None, "previous": None},
        {"count": "0", "results": [], "next": None, "previous": None},
        {"count": False, "results": [], "next": None, "previous": None},
        {"count": 1, "results": [], "next": None, "previous": None},
    ],
)
async def test_invalid_collections_never_become_empty(value):
    with pytest.raises(ResearchError) as error:
        await acquire(HTTP(response() | {"body": value}), IDENTITY)
    assert error.value.code == "invalid_source_response"
    assert "interpro-secret-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "path,value",
    [
        (("metadata",), None),
        (("metadata", "accession"), "IPR1"),
        (("metadata", "type"), "unknown"),
        (("metadata", "source_database"), "pfam"),
        (("metadata", "name"), ""),
        (("metadata", "go_terms"), {}),
        (("metadata", "go_terms", 0, "identifier"), "GO:broken"),
        (("metadata", "go_terms", 0, "category"), None),
        (("metadata", "member_databases"), []),
        (("metadata", "member_databases", "pfam"), []),
        (("proteins",), []),
        (("proteins", 0, "accession"), "P04637"),
        (("proteins", 0, "organism"), "10090"),
        (("proteins", 0, "organism"), 9606),
        (("proteins", 0, "protein_length"), 765),
        (("proteins", 0, "protein_length"), True),
        (("proteins", 0, "in_alphafold"), "true"),
        (("proteins", 0, "source_database"), "unknown"),
        (("proteins", 0, "entry_protein_locations"), []),
        (("proteins", 0, "entry_protein_locations", 0, "fragments"), []),
        (("proteins", 0, "entry_protein_locations", 0, "representative"), "false"),
        (("proteins", 0, "entry_protein_locations", 0, "score"), float("nan")),
        (("proteins", 0, "entry_protein_locations", 0, "model"), {}),
        (("proteins", 0, "entry_protein_locations", 0, "fragments", 0, "start"), 0),
        (("proteins", 0, "entry_protein_locations", 0, "fragments", 0, "start"), "457"),
        (("proteins", 0, "entry_protein_locations", 0, "fragments", 0, "end"), 767),
        (("proteins", 0, "entry_protein_locations", 0, "fragments", 0, "end"), 456),
        (("proteins", 0, "entry_protein_locations", 0, "fragments", 0, "dc-status"), "unknown"),
    ],
)
async def test_partial_nested_identity_and_coordinates_are_failure(path, value):
    row = entry()
    node = row
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ResearchError) as error:
        await acquire(HTTP(response(body([row]))), IDENTITY)
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "link",
    [
        "https://exfil.invalid/?cursor=key&page_size=25",
        "http://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?cursor=key&page_size=25",
        "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P04637/?cursor=key&page_size=25",
        "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?cursor=&page_size=25",
        "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?cursor=key&page_size=2",
        "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?cursor=key&page_size=25&search=other",
        "https://www.ebi.ac.uk/interpro/api/entry/interpro/protein/uniprot/P15056/?cursor=key&cursor=other&page_size=25",
    ],
)
async def test_next_links_cannot_change_host_identity_or_request(link):
    value = body(count=2, after="NEXT") | {"next": link}
    with pytest.raises(ResearchError):
        await acquire(HTTP(response() | {"body": value}), IDENTITY)


async def test_populated_and_explicit_empty_projection():
    http = HTTP(response(), response(body([])), response(status=204))
    populated = await acquire(http, IDENTITY)
    assert populated["records"][0]["metadata"] == {
        "accession": "IPR000719",
        "name": "Synthetic entry",
        "type": "domain",
        "source_database": "interpro",
    }
    assert (
        populated["records"][0]["proteins"][0]["entry_protein_locations"][0]["fragments"]
        == entry()["proteins"][0]["entry_protein_locations"][0]["fragments"]
    )
    assert populated["source_release"] == "110.0"
    for _ in range(2):
        empty = await acquire(http, IDENTITY)
        assert empty["records"] == [] and empty["coverage"]["complete"] is True
        assert empty["coverage"]["total_entries"] == 0


async def test_continuation_sequential_and_scope_qualified():
    http = HTTP(
        response(body(count=2, after="NEXT")), response(body([entry(accession="IPR001245")], count=2))
    )
    first = await acquire(http, IDENTITY)
    second = await acquire(
        http,
        IDENTITY,
        after=first["_provider_page"]["continuation"],
        scanned=1,
        total=2,
        release="110.0",
        seen=["IPR000719"],
    )
    assert second["_provider_page"]["exhausted"] is True
    assert http.calls[1][2]["params"] == {"page_size": 25, "cursor": "NEXT"}
    assert first["section_outcomes"]["interpro"]["outcome"] == "partial"


@pytest.mark.parametrize(
    "change,code",
    [
        ("release", "source_contract_changed"),
        ("total", "source_contract_changed"),
        ("replay", "invalid_source_response"),
        ("empty", "invalid_source_response"),
        ("204", "invalid_source_response"),
    ],
)
async def test_continuation_drift_and_nonadvancement_are_not_absence(change, code):
    value = response(body([entry(accession="IPR001245")], count=2))
    if change == "release":
        value["headers"]["interpro-version"] = "111.0"
    if change == "total":
        value["body"]["count"] = 3
        value["body"]["next"] = body(count=3, after="AFTER")["next"]
    if change == "replay":
        value["body"]["results"] = [entry()]
    if change == "empty":
        value["body"]["results"] = []
    if change == "204":
        value = response(status=204)
    with pytest.raises(ResearchError) as error:
        await acquire(
            HTTP(value), IDENTITY, after="NEXT", scanned=1, total=2, release="110.0", seen=["IPR000719"]
        )
    assert error.value.code == code


async def test_discontinuous_fragments_do_not_fill_gaps_or_rename_families():
    fragments = [
        {"start": 500, "end": 550, "dc-status": "C_TERMINAL_DISC"},
        {"start": 650, "end": 700, "dc-status": "N_TERMINAL_DISC"},
    ]
    value = await acquire(HTTP(response(body([entry(kind="family", fragments=fragments)]))), IDENTITY)
    assert overlaps(value, 600) == []
    matched = overlaps(value, 500)
    assert matched[0]["entry_type"] == "family" and matched[0]["representative"] is False
    assert overlaps(value, 700)[0]["end"] == 700


@pytest.fixture
async def mcp_boundary(monkeypatch):
    import httpx
    from fastmcp import Client
    from interpro_helpers import protein
    from native_helpers import BRAF

    from biomedmcp import transport
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    responses, calls = [], []

    def handler(request):
        calls.append(request)
        if request.url.host == "rest.uniprot.org":
            assert request.url.path == "/uniprotkb/P15056" or request.url.path == "/uniprotkb/search"
            return httpx.Response(
                200, json=protein() if request.url.path.endswith("P15056") else {"results": [protein()]}
            )
        if request.url.host == "myvariant.info":
            return httpx.Response(200, json={"hits": [deepcopy(BRAF)], "total": 1})
        assert request.url.host == "www.ebi.ac.uk"
        assert request.url.path == "/interpro/api/entry/interpro/protein/uniprot/P15056/"
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=value, headers={"InterPro-Version": "110.0"})

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler))
    )
    service = ResearchService()
    async with Client(create_server(service=service)) as client:
        yield client, responses, calls, service


GET = {"entity": "protein", "id": "P15056", "sections": ["domains"]}
RELATE = {"entity": "variant", "id": "BRAF V600E", "relation": "structure"}


async def test_actual_mcp_invalid_source_uncached_then_valid_cache_and_provenance(mcp_boundary):
    client, responses, calls, _ = mcp_boundary
    responses.extend([{}, body()])
    bad = (await client.call_tool_mcp("get", GET)).structured_content
    assert (
        bad["outcome"] == "error" and bad["sections"]["domains"]["error"]["code"] == "invalid_source_response"
    )
    assert bad["provenance"] == []
    good = (await client.call_tool_mcp("get", GET)).structured_content
    assert good["sections"]["domains"]["data"]["records"][0]["metadata"]["accession"] == "IPR000719"
    assert good["provenance"][0]["sources"] == ["interpro", "uniprot"]
    assert good["provenance"][0]["source_version"] == "110.0"
    cached = (await client.call_tool_mcp("get", GET)).structured_content
    assert cached["provenance"][0]["cached"] is True
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 2


async def test_actual_mcp_scoped_cursor_reaches_later_entry_without_prefix_replay(mcp_boundary):
    client, responses, calls, service = mcp_boundary
    from biomedmcp.contracts import GetRequest
    from biomedmcp.errors import ResearchError

    responses.extend([body(count=2, after="NEXT"), body([entry(accession="IPR001245")], count=2)])
    first = (await client.call_tool_mcp("get", GET)).structured_content
    assert first["outcome"] == "partial"
    action = first["next_actions"][0]
    assert "NEXT" not in str(first)
    assert action["tool"] == "get" and action["arguments"]["id"] == "P15056"
    for changes in [
        {"id": "P04637"},
        {"species": 10090},
        {
            "section_parameters": {
                "domains": {
                    "limit": 2,
                    "cursor": action["arguments"]["section_parameters"]["domains"]["cursor"],
                }
            }
        },
    ]:
        with pytest.raises(ResearchError):
            await service.get(GetRequest(**(action["arguments"] | changes)), scope="local")
    with pytest.raises(ResearchError):
        await service.get(GetRequest(**action["arguments"]), scope="other")
    before = len(calls)
    second = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert second["outcome"] == "data" and second["next_actions"] == []
    assert second["sections"]["domains"]["data"]["records"][0]["metadata"]["accession"] == "IPR001245"
    acquired = [r for r in calls[before:] if r.url.host == "www.ebi.ac.uk"]
    assert len(acquired) == 1 and acquired[0].url.params["cursor"] == "NEXT"


@pytest.mark.parametrize("failure", ["connect", "json", 401, 403, 404, 429, 503, "shape"])
async def test_actual_variant_relation_retains_primary_evidence_when_interpro_fails(mcp_boundary, failure):
    import httpx

    client, responses, calls, _ = mcp_boundary
    value = (
        {}
        if failure == "shape"
        else httpx.ConnectError("interpro-secret-sentinel")
        if failure == "connect"
        else httpx.Response(200 if failure == "json" else failure, text="interpro-secret-sentinel")
    )
    responses.extend([value, value])
    for _ in range(2):
        result = (await client.call_tool_mcp("relate", RELATE)).structured_content
        assert result["outcome"] == "partial"
        data = result["sections"]["structure"]["data"]
        assert data["protein"]["accession"] == "P15056" and data["structures"][0]["pdb_id"] == "1ABC"
        assert data["interpro_coverage"]["complete"] is False
        assert data["section_outcomes"]["interpro"]["outcome"] == "unavailable"
        assert data["section_outcomes"]["interpro"]["error"]["code"] != "empty"
        assert "interpro" not in result["provenance"][0]["sources"]
        assert "interpro-secret-sentinel" not in str(result)
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 2


async def test_actual_variant_scans_later_pages_and_preserves_non_domain_entry_types(mcp_boundary):
    client, responses, calls, _ = mcp_boundary
    nonmatch = entry(fragments=[{"start": 1, "end": 50, "dc-status": "CONTINUOUS"}])
    responses.extend(
        [
            body([nonmatch], count=2, after="NEXT"),
            body([entry(accession="IPR001245", kind="family")], count=2),
        ]
    )
    value = (await client.call_tool_mcp("relate", RELATE)).structured_content
    data = value["sections"]["structure"]["data"]
    assert value["outcome"] == "data" and data["domains"] == []
    assert data["interpro_matches"][0]["entry_type"] == "family"
    assert data["interpro_coverage"]["complete"] is True
    assert value["provenance"][0]["sources"] == ["interpro", "myvariant", "uniprot"]
    assert len([r for r in calls if r.url.host == "www.ebi.ac.uk"]) == 2


@pytest.mark.parametrize(
    "value",
    [
        body([None]),
        body([{}]),
        body([entry(), entry()]),
        body([]) | {"count": -1},
        body([]) | {"count": {}},
        body() | {"previous": 3},
        body() | {"results": {}},
        body() | {"next": 3},
        body([]) | {"next": body(count=1, after="NEXT")["next"]},
        body(count=2),
    ],
)
async def test_partial_pagination_and_duplicate_entries_fail(value):
    with pytest.raises(ResearchError):
        await acquire(HTTP(response(value)), IDENTITY)


@pytest.mark.parametrize(
    "change", ["empty", "many", "accession", "species", "length", "sequence", "taxon_type"]
)
def test_empty_or_conflicting_uniprot_identity_cannot_anchor_absence(change):
    from interpro_helpers import protein

    from biomedmcp.native.interpro import protein_identity

    row = protein()
    value = {"results": [row]}
    if change == "empty":
        value = {"results": []}
    if change == "many":
        value = {"results": [row, row]}
    if change == "accession":
        row["primaryAccession"] = "P04637"
    if change == "species":
        row["organism"]["taxonId"] = 10090
    if change == "taxon_type":
        row["organism"]["taxonId"] = "9606"
    if change == "length":
        row["sequence"]["length"] -= 1
    if change == "sequence":
        row["sequence"]["value"] = ""
    with pytest.raises(ResearchError):
        protein_identity(value, "P15056", 9606)


@pytest.mark.parametrize("status", [200, 204])
async def test_actual_mcp_valid_empty_is_source_confined_with_verified_identity(mcp_boundary, status):
    import httpx

    client, responses, _calls, _ = mcp_boundary
    responses.append(
        httpx.Response(status, json=body([]), headers={"InterPro-Version": "110.0"})
        if status == 200
        else httpx.Response(204, headers={"InterPro-Version": "110.0"})
    )
    result = (await client.call_tool_mcp("get", GET)).structured_content
    assert result["outcome"] == "empty"
    data = result["sections"]["domains"]["data"]
    assert data["records"] == [] and data["protein_identity"] == IDENTITY
    assert data["coverage"]["complete"] is True and result["provenance"][0]["sources"] == [
        "interpro",
        "uniprot",
    ]
    assert "biological function" in data["coverage"]["interpretation"]


async def test_actual_mcp_bounded_variant_scan_continues_after_prefix(mcp_boundary):
    client, responses, calls, _ = mcp_boundary
    for page in range(4):
        rows = [entry(accession=f"IPR{i:06}") for i in range(page * 25 + 1, page * 25 + 26)]
        responses.append(body(rows, count=101, after=f"N{page}"))
    responses.append(body([entry(accession="IPR000101")], count=101))
    first = (await client.call_tool_mcp("relate", RELATE)).structured_content
    assert first["outcome"] == "partial"
    assert first["sections"]["structure"]["data"]["interpro_coverage"]["acquired_entries"] == 100
    action = first["next_actions"][0]
    assert action["tool"] == "get" and action["arguments"]["id"] == "P15056"

    def exposes_provider_control(value):
        if isinstance(value, dict):
            return any(
                key == "_interpro_continuation" or exposes_provider_control(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(exposes_provider_control(item) for item in value)
        if isinstance(value, str):
            return value == "N3" or "cursor=N3" in value
        return False

    # A random service-issued signature can contain the substring N3. Check
    # actual plaintext provider controls, while permitting opaque service cursors.
    assert not exposes_provider_control(first)
    second = (await client.call_tool_mcp(action["tool"], action["arguments"])).structured_content
    assert second["outcome"] == "data"
    assert second["sections"]["domains"]["data"]["records"][0]["metadata"]["accession"] == "IPR000101"
    requests = [r for r in calls if r.url.host == "www.ebi.ac.uk"]
    assert len(requests) == 5 and [r.url.params.get("cursor") for r in requests] == [
        None,
        "N0",
        "N1",
        "N2",
        "N3",
    ]


async def test_actual_mcp_later_malformed_page_keeps_acquired_overlap_and_unassessed_coverage(mcp_boundary):
    client, responses, _, _ = mcp_boundary
    responses.extend([body(count=2, after="NEXT"), {}])
    result = (await client.call_tool_mcp("relate", RELATE)).structured_content
    data = result["sections"]["structure"]["data"]
    assert result["outcome"] == "partial" and data["domains"][0]["accession"] == "IPR000719"
    assert (
        data["interpro_coverage"]["complete"] is False and data["interpro_coverage"]["acquired_entries"] == 1
    )
    assert data["section_outcomes"]["interpro"]["outcome"] == "partial"
    assert data["section_outcomes"]["interpro"]["error"]["code"] == "invalid_source_response"
    assert "interpro" in result["provenance"][0]["sources"]


@pytest.mark.parametrize("mutation", ["missing", "bool", "unhashable", "duplicate", "bad_release", "extra"])
async def test_actual_mcp_invalid_or_expired_cursor_state_fails_before_http(mcp_boundary, mutation):
    client, responses, calls, service = mcp_boundary
    from biomedmcp.runtime import digest

    responses.append(body(count=3, after="NEXT"))
    first = (await client.call_tool_mcp("get", GET)).structured_content
    arguments = first["next_actions"][0]["arguments"]
    cursor = arguments["section_parameters"]["domains"]["cursor"]
    key = "interpro-page:" + digest(cursor)
    state = await service.runtime.cache.get(key)
    if mutation == "missing":
        service.runtime.cache.values.pop(key)
    else:
        if mutation == "bool":
            state["scanned"] = True
        if mutation == "unhashable":
            state["seen"] = [{}]
        if mutation == "duplicate":
            state["seen"] = ["IPR000719", "IPR000719"]
        if mutation == "bad_release":
            state["release"] = []
        if mutation == "extra":
            state["limit"] = 999
        await service.runtime.cache.put(key, state, 3600)
    before = len(calls)
    bad = (await client.call_tool_mcp("get", arguments)).structured_content
    assert bad["outcome"] == "error" and bad["error"]["code"] == (
        "expired_cursor" if mutation == "missing" else "cache_invalid_data"
    )
    assert len(calls) == before


async def test_cursor_storage_limit_does_not_erase_partial_coverage(mcp_boundary, monkeypatch):
    client, responses, _, service = mcp_boundary
    original = service.runtime.cache.put

    async def put(key, value, ttl):
        return False if key.startswith("interpro-page:") else await original(key, value, ttl)

    monkeypatch.setattr(service.runtime.cache, "put", put)
    responses.append(body(count=2, after="NEXT"))
    value = (await client.call_tool_mcp("get", GET)).structured_content
    assert value["outcome"] == "partial" and value["next_actions"] == []
    assert value["sections"]["domains"]["data"]["coverage"]["continuation_status"] == "storage_limit"
    assert any("unassessed" in warning for warning in value["sections"]["domains"]["warnings"])


async def test_explicit_sources_cannot_bypass_protein_identity(mcp_boundary):
    client, _, calls, _ = mcp_boundary
    value = (await client.call_tool_mcp("get", GET | {"sources": ["interpro"]})).structured_content
    assert value["error"]["code"] == "source_plan_conflict" and calls == []


@pytest.mark.parametrize("release", [None, "110.0"])
async def test_release_is_observed_or_unknown_without_inventing_pin(release):
    value = await acquire(HTTP(response(release=release)), IDENTITY)
    assert value["source_release"] == release


@pytest.mark.parametrize("release", ["", "latest", 110, [], "110.0?secret=sentinel"])
async def test_invalid_release_metadata_fails(release):
    with pytest.raises(ResearchError):
        await acquire(HTTP(response(release=release)), IDENTITY)


async def test_canonical_isoform_and_nonhuman_preflight_are_explicit(mcp_boundary):
    client, _, calls, service = mcp_boundary
    from biomedmcp.contracts import GetRequest

    value = (await client.call_tool_mcp("get", GET | {"id": "P15056-2"})).structured_content
    assert value["error"]["code"] == "invalid_identifier" and calls == []
    await service.get(GetRequest(**(GET | {"species": 10090})), scope="local", _plan_only=True)


def test_boolean_taxonomy_never_matches_numeric_identity():
    from interpro_helpers import protein

    from biomedmcp.native.interpro import protein_identity

    row = protein()
    row["organism"]["taxonId"] = True
    with pytest.raises(ResearchError):
        protein_identity(row, "P15056", 1)
