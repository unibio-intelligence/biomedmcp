import httpx
import pytest
from native_helpers import HTTP
from test_research_contracts import Adapters

from biomedmcp.contracts import GetRequest, SearchRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.http import ProviderHTTP
from biomedmcp.native.providers import NativeProviders
from biomedmcp.native.regulatory import Regulatory


@pytest.mark.parametrize(
    "section,table,field,value",
    [
        ("interactions", "pair_view", "genesymbol", "eq.CYP2D6"),
        ("recommendations", "recommendation_view", "lookupkey->>CYP2D6", "not.is.null"),
        ("frequencies", "population_frequency_view", "genesymbol", "eq.CYP2D6"),
        ("guidelines", "guideline_summary_view", "genes", 'cs.[{"symbol":"CYP2D6"}]'),
    ],
)
async def test_native_cpic_section_queries(section, table, field, value):
    http = HTTP([{"genesymbol": "CYP2D6", "drugname": "codeine"}])
    result = await NativeProviders(Adapters(), http).pgx("CYP2D6", section)
    assert result[0]["drugname"] == "codeine"
    assert http.calls[0][1].endswith("/" + table)
    assert http.calls[0][2]["params"][field] == value


async def test_cpic_drug_search_does_not_silently_ignore_gene_or_level():
    http = HTTP([])
    await NativeProviders(Adapters(), http).pgx(
        "codeine", "interactions", {"drug": ["codeine"], "cpic_level": "A"}
    )
    assert http.calls[0][2]["params"]["drugname"] == "ilike.*codeine*"
    assert http.calls[0][2]["params"]["cpiclevel"] == "eq.A"


async def test_gwas_threshold_and_source_native_pagination():
    from gwas_helpers import page, row

    rows = [row(i, p_value=0.1, pvalue_mantissa=1, pvalue_exponent=-1) for i in range(1, 11)]
    rows[0] = row(1, p_value=1e-9, pvalue_mantissa=1, pvalue_exponent=-9)
    http = HTTP(page(rows, total=30, size=10, number=2))
    rows = await NativeProviders(Adapters(), http).gwas("BRAF", {"p_value": 5e-8}, 10, 20)
    assert [r["id"] for r in rows] == ["1"]
    assert http.calls[0][2]["params"]["mapped_gene"] == "BRAF"
    assert http.calls[0][2]["params"]["page"] == 2


async def test_trial_sections_share_one_retained_client_and_preserve_outcomes():
    class TrialAdapter(Adapters):
        async def call(self, source, operation, params):
            self.calls.append((source, operation, params))
            return {
                "protocolSection": {
                    "identificationModule": {"nctId": params["nct_id"]},
                    "eligibilityModule": {"eligibilityCriteria": "Adults"},
                    "outcomesModule": {"primaryOutcomes": [{"measure": "Overall survival"}]},
                }
            }

    adapters = TrialAdapter()
    result = await ResearchService(adapters=adapters).get(
        GetRequest(entity="trial", id="NCT01234567", sections=["eligibility", "outcomes"]), scope="alice"
    )
    assert len(adapters.calls) == 1
    assert result.sections["eligibility"].data["eligibilityCriteria"] == "Adults"
    assert result.sections["outcomes"].data["primaryOutcomes"][0]["measure"] == "Overall survival"


async def test_monarch_disease_relation_keeps_direction_and_curie():
    http = HTTP({"items": [{"id": "synthetic", "subject": "HGNC:1", "object": "MONDO:0001",
                           "subject_category": "biolink:Gene", "object_category": "biolink:Disease",
                           "category": "biolink:CorrelatedGeneToDiseaseAssociation",
                           "predicate": "biolink:gene_associated_with_condition"}],
                 "total": 1, "limit": 25, "offset": 0})
    result = await ResearchService(http=http).get(
        GetRequest(entity="disease", id="MONDO:0001", sections=["genes"]), scope="alice"
    )
    assert result.sections["genes"].data["records"][0]["subject"] == "HGNC:1"
    assert http.calls[0][2]["params"]["object"] == "MONDO:0001"
    assert "biolink:CorrelatedGeneToDiseaseAssociation" in http.calls[0][2]["params"]["category"]
    assert http.calls[0][2]["params"]["direct"] is True


async def test_native_ema_preserves_regulatory_region_and_candidates():
    http = HTTP(
        [
            {
                "medicine_name": "Example drug",
                "active_substance": "aspirin",
                "authorisation_status": "Authorised",
            },
            {"medicine_name": "other", "active_substance": "unrelated"},
        ]
    )
    result = await ResearchService(http=http).search(
        SearchRequest(entity="drug", query="aspirin", filters={"region": "eu"}), scope="alice"
    )
    assert len(result.records) == 1 and result.records[0]["active_substance"] == "aspirin"
    assert result.query["execution"]["sources"] == ["ema"]
    assert result.provenance[0].source == "ema"


