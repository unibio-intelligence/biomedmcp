"""UniProt scientific method, input identity, and annotation contracts (offline)."""

from copy import deepcopy
from hashlib import sha256

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

pytestmark = pytest.mark.source_permissions


def record(accession="P15056", sequence="MAV", **extra):
    return {
        "primaryAccession": accession,
        "organism": {"taxonId": 9606},
        "sequence": {"value": sequence, "length": len(sequence)},
        "comments": [
            {
                "commentType": "SIMILARITY",
                "texts": [
                    {
                        "value": "Belongs to the protein kinase superfamily.",
                        "evidences": [{"evidenceCode": "ECO:0000305"}],
                    }
                ],
            }
        ],
        "uniProtKBCrossReferences": [{"database": "PDB", "id": "4HHB"}],
        **extra,
    }


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient
    calls = []

    def install(handler):
        def respond(request):
            calls.append(request)
            return handler(request)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
        )
        return calls

    return install


def reply(payload, release="2026_03"):
    return httpx.Response(200, json=deepcopy(payload), headers={"x-uniprot-release": release})


@pytest.mark.parametrize(
    "mode,field,database",
    [
        ("similarity_annotations", "cc_similarity", None),
        ("orthology_references", "xref_orthodb", "OrthoDB"),
        ("phylogeny_references", "xref_phylomedb", "PhylomeDB"),
    ],
)
async def test_evolution_modes_select_actual_source_fields_and_never_infer_relationships(
    wire, mode, field, database
):
    payload = record(analysis_type="forged", source_release="invented")
    payload["accession"] = "wrong"
    if database:
        payload["uniProtKBCrossReferences"].append({"database": database, "id": "source-reference"})
    calls = wire(lambda request: reply(payload))
    result = await SourceAdapters().call(
        "uniprot", "analyze_evolution", {"accession": "P15056", "analysis_type": mode}
    )
    assert calls[0].url.params["fields"] == f"accession,id,organism_id,{field}"
    assert "query" not in calls[0].url.params
    assert result["analysis_type"] == mode and result["accession"] == "P15056"
    assert result["source_release"] == "2026_03"
    assert result["identity"]["taxon_id"] == 9606
    assert result["annotation_status"] == "reported"
    assert result["annotations"][0]["input_locator"].startswith("/")
    assert (
        "no inferred" in result["method"]
        and "External reference contents were not retrieved" in result["method"]
    )


@pytest.mark.parametrize(
    "params",
    [
        {"accession": "BRAF"},
        {"accession": "P15056/other"},
        {"accession": "P15056", "analysis_type": "orthologs"},
        {"accession": "P15056", "analysis_type": "phylogeny"},
        {"accession": "P15056", "target_organism": "mouse"},
    ],
)
async def test_invalid_identity_and_unsupported_inference_rejected_before_http(wire, params):
    calls = wire(lambda request: reply(record()))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("uniprot", "analyze_evolution", params)
    assert caught.value.code == "invalid_parameters" and calls == []


async def test_missing_annotations_retains_record_as_partial_unknown(wire):
    wire(lambda request: reply(record(comments=[])))
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {"source": "uniprot", "operation": "analyze_evolution", "params": {"accession": "P15056"}},
            )
        ).data
    assert result["outcome"] == "partial"
    data = result["sections"]["uniprot"]["data"]
    assert data["primaryAccession"] == "P15056"
    assert data["annotations"] == [] and data["annotation_status"] == "not_reported"
    assert result["provenance"][0]["source_version"] == "2026_03"


