"""Synthetic acquisition, cache and actual MCP contracts for held aggregators."""

import importlib
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp.exceptions import ToolError

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError
from biomedmcp.native.biothings import CacheEntry, mappings, response_contract
from biomedmcp.native.catalog import ADVANCED

SENTINEL = "synthetic-api-key-secret-sentinel"
CHEM = {
    "_id": "AAAAAAAAAAAAAA-BBBBBBBBBB-C",
    "query": "CHEMBL1",
    "chembl": {"molecule_chembl_id": "CHEMBL1", "inchikey": "AAAAAAAAAAAAAA-BBBBBBBBBB-C"},
}
DISEASE = {
    "_id": "MONDO:0000001",
    "query": "DOID:1",
    "mondo": {"id": "MONDO:0000001"},
    "disease_ontology": {"doid": "DOID:1"},
}


@pytest.fixture
def mocked_http(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters()

    return install


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        "bad",
        {"error": SENTINEL},
        {"total": 0},
        {"hits": []},
        {"total": True, "hits": []},
        {"total": -1, "hits": []},
        {"total": "0", "hits": []},
        {"total": 0, "hits": [{}]},
        {"total": 1, "hits": [None]},
        {"total": 1, "hits": [{}]},
        {"total": 1, "hits": [{"_id": ""}]},
        {"total": 0, "hits": [], "took": True},
        {"total": 0, "hits": [], "max_score": float("nan")},
        {"total": 0, "hits": [], "success": False},
    ],
)
def test_query_malformed_never_becomes_healthy_empty(value):
    with pytest.raises(ResearchError) as failure:
        response_contract("GET", "query", value)
    assert failure.value.code == "invalid_source_response"
    assert SENTINEL not in str(failure.value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"error": SENTINEL},
        {"_id": None},
        {"_id": 1},
        {"_id": " "},
        {"_id": "1", "success": False},
    ],
)
@pytest.mark.parametrize("endpoint", ["chem/alias", "disease/alias"])
def test_annotation_requires_record_identity(endpoint, value):
    with pytest.raises(ResearchError):
        response_contract("GET", endpoint, value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        "bad",
        [None],
        [{}],
        [{"query": "X"}],
        [{"query": "X", "notfound": "true"}],
        [{"query": "X", "notfound": True, "_id": "1"}],
        [{"query": "X", "_id": "1", "error": SENTINEL}],
    ],
)
@pytest.mark.parametrize("endpoint", ["query", "chem", "disease"])
def test_bulk_requires_explicit_outcomes(endpoint, value):
    with pytest.raises(ResearchError):
        response_contract("POST", endpoint, value)


@pytest.mark.parametrize(
    "value", [[], [CHEM | {"query": "OTHER"}], [CHEM, {"query": "CHEMBL1", "notfound": True}]]
)
def test_bulk_omitted_unknown_contradictory_results_fail_before_storage(value):
    with pytest.raises(ResearchError):
        response_contract("POST", "query", value, {"q": ["CHEMBL1"]})


def test_valid_empty_facet_alias_and_explicit_missingness():
    assert response_contract("GET", "query", {"total": 0, "hits": []})["total"] == 0
    assert response_contract("GET", "query", {"total": 2, "facets": {}}, {"size": 0})["total"] == 2
    assert response_contract("GET", "chem/alias", CHEM)["_id"] != "alias"
    assert response_contract("POST", "query", [{"query": "X", "notfound": True}], {"q": ["X"]})


@pytest.mark.parametrize(
    "source,endpoint,healthy", [("mychem", "chem/alias", CHEM), ("mydisease", "disease/alias", DISEASE)]
)
async def test_invalid_response_uncached_recovery_cached_and_mutation_isolated(
    mocked_http, source, endpoint, healthy
):
    bodies = [{"error": SENTINEL}, healthy]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=bodies[min(len(requests) - 1, 1)])

    mocked_http(handler)
    module = importlib.import_module(source + "_mcp.client")
    client = getattr(module, "MyChemClient" if source == "mychem" else "MyDiseaseClient")(rate_limit=None)
    with pytest.raises(ToolError) as failure:
        await client.get(endpoint)
    assert "invalid_source_response" in str(failure.value)
    assert SENTINEL not in str(failure.value)
    assert not client._cache
    result = await client.get(endpoint)
    result["_id"] = "mutated"
    assert (await client.get(endpoint))["_id"] == healthy["_id"]
    assert len(requests) == 2
    key = client._get_cache_key("GET", endpoint, params=None)
    client._cache[key] = CacheEntry({"error": SENTINEL})
    with pytest.raises(ToolError):
        await client.get(endpoint)
    assert key not in client._cache and len(requests) == 2