async def test_ema_section_uses_explicit_selected_owner():
    http = HTTP([{"medicine_name": "aspirin", "activity": "new indication"}])
    result = await ResearchService(http=http).get(
        GetRequest(entity="drug", id="aspirin", sections=["regulatory"], sources=["ema"]), scope="alice"
    )
    assert result.outcome == "data"
    assert "post_authorisation" in http.calls[0][1]
    assert result.provenance[0].source == "ema"


async def test_who_vaccine_csv_and_header_drift():
    csv = "VACCINE TYPE,COMMERCIAL NAME,MANUFACTURER\nPolio,Example Vaccine,Example Co\nOther,Other Vaccine,Elsewhere\n"
    http = HTTP(csv)
    result = await Regulatory(http).who("Polio", product_type="vaccine")
    assert result["records"][0]["COMMERCIAL NAME"] == "Example Vaccine"
    assert "not a national marketing" in result["regulatory_meaning"]
    assert http.calls[0][1].endswith("/vaccines/prequalified/export")
    with pytest.raises(ResearchError, match="headers changed"):
        await Regulatory(HTTP("<html>Service unavailable</html>")).who("Polio", product_type="vaccine")


async def test_who_diagnostics_manufacturer_filter():
    text = "product code,product name,pathogen/disease/marker,manufacturer name\n1,HIV assay,HIV,A Labs\n2,HIV assay,HIV,B Labs\n"
    result = await Regulatory(HTTP(text)).who("HIV", product_type="ivd", manufacturer="B Labs")
    assert [r["product code"] for r in result["records"]] == ["2"]


@pytest.mark.parametrize(
    "entity,source,query,text",
    [
        (
            "drug",
            "who",
            "insulin",
            '"WHO Reference Number","INN, Dosage Form and Strength",Applicant\nP1,insulin,Example Co\n',
        ),
        (
            "diagnostic",
            "who-ivd",
            "HIV",
            "Product name,Product Code,Pathogen/Disease/Marker,Manufacturer name\nHIV assay,D1,HIV,Example Co\n",
        ),
    ],
)
async def test_live_who_header_case_is_accepted_through_dispatch(entity, source, query, text):
    from biomedmcp.dispatch import execute

    result = await execute(
        ResearchService(http=HTTP(text)),
        "search",
        {
            "entity": entity,
            "query": query,
            "filters": {"source": source},
            "limit": 3,
        },
        scope="public",
    )
    assert result.outcome == "data" and len(result.records) == 1
    assert result.provenance[0].source == source
    assert ("Product Code" if entity == "diagnostic" else "WHO Reference Number") in result.records[0]


@pytest.mark.parametrize(
    "header",
    [
        "product code,product name,pathogen/disease/marker,manufacturer name, Product Code ",
        "product code,product name,manufacturer name",
    ],
)
async def test_who_missing_or_case_equivalent_duplicate_columns_fail_closed(header):
    with pytest.raises(ResearchError, match="headers changed"):
        await Regulatory(HTTP(header + "\n")).who("HIV", product_type="ivd")


async def test_explicit_sources_cannot_conflict_with_region_or_product_type():
    service = ResearchService(http=HTTP())
    for filters in [{"region": "eu", "source": "mychem"}, {"product_type": "vaccine", "source": "mychem"}]:
        with pytest.raises(ResearchError):
            await service.search(
                SearchRequest(entity="drug", query="aspirin", filters=filters), scope="alice"
            )
    assert service.providers.http.calls == []


async def test_native_http_rejects_graphql_errors_and_unsafe_xml(monkeypatch):
    from biomedmcp import transport

    real = httpx.AsyncClient
    responses = [
        httpx.Response(200, json={"errors": [{"message": "upstream error"}]}),
        httpx.Response(200, text='<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'),
    ]
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda req: responses.pop(0))),
    )
    with pytest.raises(ResearchError, match="application error"):
        await ProviderHTTP().post("https://example.org/graphql", {"query": "test"})
    with pytest.raises(ResearchError, match="parsed safely"):
        await ProviderHTTP().xml("https://example.org/xml")


async def test_uniprot_client_handles_opaque_cursor_without_a_second_client(monkeypatch):
    from uniprot_mcp.server import query_proteins

    from biomedmcp import transport

    real = httpx.AsyncClient
    requests = []

    def respond(req):
        requests.append(req)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"results": [{"primaryAccession": "P00001"}, {"primaryAccession": "P00002"}]},
                headers={"Link": '<https://rest.uniprot.org/uniprotkb/search?cursor=NEXT>; rel="next"'},
            )
        assert req.url.params["cursor"] == "NEXT"
        return httpx.Response(200, json={"results": [{"primaryAccession": "P00003"}]})

    monkeypatch.setattr(transport, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond)))
    first = await query_proteins(query="BRAF", query_type="advanced", limit=2)
    result = await query_proteins(
        query="BRAF",
        query_type="advanced",
        limit=2,
        offset=2,
        page_cursor=first["_provider_page"]["continuation"],
    )
    assert result["results"] == [{"primaryAccession": "P00003"}]
    assert len(requests) == 2
    assert [r.url.params["size"] for r in requests] == ["2", "2"]