@pytest.mark.parametrize(
    "comment",
    [
        {},
        {"commentType": "FUNCTION"},
        {"commentType": "SIMILARITY", "texts": []},
        {"commentType": "FUNCTION", "texts": None},
        {"commentType": "FUNCTION", "texts": [{"value": ""}]},
        {"commentType": "FUNCTION", "texts": [{"value": 4}]},
        {"commentType": "FUNCTION", "texts": [{"value": "text", "evidences": {}}]},
        *[
            {"commentType": "FUNCTION", "texts": [{"value": "text", "evidences": [evidence]}]}
            for evidence in [
                {},
                {"evidenceCode": "wrong"},
                {"evidenceCode": "ECO:0000269", "source": "PubMed"},
                {"evidenceCode": "ECO:0000269", "id": "1"},
                {"evidenceCode": "ECO:0000269", "source": "PubMed", "id": True},
            ]
        ],
    ],
)
async def test_present_function_similarity_annotation_shape_is_validated(wire, comment):
    wire(lambda request: reply(record(comments=[comment])))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("uniprot", "analyze_evolution", {"accession": "P15056"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "accessions",
    [[], ["P15056"], ["P15056"] * 2, ["BRAF", "P04637"], ["P15056", "P04637/other"], ["P15056"] * 6],
)
async def test_comparison_identity_preflight(wire, accessions):
    calls = wire(lambda request: reply(record()))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("uniprot", "compare_proteins", {"accessions": accessions})
    assert caught.value.code == "invalid_parameters" and calls == []


async def test_actual_mcp_sequence_comparison_has_methods_qualified_inputs_and_exact_metrics(wire):
    calls = wire(
        lambda request: reply(
            record(
                request.url.path.rsplit("/", 1)[1], "MAV" if request.url.path.endswith("P15056") else "MAXV"
            )
        )
    )
    async with Client(create_server(service=ResearchService(adapters=SourceAdapters()))) as client:
        result = (
            await client.call_tool(
                "query_source",
                {
                    "source": "uniprot",
                    "operation": "compare_proteins",
                    "params": {"accessions": ["P15056", "P04637"]},
                },
            )
        ).data
    assert result["outcome"] == "data"
    data = result["sections"]["uniprot"]["data"]
    assert len(calls) == 2 and all("organism_id" in r.url.params["fields"] for r in calls)
    assert data["summaries"][0]["sequence_sha256"] == sha256(b"MAV").hexdigest()
    assert data["summaries"][1]["contains_ambiguous_residues"]
    pair = data["pairwise_comparisons"][0]
    assert pair["exact_sequence_match"] is False and pair["residue_count_difference_left_minus_right"] == -1
    assert pair["input_locators"] == ["/results/0/data", "/results/1/data"]
    assert "no alignment" in data["method"]
    assert result["provenance"][0]["source_version"] == "2026_03"


@pytest.mark.parametrize(
    "kind,key", [("function", "shared_function_statement_texts"), ("structure", "shared_pdb_reference_ids")]
)
async def test_literal_annotation_comparisons(wire, kind, key):
    comments = [
        {
            "commentType": "FUNCTION",
            "texts": [
                {
                    "value": "Kinase activity.",
                    "evidences": [{"evidenceCode": "ECO:0000269", "source": "PubMed", "id": "1508179"}],
                }
            ],
        }
    ]
    wire(lambda request: reply(record(request.url.path.rsplit("/", 1)[1], comments=comments)))
    result = await SourceAdapters().call(
        "uniprot", "compare_proteins", {"accessions": ["P15056", "P04637"], "comparison_type": kind}
    )
    assert result["pairwise_comparisons"][0][key] == (
        ["Kinase activity."] if kind == "function" else ["4HHB"]
    )
    assert result["summaries"][0]["annotations"][0]["input_locator"].startswith("/results/0/data/")
    assert result["section_outcomes"]["comparison"]["outcome"] == "data"


@pytest.mark.parametrize("failure", ["missing_annotation", "wrong_shape", "alias"])
async def test_missing_measurements_failures_or_aliases_retain_other_peer_as_partial(wire, failure):
    def handler(request):
        accession = request.url.path.rsplit("/", 1)[1]
        if accession == "P15056":
            return reply(record())
        if failure == "wrong_shape":
            return reply({})
        if failure == "alias":
            return reply(record(secondaryAccessions=[accession]))
        return reply(record(accession, uniProtKBCrossReferences=[]))

    wire(handler)
    result = await SourceAdapters().call(
        "uniprot", "compare_proteins", {"accessions": ["P15056", "P04637"], "comparison_type": "structure"}
    )
    assert result["results"][0]["data"]["primaryAccession"] == "P15056"
    assert result["section_outcomes"]["comparison"]["outcome"] == "unavailable"
    assert result["warnings"]
    assert result["pairwise_comparisons"][0]["status"] == "unavailable"
    assert result["pairwise_comparisons"][0]["input_locators"] == []
    if failure == "wrong_shape":
        assert result["results"][1]["error"]["code"] == "invalid_source_response"
    else:
        assert result["pairwise_comparisons"][0]["status"] == "unavailable"
        assert "shared_pdb_reference_ids" not in result["pairwise_comparisons"][0]


@pytest.mark.parametrize(
    "releases,expected",
    [
        (["2026_03", "2026_02"], None),
        (["", "2026_03"], None),
        (["forged", "forged"], None),
        (["2026_03", "2026_03"], "2026_03"),
    ],
)
async def test_release_is_observed_header_not_provider_payload_and_mixed_versions_retained(
    wire, releases, expected
):
    wire(
        lambda request: reply(
            record(request.url.path.rsplit("/", 1)[1], source_release="invented"),
            releases[0 if request.url.path.endswith("P15056") else 1],
        )
    )
    result = await SourceAdapters().call("uniprot", "compare_proteins", {"accessions": ["P15056", "P04637"]})
    assert result["source_release"] == expected
    assert all(s["identity"]["source_release"] != "invented" for s in result["summaries"])
    if releases == ["2026_03", "2026_02"]:
        assert "different UniProt releases" in result["warnings"][0]
