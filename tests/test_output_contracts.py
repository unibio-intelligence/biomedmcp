"""Public wire contracts exercised through the pinned MCP client and CLI."""

import asyncio
import json
import os
import socket
import sys
from contextlib import nullcontext

import httpx
import jsonschema
import pytest
import uvicorn
from fastmcp import Client

from biomedmcp import cli
from biomedmcp.contracts import ResearchResult, Section
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.output_contracts import CATALOG_BYTE_BUDGET

SENTINEL = "credential-sentinel-do-not-echo"


class Service:
    async def get(self, request, *, scope, _plan_only=False):
        if _plan_only:
            return
        if request.id.startswith("raise-"):
            code = request.id.removeprefix("raise-")
            raise ResearchError(code, "The source could not complete the request.", retryable=True)
        if request.id == "unexpected":
            raise RuntimeError(SENTINEL)
        if request.id == "invalid-output":
            return ResearchResult(
                entity=request.entity,
                outcome="error",
                sections={"record": Section(outcome="error", error={"message": SENTINEL})},
            )
        outcome = request.id
        error = ResearchError("source_unavailable", "Source unavailable.", retryable=True).as_dict()
        return ResearchResult(
            entity=request.entity,
            outcome=outcome,
            sections={
                "record": Section(
                    outcome=outcome,
                    data={"id": "P12345"} if outcome in {"data", "partial"} else None,
                    error=error if outcome in {"partial", "unavailable", "error"} else None,
                )
            },
        )

    async def capabilities(self, **kwargs):
        return {"product": "biomedmcp"}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    return create_server(service=Service())


def wire(result):
    structured = result.structured_content
    text = json.loads("\n".join(block.text for block in result.content if block.type == "text"))
    assert structured == text
    return structured


@pytest.mark.asyncio
async def test_all_thirteen_tools_advertise_self_contained_output_schemas(server):
    async with Client(server) as client:
        tools = await client.list_tools()
    assert len(tools) == 13
    for tool in tools:
        assert tool.output_schema is not None, tool.name
        jsonschema.Draft202012Validator.check_schema(tool.output_schema)
        assert tool.output_schema["type"] == "object"
    size = len(
        json.dumps(
            [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )
    assert size <= CATALOG_BYTE_BUDGET


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["data", "empty", "partial", "ambiguous", "unavailable", "error"])
async def test_scientific_outcomes_validate_and_preserve_wire_semantics(server, outcome):
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "get")
        result = await client.call_tool_mcp("get", {"entity": "protein", "id": outcome})
    value = wire(result)
    jsonschema.validate(value, tool.output_schema)
    assert value["schema_version"] == "1.0" and value["outcome"] == outcome
    assert result.is_error == (outcome in {"unavailable", "error"})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["source_unavailable", "source_rate_limited", "operation_timeout"])
async def test_raised_errors_keep_code_retryability_correction_and_text(server, code):
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "get")
        result = await client.call_tool_mcp("get", {"entity": "protein", "id": "raise-" + code})
    value = wire(result)
    jsonschema.validate(value, tool.output_schema)
    assert result.is_error and value["outcome"] == "error"
    assert value["error"]["code"] == code and value["error"]["retryable"]
    assert value["error"]["correction"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args",
    [
        ("get", {"entity": SENTINEL, "id": "data"}),
        ("capabilities", {"entity": SENTINEL}),
        ("quota", {SENTINEL: SENTINEL}),
        ("batch", {"calls": SENTINEL}),
    ],
)
async def test_validation_errors_are_structured_and_never_echo_input(server, name, args, caplog):
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == name)
        result = await client.call_tool_mcp(name, args)
    value = wire(result)
    jsonschema.validate(value, tool.output_schema)
    assert result.is_error and value["error"]["code"] == "invalid_parameters"
    assert value["error"]["correction"]
    assert SENTINEL not in json.dumps(value) + caplog.text


@pytest.mark.asyncio
async def test_unexpected_exception_is_sanitized_before_sdk_logging(server, caplog):
    async with Client(server) as client:
        result = await client.call_tool_mcp("get", {"entity": "protein", "id": "unexpected"})
    value = wire(result)
    assert result.is_error and value["error"]["code"] == "internal_error"
    assert SENTINEL not in json.dumps(value) + caplog.text


@pytest.mark.asyncio
async def test_invalid_output_fails_safely_and_batch_keeps_successful_peer(server, caplog):
    async with Client(server) as client:
        result = await client.call_tool_mcp("get", {"entity": "protein", "id": "invalid-output"})
        batch = await client.call_tool_mcp(
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "protein", "id": id_}}
                    for id_ in ["data", "invalid-output"]
                ]
            },
        )
    assert wire(result)["error"]["code"] == "invalid_output" and result.is_error
    value = wire(batch)
    assert not batch.is_error and value["outcome"] == "partial"
    assert value["results"][0]["sections"]["record"]["data"] == {"id": "P12345"}
    assert value["results"][1]["error"]["code"] == "invalid_output"
    assert SENTINEL not in json.dumps(value) + str(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["capabilities", "quota"])
