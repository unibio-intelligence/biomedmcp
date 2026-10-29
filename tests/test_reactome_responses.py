"""Reactome gene membership is a JSON list, not a searchable envelope.

Contract: https://github.com/reactome/reactome2py/blob/main/reactome2py/content.py
(`pathways_low_entity`). These fixed rows are synthetic, not live qualification.
"""

import httpx
import pytest

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError

PATHWAY = {"stId": "R-HSA-9000001", "displayName": "Synthetic membership", "schemaClass": "Pathway"}
IDENTITY = {
    "_id": "2064",
    "symbol": "ERBB2",
    "taxid": 9606,
    "entrezgene": 2064,
    "ensembl": {"gene": "ENSG00000141736"},
}


@pytest.fixture
def source_http(monkeypatch):
    original = httpx.AsyncClient

    def install(payload):
        requests = []

        def respond(request):
            requests.append(request)
            if request.url.host == "mygene.info":
                return httpx.Response(200, json={"hits": [IDENTITY], "total": 1})
            assert request.url.host == "reactome.org"
            assert request.url.path == "/ContentService/data/mapping/UniProt/ERBB2/pathways"
            assert request.url.params["species"] in {"Homo sapiens", "9606"}
            return httpx.Response(200, json=payload)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
        )
        return requests

    return install


@pytest.mark.parametrize("rows", [[PATHWAY], []])
async def test_gene_pathway_list_preserves_membership_and_explicit_empty(source_http, rows):
    source_http(rows)
    result = await SourceAdapters().call("reactome", "find_pathways_by_gene", {"gene": "ERBB2"})
    assert result == {"gene": "ERBB2", "species": "Homo sapiens", "results": rows}


@pytest.mark.parametrize(
    "payload",
    [{}, {"results": []}, None, [None], [{}], [{"stId": "R-HSA-9000001"}], [{**PATHWAY, "displayName": 7}]],
)
async def test_malformed_membership_cannot_be_healthy_empty(source_http, payload):
    source_http(payload)
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("reactome", "find_pathways_by_gene", {"gene": "ERBB2"})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("rows,outcome", [([PATHWAY], "data"), ([], "empty"), ({}, "error")])
async def test_public_gene_enrichment_retains_identity_evidence_and_failure(source_http, rows, outcome):
    requests = source_http(rows)
    service = ResearchService()
    result = await service.get(
        GetRequest(entity="gene", id="2064", sections=["pathways"]), scope="synthetic-reactome"
    )
    section = result.sections["pathways"]
    assert section.outcome == outcome
    assert result.query["qualified_identity"]["symbol"] == "ERBB2"
    if outcome == "data":
        assert section.data["results"] == rows
        assert section.evidence_ids
        assert {p.source for p in result.provenance} == {"reactome"}
        assert result.provenance[0].sources == ["mygene", "reactome"]
    elif outcome == "error":
        assert section.error["code"] == "invalid_source_response"
    assert len(requests) == 2


@pytest.mark.parametrize("failure", ["503", "json", "connect"])
async def test_gene_pathway_provider_failure_is_sanitized_before_adapter_logs(
    monkeypatch, caplog, capsys, failure
):
    sentinel = "synthetic-reactome-credential-sentinel"
    original = httpx.AsyncClient

    def respond(request):
        if failure == "connect":
            raise httpx.ConnectError(sentinel, request=request)
        if failure == "json":
            return httpx.Response(200, text=sentinel)
        return httpx.Response(503, json={"error": sentinel})

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("reactome", "find_pathways_by_gene", {"gene": "ERBB2"})
    assert caught.value.code == ("invalid_source_response" if failure == "json" else "source_unavailable")
    output = capsys.readouterr()
    assert sentinel not in str(caught.value) + caplog.text + output.out + output.err
