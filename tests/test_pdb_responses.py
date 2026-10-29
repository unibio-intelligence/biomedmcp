"""RCSB entry/search/file semantics through the retained adapter and public MCP."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions

ENTRY = json.loads((Path(__file__).parent / "fixtures/pdb-entry-4hhb-2026-10-11.json").read_text())
SEARCH = {"result_type": "entry", "total_count": 3, "result_set": [{"identifier": "4HHB", "score": 1.0}]}
CIF = "data_4HHB\n_entry.id 4HHB\n#\nloop_\n_atom_site.id\n_atom_site.type_symbol\n_atom_site.label_atom_id\n_atom_site.label_comp_id\n_atom_site.label_asym_id\n_atom_site.Cartn_x\n_atom_site.Cartn_y\n_atom_site.Cartn_z\n1 N N ALA A 1.25 2.5 3.75\n#\n"
PDB = (
    "HEADER".ljust(62)
    + "4HHB\n"
    + "ATOM  "
    + f"{1:5d} {'N':^4} {'ALA':>3} A{1:4d}    {1.25:8.3f}{2.5:8.3f}{3.75:8.3f}{1:6.2f}{10:6.2f}{'':10}{'N':>2}  \n"
)
XML = '<datablock datablockName="4HHB"><atom_site id="1"><type_symbol>N</type_symbol><label_atom_id>N</label_atom_id><label_comp_id>ALA</label_comp_id><label_asym_id>A</label_asym_id><Cartn_x>1.25</Cartn_x><Cartn_y>2.5</Cartn_y><Cartn_z>3.75</Cartn_z></atom_site></datablock>'


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters()

    return install


async def test_search_uses_current_filters_sorts_and_preserves_provider_continuation(wire):
    observed = []

    def handler(request):
        body = json.loads(request.content)
        observed.append(body)
        assert request.url.host == "search.rcsb.org"
        assert body["request_options"]["paginate"] == {"start": 0, "rows": 1}
        assert body["request_options"]["sort"] == [
            {"sort_by": "rcsb_entry_info.resolution_combined", "direction": "asc"}
        ]
        assert body["query"]["nodes"][1]["parameters"]["value"] == "X-RAY DIFFRACTION"
        return httpx.Response(200, json=SEARCH)

    result = await wire(handler).call(
        "pdb",
        "search_structures",
        {
            "query": "hemoglobin",
            "limit": 1,
            "sort_by": "rcsb_entry_info.resolution_combined",
            "sort_direction": "asc",
            "experimental_method": "X-RAY DIFFRACTION",
            "resolution_range": "0.0-2.0",
        },
    )
    assert result["records"] == SEARCH["result_set"] and len(observed) == 1
    assert result["_provider_page"]["next_offset"] == 1
    assert result["coverage"]["accessible_window_exhausted"] is False


async def test_actual_mcp_search_continuation_is_executable_without_repeating_first_window(wire):
    offsets = []

    def handler(request):
        offset = json.loads(request.content)["request_options"]["paginate"]["start"]
        offsets.append(offset)
        return httpx.Response(
            200,
            json={
                "result_type": "entry",
                "total_count": 2,
                "result_set": [{"identifier": "4HHB" if offset == 0 else "1HH3", "score": 1.0}],
            },
        )

    wire(handler)
    async with Client(create_server(service=ResearchService())) as client:
        first = (
            await client.call_tool(
                "query_source",
                {
                    "source": "pdb",
                    "operation": "search_structures",
                    "params": {"query": "hemoglobin", "limit": 1},
                },
            )
        ).data
        action = first["next_actions"][0]
        second = (await client.call_tool(action["tool"], action["arguments"])).data
    assert offsets == [0, 1]
    assert first["sections"]["pdb"]["data"]["records"][0]["identifier"] == "4HHB"
    assert second["sections"]["pdb"]["data"]["records"][0]["identifier"] == "1HH3"
    assert not second["next_actions"]
    assert first["provenance"] and second["provenance"]


@pytest.mark.parametrize("offset,total", [(0, 0), (2, None)])
async def test_documented_no_content_search_does_not_invent_a_total_after_offset(wire, offset, total):
    result = await wire(lambda _: httpx.Response(204)).call(
        "pdb", "search_structures", {"query": "no match", "offset": offset}
    )
    assert result["records"] == [] and result["total_count"] is total
    assert result["coverage"]["offset"] == offset


@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        "not a search response",
        {"_rcsb_no_content": True},
        {"result_type": "entry", "total_count": 0},
        {"result_type": "assembly", "total_count": 0, "result_set": []},
        {"result_type": "entry", "total_count": 0, "result_set": {}},
        {"result_type": "entry", "total_count": True, "result_set": []},
        {"result_type": "entry", "total_count": 3, "result_set": []},
        {**SEARCH, "error": "synthetic provider error"},
        {**SEARCH, "result_set": [{"identifier": "4HHB", "score": True}]},
        {**SEARCH, "result_set": [{"identifier": "not-pdb", "score": 1}]},
        {**SEARCH, "result_set": [{"identifier": "4HHB", "score": -1}]},
        {**SEARCH, "result_set": [{"identifier": "4HHB", "score": 1, "services": {}}]},
        {**SEARCH, "result_set": [SEARCH["result_set"][0], SEARCH["result_set"][0]]},
    ],
)
async def test_malformed_search_is_never_healthy_empty(wire, payload):
    with pytest.raises(ResearchError) as error:
        await wire(lambda _: httpx.Response(200, json=payload)).call(
            "pdb", "search_structures", {"query": "hemoglobin"}
        )
    assert error.value.code == "invalid_source_response"


async def test_explicit_consistent_empty_collection_is_valid(wire):
    result = await wire(
        lambda _: httpx.Response(200, json={"result_type": "entry", "total_count": 0, "result_set": []})
    ).call("pdb", "search_structures", {"query": "no match"})
    assert result["records"] == [] and result["total_count"] == 0


@pytest.mark.parametrize(
    "operation,params",
    [
        ("search_structures", {"query": "hemoglobin"}),
        ("get_structure_info", {"pdb_id": "4HHB"}),
    ],
)
async def test_no_content_cannot_hide_a_body_or_mean_a_missing_entry(wire, operation, params):
    with pytest.raises(ResearchError) as error:
        await wire(
            lambda _: httpx.Response(204, content=b"{}" if operation == "search_structures" else b"")
        ).call("pdb", operation, params)
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("operation", ["get_structure_info", "get_structure_quality"])
@pytest.mark.parametrize("payload", [None, {}, [], "not an entry", {"errors": ["synthetic provider error"]}])
async def test_absent_or_wrong_typed_entries_are_not_empty_or_quality_successes(wire, operation, payload):
    with pytest.raises(ResearchError) as error:
        await wire(lambda _: httpx.Response(200, json=payload)).call("pdb", operation, {"pdb_id": "4HHB"})
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("operation", ["get_structure_info", "get_structure_quality"])
async def test_real_dated_entry_fixture_preserves_identity_and_observed_revision(wire, operation):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=ENTRY)

    value = await wire(handler).call("pdb", operation, {"pdb_id": "4HHB"})
    assert paths == ["/rest/v1/core/entry/4hhb"]
    if operation == "get_structure_quality":
        assert value["resolution"] == [1.74] and value["resolution_units"] == "angstroms"
        assert value["released_experimental_data_available"] is False
        assert "structure_factors_available" not in value
        assert value["validation_status"] == "available"
        assert value["validation_summary"] == {k: v for k, v in ENTRY.items() if k.startswith("pdbx_vrpt_")}
        assert value["source_revision"]["revision_date"] == ENTRY["rcsb_accession_info"]["revision_date"]
    else:
        assert value["data"]["rcsb_id"] == "4HHB"


@pytest.mark.parametrize(
    "path,value",
    [
        (("rcsb_id",), "1HH3"),
        (("rcsb_entry_container_identifiers", "entry_id"), "1HH3"),
        (("rcsb_entry_info",), None),
        (("rcsb_entry_info", "structure_determination_methodology"), "unknown"),
        (("rcsb_entry_info", "polymer_entity_count"), -1),
        (("rcsb_entry_info", "resolution_combined"), [0]),
        (("rcsb_entry_info", "resolution_combined"), [True]),
        (("rcsb_accession_info", "deposit_date"), "not a date"),
        (("rcsb_accession_info", "has_released_experimental_data"), True),
        (("pdbx_vrpt_summary_geometry",), {}),
    ],
)
@pytest.mark.parametrize("operation", ["get_structure_info", "get_structure_quality"])
async def test_invalid_entry_identity_nested_types_and_measurements_fail_before_caching(
    wire, path, value, operation
):
    payload = deepcopy(ENTRY)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ResearchError) as error:
        await wire(lambda _: httpx.Response(200, json=payload)).call("pdb", operation, {"pdb_id": "4HHB"})
    assert error.value.code == "invalid_source_response"


async def test_missing_validation_preserves_entry_as_partial_and_measurements_as_unknown(wire):
    payload = {
        "rcsb_id": "4HHB",
        "rcsb_entry_container_identifiers": {"entry_id": "4HHB"},
        "rcsb_entry_info": {"structure_determination_methodology": "experimental"},
    }
    wire(lambda _: httpx.Response(200, json=payload))
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "pdb", "operation": "get_structure_quality", "params": {"pdb_id": "4HHB"}},
            )
        ).data
    assert result["outcome"] == "partial" and result["provenance"]
    assert result["provenance"][0]["source_version"] is None
    data = result["sections"]["pdb"]["data"]
    assert data["resolution"] is None and data["polymer_entity_count"] is None
    assert data["released_experimental_data_available"] is None
    assert data["validation_status"] == "unavailable" and data["validation_summary"] is None


async def test_observed_entry_revision_is_cited_without_claiming_live_replay(wire):
    wire(lambda _: httpx.Response(200, json=ENTRY))
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "pdb", "operation": "get_structure_info", "params": {"pdb_id": "4HHB"}},
            )
        ).data
    assert result["provenance"][0]["source_version"] == "4.3"
    assert result["provenance"][0]["url"] == "https://www.rcsb.org/structure/4hhb"
    assert result["receipt"]["time_dependent"] is True


@pytest.mark.parametrize("format,content", [("mmcif", CIF), ("pdb", PDB), ("xml", XML)])
async def test_coordinate_download_has_entry_identity_finite_coordinates_and_exact_bytes(
    wire, format, content
):
    value = await wire(lambda _: httpx.Response(200, text=content)).call(
        "pdb", "download_structure", {"pdb_id": "4HHB", "format": format}
    )
    assert value["identity_checked"] is True
    assert value["content_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert value["content_utf8_bytes"] == len(content.encode())
    assert "not independently verified" in value["coordinate_checks"]


async def test_cif_quoting_comments_and_single_row_category_remain_valid(wire):
    content = "data_4HHB\n_entry.id '4HHB'\n_struct.title\n;Literal source text containing data_other and _atom_site.id\n;\n# comment\n_atom_site.id 1\n_atom_site.type_symbol N\n_atom_site.label_atom_id 'N'\n_atom_site.label_comp_id ALA\n_atom_site.label_asym_id A\n_atom_site.Cartn_x 1.25\n_atom_site.Cartn_y 2.5\n_atom_site.Cartn_z 3.75\n"
    result = await wire(lambda _: httpx.Response(200, text=content)).call(
        "pdb", "download_structure", {"pdb_id": "4HHB", "format": "mmcif"}
    )
    assert result["content"] == content and result["identity_checked"]


@pytest.mark.parametrize(
    "format,content",
    [
        ("mmcif", "<html>provider error</html>"),
        ("mmcif", CIF.replace("4HHB", "1HH3")),
        ("mmcif", CIF.replace("1 N N ALA A 1.25 2.5 3.75", "")),
        ("mmcif", CIF.replace("1.25", "nan")),
        ("pdb", PDB.replace("4HHB", "1HH3")),
        ("pdb", PDB.split("ATOM")[0]),
        ("pdb", PDB.replace("1.250", "  nan")),
        ("xml", XML.replace("4HHB", "1HH3")),
        ("xml", XML.replace("1.25", "nan")),
        ("xml", '<!DOCTYPE x [<!ENTITY ex SYSTEM "file:///etc/passwd">]>' + XML.replace("1.25", "&ex;")),
    ],
)
async def test_invalid_coordinate_files_are_not_successful_downloads(wire, format, content):
    with pytest.raises(ResearchError) as error:
        await wire(lambda _: httpx.Response(200, text=content)).call(
            "pdb", "download_structure", {"pdb_id": "4HHB", "format": format}
        )
    assert error.value.code == "invalid_source_response"


async def test_legacy_pdb_assembly_uses_documented_url_and_checks_biomolecule(wire):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, text=PDB + "REMARK 350 BIOMOLECULE: 1\n")

    result = await wire(handler).call("pdb", "download_structure", {"pdb_id": "4HHB", "assembly_id": "1"})
    assert paths == ["/download/4hhb.pdb1"] and result["assembly_id"] == "1"


@pytest.mark.parametrize(
    "operation,params",
    [
        ("download_structure", {"pdb_id": "4HHB", "format": "mmtf"}),
        ("download_structure", {"pdb_id": "4HHB", "format": "xml", "assembly_id": "1"}),
        ("download_structure", {"pdb_id": "4HHB", "assembly_id": "../other"}),
        ("get_structure_info", {"pdb_id": "٤HHB"}),
        ("search_structures", {"query": "hemoglobin", "experimental_method": "X-RAY"}),
        ("search_structures", {"query": "hemoglobin", "sort_by": "release_date"}),
        ("search_structures", {"query": "hemoglobin", "resolution_range": "2.0-1.0"}),
        ("search_structures", {"query": "hemoglobin", "resolution_range": "nan-2.0"}),
    ],
)
async def test_retired_or_unqualified_requests_are_rejected_before_http(wire, operation, params):
    def forbidden(_):
        pytest.fail("Rejected PDB parameters must not contact a source")

    with pytest.raises(ResearchError) as error:
        await wire(forbidden).call("pdb", operation, params)
    assert error.value.code in {"invalid_parameters", "unsupported_filter"}


async def test_invalid_pdb_source_result_is_not_reused_as_a_cached_success(wire):
    replies = [None, ENTRY]

    def handler(_):
        return httpx.Response(200, json=replies.pop(0))

    wire(handler)
    async with Client(create_server(service=ResearchService())) as client:
        params = {"source": "pdb", "operation": "get_structure_info", "params": {"pdb_id": "4HHB"}}
        first = (await client.call_tool_mcp("query_source", params)).structured_content
        second = (await client.call_tool("query_source", params)).data
    assert first["outcome"] == "error" and not first["provenance"]
    assert second["outcome"] == "data" and second["provenance"]
    assert not replies


@pytest.mark.parametrize(
    "content", [b"\xffinvalid UTF-8", b"x" * 4_000_001], ids=["invalid_utf8", "oversized"]
)
async def test_binary_or_oversized_inline_downloads_fail_without_evidence(wire, content):
    with pytest.raises(ResearchError) as error:
        await wire(lambda _: httpx.Response(200, content=content)).call(
            "pdb", "download_structure", {"pdb_id": "4HHB", "format": "mmcif"}
        )
    assert error.value.code in {"invalid_source_response", "source_response_budget"}


async def test_offset_boundary_keeps_evidence_without_emitting_an_invalid_next_action(wire):
    wire(lambda _: httpx.Response(200, json={**SEARCH, "total_count": 100_000_002}))
    async with Client(create_server(service=ResearchService())) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "pdb",
                    "operation": "search_structures",
                    "params": {"query": "hemoglobin", "offset": 100_000_000, "limit": 1},
                },
            )
        ).data
    assert result["outcome"] == "partial" and result["provenance"]
    assert result["sections"]["pdb"]["data"]["records"] == SEARCH["result_set"]
    assert result["sections"]["pdb"]["data"]["coverage"]["continuation_status"] == "unavailable"
    assert not result["next_actions"]