@pytest.mark.parametrize(
    "source,operation,params,row",
    [
        (
            "mychem",
            "map_identifiers",
            {"input_ids": ["CHEMBL1"], "from_type": "chembl", "to_types": ["inchikey"]},
            CHEM,
        ),
        (
            "mydisease",
            "map_disease_ids",
            {"input_ids": ["DOID:1"], "from_type": "doid", "to_types": ["mondo"]},
            DISEASE,
        ),
    ],
)
async def test_actual_mcp_bulk_documented_wire_and_ambiguity(mocked_http, source, operation, params, row):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST" and request.url.path == "/v1/query"
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        form = parse_qs(request.content.decode())
        assert form["q"] == params["input_ids"] and "ids" not in form
        return httpx.Response(200, json=[row, row | {"_id": row["_id"] + "2"}])

    result = await mocked_http(handler).call(source, operation, params)
    assert result["status"] == "partial"
    assert result["mappings"][0]["status"] == "ambiguous"
    assert len(result["mappings"][0]["candidates"]) == 2 and len(requests) == 1


@pytest.mark.parametrize(
    "source,operation,params",
    [
        (
            "mychem",
            "map_identifiers",
            {"input_ids": ["CHEMBL1"], "from_type": "chembl", "to_types": ["inchikey"]},
        ),
        (
            "mydisease",
            "map_disease_ids",
            {"input_ids": ["DOID:1"], "from_type": "doid", "to_types": ["mondo"]},
        ),
    ],
)
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_actual_mcp_provider_error_never_logs_credentials(
    mocked_http, capsys, caplog, source, operation, params, status
):
    adapter = mocked_http(lambda request: httpx.Response(status, text=SENTINEL))
    with pytest.raises(ResearchError) as failure:
        await adapter.call(source, operation, params)
    output = capsys.readouterr()
    assert SENTINEL not in str(failure.value) + caplog.text + output.out + output.err


@pytest.mark.parametrize(
    "source,operation", [("mychem", "map_identifiers"), ("mydisease", "map_disease_ids")]
)
@pytest.mark.parametrize(
    "change",
    [
        {"input_ids": []},
        {"input_ids": ["A,B"]},
        {"input_ids": ["A B"]},
        {"to_types": ["unsupported"]},
        {"from_type": "unsupported"},
    ],
)
async def test_invalid_mapping_arguments_fail_before_provider_io(mocked_http, source, operation, change):
    def handler(request):
        pytest.fail("invalid input reached provider")

    params = {
        "input_ids": ["A"],
        "from_type": "chembl" if source == "mychem" else "doid",
        "to_types": ["inchikey" if source == "mychem" else "mondo"],
    } | change
    with pytest.raises(ResearchError):
        await mocked_http(handler).call(source, operation, params)


def test_mapping_missingness_many_values_and_duplicate_inputs():
    fields = {"chembl": "chembl.molecule_chembl_id", "inchikey": "chembl.inchikey"}
    row = CHEM | {"chembl": [{"inchikey": "KEY1"}, {"inchikey": "KEY2"}]}
    result = mappings(
        [row, {"query": "X", "notfound": True}],
        ["CHEMBL1", "CHEMBL1", "X"],
        "chembl",
        ["inchikey"],
        fields,
        False,
    )
    assert result["total_input"] == 3 and result["unique_inputs"] == 2
    assert result["mappings"][0]["candidates"][0]["mappings"]["inchikey"] == ["KEY1", "KEY2"]
    assert result["mappings"][1]["status"] == "not_found"
    assert not result["missing_policy_satisfied"]


@pytest.mark.parametrize(
    "field,value", [("chembl", "bad"), ("chembl", [None]), ("chembl", {"inchikey": {"bad": 1}})]
)
def test_selected_nested_containers_are_not_missing_annotations(field, value):
    payload = CHEM | {field: value}
    if isinstance(value, dict):
        with pytest.raises(ResearchError):
            mappings(
                [payload],
                ["CHEMBL1"],
                "chembl",
                ["inchikey"],
                {"chembl": "chembl.molecule_chembl_id", "inchikey": "chembl.inchikey"},
                True,
            )
    else:
        with pytest.raises(ResearchError):
            response_contract("GET", "chem/alias", payload, {"fields": "chembl.inchikey"})


