"""Adapter tests with a synthetic GraphQL transport; no payload is biomedical data."""

import inspect
from copy import deepcopy

import pytest
from fastmcp import Client
from graphql import FieldNode, OperationDefinitionNode, parse, value_from_ast_untyped
from opentargets_mcp import queries
from opentargets_mcp.queries import OpenTargetsClient
from opentargets_mcp.server import mcp
from opentargets_mcp.tools import composite, drug, unified
from opentargets_mcp.tools.drug import safety
from opentargets_mcp.tools.unified import UnifiedTools

from biomedmcp.errors import ResearchError
from biomedmcp.native.opentargets import plan

TARGET = "ENSG00000157764"
LOCUS = "synthetic-locus"
STUDY = {
    "id": "synthetic-study",
    "studyType": "gwas",
    "projectId": "p",
    "traitFromSource": "t",
    "pubmedId": None,
    "nSamples": 10,
    "nCases": 4,
    "nControls": 6,
    "target": None,
    "diseases": [],
}
CREDIBLE = {
    "studyLocusId": LOCUS,
    "studyId": "synthetic-study",
    "studyType": "gwas",
    "chromosome": "7",
    "position": 5,
    "pValueMantissa": 1.0,
    "pValueExponent": -8,
    "finemappingMethod": None,
    "confidence": None,
    "qtlGeneId": None,
    "variant": None,
    "study": STUDY,
    "region": None,
    "beta": None,
    "zScore": None,
    "standardError": None,
    "credibleSetIndex": None,
    "credibleSetlog10BF": None,
    "purityMeanR2": None,
    "purityMinR2": None,
    "locusStart": None,
    "locusEnd": None,
    "sampleSize": None,
    "isTransQtl": None,
    "effectAlleleFrequencyFromSource": None,
}
DRUG = {
    "id": "CHEMBL1",
    "name": "Synthetic drug",
    "description": None,
    "maximumClinicalStage": "PHASE_II",
    "mechanismsOfAction": {
        "rows": [
            {
                "mechanismOfAction": "m",
                "actionType": "INHIBITOR",
                "targetName": "BRAF",
                "targets": [{"id": TARGET, "approvedSymbol": "BRAF", "approvedName": "n"}],
                "references": [],
            }
        ]
    },
    "indications": {
        "count": 1,
        "rows": [
            {
                "id": "i",
                "maxClinicalStage": "PHASE_II",
                "disease": {"id": "EFO_1", "name": "d"},
                "clinicalReports": [],
            }
        ],
    },
    "adverseEvents": {
        "count": 1,
        "criticalValue": 0.5,
        "rows": [{"name": "e", "meddraCode": None, "count": 3, "logLR": 1.5}],
    },
    "crossReferences": [{"source": "drugbank", "ids": ["DB1"]}],
}
FIXTURES = {
    "credibleSet": CREDIBLE,
    "drug": DRUG,
    "meta": {
        "name": "ot",
        "product": "platform",
        "apiVersion": {"x": "25", "y": "9", "z": "0", "suffix": None},
        "dataVersion": {"year": "25", "month": "09", "iteration": None},
    },
    "search": {
        "total": 1,
        "hits": [
            {
                "id": "CHEMBL1",
                "name": "Synthetic drug",
                "entity": "drug",
                "score": 2.0,
                "description": None,
                "object": {
                    "__typename": "Drug",
                    "id": "CHEMBL1",
                    "name": "Synthetic drug",
                    "drugType": "s",
                    "maximumClinicalStage": "PHASE_II",
                },
            }
        ],
    },
    "variant": {
        "id": "7_5_A_T",
        "variantDescription": "v",
        "chromosome": "7",
        "position": 5,
        "referenceAllele": "A",
        "alternateAllele": "T",
        "hgvsId": None,
        "rsIds": [],
        "dbXrefs": [],
        "alleleFrequencies": [],
        "mostSevereConsequence": None,
        "transcriptConsequences": [],
        "variantEffect": [],
        "pharmacogenomics": [],
    },
}


