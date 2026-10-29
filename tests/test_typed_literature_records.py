"""Bibliographic absence, reported negatives and conflicting source claims differ."""

import json
from copy import deepcopy

import jsonschema
import pytest
from defusedxml import ElementTree
from fastmcp import Client
from native_helpers import HTTP, PUBMED

from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.evidence import deduplicate_articles
from biomedmcp.mcp.server import create_server
from biomedmcp.native.literature import Literature, normalize_epmc
from biomedmcp.native.openalex import work as openalex_work
from biomedmcp.output_contracts import output_schema
from biomedmcp.receipts import verify_receipt
from biomedmcp.scientific_records import LiteratureRecord, source_pmid


def epmc(**extra):
    return {"id": "123", "source": "MED", "title": "Synthetic source metadata", **extra}


def claims(row):
    return {claim["kind"]: claim for claim in row["source_assertions"]}


@pytest.mark.asyncio
async def test_actual_catalog_references_resolve_within_each_advertised_schema(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(http=FederatedHTTP()))) as client:
        tools = await client.list_tools()
    for tool in tools:
        for schema in (tool.input_schema, tool.output_schema):
            jsonschema.Draft202012Validator.check_schema(schema)
            pending = [schema]
            while pending:
                node = pending.pop()
                if isinstance(node, dict):
                    if "$ref" in node:
                        assert node["$ref"].startswith("#/$defs/")
                        target = schema
                        for part in node["$ref"][2:].split("/"):
                            target = target[part.replace("~1", "/").replace("~0", "~")]
                        assert isinstance(target, dict)
                    pending.extend(node.values())
                elif isinstance(node, list):
                    pending.extend(node)


@pytest.mark.parametrize(
    "normalizer,row", [(normalize_epmc, epmc()), (openalex_work, {"id": "https://openalex.org/W123", "title": "Synthetic"})]
)
def test_missing_citations_access_and_retraction_are_unknown(normalizer, row):
    result = normalizer(row)
    assert result["record_type"] == "literature" and result["identities"]
    assert result["citation_count"] is result["is_open_access"] is result["is_retracted"] is None
    assert all(
        claim["missingness"] == "not_supplied" and claim["value"] is None
        for claim in result["source_assertions"]
    )
    LiteratureRecord.model_validate(result)


@pytest.mark.parametrize("value", [0, "0", 17, "17"])
def test_explicit_epmc_zero_and_negative_flags_are_reported(value):
    row = normalize_epmc(epmc(citedByCount=value, isOpenAccess="N", isRetracted="N"))
    assert row["citation_count"] == int(value)
    assert row["is_open_access"] is row["is_retracted"] is False
    assert all(claim["missingness"] == "reported" for claim in row["source_assertions"])
    assert claims(row)["citation_count"]["unit"] == "citations"


@pytest.mark.parametrize(
    "field,value",
    [
        ("citedByCount", True),
        ("citedByCount", -1),
        ("citedByCount", 1.5),
        ("citedByCount", "NaN"),
        ("isOpenAccess", "false"),
        ("isRetracted", 0),
        ("isRetracted", []),
        ("title", []),
        ("abstractText", {}),
        ("doi", []),
        ("authorList", []),
        ("authorList", {"author": [42]}),
        ("authorList", {"author": [{"fullName": 42}]}),
    ],
)
def test_malformed_epmc_fields_fail_without_echoing_source_data(field, value):
    with pytest.raises(ResearchError) as error:
        normalize_epmc(epmc(**{field: value}))
    assert error.value.code == "invalid_source_response"
    assert "Synthetic source metadata" not in str(error.value.as_dict())




@pytest.mark.parametrize("value", [True, {}, [], None, "False", -1])
def test_excerpt_pmid_does_not_coerce_arbitrary_source_data(value):
    with pytest.raises(ResearchError) as error:
        source_pmid(value)
    assert error.value.code == "invalid_source_response"




@pytest.mark.parametrize("remove", ["AuthorList", "PublicationTypeList"])
def test_pubmed_omitted_metadata_is_not_complete_or_negative(remove):
    root = ElementTree.fromstring(PUBMED)
    article = root.find(".//Article")
    article.remove(article.find(remove))
    row = Literature.parse_pubmed(root)[0]
    if remove == "AuthorList":
        assert row["authors"] == [] and row["author_completeness"] == "source_limited"
    else:
        assert row["is_retracted"] is None
        assert claims(row)["retraction"]["missingness"] == "not_supplied"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["pubmed", "europepmc", "pubtator", "litsense2"])
async def test_each_native_discovery_source_emits_qualified_typed_records(source):
    responses = {
        "pubmed": [{"esearchresult": {"idlist": ["123"]}}, PUBMED],
        "europepmc": [{"resultList": {"result": [epmc()]}, "hitCount": 1}],
        "pubtator": [{"results": [{"pmid": 123, "abstract": "Source excerpt"}]}],
        "litsense2": [[{"pmid": 123, "sentence": "A source sentence."}]],
    }
    rows = await Literature(HTTP(*responses[source])).search_source(source, "BRAF", {}, 10)
    assert len(rows) == 1
    row = rows[0]
    assert row["record_type"] == "literature"
    assert all(identity["source"] == source for identity in row["identities"])
    assert all(claim["source"] == source for claim in row["source_assertions"])
    assert row["content_scope"] == (
        "sentence_excerpt"
        if source == "litsense2"
        else "provider_excerpt"
        if source == "pubtator"
        else "bibliographic"
    )


