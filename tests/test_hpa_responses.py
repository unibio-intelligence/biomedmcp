"""HPA XML identity/version qualification through actual retained and public MCP."""

import hashlib
import json

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.decoding import decode_tool_result
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.hpa_records import XML_BYTES, XML_DEPTH, XML_ELEMENTS, source_record
from biomedmcp.mcp.server import create_server
from biomedmcp.recovery import RESOURCE_BYTES

ID = "ENSG00000141736"
OTHER = "ENSG00000157764"
XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<proteinAtlas schemaVersion="3.0"><entry version="25" '
    f'url="https://v25.proteinatlas.org/{ID}"><name>ERBB2</name>'
    f'<identifier id="{ID}" db="Ensembl" version="109" assembly="GRCh38.p13" '
    'gencodeVersion="43"><xref id="P04626" db="Uniprot/SWISSPROT"/></identifier>'
    "</entry></proteinAtlas>"
)
GENE = {
    "_id": "2064",
    "entrezgene": 2064,
    "symbol": "ERBB2",
    "taxid": 9606,
    "ensembl": {"gene": ID},
}


@pytest.fixture
def hpa_http(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    original = httpx.AsyncClient

    def install(handler):
        calls = []

        def route(request):
            calls.append(request)
            if request.url.host == "mygene.info":
                return httpx.Response(200, json={"hits": [GENE]})
            assert request.url.host == "www.proteinatlas.org"
            return handler(request)

        monkeypatch.setattr(
            transport, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(route))
        )
        return calls

    return install


@pytest.mark.parametrize("operation", ["get_expression_data", "analyze_localization"])
async def test_xml_identity_and_versions_are_retained_without_invented_measurements(hpa_http, operation):
    calls = hpa_http(lambda _: httpx.Response(200, text=XML))
    value = await SourceAdapters().call("protein-atlas", operation, {"ensembl_id": ID})
    assert len(calls) == 1 and calls[0].url.path == "/" + ID + ".xml"
    assert value["data"] == XML
    assert value["record_type"] == "hpa_source_xml" and value["species"] == 9606
    assert value["source_release"] == "25" and value["source_schema_version"] == "3.0"
    assert value["annotation"] == {
        "database": "Ensembl",
        "version": "109",
        "assembly": "GRCh38.p13",
        "gencode_version": 43,
    }
    assert value["xml_utf8_sha256"] == hashlib.sha256(XML.encode()).hexdigest()
    assert value["xml_utf8_bytes"] == len(XML.encode())
    assert not value["full_xsd_validated"] and not value["measurements_normalized"]
    assert value["time_dependent"] and "measurements" not in value


MALFORMED = [
    "",
    "{}",
    "null",
    "[]",
    "<html><body>login</body></html>",
    "<error>failure</error>",
    '<proteinAtlas schemaVersion="3.0"/>',
    "<proteinAtlas><entry/></proteinAtlas>",
    XML.replace('schemaVersion="3.0"', ""),
    XML.replace('version="25"', ""),
    XML.replace("<name>ERBB2</name>", ""),
    XML.replace("<name>ERBB2</name>", "<name/>"),
    XML.replace("<name>ERBB2</name>", "<name><value>ERBB2</value></name>"),
    XML.replace('db="Ensembl"', 'db="Unknown"'),
    XML.replace('version="109"', ""),
    XML.replace('assembly="GRCh38.p13"', ""),
    XML.replace('assembly="GRCh38.p13"', 'assembly=" "'),
    XML.replace('version="109"', 'version=" "'),
    XML.replace('gencodeVersion="43"', ""),
    XML.replace('gencodeVersion="43"', 'gencodeVersion="null"'),
    XML.replace('schemaVersion="3.0"', 'schemaVersion="null"'),
    XML.replace(f'id="{ID}"', 'id="null"'),
    XML.replace("https://v25.proteinatlas.org/", "https://untrusted.example/"),
    XML.replace("https://v25.proteinatlas.org/", "https://secret@v25.proteinatlas.org/"),
    XML.replace("https://v25.proteinatlas.org/", "https://v25.proteinatlas.org:bad/"),
    XML.replace("https://v25.proteinatlas.org/", "https://v25.proteinatlas.org:0/"),
    XML.replace("https://v25.proteinatlas.org/", "file:///"),
    XML.replace(f'url="https://v25.proteinatlas.org/{ID}"', f'url="https://v25.proteinatlas.org/{OTHER}"'),
    XML.replace("</entry>", "<error>synthetic untrusted provider failure</error></entry>"),
    XML.replace("</proteinAtlas>", "<entry/></proteinAtlas>"),
    XML[:-10],
    XML.replace("?>", '?><!DOCTYPE proteinAtlas [<!ENTITY bad SYSTEM "file:///private/key">]>'),
    XML.replace("?>", "?><!DOCTYPE proteinAtlas>"),
    XML.replace("</identifier>", '</identifier><identifier id="' + ID + '" db="Ensembl"/>'),
]


