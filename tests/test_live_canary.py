"""All live probes execute canonical adapters against strict offline HTTP."""

import json
import runpy
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import jsonschema
import pytest
from example_helpers import ExampleHTTP
from gtex_helpers import association, expression, gene, page

from biomedmcp import canary, transport
from biomedmcp.contracts import Provenance, ResearchResult, Section
from biomedmcp.domain import ResearchService
from biomedmcp.public_catalog import schema

SCRIPT = Path(__file__).parents[1] / "scripts/live-canary.py"
SENTINEL = "canary-secret-do-not-print-493781"


class CanaryHTTP(ExampleHTTP):
    def __init__(self, failure_status=None):
        super().__init__()
        self.failure_status = failure_status

    def __call__(self, request):
        host, path, params = request.url.host, request.url.path, request.url.params
        if self.failure_status and host == "mygene.info":
            self.requests.append(request)
            return httpx.Response(self.failure_status, text=SENTINEL)
        if host == "gtexportal.org":
            self.requests.append(request)
            if path.endswith("/reference/gene"):
                assert params["gencodeVersion"] == "v39"
                assert params["geneId"] == "PCSK9"
                data = page([gene("PCSK9", "ENSG00000169174.14")])
            else:
                assert params["datasetId"] == "gtex_v10"
                assert params["gencodeId"] == "ENSG00000169174.14"
                assert path.endswith(
                    (
                        "/expression/medianGeneExpression",
                        "/association/singleTissueEqtl",
                        "/association/singleTissueSqtl",
                    )
                ), path
                if "/association/" in path:
                    assert params["tissueSiteDetailId"] == "Thyroid"
                data = page(
                    []
                    if path.endswith("singleTissueSqtl")
                    else [association("PCSK9", "ENSG00000169174.14") if path.endswith("singleTissueEqtl") else expression("PCSK9", "ENSG00000169174.14")]
                )
            data = page(
                data["data"], size=int(params.get("itemsPerPage", 25)), index=int(params.get("page", 0))
            )
        elif host == "api.platform.opentargets.org":
            from opentargets_helpers import association as target_association
            from opentargets_helpers import profile, project

            self.requests.append(request)
            body = json.loads(request.content)
            assert body["variables"]["ensemblId"] == "ENSG00000169174"
            fixture = profile("ENSG00000169174", "PCSK9", rows=[target_association()])
            data = project(
                {
                    "data": {
                        "target": {**fixture["target"], "associatedDiseases": fixture["associated_diseases"]}
                    }
                },
                body["query"],
            )
        elif host == "www.ebi.ac.uk" and "interpro" in path:
            self.requests.append(request)
            assert path == "/interpro/api/entry/interpro/protein/uniprot/Q8NBP7/"
            from interpro_helpers import body, entry

            row = entry()
            row["proteins"][0]["accession"] = "q8nbp7"
            row["proteins"][0]["protein_length"] = 692
            data = body([row])
            row["proteins"][0]["entry_protein_locations"][0]["fragments"][0]["end"] = 650
            data = body([row])
        else:
            return super().__call__(request)
        return httpx.Response(200, json=data)


@pytest.fixture
async def canary_service(monkeypatch):
    router = CanaryHTTP()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(router))
    )
    from gtex_mcp import server as gtex

    await gtex.client.close()
    monkeypatch.setattr(gtex.client, "_rate_limit_delay", 0)
    yield ResearchService(), router
    await gtex.client.close()


def test_import_has_no_argument_parsing_or_output_side_effects():
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; runpy.run_path('scripts/live-canary.py')"],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert runpy.run_path(str(SCRIPT))["CASES"] == canary.CASES


def test_probe_definitions_use_owned_public_routes():
    cases = {case.name: case.operation for case in canary.CASES}
    assert len(cases) == len(canary.CASES) == 10
    assert cases["literature"] == "literature_search"
    assert cases["trials"] == "trial_search"
    assert cases["variant"] == "variant_evidence"


def test_actual_cli_definition_check_blocks_http_and_never_claims_live_health(tmp_path):
    from synthetic_permissions import BOOTSTRAP as PERMISSION_BOOTSTRAP

    output = tmp_path / "definitions.json"
    program = PERMISSION_BOOTSTRAP + (
        "import httpx, runpy, sys; "
        "httpx.AsyncClient.request = lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected HTTP')); "
        "sys.argv = ['live-canary.py', '--validate-only', '--output', sys.argv[1]]; "
        "runpy.run_path('scripts/live-canary.py', run_name='__main__')"
    )
    process = subprocess.run(
        [sys.executable, "-c", program, str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(output.read_text())
    assert report["definitions_valid"] and not report["qualified"]
    assert len(report["cases"]) == 10 and report["mode"] == "definitions_only"


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("status", [200, 503])
async def test_mygene_http_boundary_sanitizes_malformed_json_and_provider_body(monkeypatch, method, status):
    from fastmcp.exceptions import ToolError
    from mygene_mcp.client import MyGeneClient

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text=SENTINEL)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ToolError) as caught:
        client = MyGeneClient()
        if method == "get":
            await client.get("query", params={"q": "PCSK9"})
        else:
            await client.post("query", {"q": ["PCSK9"]})
    assert caught.value.__cause__ is None
    assert SENTINEL not in str(caught.value)
    assert json.loads(str(caught.value))["code"] == (
        "invalid_source_response" if status == 200 else "source_unavailable"
    )
    assert len(requests) == 1 and requests[0].method == method.upper()