async def test_retired_computation_names_absent_from_actual_backend_catalog():
    names = {row["name"] for row in await SourceAdapters().catalog("mychem")}
    assert not names & {
        "convert_structure",
        "search_by_structure",
        "search_by_substructure",
        "calculate_similarity_matrix",
    }
    assert ADVANCED["mychem"] == {"get_admet_properties", "map_identifiers"}
    disease_names = {row["name"] for row in await SourceAdapters().catalog("mydisease")}
    assert "get_gene_disease_score" not in disease_names and "get_gene_disease_evidence" in disease_names


@pytest.mark.parametrize(
    "source,operation,params,payload",
    [
        ("mychem", "get_admet_properties", {"chemical_id": "alias"}, CHEM),
        ("mydisease", "get_gene_disease_evidence", {"gene_symbol": "BRAF", "disease_id": "alias"}, DISEASE),
        (
            "mydisease",
            "get_phenotype_frequency",
            {"disease_id": "alias", "phenotype_id": "HP:0000001"},
            DISEASE,
        ),
    ],
)
async def test_actual_mcp_missing_measurements_partial_not_negative(
    mocked_http, source, operation, params, payload
):
    result = await mocked_http(lambda request: httpx.Response(200, json=payload)).call(
        source, operation, params
    )
    assert result["status"] == "partial" and result["record_id"] == payload["_id"]
    if source == "mychem":
        assert set(result["measurement_status"].values()) == {"unavailable"}
        assert result["admet_properties"]["toxicity"] is None
    elif operation == "get_gene_disease_evidence":
        assert result["is_associated"] is None and result["aggregate_score"] is None
        assert result["evidence_status"] == "unavailable"
    else:
        assert result["measurement_status"] == "unavailable" and result["annotations"] == []


async def test_actual_mcp_reported_gene_assertions_no_invented_confidence(mocked_http):
    reported = {"gene_name": "BRAF", "score": 0, "pmids": ["1", "2"]}
    row = DISEASE | {"disgenet": {"genes_related_to_disease": [reported, reported | {"gene_name": "OTHER"}]}}
    result = await mocked_http(lambda request: httpx.Response(200, json=row)).call(
        "mydisease", "get_gene_disease_evidence", {"gene_symbol": "BRAF", "disease_id": "alias"}
    )
    assert len(result["assertions"]) == 1
    assert result["assertions"][0]["reported_assertion"] == reported
    assert "confidence" not in result["assertions"][0] and result["is_associated"] is None


async def test_actual_mcp_admet_repeated_annotations_and_zero_are_preserved(mocked_http):
    row = CHEM | {
        "chembl": [{"toxicity": "source observation"}, {"toxicity": "other observation"}],
        "pubchem": {"logp": 0},
    }
    result = await mocked_http(lambda request: httpx.Response(200, json=row)).call(
        "mychem", "get_admet_properties", {"chemical_id": "alias"}
    )
    assert result["admet_properties"]["toxicity"]["chembl"] == ["source observation", "other observation"]
    assert result["admet_properties"]["physicochemical"]["logp"] == [0]
    assert result["status"] == "partial"


@pytest.mark.parametrize(
    "algorithm,score,numerator,denominator", [("jaccard", 1 / 3, 1, 3), ("dice", 0.5, 2, 4)]
)
async def test_actual_mcp_overlap_denominator_window_and_unavailable_annotations(
    mocked_http, algorithm, score, numerator, denominator
):
    row = DISEASE | {"hpo": [{"hpo_id": "HP:0000001"}, {"hpo_id": "HP:0000002"}]}
    payload = {"total": 101, "hits": [row, {"_id": "MONDO:2"}]}
    result = await mocked_http(lambda request: httpx.Response(200, json=payload)).call(
        "mydisease",
        "get_phenotype_similarity",
        {
            "phenotype_list": ["HP:0000001", "HP:0000003", "HP:0000001"],
            "algorithm": algorithm,
            "min_similarity": 0,
        },
    )
    found = result["diseases"][0]
    assert (
        found["similarity_score"] == score
        and found["numerator"] == numerator
        and found["denominator"] == denominator
    )
    assert result["source_window"]["has_more"] and result["source_window"]["source_total"] == 101
    assert result["unavailable_annotation_ids"] == ["MONDO:2"] and result["status"] == "partial"