@pytest.mark.parametrize("operation", ["get_expression_data", "analyze_localization"])
@pytest.mark.parametrize("text", MALFORMED, ids=[f"shape-{i}" for i in range(len(MALFORMED))])
async def test_bad_xml_never_becomes_healthy_empty_or_success(hpa_http, operation, text):
    calls = hpa_http(lambda _: httpx.Response(200, text=text))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("protein-atlas", operation, {"ensembl_id": ID})
    assert caught.value.code == "invalid_source_response"
    assert len(calls) == 1


async def test_wrong_gene_is_an_identity_failure(hpa_http):
    calls = hpa_http(lambda _: httpx.Response(200, text=XML.replace(ID, OTHER)))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("protein-atlas", "get_expression_data", {"ensembl_id": ID})
    assert caught.value.code == "identity_mismatch" and len(calls) == 1


async def test_untrusted_xml_parse_failure_is_sanitized_before_sdk_logging(hpa_http, caplog, capsys):
    sentinel = "synthetic-hpa-response-sentinel"
    hpa_http(lambda _: httpx.Response(200, text="<proteinAtlas>" + sentinel))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("protein-atlas", "get_expression_data", {"ensembl_id": ID})
    assert caught.value.code == "invalid_source_response"
    captured = capsys.readouterr()
    assert sentinel not in str(caught.value) + caplog.text + captured.out + captured.err


@pytest.mark.parametrize(
    "operation,selectors",
    [
        ("get_expression_data", {"tissue_type": "brain", "expression_level": "high"}),
        ("analyze_localization", {"search_by_location": "nucleus", "include_reliability": False}),
    ],
)
async def test_source_xml_does_not_masquerade_as_a_filtered_or_derived_measure(
    hpa_http, operation, selectors
):
    hpa_http(lambda _: httpx.Response(200, text=XML))
    result = await SourceAdapters().call("protein-atlas", operation, {"ensembl_id": ID, **selectors})
    assert not result["selection"]["applied"] and result["selection"]["scope"] == "whole_gene_source_xml"
    assert all(result["selection"][key] == value for key, value in selectors.items())
    assert result["warnings"] and result["data"] == XML


@pytest.mark.parametrize("value", [None, "ERBB2", "ENSMUSG00000059552", ID + ".2", ID + "/../other"])
async def test_unqualified_gene_is_rejected_before_acquisition(hpa_http, value):
    calls = hpa_http(lambda _: pytest.fail("Invalid identity acquired upstream data"))
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("protein-atlas", "analyze_localization", {"ensembl_id": value})
    assert caught.value.code == "invalid_identifier" and not calls


@pytest.mark.parametrize("ids", [[], [ID, ID], [ID] * 11, [ID, "ERBB2"], None])
async def test_comparison_rejects_ambiguous_or_silently_truncated_inputs(hpa_http, ids):
    calls = hpa_http(lambda _: pytest.fail("Invalid comparison acquired upstream data"))
    with pytest.raises(ResearchError):
        await SourceAdapters().call("protein-atlas", "compare_expression_profiles", {"ensembl_ids": ids})
    assert not calls


async def test_public_gene_xml_provenance_release_and_missing_measurement_are_explicit(hpa_http):
    calls = hpa_http(lambda _: httpx.Response(200, text=XML))
    async with Client(create_server(service=ResearchService())) as client:
        first = (
            await client.call_tool(
                "get", {"entity": "gene", "id": "ERBB2", "species": 9606, "sections": ["hpa"]}
            )
        ).data
        section = first["sections"]["hpa"]
        assert section["outcome"] == "data" and not section["truncated"]
        data = section["data"]
        assert data["ensembl_id"] == ID and not data["measurements_normalized"]
        proof = next(p for p in first["provenance"] if p["source"] == "protein-atlas")
        assert proof["source_version"] == "25" and proof["url"].endswith(ID + ".xml")
        assert first["receipt"]["time_dependent"]
        before = len(calls)
        second = (
            await client.call_tool(
                "get", {"entity": "gene", "id": "ERBB2", "species": 9606, "sections": ["hpa"]}
            )
        ).data
        assert len(calls) == before
        assert second["sections"]["hpa"]["evidence_ids"] == section["evidence_ids"]