async def test_utility_outputs_satisfy_advertised_versioned_contract(server, name):
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == name)
        result = await client.call_tool_mcp(name, {})
    value = wire(result)
    jsonschema.validate(value, tool.output_schema)
    assert value["schema_version"] == "1.0" and not result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "source_authentication_failed", False),
        (403, "source_access_denied", False),
        (404, "source_not_found", False),
        (429, "source_rate_limited", True),
        (503, "source_unavailable", True),
    ],
)
async def test_native_http_statuses_preserve_safe_classification(monkeypatch, status, code, retryable):
    from biomedmcp import transport
    from biomedmcp.native.http import ProviderHTTP

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"error": SENTINEL}))
        ),
    )
    with pytest.raises(ResearchError) as caught:
        await ProviderHTTP().get("https://fixture.example/data")
    assert caught.value.code == code and caught.value.retryable == retryable
    assert caught.value.correction and SENTINEL not in str(caught.value.as_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ids,outcome,is_error",
    [
        (["data", "empty"], "data", False),
        (["data", "raise-source_rate_limited"], "partial", False),
        (["raise-source_unavailable", "unavailable"], "error", True),
    ],
)
async def test_versioned_batch_status_and_each_item_schema(server, ids, outcome, is_error):
    args = {"calls": [{"operation": "get", "arguments": {"entity": "protein", "id": id_}} for id_ in ids]}
    async with Client(server) as client:
        tool = next(tool for tool in await client.list_tools() if tool.name == "batch")
        result = await client.call_tool_mcp("batch", args)
    value = wire(result)
    jsonschema.validate(value, tool.output_schema)
    assert value["schema_version"] == "1.0" and value["outcome"] == outcome
    assert result.is_error == is_error
    assert len(value["results"]) == len(ids)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,params",
    [
        ("tools", {"unknown": SENTINEL}),
        ("resources", {"unknown": SENTINEL}),
        ("prompts", {"unknown": SENTINEL}),
        ("read-resource", {}),
        ("read-resource", {"uri": 17}),
        ("get-prompt", {}),
        ("get-prompt", {"name": "target_research", "arguments": [SENTINEL]}),
    ],
)
async def test_cli_protocol_arguments_fail_before_opening_client(monkeypatch, operation, params):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid protocol arguments opened a client")

    monkeypatch.setattr("fastmcp.Client", forbidden)
    with pytest.raises(ResearchError) as caught:
        await cli.execute(operation, params, url="https://invalid.example/mcp")
    assert caught.value.code == "invalid_parameters"
    assert SENTINEL not in str(caught.value.as_dict())


@pytest.mark.parametrize(
    "failure,code",
    [
        (httpx.ConnectError(SENTINEL), "remote_unavailable"),
        (OSError(SENTINEL), "local_io_error"),
        (ValueError(SENTINEL), "invalid_request"),
    ],
)
def test_cli_main_errors_are_safe_json_and_exit_two(monkeypatch, capsys, failure, code):
    async def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(cli, "execute", fail)
    monkeypatch.setattr("sys.argv", ["biomedmcp", "quota"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    captured = capsys.readouterr()
    value = json.loads(captured.err)
    assert caught.value.code == 2 and captured.out == ""
    assert value["schema_version"] == "1.0" and value["outcome"] == "error"
    assert value["error"]["code"] == code and value["error"]["correction"]
    assert SENTINEL not in captured.err


@pytest.fixture
async def http_endpoint(server):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(64)
    runner = uvicorn.Server(
        uvicorn.Config(server.http_app(stateless_http=True), log_level="error", access_log=False)
    )
    runner.capture_signals = nullcontext
    task = asyncio.create_task(runner.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not runner.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}/mcp"
    finally:
        runner.should_exit = True
        await asyncio.wait_for(task, 10)


@pytest.mark.asyncio
async def test_live_http_discovery_advertises_schemas(http_endpoint):
    async with Client(http_endpoint) as client:
        tools = await client.list_tools()
    assert len(tools) == 13 and all(tool.output_schema for tool in tools)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["data", "empty", "partial", "ambiguous", "unavailable", "error"])
async def test_local_and_remote_cli_keep_identical_scientific_envelopes(
    monkeypatch, tmp_path, http_endpoint, outcome
):
    monkeypatch.setattr(cli, "ResearchService", lambda **kwargs: Service())
    arguments = {"entity": "protein", "id": outcome}
    local = await cli.execute("get", arguments, state_dir=tmp_path / "state")
    remote = await cli.execute("get", arguments, url=http_endpoint)
    from biomedmcp.receipts import verify_receipt

    assert verify_receipt(local) and verify_receipt(remote)
    left, right = local.pop("receipt"), remote.pop("receipt")
    assert local == remote and remote["outcome"] == outcome
    # These are distinct completed operations. Their issue times and delivered
    # result hashes differ, but the validated task and receipt semantics agree.
    for record in (left, right):
        record.pop("completed_at")
        record.pop("result_sha256")
    assert left == right


@pytest.mark.asyncio
async def test_remote_cli_preserves_controlled_raised_error(http_endpoint):
    with pytest.raises(ResearchError) as caught:
        await cli.execute("get", {"entity": "protein", "id": "raise-source_rate_limited"}, url=http_endpoint)
    assert caught.value.code == "source_rate_limited" and caught.value.retryable
    assert "Wait" in caught.value.correction


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "id_,code",
    [
        ("data", 0),
        ("empty", 0),
        ("partial", 0),
        ("ambiguous", 0),
        ("unavailable", 2),
        ("error", 2),
        ("raise-source_rate_limited", 2),
    ],
)
async def test_real_remote_cli_process_json_exit_contract(http_endpoint, id_, code):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from biomedmcp.cli import main; main()",
        "get",
        json.dumps({"entity": "protein", "id": id_}),
        "--url",
        http_endpoint,
        env={**os.environ, "UBI_PROFILE": "local"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
    assert process.returncode == code
    value = json.loads(stderr if code else stdout)
    assert value["schema_version"] == "1.0"
    assert not stdout if code else not stderr
    if id_.startswith("raise-"):
        assert value["error"]["code"] == "source_rate_limited"
        assert value["error"]["retryable"] and value["error"]["correction"]
    else:
        assert value["outcome"] == id_
