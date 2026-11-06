import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp.exceptions import ToolError
from mychem_mcp.server import mcp

KEY = "OLNTVTPDXPETLC-XPWALMASSA-N"
RECORD = {"_id": KEY, "chembl": {"molecule_chembl_id": "CHEMBL1", "inchikey": KEY, "pref_name": "EZETIMIBE"}}


def error_code(failure: ToolError) -> str:
    return json.loads(str(failure))["code"]


def respond(payload):
    return lambda request: httpx.Response(200, json=payload)


async def test_search_chemical_passes_query_envelope_through(mocked):
    result = await mocked(mcp, respond({"hits": [RECORD], "total": 1}))(
        "search_chemical", q="ezetimibe", size=5, from_=0
    )
    request = mocked.requests[0]
    assert request.url.host == "mychem.info" and request.url.path == "/v1/query"
    assert request.url.params["q"] == "ezetimibe" and request.url.params["size"] == "5"
    assert result["hits"][0]["_id"] == KEY and result["total"] == 1


async def test_get_chemical_by_id_fetches_annotation_and_drops_held_fields(mocked):
    row = {**RECORD, "sider": {"held": True}, "umls": {"cui": "C1"}}
    result = await mocked(mcp, respond(row))("get_chemical_by_id", chemical_id=KEY, dotfield=True)
    request = mocked.requests[0]
    assert request.url.path == f"/v1/chem/{KEY}" and request.url.params["dotfield"] == "true"
    assert result == RECORD


async def test_drug_targets_section_marks_unavailable_annotations(mocked):
    row = {**RECORD, "drugcentral": {"bioactivity": [{"target_name": "NPC1L1", "action_type": "INHIBITOR"}]}}
    result = await mocked(mcp, respond(row))("get_drug_targets", drug_id=KEY)
    assert "drugcentral.bioactivity" in mocked.requests[0].url.params["fields"]
    assert result["targets"] == {
        "drugcentral.bioactivity": [{"target_name": "NPC1L1", "action_type": "INHIBITOR"}]
    }
    assert result["annotation_status"]["drugbank.targets"] == "unavailable" and result["status"] == "complete"
    empty = await mocked(mcp, respond(RECORD))("get_disease_associations", chemical_id=KEY)
    assert empty["status"] == "partial" and empty["indications"] == {}


async def test_admet_reports_values_per_modality_without_predictions(mocked):
    row = {
        **RECORD,
        "drugbank": {"half_life": "22 hours", "toxicity": "LD50 > 5 g/kg"},
        "pubchem": {"xlogp": 4.5},
    }
    result = await mocked(mcp, respond(row))("get_admet_properties", chemical_id=KEY)
    assert result["admet_properties"]["excretion"] == {"drugbank": ["22 hours"]}
    assert result["admet_properties"]["toxicity"] == {"drugbank": ["LD50 > 5 g/kg"]}
    assert result["admet_properties"]["physicochemical"] == {"logp": [4.5]}
    assert (
        result["admet_properties"]["absorption"] is None
        and result["measurement_status"]["absorption"] == "unavailable"
    )
    assert result["status"] == "partial" and result["section_outcomes"] == {
        "get_admet_properties": {"outcome": "partial"}
    }


async def test_map_identifiers_uses_form_batch_and_reports_candidates(mocked):
    rows = [{**RECORD, "query": "CHEMBL1"}, {"query": "CHEMBL2", "notfound": True}]
    result = await mocked(mcp, respond(rows))(
        "map_identifiers",
        input_ids=["CHEMBL1", "CHEMBL2"],
        from_type="chembl",
        to_types=["inchikey", "pubchem"],
    )
    body = parse_qs(mocked.requests[0].content.decode())
    assert mocked.requests[0].method == "POST" and body["q"] == ["CHEMBL1,CHEMBL2"]
    assert body["scopes"] == ["chembl.molecule_chembl_id"] and "pubchem.cid" in body["fields"][0]
    first, second = result["mappings"]
    assert first["status"] == "resolved" and first["candidates"][0]["mappings"] == {
        "inchikey": [KEY],
        "pubchem": None,
    }
    assert second["status"] == "not_found" and result["unmapped_ids"] == ["CHEMBL2"]


async def test_map_identifiers_rejects_unknown_namespace_before_http(mocked):
    with pytest.raises(ToolError) as failure:
        await mocked(mcp, respond([]))(
            "map_identifiers", input_ids=["X"], from_type="smiles", to_types=["chembl"]
        )
    assert error_code(failure.value) == "invalid_parameters" and not mocked.requests
