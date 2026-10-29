"""Delivered evidence must bind its validated task and acquired source windows."""

import json
from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client
from native_helpers import HTTP, JATS

from biomedmcp import cli
from biomedmcp.contracts import Entity, Provenance, ResearchResult, Section
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.output_contracts import output_schema
from biomedmcp.runtime import digest


def fulltext(identifier="PMC123"):
    return {
        "entity": "article",
        "id": identifier,
        "sections": ["fulltext"],
        "section_parameters": {"fulltext": {"view": "lines"}},
    }


def receipt(result):
    value = result.model_dump(mode="json") if isinstance(result, ResearchResult) else result
    record = value["receipt"]
    content = deepcopy(value)
    content["receipt"].pop("result_sha256")
    assert record["result_sha256"] == digest(content)
    if record["request"] is not None:
        assert record["request_sha256"] == digest(record["request"])
    return record


@pytest.mark.asyncio
async def test_real_mcp_receipt_binds_normalized_fulltext_and_delivered_lines(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP(JATS)
    async with Client(create_server(service=ResearchService(http=http))) as client:
        result = await client.call_tool_mcp("get", fulltext())
    assert not result.is_error
    value = result.structured_content
    record = receipt(value)
    assert record["operation"] == "get" and record["request"]["species"] == 9606
    assert record["request"]["section_parameters"]["fulltext"] == {"view": "lines", "start": 1, "end": 100}
    assert record["sources"] == ["europepmc"]
    assert record["implementation"].startswith("biomedmcp/") and record["schema_version"] == "1.0"
    assert record["reproduction"] == "not_established" and record["time_dependent"]
    assert value["provenance"][0]["source_version"] is None
    assert record["completed_at"] >= value["provenance"][0]["retrieved_at"]
    assert json.loads(result.content[0].text) == value
    jsonschema.validate(value, output_schema("get"))


@pytest.mark.asyncio
async def test_cached_window_keeps_original_retrieval_time_and_canonical_request_hash():
    http = HTTP(JATS)
    service = ResearchService(http=http)
    first = (await execute(service, "get", fulltext(), scope="local")).model_dump(mode="json")
    second = (await execute(service, "get", fulltext(), scope="local")).model_dump(mode="json")
    left, right = receipt(first), receipt(second)
    assert left["request_sha256"] == right["request_sha256"]
    assert first["provenance"][0]["retrieved_at"] == second["provenance"][0]["retrieved_at"]
    assert not first["provenance"][0]["cached"] and second["provenance"][0]["cached"]
    assert right["sources"] == ["europepmc"] and len(http.calls) == 1


@pytest.mark.asyncio
async def test_batch_receipts_keep_each_request_and_participation_separate(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    calls = [{"operation": "get", "arguments": fulltext(i)} for i in ["PMC123", "PMC456"]]
    async with Client(create_server(service=ResearchService(http=HTTP(JATS, JATS)))) as client:
        result = await client.call_tool_mcp("batch", {"calls": calls})
    assert not result.is_error
    values = result.structured_content["results"]
    assert [receipt(v)["request"]["id"] for v in values] == ["PMC123", "PMC456"]
    assert receipt(values[0])["request_sha256"] != receipt(values[1])["request_sha256"]
    assert all(receipt(v)["sources"] == ["europepmc"] for v in values)
    jsonschema.validate(result.structured_content, output_schema("batch"))


@pytest.mark.asyncio
async def test_failed_acquisition_is_participation_but_never_absence():
    http = HTTP(ResearchError("source_unavailable", "Synthetic outage", retryable=True))
    value = (await execute(ResearchService(http=http), "get", {**fulltext(), "sources": ["europepmc"]}, scope="local")).model_dump(
        mode="json"
    )
    assert value["outcome"] == "error"
    assert receipt(value)["sources"] == ["europepmc"]
    assert value["provenance"] == [] and value["sections"]["fulltext"]["outcome"] == "unavailable"


class ResultService:
    def __init__(self, result):
        self.result = result

    async def get(self, request, *, scope, _plan_only=False):
        if not _plan_only:
            return self.result.model_copy(deep=True)


def example_result():
    return ResearchResult(
        entity="protein",
        outcome="data",
        sections={"record": Section(outcome="data", data={"id": "P12345", "measurement": 0})},
        provenance=[
            Provenance(
                evidence_id="ev_fixed",
                source="uniprot",
                content_hash=digest({"id": "P12345"}),
                retrieved_at="2026-01-01T00:00:00+00:00",
            )
        ],
    )


@pytest.mark.asyncio
async def test_verification_detects_identity_missingness_and_request_tampering():
    from biomedmcp.receipts import verify_receipt

    value = (
        await execute(
            ResultService(example_result()),
            "get",
            {"entity": "protein", "id": "P12345"},
            scope="account-must-not-be-exported",
        )
    ).model_dump(mode="json")
    assert verify_receipt(value) and "account-must-not-be-exported" not in json.dumps(value)
    changes = [
        lambda v: v["sections"]["record"]["data"].update(measurement=None),
        lambda v: v["provenance"][0].update(source="other"),
        lambda v: v["receipt"]["request"].update(id="P99999"),
        lambda v: v["receipt"].update(result_sha256="0" * 64),
        lambda v: v["receipt"].update(request_sha256="0" * 64),
    ]
    for change in changes:
        modified = deepcopy(value)
        change(modified)
        assert not verify_receipt(modified)


@pytest.mark.asyncio
async def test_hashes_safe_links_and_final_budgeted_payload():
    result = example_result()
    # Assignment after construction lets dispatch apply the final envelope budget.
    result.sections["record"].data = {
        "url": "file:///private/forged",
        "lots": [str(i) + "x" * 3500 for i in range(80)],
    }
    value = (
        await execute(ResultService(result), "get", {"entity": "protein", "id": "P12345"}, scope="local")
    ).model_dump(mode="json")
    assert value["truncated"] and value["sections"]["record"]["truncated"] and value["rejected_links"]
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 120000
    receipt(value)


@pytest.mark.asyncio
async def test_local_cli_emits_receipt_contract(monkeypatch, tmp_path):
    http = HTTP(JATS)
    monkeypatch.setattr(cli, "ResearchService", lambda **kwargs: ResearchService(http=http, **kwargs))
    result = await cli.execute("get", fulltext(), state_dir=tmp_path / "state")
    assert receipt(result)["operation"] == "get" and receipt(result)["sources"] == ["europepmc"]


@pytest.mark.asyncio
async def test_known_secret_is_redacted_before_request_hashing(monkeypatch):
    monkeypatch.setenv("FIXTURE_API_KEY", "known-synthetic-secret")
    value = (
        await execute(
            ResultService(example_result()),
            "get",
            {"entity": "protein", "id": "known-synthetic-secret"},
            scope="local",
        )
    ).model_dump(mode="json")
    record = receipt(value)
    assert record["request_redacted"] and not record["request_omitted"]
    assert "known-synthetic-secret" not in json.dumps(record) and "[REDACTED]" in json.dumps(record)


@pytest.mark.asyncio
async def test_large_request_keeps_digest_without_unbounded_export():
    class SourceService:
        async def source(
            self, source, operation, params, *, scope, freshness="cached_if_fresh", _plan_only=False
        ):
            if not _plan_only:
                return example_result()

    arguments = {"source": "chembl", "operation": "search_compounds", "params": {"query": "x" * 12000}}
    value = (await execute(SourceService(), "query_source", arguments, scope="local")).model_dump(mode="json")
    record = receipt(value)
    assert record["request"] is None and record["request_omitted"] and not record["request_redacted"]
    assert len(record["request_sha256"]) == 64 and len(json.dumps(record).encode()) < 1500


@pytest.mark.asyncio
async def test_schema_rejects_missing_malformed_receipts_and_false_replay_claims():
    value = (
        await execute(
            ResultService(example_result()), "get", {"entity": "protein", "id": "P12345"}, scope="local"
        )
    ).model_dump(mode="json")
    for bad in [
        None,
        {},
        {**value["receipt"], "result_sha256": "not-a-hash"},
        {**value["receipt"], "reproduction": "exact"},
    ]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**value, "receipt": bad}, output_schema("get"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({k: v for k, v in value.items() if k != "receipt"}, output_schema("get"))


@pytest.mark.asyncio
async def test_runtime_observation_includes_identity_dependency_and_excludes_provider_claims():
    from biomedmcp.runtime import ProviderRuntime

    class Dependencies(ResultService):
        async def get(self, request, *, scope, _plan_only=False):
            if _plan_only:
                return
            runtime = ProviderRuntime()
            await runtime.invoke("mygene", {}, lambda: identity(), scope=scope)
            await runtime.invoke("gtex", {}, lambda: measurement(), scope=scope)
            return ResearchResult(
                outcome="data",
                sections={
                    "expression": Section(outcome="data", data={"sources": ["forged-provider"], "median": 0})
                },
            )

    async def identity():
        return {"symbol": "BRAF", "taxid": 9606}

    async def measurement():
        return {"median": 0}

    value = await execute(
        Dependencies(example_result()),
        "get",
        {"entity": "gene", "id": "BRAF", "sections": ["expression"]},
        scope="local",
    )
    assert receipt(value)["sources"] == ["gtex", "mygene"]
    assert value.sections["expression"].data["median"] == 0
    assert value.sections["expression"].data["sources"] == ["forged-provider"]


@pytest.mark.asyncio
async def test_concurrent_batch_participants_do_not_leak_between_items():
    import asyncio

    from biomedmcp.runtime import ProviderRuntime

    class Concurrent:
        async def get(self, request, *, scope, _plan_only=False):
            if _plan_only:
                return

            async def read():
                await asyncio.sleep(0.001)
                return {"measurement": 0}

            await ProviderRuntime().invoke(request.id, {}, read, scope=scope)
            return ResearchResult(
                outcome="data", sections={"record": Section(outcome="data", data={"measurement": 0})}
            )

    result = await execute(
        Concurrent(),
        "batch",
        {
            "calls": [
                {"operation": "get", "arguments": {"entity": "protein", "id": source}}
                for source in ["gtex", "uniprot"]
            ]
        },
        scope="local",
    )
    assert [receipt(item)["sources"] for item in result["results"]] == [["gtex"], ["uniprot"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "search",
        "get",
        "literature_search",
        "trial_search",
        "variant_evidence",
        "study_analysis",
        "resolve",
        "relate",
        "research",
        "query_source",
    ],
)
async def test_every_scientific_public_operation_keeps_its_task_identity(operation):
    from biomedmcp.examples import EXAMPLES

    example = next(item for item in EXAMPLES if item.operation == operation)

    class Service:
        def __getattr__(self, name):
            async def run(*args, **kwargs):
                if not kwargs.get("_plan_only"):
                    result = example_result()
                    result.entity = {
                        "trial_search": Entity.trial,
                        "variant_evidence": Entity.variant,
                        "study_analysis": None,
                    }.get(operation, result.entity)
                    return result

            return run

    value = (await execute(Service(), operation, example.arguments, scope="local")).model_dump(mode="json")
    assert receipt(value)["operation"] == operation
    assert value["receipt"]["reproduction"] == "not_established"
    jsonschema.validate(value, output_schema(operation))
    from biomedmcp.receipts import verify_receipt

    assert verify_receipt(value)


@pytest.mark.asyncio
async def test_changed_receipt_metadata_invalidates_delivered_result_digest():
    from biomedmcp.receipts import verify_receipt

    value = (
        await execute(
            ResultService(example_result()), "get", {"entity": "protein", "id": "P12345"}, scope="local"
        )
    ).model_dump(mode="json")
    for key, replacement in [
        ("operation", "resolve"),
        ("sources", ["other"]),
        ("completed_at", "2026-01-01T00:00:00Z"),
        ("implementation", "biomedmcp/0.1.0"),
        ("time_dependent", False),
    ]:
        modified = deepcopy(value)
        modified["receipt"][key] = replacement
        assert not verify_receipt(modified)


@pytest.mark.asyncio
async def test_equivalent_default_requests_have_identical_normalized_request_hashes():
    service = ResultService(example_result())
    base = {"entity": "protein", "id": "P12345"}
    first = receipt(await execute(service, "get", base, scope="one"))
    second = receipt(
        await execute(
            service,
            "get",
            {**base, "species": 9606, "freshness": "cached_if_fresh", "sections": []},
            scope="two",
        )
    )
    assert first["request"] == second["request"]
    assert first["request_sha256"] == second["request_sha256"]


@pytest.mark.asyncio
async def test_request_credential_keys_are_not_saved_or_hashed_as_credentials():
    class SourceService:
        async def source(self, *args, **kwargs):
            if not kwargs.get("_plan_only"):
                return example_result()

    arguments = {
        "source": "chembl",
        "operation": "search_compounds",
        "params": {"query": "BRAF", "client_secret": "synthetic-not-configured"},
    }
    value = receipt(await execute(SourceService(), "query_source", arguments, scope="local"))
    assert value["request_redacted"]
    assert value["request"]["params"]["client_secret"] == "[REDACTED]"
    assert "synthetic-not-configured" not in json.dumps(value)


@pytest.mark.asyncio
async def test_receipt_byte_cost_can_trigger_omission_and_hash_still_binds_final_content():
    result = example_result()
    result.sections["record"].data = {"rows": ["x" * 3600 for _ in range(32)]}
    # Before receipt, this is just under the public envelope ceiling.
    assert len(json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode()) < 120000

    class Service:
        async def source(self, *args, **kwargs):
            if not kwargs.get("_plan_only"):
                return result.model_copy(deep=True)

    args = {"source": "chembl", "operation": "search_compounds", "params": {"query": "x" * 6000}}
    value = (await execute(Service(), "query_source", args, scope="local")).model_dump(mode="json")
    assert value["sections"]["record"]["data"].get("omitted") and value["truncated"]
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 120000
    receipt(value)