def project(value, selection, variables):
    """Return only the selected fields, as an honest GraphQL server would."""
    if value is None or selection is None:
        return deepcopy(value)
    if isinstance(value, list):
        return [project(row, selection, variables) for row in value]
    result = {}
    for node in selection.selections:
        if not isinstance(node, FieldNode):
            for inner in project(value, node.selection_set, variables).items():
                result.setdefault(*inner)
            continue
        skipped = any(
            (d.name.value == "include") != value_from_ast_untyped(d.arguments[0].value, variables)
            for d in node.directives
        )
        if skipped:
            continue
        key = (node.alias or node.name).value
        result[key] = (
            value["__typename"]
            if node.name.value == "__typename"
            else project(value[node.name.value], node.selection_set, variables)
        )
    return result


class Transport:
    def __init__(self, fixtures=FIXTURES):
        self.fixtures, self.calls = fixtures, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs["json"]))
        document = parse(kwargs["json"]["query"])
        operation = next(n for n in document.definitions if isinstance(n, OperationDefinitionNode))
        data = project(self.fixtures, operation.selection_set, kwargs["json"]["variables"])

        class Reply:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": data}

        return Reply()


@pytest.fixture
def transport(monkeypatch):
    value = Transport()
    monkeypatch.setattr(queries.httpx, "AsyncClient", lambda **kwargs: value)
    return value


def documents():
    for module in (composite, drug, safety, unified):
        for name, value in vars(module).items():
            if isinstance(value, str) and value.startswith("query "):
                yield pytest.param(value, id=f"{module.__name__}.{name}")


@pytest.mark.parametrize("document", list(documents()))
def test_every_static_document_matches_the_reviewed_contract(document):
    assert "__ubi" not in document and plan(document)[0]


async def test_client_posts_the_planned_document_and_verifies_identity(transport):
    result = await OpenTargetsClient()._query(
        "query($id:String!){drug(chemblId:$id){name}}", {"id": "CHEMBL1"}
    )
    url, body = transport.calls[0]
    assert url == queries.ENDPOINT and body["variables"] == {"id": "CHEMBL1"}
    assert "__ubi_requested_identity" in body["query"] and result == {"drug": {"name": "Synthetic drug"}}
    with pytest.raises(ResearchError) as caught:
        await OpenTargetsClient()._query("query($id:String!){drug(chemblId:$id){name}}", {"id": "CHEMBL2"})
    assert caught.value.code == "invalid_source_response"


async def test_mcp_tools_validate_parameters_and_return_json_records(transport):
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert names == {
            "get_entity",
            "search_drugs",
            "analyze_advanced",
            "analyze_association",
            "query_genetics",
        }
        found = (await client.call_tool("search_drugs", {"query": "synthetic", "limit": 5})).data
        meta = (
            await client.call_tool("analyze_advanced", {"analysis_type": "metadata", "entity_ids": []})
        ).data
    assert found["records"][0]["object"]["__typename"] == "Drug" and found["coverage"]["exhaustive"] is True
    assert meta["meta"]["dataVersion"]["year"] == "25" and len(transport.calls) == 2


async def test_drug_entity_sections_are_promoted_and_mirrored(transport):
    result = await UnifiedTools().get_entity(
        OpenTargetsClient(),
        "drug",
        "CHEMBL1",
        sections=["identity", "mechanisms_of_action", "indications", "adverse_events", "cross_references"],
    )
    assert (
        result["drug"]["id"] == "CHEMBL1"
        and result["mechanisms_of_action"]["rows"][0]["targetName"] == "BRAF"
    )
    assert result["adverse_events"]["adverseEvents"]["rows"][0]["logLR"] == 1.5
    assert result["specialized"]["cross_references"]["crossReferences"][0]["ids"] == ["DB1"]
    assert result["section_outcomes"]["specialized/cross_references"] == {"outcome": "data"}
    assert set(result["section_outcomes"]) == {
        "drug",
        "mechanisms_of_action",
        "indications",
        "adverse_events",
        "specialized/cross_references",
    }
    assert len(transport.calls) == 5


