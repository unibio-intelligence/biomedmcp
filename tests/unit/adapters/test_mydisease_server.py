import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp.exceptions import ToolError
from mydisease_mcp.server import ID_FIELDS, mcp

MONDO = "MONDO:0007750"
RECORD = {
    "_id": MONDO,
    "mondo": {"mondo": MONDO, "label": "familial hypercholesterolemia"},
    "disease_ontology": {"doid": "DOID:13810"},
}


def error_code(failure: ToolError) -> str:
    return json.loads(str(failure))["code"]


def respond(payload):
    return lambda request: httpx.Response(200, json=payload)


async def test_search_and_record_reads_keep_upstream_shapes(mocked):
    call = mocked(mcp, respond({"hits": [RECORD], "total": 1}))
    found = await call("search_disease", q="familial hypercholesterolemia")
    assert mocked.requests[0].url.path == "/v1/query" and found["hits"][0]["_id"] == MONDO
    record = await mocked(mcp, respond({**RECORD, "umls": {"cui": "C0020445"}}))(
        "get_disease_by_id", disease_id=MONDO
    )
    assert mocked.requests[-1].url.path == f"/v1/disease/{MONDO}" and record == RECORD


async def test_prevalence_section_reports_orphanet_rows_or_unavailability(mocked):
    row = {
        **RECORD,
        "orphanet": {
            "prevalence": [{"prevalence_class": "1-9 / 100 000", "prevalence_type": "Point prevalence"}]
        },
    }
    result = await mocked(mcp, respond(row))("get_disease_prevalence", disease_id=MONDO)
    assert result["prevalence"]["orphanet.prevalence"][0]["prevalence_class"] == "1-9 / 100 000"
    empty = await mocked(mcp, respond(RECORD))("get_disease_prognosis", disease_id=MONDO)
    assert empty["status"] == "partial" and set(empty["annotation_status"].values()) == {"unavailable"}


async def test_gene_disease_evidence_keeps_only_reported_assertions_for_the_symbol(mocked):
    genes = [{"gene_name": "LDLR", "score": 0.9, "pmids": [1]}, {"gene_name": "APOB", "score": 0.7}]
    row = {**RECORD, "disgenet": {"genes_related_to_disease": genes}}
    result = await mocked(mcp, respond(row))(
        "get_gene_disease_evidence", gene_symbol="LDLR", disease_id=MONDO
    )
    assert result["assertions"] == [{"source": "disgenet", "reported_assertion": genes[0]}]
    assert (
        result["is_associated"] is None
        and result["aggregate_score"] is None
        and result["status"] == "complete"
    )
    absent = await mocked(mcp, respond(RECORD))(
        "get_gene_disease_evidence", gene_symbol="LDLR", disease_id=MONDO
    )
    assert (
        absent["evidence_status"] == "unavailable"
        and absent["section_outcomes"]["get_gene_disease_evidence"]["outcome"] == "partial"
    )


async def test_phenotype_frequency_collects_nested_hpo_rows_verbatim(mocked):
    nested = [
        {"hpo_id": "HP:0003124", "frequency_hp": "HP:0040281"},
        {"hpo_id": "HP:0003124", "frequency": "n/a"},
        {"hpo_id": "HP:0000001"},
    ]
    row = {**RECORD, "hpo": {"phenotype_related_to_disease": nested}}
    result = await mocked(mcp, respond(row))(
        "get_phenotype_frequency", disease_id=MONDO, phenotype_id="HP:0003124"
    )
    assert mocked.requests[0].url.params["fields"] == "hpo"
    assert [a["measurement_status"] for a in result["annotations"]] == ["reported", "unavailable"]
    assert result["annotations"][0]["frequency_hp"] == "HP:0040281" and result["status"] == "partial"


@pytest.mark.parametrize(
    "algorithm,score,numerator,denominator", [("jaccard", 0.5, 2, 4), ("dice", 2 / 3, 4, 6)]
)
async def test_phenotype_similarity_is_exact_overlap_in_one_window(
    mocked, algorithm, score, numerator, denominator
):
    hits = [
        {
            "_id": "MONDO:1",
            "hpo": {
                "phenotype_related_to_disease": [
                    {"hpo_id": "HP:0000001"},
                    {"hpo_id": "HP:0000002"},
                    {"hpo_id": "HP:0000009"},
                ]
            },
        },
        {"_id": "MONDO:2", "hpo": [{"hpo_id": "HP:0000008"}]},
        {"_id": "MONDO:3"},
    ]
    result = await mocked(mcp, respond({"hits": hits, "total": 3}))(
        "get_phenotype_similarity",
        phenotype_list=["HP:0000001", "HP:0000002", "HP:0000003"],
        algorithm=algorithm,
        min_similarity=0.1,
        size=50,
    )
    params = mocked.requests[0].url.params
    assert 'hpo.phenotype_related_to_disease.hpo_id:"HP:0000003"' in params["q"] and params["size"] == "50"
    assert [d["disease_id"] for d in result["diseases"]] == ["MONDO:1"]
    top = result["diseases"][0]
    assert (top["similarity_score"], top["numerator"], top["denominator"]) == (score, numerator, denominator)
    assert top["shared_phenotypes"] == ["HP:0000001", "HP:0000002"]
    assert (
        result["unavailable_annotation_ids"] == ["MONDO:3"] and result["source_window"]["has_more"] is False
    )


async def test_map_disease_ids_batches_by_form_and_never_offers_held_namespaces(mocked):
    assert "umls" not in ID_FIELDS
    rows = [{**RECORD, "query": "DOID:13810"}]
    result = await mocked(mcp, respond(rows))(
        "map_disease_ids", input_ids=["DOID:13810"], from_type="doid", to_types=["mondo"]
    )
    body = parse_qs(mocked.requests[0].content.decode())
    assert body == {"q": ["DOID:13810"], "scopes": ["disease_ontology.doid"], "fields": ["mondo.mondo"]}
    assert (
        result["mappings"][0]["candidates"][0]["mappings"] == {"mondo": [MONDO]}
        and result["status"] == "complete"
    )


async def test_invalid_hpo_identifier_is_rejected_before_http(mocked):
    with pytest.raises(ToolError):
        await mocked(mcp, respond(RECORD))("get_phenotype_frequency", disease_id=MONDO, phenotype_id="HP:1")
    assert not mocked.requests
    with pytest.raises(ToolError) as failure:
        await mocked(mcp, respond([]))(
            "map_disease_ids", input_ids=["A B"], from_type="doid", to_types=["mondo"]
        )
    assert error_code(failure.value) == "invalid_parameters" and not mocked.requests