async def test_variant_structure_checks_reference_and_domain_interval():
    from interpro_helpers import body, entry, protein, response

    class ProteinAdapter(Adapters):
        async def call(self, source, operation, params):
            self.calls.append((source, operation, params))
            return {"results": [protein()]}

    domains = response(body([entry(fragments=[{"start": 500, "end": 650, "dc-status": "CONTINUOUS"}])]))
    provider = NativeProviders(ProteinAdapter(), HTTP(domains))
    result = await provider.variant_structure({"identity": {"gene": "BRAF", "change": "V600E"}})
    assert result["domains"][0]["accession"] == "IPR000719"
    assert result["structures"][0]["covers_requested_sequence_position"] is True
    assert (
        result["position"] == 600 and "author residue numbering is not mapped" in result["coordinate_system"]
    )
    with pytest.raises(ResearchError, match="reference amino acid"):
        await provider.variant_structure({"identity": {"gene": "BRAF", "change": "R600E"}})


async def test_mcp_get_exposes_and_enforces_source_restriction(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    adapters = Adapters()
    service = ResearchService(adapters=adapters)
    async with Client(create_server(service=service)) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert "sources" in tools["get"].input_schema["properties"]
        result = (
            await client.call_tool(
                "get", {"entity": "gene", "id": "BRAF", "sections": ["expression"], "sources": ["gtex"]}
            )
        ).data
        assert set(result["sections"]) == {"expression"}
    assert [c[0] for c in adapters.calls] == ["gtex"]


async def test_unknown_drug_source_fails_before_network():
    http = HTTP()
    with pytest.raises(ResearchError, match="Select mychem"):
        await ResearchService(http=http).search(
            SearchRequest(entity="drug", query="BRAF", filters={"source": "not-a-provider"}), scope="alice"
        )
    assert not http.calls


async def test_gtex_dynamic_qtl_has_one_route_and_preserves_variant_and_release():
    adapters = Adapters()
    service = ResearchService(adapters=adapters)
    result = await service.get(
        GetRequest(
            entity="gene",
            id="BRAF",
            sections=["eqtl"],
            sources=["gtex"],
            source_versions={"gtex": "gtex_v8"},
            section_parameters={
                "eqtl": {
                    "analysis_mode": "dynamic",
                    "variant_id": "chr7_140753336_A_T_b38",
                    "tissue_id": "Thyroid",
                }
            },
        ),
        scope="alice",
    )
    assert result.outcome == "data"
    assert len(adapters.calls) == 1
    assert adapters.calls[0][2]["analysis_mode"] == "dynamic"
    assert adapters.calls[0][2]["dataset_id"] == "gtex_v8"
    assert adapters.calls[0][2]["variant_id"] == "chr7_140753336_A_T_b38"


async def test_clingen_linked_data_is_native_and_provider_qualified():
    from clingen_helpers import LINK, envelope

    from biomedmcp.extensions import ExtendedSources

    http = HTTP(envelope({"CivicEvidence": [LINK]}))
    value = await ExtendedSources(http=http).call("clingen", "linked_data", {"caid": "CA123"})
    assert value["requested_caid"] == "CA123"
    assert value["records"][0]["entity"] == LINK
    assert http.calls[0][1] == "https://ldh.genome.network/ldh/Variant/id/CA123/ld"


async def test_licensed_evidence_fails_closed_without_keys(monkeypatch):
    monkeypatch.delenv("ONCOKB_TOKEN", raising=False)
    monkeypatch.delenv("UBI_LICENSED_SOURCES", raising=False)
    http = HTTP()
    result = await ResearchService(http=http).get(
        GetRequest(entity="variant", id="BRAF V600E", sections=["oncokb"]), scope="alice"
    )
    assert result.sections["oncokb"].outcome == "unavailable"
    assert not http.calls


async def test_openfda_only_documented_no_matches_is_empty(monkeypatch):
    from openfda_mcp.server import fda_api_request

    from biomedmcp import transport

    real = httpx.AsyncClient
    responses = [
        httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "No matches found!"}}),
        httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "Endpoint removed"}}),
    ]
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda req: responses.pop(0))),
    )
    assert await fda_api_request("drug/event", search="test") == {"results": []}
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="source_not_found"):
        await fda_api_request("drug/event", search="test")