async def test_drug_disease_mode_reports_indication_coverage(transport):
    result = await UnifiedTools().analyze_association(OpenTargetsClient(), "CHEMBL1", "drug-disease")
    assert result["indications"]["rows"][0]["disease"]["id"] == "EFO_1" and result["coverage"]["exhaustive"]
    mechanism = await UnifiedTools().analyze_association(OpenTargetsClient(), "CHEMBL1", "drug-target")
    assert mechanism["targets"][0]["id"] == TARGET and len(transport.calls) == 4


async def test_credible_set_mode_keeps_identity_and_rejects_foreign_rows(transport):
    result = await UnifiedTools().query_genetics(OpenTargetsClient(), "credible_set", credible_set_id=LOCUS)
    assert result["credible_set"]["studyId"] == "synthetic-study"
    transport.fixtures = {**FIXTURES, "credibleSet": {**CREDIBLE, "studyLocusId": "other"}}
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().query_genetics(OpenTargetsClient(), "credible_set", credible_set_id=LOCUS)
    assert caught.value.code == "invalid_source_response"
    transport.fixtures = {**FIXTURES, "credibleSet": None}
    with pytest.raises(ResearchError) as caught:
        await UnifiedTools().query_genetics(OpenTargetsClient(), "credible_set", credible_set_id=LOCUS)
    assert caught.value.code == "source_not_found"


async def test_variant_pharmacogenomics_flag_selects_wire_fields(transport):
    tools = UnifiedTools()
    plain = await tools.query_genetics(OpenTargetsClient(), "variant", variant_id="7_5_A_T")
    pgx = await tools.query_genetics(
        OpenTargetsClient(), "variant", variant_id="7_5_A_T", include_pharmacogenomics=True
    )
    assert "pharmacogenomics" not in plain["variant"] and pgx["variant"]["pharmacogenomics"] == []
    assert "evidences" not in plain and "credible_sets" not in plain


@pytest.mark.parametrize(
    "operation,params",
    [
        ("get_entity", {"entity_type": "protein", "entity_id": TARGET}),
        ("get_entity", {"entity_type": "target", "entity_id": TARGET, "sections": ["identity", "unknown"]}),
        ("get_entity", {"entity_type": "target", "entity_id": "BRAF"}),
        (
            "analyze_association",
            {"source_id": "CHEMBL1", "association_type": "drug-target", "min_score": 0.5},
        ),
        (
            "analyze_association",
            {"source_id": "EFO_1", "association_type": "discover-opportunities", "filters": {"ranking": 1}},
        ),
        ("analyze_association", {"source_id": TARGET, "target_id": "EFO_1", "evidence_types": []}),
        (
            "query_genetics",
            {"query_type": "credible_set", "credible_set_id": LOCUS, "include_credible_sets": True},
        ),
        ("query_genetics", {"query_type": "variant", "variant_id": "7_5_A_T", "evidence_cursor": "x"}),
        ("search_drugs", {"query": " ", "limit": 5}),
    ],
)
async def test_unconsumed_or_invalid_parameters_fail_before_any_request(transport, operation, params):
    with pytest.raises(ResearchError) as caught:
        await getattr(UnifiedTools(), operation)(OpenTargetsClient(), **params)
    assert caught.value.code == "invalid_parameters" and transport.calls == []


def test_tool_signatures_match_the_unified_operations():
    from opentargets_mcp import server

    for name in ("get_entity", "search_drugs", "analyze_advanced", "analyze_association", "query_genetics"):
        tool = inspect.signature(
            getattr(server, name).fn if hasattr(getattr(server, name), "fn") else getattr(server, name)
        )
        expected = list(inspect.signature(getattr(UnifiedTools, name)).parameters)[2:]
        assert list(tool.parameters) == expected, name
