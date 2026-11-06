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
        "build_dossier",
        {
            "workflow": "variant_dossier",
            "focus": "BRAF V600E",
            "sections": ["cbioportal"],
            "section_parameters": {
                "cbioportal": {"molecular_profile_id": "study_mutations", "sample_list_id": "study_all"}
            },
        },
    ),
    ("search_records", {"entity": "gene", "query": "BRAF"}),
    ("get_record", {"entity": "gene", "id": "BRAF", "sections": ["expression"]}),
    (
        "get_record",
        {
            "entity": "article",
            "id": "PMC123",
            "sections": ["fulltext"],
            "section_parameters": {"fulltext": {"view": "lines", "start": 1, "end": 3}},
        },
    ),
    ("search_literature", {"query": "BRAF", "filters": {"source": "pubmed", "date_from": "2024-01-01"}}),
    ("search_trials", {"query": "melanoma", "filters": {"status": "RECRUITING"}}),
    ("get_variant_evidence", {"id": "BRAF V600E"}),
    ("analyze_study", {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"}),
    ("analyze_study", {"analysis": "survival", "study": "ubi_synthetic", "gene": "TP53", "endpoint": "os"}),
]
INVALID = [
    (
        "query_source",
        {"source": "study", "operation": "survival", "params": {"study": "ubi_synthetic", "gene": "TP53"}},
    ),
    ("search_records", {"entity": "article", "query": "BRAF"}),
    ("search_records", {"entity": "trial", "query": "melanoma"}),
    ("search_records", {"entity": "gene", "query": "BRAF", "filters": {"reviewed": True}}),
    ("get_record", {"entity": "variant", "id": "BRAF V600E"}),
    ("get_record", {"entity": "protein", "id": "P15056", "sections": ["expression"]}),
    ("search_literature", {"query": "BRAF", "filters": {"phase": "PHASE3"}}),
    ("search_trials", {"query": "cancer", "filters": {"journal": ["Nature"]}}),
    ("get_variant_evidence", {"id": "BRAF V600E", "sections": ["expression"]}),
    ("analyze_study", {"analysis": "survival", "study": "ubi_synthetic", "gene": "TP53", "target": "KRAS"}),
    ("analyze_study", {"analysis": "co_occurrence", "study": "ubi_synthetic", "genes": ["TP53"]}),
    ("build_dossier", {"workflow": "variant_evidence", "focus": "BRAF V600E"}),
    ("build_dossier", {"workflow": "literature_review", "focus": "BRAF"}),
    ("build_dossier", {"workflow": "patent_landscape", "focus": "BRAF"}),
    ("build_dossier", {"workflow": "study_summary", "focus": "BRAF"}),
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
            "run_batch",
            {
                "calls": [
                    {"operation": "get_record", "arguments": {"entity": "gene", "id": "BRAF"}},
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
    local = await cli.execute("search_literature", deepcopy(args))
    async with Client(create_server(service=service())) as client:
        remote = (await client.call_tool("search_literature", deepcopy(args))).data
        tools = {t.name: t.input_schema for t in await client.list_tools()}
    for value in (local, remote):
        assert value["outcome"] == "data"
        assert value["records"][0]["pmid"] == "123"
        assert value["records"][0]["is_retracted"] is True
        assert {p["source"] for p in value["provenance"]} == {"pubmed"}
    assert local["records"] == remote["records"]
    jsonschema.validate(args, tools["search_literature"])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"query": "BRAF", "filters": {"phase": "3"}}, tools["search_literature"])


async def test_study_task_executes_native_science_and_reports_denominator(study):
    _, install = study
    install()
    result = await execute(
        ResearchService(),
        "analyze_study",
        {"analysis": "gene_profile", "study": "ubi_synthetic", "gene": "TP53"},
        scope="alice",
    )
    data = result.sections["study"].data
    assert data["total_samples"] == 4 and data["frequency"] == 0.5
    assert data["denominator"] == "declared mutation-assayed samples"
    assert result.provenance


async def test_capabilities_point_only_to_public_task_owners():
    service = ResearchService()
    variants = await execute(service, "get_capabilities", {"entity": "variant"}, scope="alice")
    assert "get_variant_evidence" in variants["schemas"] and "get_record" not in variants["schemas"]
    study_info = await execute(service, "get_capabilities", {"source": "study"}, scope="alice")
    assert study_info["operations"] == []
    assert any(row["tool"] == "analyze_study" for row in study_info["canonical_routes"])
    sequence = await execute(service, "get_capabilities", {"entity": "sequence"}, scope="alice")
    assert sequence["schemas"] == {}
    root = await execute(service, "get_capabilities", {}, scope="alice")
    assert "variant_evidence" not in root["workflows"]


def test_operation_inventory_has_one_owner_per_primitive():
    rows = operation_map()
    assert len({row["primitive"] for row in rows}) == len(rows)
    mapped = {row["primitive"]: row["tool"] for row in rows}
    assert mapped["search/article"] == "search_literature"
    assert mapped["search/trial"] == "search_trials"
    assert mapped["get/variant/record"] == "get_variant_evidence"
    assert mapped["get/gene/expression"] == "get_record"
    assert mapped["get/protein/record"] == "get_record"
    assert mapped["source/study/survival"] == "analyze_study"


async def test_live_catalog_stays_within_reviewed_schema_budget(monkeypatch):
    import json

    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server()) as client:
        tools = [t.model_dump(mode="json", exclude_none=True) for t in await client.list_tools()]
    assert len(tools) == 13
    from biomedmcp.output_contracts import (
        CATALOG_BYTE_BUDGET,
        MODEL_VISIBLE_BYTE_BUDGET,
        TOOL_DESCRIPTION_BYTE_LIMIT,
    )

    # Scientific receipts retain independently resolvable schemas in the
    # bounded catalog; external resource refs cannot validate them.
    assert len(json.dumps(tools, separators=(",", ":"), sort_keys=True).encode()) <= CATALOG_BYTE_BUDGET
    visible = [{k: v for k, v in tool.items() if k != "output_schema"} for tool in tools]
    assert (
        len(json.dumps(visible, separators=(",", ":"), sort_keys=True).encode()) <= MODEL_VISIBLE_BYTE_BUDGET
    )
    for tool in tools:
        assert len(tool["description"].encode()) <= TOOL_DESCRIPTION_BYTE_LIMIT, tool["name"]
        assert tool["title"] and "_" in tool["name"], tool["name"]


@pytest.mark.parametrize(
    "native,public",
    [
        ({"tool": "search", "arguments": {"entity": "gene", "query": "BRAF"}}, "search_records"),
        ({"tool": "search", "arguments": {"entity": "article", "query": "BRAF"}}, "search_literature"),
        ({"tool": "get", "arguments": {"entity": "gene", "id": "BRAF"}}, "get_record"),
        ({"tool": "get", "arguments": {"entity": "variant", "id": "BRAF V600E"}}, "get_variant_evidence"),
        (
            {"tool": "get_record", "arguments": {"entity": "variant", "id": "BRAF V600E"}},
            "get_variant_evidence",
        ),
        ({"tool": "resolve", "arguments": {"query": "BRAF", "entity": "gene"}}, "resolve_entity"),
        (
            {"tool": "relate", "arguments": {"entity": "gene", "id": "BRAF", "relation": "articles"}},
            "find_related",
        ),
    ],
)
def test_native_follow_up_actions_are_published_under_public_names(native, public):
    from biomedmcp.public_catalog import validated_action

    assert validated_action(native)["tool"] == public


@pytest.mark.parametrize(
    "superseded,args",
    [
        ("search", {"entity": "gene", "query": "BRAF"}),
        ("get", {"entity": "gene", "id": "BRAF"}),
        ("literature_search", {"query": "BRAF"}),
        ("variant_evidence", {"id": "BRAF V600E"}),
        ("research", {"workflow": "target_dossier", "focus": "BRAF"}),
        ("batch", {"calls": [{"operation": "get_record", "arguments": {"entity": "gene", "id": "BRAF"}}]}),
    ],
)
async def test_superseded_tool_names_are_not_aliases(monkeypatch, superseded, args):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server()) as client:
        assert superseded not in {tool.name for tool in await client.list_tools()}
    with pytest.raises(ResearchError):
        await execute(ResearchService(), superseded, args, scope="local")
