"""Agent-observed full-text ranges must agree across public entry points."""

import json
from copy import deepcopy

import jsonschema
import pytest
import structlog
from fastmcp import Client
from native_helpers import HTTP

from biomedmcp import cli
from biomedmcp.contracts import GetRequest
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.native.literature import Literature
from biomedmcp.public_catalog import schema


def arguments(parameters=None, *, identifier="PMC123"):
    return {
        "entity": "article",
        "id": identifier,
        "sections": ["fulltext"],
        "section_parameters": {"fulltext": {"view": "lines", **(parameters or {})}},
    }


INVALID = [
    {"start": 0, "end": 200},  # actual calibration/held-out participant request
    {"start": 0, "end": 2},  # actual participant retry
    {"end": 0},
    {"start": 100001, "end": 100001},
    {"end": 100001},
    {"start": 2, "end": 1},
    {"start": 1, "end": 101},  # inclusive: 101 lines, not 100
    {"start": 101},  # omitted end uses 100
    {"end": 101},  # omitted start uses 1
]


@pytest.mark.parametrize("parameters", INVALID[:5])
def test_advertised_schema_rejects_zero_or_unbounded_coordinates(parameters):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(arguments(parameters), schema("get"))


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", INVALID)
async def test_actual_mcp_rejects_invalid_range_before_acquisition(monkeypatch, parameters):
    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP()
    async with Client(create_server(service=ResearchService(http=http))) as client:
        result = await client.call_tool_mcp("get", arguments(parameters))
    assert result.is_error
    assert result.structured_content["error"]["code"] == "invalid_parameters"
    assert result.structured_content["error"]["retryable"] is False
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [INVALID[0], INVALID[5], INVALID[6]])
async def test_local_cli_reports_the_same_controlled_parameter_error(monkeypatch, tmp_path, parameters):
    http = HTTP()
    monkeypatch.setattr(cli, "ResearchService", lambda **kwargs: ResearchService(http=http, **kwargs))
    with pytest.raises(ResearchError) as error:
        await cli.execute("get", arguments(parameters), state_dir=tmp_path / "state")
    assert error.value.code == "invalid_parameters"
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [INVALID[0], INVALID[5], INVALID[6]])
async def test_bad_late_batch_range_prevents_every_provider_request(monkeypatch, parameters):
    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP()
    calls = [
        {"operation": "get", "arguments": {"entity": "article", "id": "123"}},
        {"operation": "get", "arguments": arguments(parameters)},
    ]
    with pytest.raises(ResearchError) as error:
        await execute(
            ResearchService(http=http),
            "batch",
            {"calls": calls},
            scope="test",
        )
    assert error.value.code == "invalid_parameters"
    assert http.calls == []
    async with Client(create_server(service=ResearchService(http=http))) as client:
        result = await client.call_tool_mcp("batch", {"calls": calls})
    assert result.is_error and result.structured_content["error"]["code"] == "invalid_parameters"
    assert http.calls == []


def test_cli_command_has_a_safe_json_error_and_nonzero_exit(monkeypatch, tmp_path, capsys):
    http = HTTP()
    monkeypatch.setattr(cli, "ResearchService", lambda **kwargs: ResearchService(http=http, **kwargs))
    monkeypatch.setattr(
        "sys.argv",
        ["biomedmcp", "get", json.dumps(arguments(INVALID[0])), "--state-dir", str(tmp_path / "state")],
    )
    logging_config = structlog.get_config()
    try:
        with pytest.raises(SystemExit) as error:
            cli.main()
    finally:
        # The real CLI configures its logger for stderr. Do not leave it bound
        # to capsys's temporary stream after this in-process command exits.
        structlog.configure(**logging_config)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_parameters"
    assert http.calls == []


PAPER = (
    "<article><body><sec>"
    + "".join(f"<p>Assayed sample {i}.</p>" for i in range(1, 121))
    + "</sec></body></article>"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parameters,start,end",
    [
        ({}, 1, 100),
        ({"start": 1, "end": 100}, 1, 100),
        ({"start": 101, "end": 120}, 101, 120),
        ({"start": 90}, 90, 100),
        ({"end": 80}, 1, 80),
    ],
)
async def test_schema_mcp_cli_and_native_preserve_inclusive_lines(
    monkeypatch, tmp_path, parameters, start, end
):
    monkeypatch.setenv("UBI_PROFILE", "local")
    request = arguments(parameters)
    jsonschema.validate(request, schema("get"))
    mcp_http, cli_http, native_http = HTTP(PAPER), HTTP(PAPER), HTTP(PAPER)
    async with Client(create_server(service=ResearchService(http=mcp_http))) as client:
        output = await client.call_tool_mcp("get", deepcopy(request))
    assert not output.is_error
    monkeypatch.setattr(cli, "ResearchService", lambda **kwargs: ResearchService(http=cli_http, **kwargs))
    local = await cli.execute("get", deepcopy(request), state_dir=tmp_path / "state")
    native = await Literature(native_http).fulltext("PMC123", view="lines", **parameters)
    for result in [output.structured_content, local]:
        assert result["outcome"] == "data"
        section = result["sections"]["fulltext"]
        assert section["outcome"] == "data"
        proof = result["provenance"][0]
        assert proof["source"] == "europepmc" and proof["content_hash"]
        assert section["evidence_ids"] == [proof["evidence_id"]]
        assert section["data"] == native
    assert native["start"] == start and native["end"] == end and native["line_count"] == 120
    assert [line["number"] for line in native["lines"]] == list(range(start, end + 1))
    assert native["lines"][0]["text"] == f"Assayed sample {start}."
    assert native["truncated"] is (end < 120)
    assert len(mcp_http.calls) == len(cli_http.calls) == len(native_http.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [INVALID[0], INVALID[5], INVALID[6]])
async def test_native_internal_reader_cannot_bypass_window_validation(parameters):
    http = HTTP()
    with pytest.raises(ResearchError) as error:
        await Literature(http).fulltext("PMC123", view="lines", **parameters)
    assert error.value.code == "invalid_parameters"
    assert http.calls == []


def test_internal_planning_validation_does_not_echo_rejected_article_identity():
    sentinel = "10.1234/rejected-input-sentinel-" + "x" * 256
    request = GetRequest.model_validate(arguments(identifier=sentinel))
    with pytest.raises(ResearchError) as error:
        ResearchService(http=HTTP())._get_plan(request)
    assert error.value.code == "invalid_parameters"
    assert sentinel not in str(error.value.as_dict())


def test_internal_planning_range_error_is_controlled_before_public_adaptation():
    request = GetRequest.model_validate(arguments(INVALID[0]))
    with pytest.raises(ResearchError) as error:
        ResearchService(http=HTTP())._get_plan(request)
    assert error.value.code == "invalid_parameters"


@pytest.mark.asyncio
async def test_actual_mcp_hides_invalid_article_identity_in_planning(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    sentinel = "10.1234/rejected-input-sentinel-" + "x" * 256
    http = HTTP()
    async with Client(create_server(service=ResearchService(http=http))) as client:
        result = await client.call_tool_mcp("get", arguments(identifier=sentinel))
    assert result.is_error and result.structured_content["error"]["code"] == "invalid_parameters"
    assert sentinel not in json.dumps(result.structured_content)
    assert http.calls == []