@pytest.mark.parametrize("case", canary.CASES, ids=lambda case: case.name)
async def test_each_probe_schema_plan_and_actual_adapter_execution(canary_service, case):
    service, router = canary_service
    jsonschema.validate(case.request(), schema(case.operation))
    plan = await canary.validate_case(service, case)
    assert plan["classification"] == "valid_probe"
    assert router.requests == []
    result = await canary.execute(service, case.operation, case.request(), scope="qualification")
    value = canary.observation(case, result, plan["expected_sections"])
    assert value["passed"], result.model_dump(mode="json")
    assert value["participating_sources"] == sorted(case.sources)
    assert value["classification"] == ("healthy_empty" if case.name == "gtex-sqtl" else "healthy_data")
    assert router.requests
    assert len(value["result_sha256"]) == 64
    assert "records" not in value


async def test_full_suite_preflights_before_first_http_and_qualifies(canary_service, monkeypatch):
    service, router = canary_service
    preflighted = []
    original = canary.validate_case

    async def checked(service, case):
        assert router.requests == []
        value = await original(service, case)
        preflighted.append(case.name)
        return value

    monkeypatch.setattr(canary, "validate_case", checked)
    report = await canary.run(service=service)
    assert preflighted == [case.name for case in canary.CASES]
    assert report["definitions_valid"] and report["qualified"]
    assert canary.exit_code(report) == 0
    assert all(row["observation"]["executed"] for row in report["cases"])


async def test_validation_only_cannot_qualify_live_health(canary_service):
    service, router = canary_service
    report = await canary.run(service=service, validation_only=True)
    assert report["definitions_valid"] and not report["qualified"]
    assert report["mode"] == "definitions_only" and canary.exit_code(report) == 0
    assert router.requests == []
    assert all("observation" not in row for row in report["cases"])


@pytest.mark.parametrize("mutation", ["legacy", "wrong_sources", "missing_tissue", "duplicate", "omitted"])
async def test_invalid_probe_or_missing_coverage_fails_without_io(canary_service, mutation):
    service, router = canary_service
    cases = list(canary.CASES)
    if mutation == "legacy":
        cases[5] = replace(cases[5], operation="search", arguments={"entity": "article", "query": "PCSK9"})
    elif mutation == "wrong_sources":
        cases[4] = replace(cases[4], sources=("opentargets",))
    elif mutation == "missing_tissue":
        cases[2] = replace(cases[2], arguments={"entity": "gene", "id": "PCSK9", "sections": ["eqtl"]})
    elif mutation == "duplicate":
        cases.append(cases[0])
    else:
        cases.pop()
    report = await canary.run(service=service, cases=cases, validation_only=True)
    assert not report["definitions_valid"] and not report["qualified"]
    assert canary.exit_code(report) == 1 and router.requests == []
    if mutation == "omitted":
        assert report["missing_required_cases"] == ["variant"]
    else:
        assert any(row["preflight"]["classification"] == "invalid_probe" for row in report["cases"])


async def test_missing_configuration_distinct_from_provider_failure(canary_service, monkeypatch):
    service, router = canary_service
    original = service.source_availability
    monkeypatch.setattr(
        service,
        "source_availability",
        lambda source: (False, SENTINEL) if source == "gtex" else original(source),
    )
    report = await canary.run(service=service)
    assert not report["qualified"] and canary.exit_code(report) == 1
    affected = [row for row in report["cases"] if row["case"].startswith("gtex-")]
    assert all(
        row["observation"]["classification"] == "missing_configuration" and not row["observation"]["executed"]
        for row in affected
    )
    assert not any(request.url.host == "gtexportal.org" for request in router.requests)
    assert SENTINEL not in json.dumps(report)


@pytest.mark.parametrize("status", [200, 401, 404, 429, 503])
async def test_actual_http_failures_fail_required_qualification_and_hide_bodies(
    canary_service, status, capsys, caplog
):
    service, router = canary_service
    transport.configure()
    router.failure_status = status
    report = await canary.run(service=service)
    assert not report["qualified"] and canary.exit_code(report) == 1
    row = report["cases"][0]["observation"]
    assert row["classification"] == "provider_failure" and not row["passed"]
    assert report["cases"][5]["observation"]["passed"]  # healthy independent PubMed evidence
    captured = capsys.readouterr()
    assert SENTINEL not in json.dumps(report) + captured.out + captured.err + caplog.text


