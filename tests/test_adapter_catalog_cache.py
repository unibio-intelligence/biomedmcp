"""Cached schemas remain current, isolated and enforced before scientific I/O."""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import FastMCP

from biomedmcp import adapters as adapter_module
from biomedmcp.adapters import PROVIDERS, SourceAdapters
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.catalog import ADVANCED

SOURCE = "chembl"


@pytest.fixture
async def catalog_fixture(monkeypatch):
    server = FastMCP("catalog-fixture", version="fixture-1")
    calls = []

    @server.tool(version="1")
    async def lookup(value: int):
        calls.append(value)
        return {"value": value}

    monkeypatch.setitem(PROVIDERS, SOURCE, {"module": "unused", "required_env": []})
    monkeypatch.setitem(ADVANCED, SOURCE, {"lookup"})
    adapters = SourceAdapters()
    adapters._servers[SOURCE] = server
    discoveries = []
    original = adapter_module.Client

    class Client(original):
        async def list_tools(self, *args, **kwargs):
            discoveries.append(True)
            return await super().list_tools(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "Client", Client)
    return adapters, server, calls, discoveries


async def test_repeated_preflight_and_execution_discovers_unchanged_catalog_once(catalog_fixture):
    adapters, _, calls, discoveries = catalog_fixture
    service = ResearchService(adapters=adapters)
    for value in range(3):
        result = await execute(
            service,
            "query_source",
            {
                "source": SOURCE,
                "operation": "lookup",
                "params": {"value": value},
                "freshness": "fresh",
            },
            scope="cache-test",
        )
        assert result.outcome == "data"
    assert calls == [0, 1, 2]
    assert len(discoveries) == 1


async def test_returned_catalog_cannot_mutate_cached_validator_or_peer_views(catalog_fixture):
    adapters, _, calls, discoveries = catalog_fixture
    catalog = await adapters.catalog(SOURCE)
    original = deepcopy(catalog)
    catalog[0]["input_schema"]["properties"]["value"]["type"] = "string"
    catalog[0]["input_schema"]["required"].clear()
    catalog.append({"name": "injected", "input_schema": {}})
    assert await adapters.catalog(SOURCE) == original
    with pytest.raises(ResearchError, match="input contract"):
        await adapters.call(SOURCE, "lookup", {"value": "wrong"})
    assert not calls and len(discoveries) == 1


@pytest.mark.parametrize("params", [{"value": "wrong"}, {}, {"value": 1, "extra": 2}])
async def test_warm_schema_still_validates_every_request(catalog_fixture, params):
    adapters, _, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", params)
    assert caught.value.code == "invalid_parameters"
    assert not calls and len(discoveries) == 1


async def test_cached_schemas_preserve_atomic_batch_preflight(catalog_fixture):
    adapters, _, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    with pytest.raises(ResearchError) as caught:
        await execute(
            ResearchService(adapters=adapters),
            "batch",
            {
                "calls": [
                    {
                        "operation": "query_source",
                        "arguments": {"source": SOURCE, "operation": "lookup", "params": {"value": 1}},
                    },
                    {
                        "operation": "query_source",
                        "arguments": {
                            "source": SOURCE,
                            "operation": "lookup",
                            "params": {"value": "invalid"},
                        },
                    },
                ]
            },
            scope="cache-test",
        )
    assert caught.value.code == "invalid_parameters"
    assert not calls and len(discoveries) == 1


async def test_concurrent_initial_catalog_discovery_is_coalesced(catalog_fixture):
    adapters, _, calls, discoveries = catalog_fixture
    await asyncio.gather(*(adapters.validate(SOURCE, "lookup", {"value": n}) for n in range(12)))
    assert len(discoveries) == 1 and not calls


