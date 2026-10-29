from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client
from native_helpers import HTTP, PUBMED
from test_research_contracts import Adapters

from biomedmcp import cli
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.public_catalog import ADAPTERS, operation_map, schema

VALID = [
    (
        "research",
        {
            "workflow": "variant_dossier",
            "focus": "BRAF V600E",
            "sections": ["cbioportal"],
            "section_parameters": {
                "cbioportal": {"molecular_profile_id": "study_mutations", "sample_list_id": "study_all"}
            },
        },
    ),
    ("search", {"entity": "gene", "query": "BRAF"}),
    ("get", {"entity": "gene", "id": "BRAF", "sections": ["expression"]}),
    (
        "get",
        {
            "entity": "article",
            "id": "PMC123",
            "sections": ["fulltext"],
            "section_parameters": {"fulltext": {"view": "lines", "start": 1, "end": 3}},
        },
    ),
    ("literature_search", {"query": "BRAF", "filters": {"source": "pubmed", "date_from": "2024-01-01"}}),
    ("trial_search", {"query": "melanoma", "filters": {"status": "RECRUITING"}}),
    ("variant_evidence", {"id": "BRAF V600E"}),
    ("study_analysis", {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}),
    ("study_analysis", {"analysis": "survival", "study": "ubi_synthetic", "gene": "TP53", "endpoint": "os"}),
]
INVALID = [
    (
        "query_source",
        {"source": "study", "operation": "survival", "params": {"study": "ubi_synthetic", "gene": "TP53"}},
    ),
    ("search", {"entity": "article", "query": "BRAF"}),
    ("search", {"entity": "trial", "query": "melanoma"}),
    ("search", {"entity": "gene", "query": "BRAF", "filters": {"reviewed": True}}),
    ("get", {"entity": "variant", "id": "BRAF V600E"}),
    ("get", {"entity": "protein", "id": "P15056", "sections": ["expression"]}),
    ("literature_search", {"query": "BRAF", "filters": {"phase": "PHASE3"}}),
    ("trial_search", {"query": "cancer", "filters": {"journal": ["Nature"]}}),
    ("variant_evidence", {"id": "BRAF V600E", "sections": ["expression"]}),
    ("study_analysis", {"analysis": "survival", "study": "ubi_synthetic", "gene": "TP53", "target": "KRAS"}),
    ("study_analysis", {"analysis": "co_occurrence", "study": "ubi_synthetic", "genes": ["TP53"]}),
    ("research", {"workflow": "variant_evidence", "focus": "BRAF V600E"}),
    ("research", {"workflow": "literature_review", "focus": "BRAF"}),
    ("research", {"workflow": "patent_landscape", "focus": "BRAF"}),
    ("research", {"workflow": "study_summary", "focus": "BRAF"}),
]


@pytest.mark.parametrize("name,args", VALID)
def test_advertised_schema_and_runtime_agree_on_valid_calls(name, args):
    jsonschema.validate(args, schema(name))
    ADAPTERS[name].validate_python(args)


@pytest.mark.parametrize("name,args", INVALID)
def test_invalid_and_duplicate_routes_rejected_in_schema_and_runtime(name, args):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(args, schema(name))
    with pytest.raises(ValueError):
        ADAPTERS[name].validate_python(args)


async def test_batch_rejects_duplicate_route_before_scientific_calls():
    http = HTTP()
    adapters = Adapters()
    service = ResearchService(adapters=adapters, http=http)
    with pytest.raises(ResearchError):
        await execute(
            service,
            "batch",
            {
                "calls": [
                    {"operation": "get", "arguments": {"entity": "gene", "id": "BRAF"}},
                    {
                        "operation": "query_source",
                        "arguments": {
                            "source": "study",
                            "operation": "survival",
                            "params": {"study": "ubi_synthetic", "gene": "TP53"},
                        },
                    },
                ]
            },
            scope="alice",
        )
    assert not adapters.calls and not http.calls


async def test_literature_task_mcp_cli_parity_uses_native_provider(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")

    def service(**kwargs):
        return ResearchService(http=HTTP({"esearchresult": {"idlist": ["123"]}}, PUBMED), **kwargs)

    monkeypatch.setattr(cli, "ResearchService", service)
    args = {"query": "BRAF", "filters": {"source": "pubmed", "date_from": "2024-01-01"}}
    local = await cli.execute("literature_search", deepcopy(args))
    async with Client(create_server(service=service())) as client:
        remote = (await client.call_tool("literature_search", deepcopy(args))).data
        tools = {t.name: t.input_schema for t in await client.list_tools()}
    for value in (local, remote):
        assert value["outcome"] == "data"
        assert value["records"][0]["pmid"] == "123"
        assert value["records"][0]["is_retracted"] is True
        assert {p["source"] for p in value["provenance"]} == {"pubmed"}
    assert local["records"] == remote["records"]
    jsonschema.validate(args, tools["literature_search"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"query": "BRAF", "filters": {"phase": "3"}}, tools["literature_search"])


async def test_study_task_executes_native_science_and_reports_denominator(study):
    _, install = study
    install()
    result = await execute(
        ResearchService(),
        "study_analysis",
        {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"},
        scope="alice",
    )
    data = result.sections["study"].data
    assert data["total_samples"] == 4 and data["frequency"] == 0.5
    assert data["denominator"] == "declared mutation-assayed samples"
    assert result.provenance


async def test_capabilities_point_only_to_public_task_owners():
    service = ResearchService()
    variants = await execute(service, "capabilities", {"entity": "variant"}, scope="alice")
    assert "variant_evidence" in variants["schemas"] and "get" not in variants["schemas"]
    study_info = await execute(service, "capabilities", {"source": "study"}, scope="alice")
    assert study_info["operations"] == []
    assert any(row["tool"] == "study_analysis" for row in study_info["canonical_routes"])
    sequence = await execute(service, "capabilities", {"entity": "sequence"}, scope="alice")
    assert sequence["schemas"] == {}
    root = await execute(service, "capabilities", {}, scope="alice")
    assert "variant_evidence" not in root["workflows"]


def test_operation_inventory_has_one_owner_per_primitive():
    rows = operation_map()
    assert len({row["primitive"] for row in rows}) == len(rows)
    mapped = {row["primitive"]: row["tool"] for row in rows}
    assert mapped["search/article"] == "literature_search"
    assert mapped["search/trial"] == "trial_search"
    assert mapped["get/variant/record"] == "variant_evidence"
    assert mapped["get/gene/expression"] == "get"
    assert mapped["get/protein/record"] == "get"
    assert mapped["source/study/survival"] == "study_analysis"


async def test_live_catalog_stays_within_reviewed_schema_budget(monkeypatch):
    import json

    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server()) as client:
        tools = [t.model_dump(mode="json", exclude_none=True) for t in await client.list_tools()]
    assert len(tools) == 13
    from biomedmcp.output_contracts import CATALOG_BYTE_BUDGET

    # Scientific receipts retain independently resolvable schemas in the
    # bounded catalog; external resource refs cannot validate them.
    assert len(json.dumps(tools, separators=(",", ":"), sort_keys=True).encode()) <= CATALOG_BYTE_BUDGET