async def test_actual_mcp_frequency_preserves_all_exact_rows_and_raw_zero(mocked_http):
    row = DISEASE | {
        "phenotype_related_to_disease": [
            {"hpo_id": "HP:0000001", "frequency": 0},
            {"hpo_id": "HP:0000001", "frequency_hp": "HP:0040281"},
            {"hpo_phenotype": "HP:0000001", "frequency": "wrong identifier field"},
        ],
        "hpo": [{"hpo_id": "HP:0000001"}],
    }
    result = await mocked_http(lambda request: httpx.Response(200, json=row)).call(
        "mydisease", "get_phenotype_frequency", {"disease_id": "alias", "phenotype_id": "HP:0000001"}
    )
    assert len(result["annotations"]) == 3 and result["annotations"][0]["frequency"] == 0
    assert result["annotations"][1]["frequency_hp"] == "HP:0040281"
    assert result["annotations"][2]["measurement_status"] == "unavailable"


@pytest.mark.source_permissions
@pytest.mark.parametrize("source", ["mychem", "mydisease"])
async def test_owner_default_activation_preserves_unresolved_aggregator_rights(source):
    from biomedmcp.source_licensing import review

    assert SourceAdapters().availability(source)[0]
    assert review(source)["review_status"] == "content_review_required"
    assert review(source)["activation_basis"] == "owner_default_allow"


@pytest.mark.parametrize("source", ["mychem", "mydisease"])
@pytest.mark.parametrize("failure_type", [RuntimeError, httpx.ConnectError, httpx.ReadTimeout])
async def test_unexpected_and_network_failures_are_sanitized_before_sdk_logging(
    mocked_http, caplog, capsys, source, failure_type
):
    def handler(request):
        raise failure_type(SENTINEL)

    adapter = mocked_http(handler)
    params = {
        "input_ids": ["A"],
        "from_type": "chembl" if source == "mychem" else "doid",
        "to_types": ["inchikey" if source == "mychem" else "mondo"],
    }
    with pytest.raises(ResearchError):
        await adapter.call(source, "map_identifiers" if source == "mychem" else "map_disease_ids", params)
    output = capsys.readouterr()
    assert SENTINEL not in caplog.text + output.out + output.err


def test_positive_total_without_any_first_window_records_is_not_empty_evidence():
    with pytest.raises(ResearchError):
        response_contract("GET", "query", {"total": 1, "hits": []}, {"size": 10})
    assert response_contract("GET", "query", {"total": 1, "hits": []}, {"size": 10, "from": 1})
    assert response_contract("GET", "query", {"total": 1, "hits": []}, {"size": 0})


@pytest.mark.parametrize("source,row", [("mychem", CHEM), ("mydisease", DISEASE)])
async def test_actual_mcp_duplicate_inputs_query_once_and_preserve_original_counts(mocked_http, source, row):
    def handler(request):
        assert parse_qs(request.content.decode())["q"] == [row["query"]]
        return httpx.Response(200, json=[row])

    operation = "map_identifiers" if source == "mychem" else "map_disease_ids"
    params = {
        "input_ids": [row["query"], row["query"]],
        "from_type": "chembl" if source == "mychem" else "doid",
        "to_types": ["inchikey" if source == "mychem" else "mondo"],
    }
    result = await mocked_http(handler).call(source, operation, params)
    assert result["total_input"] == 2 and result["unique_inputs"] == 1
    assert result["mappings"][0]["status"] == "resolved"


@pytest.mark.parametrize(
    "source,operation,params,payload",
    [
        ("mychem", "get_admet_properties", {"chemical_id": "alias"}, CHEM),
        ("mydisease", "get_gene_disease_evidence", {"gene_symbol": "BRAF", "disease_id": "alias"}, DISEASE),
        (
            "mydisease",
            "get_phenotype_frequency",
            {"disease_id": "alias", "phenotype_id": "HP:0000001"},
            DISEASE,
        ),
        (
            "mydisease",
            "get_phenotype_similarity",
            {"phenotype_list": ["HP:0000001"]},
            {"total": 0, "hits": []},
        ),
    ],
)
async def test_actual_public_mcp_promotes_trusted_annotation_partialness(
    mocked_http, source, operation, params, payload
):
    from fastmcp import Client
    from biomedmcp.domain import ResearchService
    from biomedmcp.mcp.server import create_server

    adapter = mocked_http(lambda request: httpx.Response(200, json=payload))
    async with Client(create_server(service=ResearchService(adapters=adapter))) as client:
        result = (
            await client.call_tool(
                "query_source", {"source": source, "operation": operation, "params": params}
            )
        ).data
    assert result["outcome"] == "partial" and result["sections"][source]["outcome"] == "partial"