async def test_tool_replacement_invalidates_schema_before_next_request(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    server.local_provider.remove_tool("lookup")

    @server.tool
    async def lookup(value: str):
        calls.append(value)
        return {"value": value}

    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters" and not calls
    assert len(discoveries) == 2
    await adapters.call(SOURCE, "lookup", {"value": "accepted"})
    assert calls == ["accepted"] and len(discoveries) == 2


async def test_in_place_schema_change_invalidates_compiled_validator(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    tool = await server.get_tool("lookup")
    tool.parameters["properties"]["value"]["minimum"] = 5
    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters" and not calls
    await adapters.validate(SOURCE, "lookup", {"value": 5})
    assert len(discoveries) == 2


async def test_removed_operation_is_not_retained_in_warm_catalog(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    server.local_provider.remove_tool("lookup")
    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "unknown_operation" and not calls
    assert await adapters.catalog(SOURCE) == [] and len(discoveries) == 2


async def test_schema_compiles_once_but_validation_runs_for_every_request(catalog_fixture, monkeypatch):
    adapters, _, calls, discoveries = catalog_fixture
    compiled, validated = [], []
    original = adapter_module.jsonschema.validators.validator_for

    def factory(schema, **kwargs):
        if kwargs:
            return original(schema, **kwargs)
        validator = original(schema)

        class Spy:
            @staticmethod
            def check_schema(schema):
                compiled.append(True)
                validator.check_schema(schema)

            def __init__(self, schema):
                self.validator = validator(schema)

            def validate(self, params):
                validated.append(deepcopy(params))
                self.validator.validate(params)

        return Spy

    monkeypatch.setattr(adapter_module.jsonschema.validators, "validator_for", factory)
    for value in range(4):
        await adapters.validate(SOURCE, "lookup", {"value": value})
    assert len(compiled) == len(discoveries) == 1
    assert validated == [{"value": value} for value in range(4)] and not calls


async def test_required_configuration_is_checked_after_schema_warms(catalog_fixture, monkeypatch):
    adapters, _, calls, discoveries = catalog_fixture
    monkeypatch.setitem(PROVIDERS[SOURCE], "required_env", ["CATALOG_TEST_TOKEN"])
    monkeypatch.setenv("CATALOG_TEST_TOKEN", "synthetic")
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    monkeypatch.delenv("CATALOG_TEST_TOKEN")
    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "source_unavailable" and not calls
    monkeypatch.setenv("CATALOG_TEST_TOKEN", "synthetic")
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert len(discoveries) == 1


async def test_changed_server_identity_invalidates_catalog(catalog_fixture):
    adapters, _, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    replacement = FastMCP("replacement", version="fixture-2")

    @replacement.tool
    async def lookup(value: str):
        return {"value": value}

    adapters._servers[SOURCE] = replacement
    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters" and not calls
    await adapters.validate(SOURCE, "lookup", {"value": "new"})
    assert len(discoveries) == 2


async def test_tool_version_change_invalidates_highest_version_schema(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})

    @server.tool(version="2")
    async def lookup(value: str):
        return {"value": value}

    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters" and not calls
    await adapters.validate(SOURCE, "lookup", {"value": "new"})
    assert len(discoveries) == 2


async def test_disabled_tool_cannot_be_authorized_by_old_schema(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    server.disable(names={"lookup"})
    with pytest.raises(ResearchError) as caught:
        await adapters.call(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "unknown_operation" and not calls
    server.enable(names={"lookup"})
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert len(discoveries) == 3


async def test_discovery_failure_is_not_cached_and_recovers(catalog_fixture, monkeypatch):
    adapters, _, calls, discoveries = catalog_fixture
    original = adapter_module.Client.list_tools
    first = True

    async def fail_once(self, *args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise ResearchError("adapter_not_installed", "fixture failure")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(adapter_module.Client, "list_tools", fail_once)
    with pytest.raises(ResearchError):
        await adapters.catalog(SOURCE)
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    await adapters.validate(SOURCE, "lookup", {"value": 2})
    assert len(discoveries) == 1 and not calls


async def test_cancelled_discovery_releases_lock_and_does_not_poison_cache(catalog_fixture, monkeypatch):
    adapters, _, calls, discoveries = catalog_fixture
    entered = asyncio.Event()
    original = adapter_module.Client.list_tools
    first = True

    async def pause_once(self, *args, **kwargs):
        nonlocal first
        if first:
            first = False
            entered.set()
            await asyncio.Event().wait()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(adapter_module.Client, "list_tools", pause_once)
    task = asyncio.create_task(adapters.catalog(SOURCE))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(adapters.validate(SOURCE, "lookup", {"value": 1}), 1)
    assert len(discoveries) == 1 and not calls


async def test_schema_change_during_discovery_never_publishes_torn_catalog(catalog_fixture, monkeypatch):
    adapters, server, calls, discoveries = catalog_fixture
    original = adapter_module.Client.list_tools
    first = True

    async def mutate_once(self, *args, **kwargs):
        nonlocal first
        tools = await original(self, *args, **kwargs)
        if first:
            first = False
            (await server.get_tool("lookup")).parameters["properties"]["value"]["minimum"] = 5
        return tools

    monkeypatch.setattr(adapter_module.Client, "list_tools", mutate_once)
    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters"
    await adapters.validate(SOURCE, "lookup", {"value": 5})
    assert len(discoveries) == 2 and not calls


async def test_invalid_changed_schema_fails_closed_and_recovers(catalog_fixture):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    schema = (await server.get_tool("lookup")).parameters["properties"]["value"]
    schema["type"] = "synthetic-schema-secret-sentinel"
    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_adapter_schema"
    assert "sentinel" not in str(caught.value) and not calls
    schema["type"] = "integer"
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert len(discoveries) == 2


async def test_continuously_changing_schema_has_bounded_discovery(catalog_fixture, monkeypatch):
    adapters, server, calls, discoveries = catalog_fixture
    original = adapter_module.Client.list_tools
    schema = (await server.get_tool("lookup")).parameters["properties"]["value"]

    async def mutate(self, *args, **kwargs):
        tools = await original(self, *args, **kwargs)
        schema["minimum"] = schema.get("minimum", 0) + 1
        return tools

    monkeypatch.setattr(adapter_module.Client, "list_tools", mutate)
    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 5})
    assert caught.value.code == "adapter_schema_changed" and caught.value.retryable
    assert len(discoveries) == 3 and not calls


def test_benchmark_is_import_safe_and_blocks_provider_http():
    import runpy
    from pathlib import Path

    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/benchmark-adapters.py"))
    assert callable(module["benchmark"])


async def test_benchmark_modes_produce_same_result_and_record_no_provider_latency():
    import runpy
    from pathlib import Path

    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/benchmark-adapters.py"))
    report = await module["benchmark"](iterations=2, repeats=1)
    assert report["workload"]["provider_requests"] == report["workload"]["provider_latency_ms"] == 0
    assert report["validation"]["catalog_tools"] > 0
    assert set(report["session_comparison"]) == {
        "fresh_mcp_session",
        "reused_mcp_session",
        "direct_typed_function",
    }
    assert all(len(value["milliseconds_per_call"]) == 1 for value in report["session_comparison"].values())


async def test_server_replacement_during_warm_revision_check_uses_new_schema(catalog_fixture, monkeypatch):
    adapters, server, calls, discoveries = catalog_fixture
    await adapters.validate(SOURCE, "lookup", {"value": 1})
    replacement = FastMCP("replacement", version="fixture-2")

    @replacement.tool
    async def lookup(value: str):
        return {"value": value}

    original = server.list_tools

    async def replace_during_revision(*args, **kwargs):
        tools = await original(*args, **kwargs)
        adapters._servers[SOURCE] = replacement
        return tools

    monkeypatch.setattr(server, "list_tools", replace_during_revision)
    with pytest.raises(ResearchError) as caught:
        await adapters.validate(SOURCE, "lookup", {"value": 1})
    assert caught.value.code == "invalid_parameters" and not calls
    await adapters.validate(SOURCE, "lookup", {"value": "new"})
    assert len(discoveries) == 2