class FederatedHTTP:
    def __init__(self, bad_epmc=False):
        self.calls = []
        self.bad_epmc = bad_epmc

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "esearch.fcgi" in url:
            return {"esearchresult": {"idlist": ["123"]}}
        if "efetch.fcgi" in url:
            return PUBMED
        if "europepmc" in url:
            return {
                "resultList": {
                    "result": [
                        epmc(citedByCount=True if self.bad_epmc else 0, isRetracted="N", isOpenAccess="N")
                    ]
                },
                "hitCount": 1,
            }
        if "pubtator" in url:
            return {"results": []}
        raise AssertionError("Unexpected provider fixture request")

    async def xml(self, url, **kwargs):
        return ElementTree.fromstring(await self.get(url, **kwargs))


@pytest.mark.asyncio
async def test_actual_mcp_preserves_conflicting_claims_with_each_window_locator(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(http=FederatedHTTP()))) as client:
        tools = await client.list_tools()
        assert all("$defs" in tool.output_schema for tool in tools)
        result = await client.call_tool_mcp("literature_search", {"query": "BRAF"})
    assert not result.is_error
    value = result.structured_content
    assert len(value["records"]) == 1
    row = value["records"][0]
    assert row["is_retracted"] is True
    retractions = {
        claim["source"]: claim for claim in row["source_assertions"] if claim["kind"] == "retraction"
    }
    assert retractions["pubmed"]["value"] is True and retractions["europepmc"]["value"] is False
    proofs = {proof["evidence_id"]: proof for proof in value["provenance"]}
    for claim in row["source_assertions"]:
        assert claim["evidence_ids"]
        assert all(proofs[evidence]["source"] == claim["source"] for evidence in claim["evidence_ids"])
    for identity in row["identities"]:
        assert identity["evidence_ids"]
        assert all(proofs[evidence]["source"] == identity["source"] for evidence in identity["evidence_ids"])
    assert verify_receipt(value)
    jsonschema.validate(value, next(tool.output_schema for tool in tools if tool.name == "literature_search"))
    assert json.loads(result.content[0].text) == value


@pytest.mark.asyncio
async def test_malformed_count_keeps_successful_peer_and_truthful_provider_failure(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(http=FederatedHTTP(bad_epmc=True)))) as client:
        result = await client.call_tool_mcp("literature_search", {"query": "BRAF"})
    value = result.structured_content
    assert not result.is_error and value["outcome"] == "partial"
    assert value["sections"]["europepmc"]["outcome"] == "error"
    assert value["sections"]["europepmc"]["error"]["code"] == "invalid_source_response"
    assert all(claim["source"] == "pubmed" for claim in value["records"][0]["source_assertions"])
    assert verify_receipt(value)


@pytest.mark.asyncio
async def test_article_get_links_its_typed_identities_and_claims_to_section_proof(monkeypatch):
    monkeypatch.setenv("UBI_PROFILE", "local")
    async with Client(create_server(service=ResearchService(http=HTTP(PUBMED)))) as client:
        result = await client.call_tool_mcp("get", {"entity": "article", "id": "123"})
    assert not result.is_error
    value = result.structured_content
    section = value["sections"]["record"]
    assert section["data"]["record_type"] == "literature"
    for field in ["identities", "source_assertions"]:
        assert all(row["evidence_ids"] == section["evidence_ids"] for row in section["data"][field])
    assert verify_receipt(value)
    jsonschema.validate(value, output_schema("get"))


def test_dedup_preserves_all_namespaces_and_independent_assertions():
    left = normalize_epmc(epmc(isRetracted="N", citedByCount=0))
    right = openalex_work({"id": "https://openalex.org/W123", "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/123/"}, "cited_by_count": 5})
    rows = deduplicate_articles([left, right])
    assert len(rows) == 1
    assert {identity["namespace"] for identity in rows[0]["identities"]} == {"pmid", "openalex"}
    counts = {
        claim["source"]: claim["value"]
        for claim in rows[0]["source_assertions"]
        if claim["kind"] == "citation_count"
    }
    assert counts == {"europepmc": 0, "openalex": 5}
    LiteratureRecord.model_validate(rows[0])


@pytest.mark.asyncio
async def test_wire_schema_rejects_changed_typed_fields(monkeypatch):
    from biomedmcp.dispatch import execute

    value = (
        await execute(
            ResearchService(http=HTTP(PUBMED)), "get", {"entity": "article", "id": "123"}, scope="local"
        )
    ).model_dump(mode="json")
    for field, replacement in [
        ("citation_count", True),
        ("is_open_access", 0),
        ("identities", []),
        ("title", {}),
        (
            "source_assertions",
            [
                {
                    "kind": "retraction",
                    "source": "pubmed",
                    "value": 1,
                    "unit": "flag",
                    "missingness": "reported",
                }
            ],
        ),
    ]:
        bad = deepcopy(value)
        bad["sections"]["record"]["data"][field] = replacement
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, output_schema("get"))