async def test_adapter_import_failure_is_missing_configuration_without_provider_io(
    canary_service, monkeypatch
):
    service, router = canary_service
    import importlib

    original = importlib.import_module

    def missing_module(name, *args, **kwargs):
        if name == "gtex_mcp.server":
            raise ImportError(SENTINEL)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", missing_module)
    report = await canary.run(service=service, validation_only=True)
    assert canary.exit_code(report) == 1 and router.requests == []
    assert report["cases"][1]["preflight"]["classification"] == "missing_configuration"
    assert SENTINEL not in json.dumps(report)


async def test_unexpected_exception_cannot_leak_or_pass(canary_service, monkeypatch):
    service, _ = canary_service
    original = canary.execute

    async def failing(service, operation, arguments, *, scope):
        if arguments.get("entity") == "protein":
            raise RuntimeError(SENTINEL)
        return await original(service, operation, arguments, scope=scope)

    monkeypatch.setattr(canary, "execute", failing)
    report = await canary.run(service=service)
    assert canary.exit_code(report) == 1 and not report["qualified"]
    assert report["cases"][8]["observation"]["classification"] == "runtime_failure"
    assert SENTINEL not in json.dumps(report)


def result_for(case, outcome="data"):
    return ResearchResult(
        outcome=outcome,
        sections={"record": Section(outcome=outcome, data=[] if outcome == "empty" else {"id": "673"})},
        provenance=[
            Provenance(source=source, evidence_id="ev_test", content_hash="a" * 64) for source in case.sources
        ],
    )


@pytest.mark.parametrize(
    "kind", ["empty", "partial", "ambiguous", "missing_section", "missing_provenance", "error_in_data"]
)
def test_positive_control_empty_partial_ambiguity_and_incomplete_proof_fail(kind):
    case = canary.CASES[0]
    result = result_for(case, "empty" if kind == "empty" else "data")
    if kind == "partial":
        result.outcome = "partial"
        result.sections["other"] = Section(
            outcome="unavailable", error={"code": "source_unavailable", "message": SENTINEL}
        )
    elif kind == "ambiguous":
        result.outcome = result.sections["record"].outcome = "ambiguous"
    elif kind == "missing_section":
        result.sections.clear()
    elif kind == "missing_provenance":
        result.provenance.clear()
    elif kind == "error_in_data":
        result.sections["record"].error = {"code": SENTINEL, "message": SENTINEL}
    value = canary.observation(case, result, ["record"])
    assert not value["passed"]
    assert SENTINEL not in json.dumps(value)
    assert (
        value["classification"]
        == {
            "empty": "healthy_empty",
            "partial": "provider_failure",
            "ambiguous": "ambiguous_identity",
            "missing_section": "invalid_result",
            "missing_provenance": "invalid_result",
            "error_in_data": "provider_failure",
        }[kind]
    )


def test_explicit_empty_collection_policy_is_separate_from_positive_control():
    case = replace(canary.CASES[0], allow_empty=True)
    assert canary.observation(case, result_for(case, "empty"), ["record"])["passed"]


@pytest.mark.parametrize("payload", [None, {}, {"message": "no collection"}])
def test_missing_empty_collection_cannot_qualify_as_healthy_empty(payload):
    case = replace(canary.CASES[0], allow_empty=True)
    result = result_for(case, "empty")
    result.sections["record"].data = payload
    value = canary.observation(case, result, ["record"])
    assert not value["passed"] and value["classification"] == "invalid_result"


@pytest.mark.parametrize(
    "code",
    [
        "provider_busy",
        "provider_budget_unavailable",
        "cache_unavailable",
        "cache_invalid_data",
        "operation_timeout",
    ],
)
def test_runtime_failure_is_distinct_from_provider_outage(code):
    case = canary.CASES[0]
    result = result_for(case, "error")
    result.sections["record"].error = {"code": code, "message": SENTINEL}
    value = canary.observation(case, result, ["record"])
    assert value["classification"] == "runtime_failure" and not value["passed"]
    assert value["error_codes"] == [code]
    assert SENTINEL not in json.dumps(value)


@pytest.mark.parametrize("qualified", [True, False])
def test_cli_writes_report_and_returns_required_exit_status(tmp_path, monkeypatch, qualified):
    async def report(**kwargs):
        return {"mode": "live", "qualified": qualified, "definitions_valid": True, "cases": []}

    monkeypatch.setattr(canary, "run", report)
    output = tmp_path / "report.json"
    assert canary.main(["--output", str(output)]) == (0 if qualified else 1)
    assert json.loads(output.read_text())["qualified"] is qualified
