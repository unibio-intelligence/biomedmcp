"""ChEMBL property types and coverage must preserve scientific meaning."""

from copy import deepcopy

import httpx
import pytest
from example_helpers import CHEMBL_PROPERTIES

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError


@pytest.fixture
def chemical_response(monkeypatch):
    original = httpx.AsyncClient

    def install(payload):
        def handler(request):
            assert request.url.path == "/chembl/api/data/molecule/CHEMBL25.json"
            if callable(payload):
                return payload(request)
            return httpx.Response(200, json=payload)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
        )
        return SourceAdapters()

    return install


PARAMS = {"chembl_id": "CHEMBL25", "property_type": "drug_likeness"}


def molecule(properties):
    return {"molecule_chembl_id": "CHEMBL25", "molecule_properties": properties}


async def test_provider_numeric_strings_are_normalized_and_raw_assertions_retained(chemical_response):
    result = await chemical_response(molecule(CHEMBL_PROPERTIES)).call(
        "chembl", "analyze_compound_properties", PARAMS
    )
    assessment = result["drug_likeness"]["lipinski_rule_of_five"]
    assert assessment["molecular_weight"] == {
        "value": 180.16,
        "unit": "g/mol",
        "threshold": 500,
        "pass": True,
    }
    assert (
        assessment["logp"]["value"] == 1.31
        and assessment["violations"] == 0
        and assessment["drug_like"] is True
    )
    assert result["properties"]["full_mwt"] == "180.16"
    assert result["compound_info"]["molecule_chembl_id"] == "CHEMBL25"


@pytest.mark.parametrize(
    "properties", [{}, None, {**CHEMBL_PROPERTIES, "full_mwt": None}, {**CHEMBL_PROPERTIES, "alogp": ""}]
)
async def test_missing_measurements_never_become_a_positive_assessment(chemical_response, properties):
    adapter = chemical_response(molecule(properties))
    result = await execute(
        ResearchService(adapters=adapter),
        "query_source",
        {"source": "chembl", "operation": "analyze_compound_properties", "params": PARAMS},
        scope="chemical-test",
    )
    assert result.outcome == "partial"
    section = result.sections["chembl"]
    assessment = section.data["drug_likeness"]["lipinski_rule_of_five"]
    assert assessment["drug_like"] is None and assessment["violations"] is None
    assert section.data["section_outcomes"]["drug_likeness"] == "unavailable"
    assert section.warnings and result.provenance


@pytest.mark.parametrize(
    "properties,violations,drug_like",
    [
        ({"full_mwt": "500", "alogp": "5", "hbd": "5", "hba": "10"}, 0, True),
        ({"full_mwt": "500.1", "alogp": "5", "hbd": "5", "hba": "10"}, 1, True),
        ({"full_mwt": "500.1", "alogp": "5.1", "hbd": "5", "hba": "10"}, 2, False),
        ({"full_mwt": "180.16", "alogp": "-1", "hbd": 1, "hba": 3}, 0, True),
    ],
)
async def test_assessment_uses_thresholds_and_complete_inputs(
    chemical_response, properties, violations, drug_like
):
    result = await chemical_response(molecule(properties)).call(
        "chembl", "analyze_compound_properties", PARAMS
    )
    assessment = result["drug_likeness"]["lipinski_rule_of_five"]
    assert assessment["violations"] == violations and assessment["drug_like"] is drug_like
    assert assessment["provider_violations"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("full_mwt", "synthetic-chemical-sentinel"),
        ("full_mwt", "nan"),
        ("full_mwt", "inf"),
        ("full_mwt", -1),
        ("full_mwt", 0),
        ("alogp", True),
        ("hbd", -1),
        ("hba", "1.5"),
        ("hba", []),
        ("num_ro5_violations", "bad"),
        ("num_ro5_violations", 5),
    ],
)
async def test_malformed_measurements_fail_without_logging_raw_provider_values(
    chemical_response, caplog, capsys, field, value
):
    props = {**CHEMBL_PROPERTIES, field: value}
    with pytest.raises(ResearchError) as caught:
        await chemical_response(molecule(props)).call("chembl", "analyze_compound_properties", PARAMS)
    assert caught.value.code == "invalid_source_response"
    captured = capsys.readouterr()
    assert "synthetic-chemical-sentinel" not in str(caught.value) + caplog.text + captured.out + captured.err


@pytest.mark.parametrize(
    "payload", [{}, [], {"molecule_chembl_id": "CHEMBL_OTHER"}, molecule([]), molecule("bad")]
)
async def test_wrong_identity_and_nonobject_property_records_fail_closed(chemical_response, payload):
    with pytest.raises(ResearchError):
        await chemical_response(payload).call("chembl", "analyze_compound_properties", PARAMS)


async def test_conflicting_provider_violation_count_is_preserved_independently(chemical_response):
    props = deepcopy(CHEMBL_PROPERTIES)
    props["num_ro5_violations"] = 2
    result = await chemical_response(molecule(props)).call("chembl", "analyze_compound_properties", PARAMS)
    assessment = result["drug_likeness"]["lipinski_rule_of_five"]
    assert assessment["violations"] == 0 and assessment["provider_violations"] == 2
    assert result["warnings"] and result["properties"]["num_ro5_violations"] == 2


@pytest.mark.parametrize("failure", ["connect", "503", "json"])
async def test_provider_failure_is_sanitized_before_adapter_logging(
    chemical_response, caplog, capsys, failure
):
    def handler(request):
        if failure == "connect":
            raise httpx.ConnectError("synthetic-chemical-sentinel", request=request)
        if failure == "json":
            return httpx.Response(200, text="synthetic-chemical-sentinel")
        return httpx.Response(503, text="synthetic-chemical-sentinel")

    with pytest.raises(ResearchError) as caught:
        await chemical_response(handler).call("chembl", "analyze_compound_properties", PARAMS)
    assert caught.value.code == ("invalid_source_response" if failure == "json" else "source_unavailable")
    captured = capsys.readouterr()
    assert "synthetic-chemical-sentinel" not in str(caught.value) + caplog.text + captured.out + captured.err


async def test_admet_and_direct_smiles_calculation_are_explicitly_unavailable(chemical_response):
    adapter = chemical_response(molecule(CHEMBL_PROPERTIES))
    service = ResearchService(adapters=adapter)
    for params in ({**PARAMS, "property_type": "admet"}, {"smiles": "CCO", "property_type": "drug_likeness"}):
        result = await execute(
            service,
            "query_source",
            {"source": "chembl", "operation": "analyze_compound_properties", "params": params},
            scope="chemical-test",
        )
        assert result.outcome == "partial"
        data = result.sections["chembl"].data
        assert "drug_likeness" not in data
        assert "unavailable" in data["section_outcomes"].values()