@pytest.mark.parametrize("bad", ["{}", XML.replace(ID, OTHER)])
async def test_public_failure_is_not_cached_and_next_valid_response_can_succeed(hpa_http, bad):
    bodies = iter([bad, XML])
    calls = hpa_http(lambda _: httpx.Response(200, text=next(bodies)))
    async with Client(create_server(service=ResearchService())) as client:
        params = {"entity": "gene", "id": "ERBB2", "species": 9606, "sections": ["hpa"]}
        first = decode_tool_result(
            await client.call_tool("get", params, raise_on_error=False), public_operation="get"
        )
        assert first["sections"]["hpa"]["outcome"] == "error"
        assert first["sections"]["hpa"]["error"]["code"] in {"invalid_source_response", "identity_mismatch"}
        second = (await client.call_tool("get", params)).data
        assert second["sections"]["hpa"]["outcome"] == "data"
    assert sum(c.url.host == "www.proteinatlas.org" for c in calls) == 2


async def test_comparison_retains_successful_peer_and_explicit_invalid_peer_without_caching(hpa_http):
    calls = hpa_http(lambda r: httpx.Response(200, text=XML if ID in r.url.path else "{}"))
    async with Client(create_server(service=ResearchService())) as client:
        params = {
            "source": "protein-atlas",
            "operation": "compare_expression_profiles",
            "params": {"ensembl_ids": [ID, OTHER]},
        }
        for _ in range(2):
            result = (await client.call_tool("query_source", params)).data
            section = result["sections"]["protein-atlas"]
            assert section["outcome"] == "partial"
            assert section["data"]["comparison"] == "source_annotations"
            assert section["data"]["results"][0]["expression"]["ensembl_id"] == ID
            assert section["data"]["results"][1]["error"]["code"] == "invalid_source_response"
    assert len(calls) == 4


async def test_large_well_formed_xml_is_exactly_recoverable_without_reacquisition(hpa_http):
    # Size of the separately retained full ERBB2 observation; source annotations
    # here are synthetic. Do not fake success by using only a tiny XML fixture.
    xml = XML.replace("</entry>", "<synonym>" + "x" * 1_774_982 + "</synonym></entry>")
    calls = hpa_http(lambda _: httpx.Response(200, text=xml))
    async with Client(create_server(service=ResearchService())) as client:
        result = (await client.call_tool("get", {"entity": "gene", "id": "ERBB2", "sections": ["hpa"]})).data
        section = result["sections"]["hpa"]
        assert section["outcome"] == "data" and section["truncated"]
        assert section["data"]["xml_utf8_sha256"] == hashlib.sha256(xml.encode()).hexdigest()
        recovery = section["recovery"]
        assert recovery["snapshot_status"] == "available" and recovery["uri"]
        omitted = next(o for o in recovery["omissions"] if o["pointer"] == "/data")
        assert omitted["total"] == len(xml) and omitted["omitted"] == len(xml) - 4000
        assert len(json.dumps(section).encode()) < RESOURCE_BYTES
        uri = omitted["uri"]
        parts = [section["data"]["data"]]
        while uri:
            resource = json.loads((await client.read_resource(uri))[0].text)
            assert resource["evidence_ids"] == section["evidence_ids"]
            assert resource["range"]["total"] == len(xml)
            assert resource["pointer"] == "/data"
            assert len(json.dumps(resource).encode()) <= RESOURCE_BYTES
            parts.append(resource["value"])
            uri = resource["next_uri"]
        assert "".join(parts) == xml
        assert hashlib.sha256("".join(parts).encode()).hexdigest() == section["data"]["xml_utf8_sha256"]
    assert sum(c.url.host == "www.proteinatlas.org" for c in calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        XML + " " * XML_BYTES,
        XML.replace("</entry>", "<x>" * XML_DEPTH + "</x>" * XML_DEPTH + "</entry>"),
        XML.replace("</entry>", "<x/>" * XML_ELEMENTS + "</entry>"),
    ],
)
def test_parser_resource_boundaries_are_enforced(text):
    with pytest.raises(ResearchError) as caught:
        source_record(text, ID)
    assert caught.value.code == "invalid_source_response"


async def test_unqualified_antibody_route_cannot_turn_html_into_evidence(monkeypatch):
    from biomedmcp import transport
    from biomedmcp.adapters import SourceAdapters
    from biomedmcp.native.catalog import ADVANCED

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unqualified antibody route must fail before HTTP")

    monkeypatch.setattr(transport.AsyncClient, "get", forbidden)
    assert "get_antibody_info" not in ADVANCED["protein-atlas"]
    with pytest.raises(ResearchError) as caught:
        await SourceAdapters().call("protein-atlas", "get_antibody_info", {"antibody_id": "HPA000001"})
    assert caught.value.code == "source_unavailable"
