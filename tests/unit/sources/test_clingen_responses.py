import json
from copy import deepcopy

import pytest
from clingen_helpers import ASSERTION, LINK, SPECIFICATION, allele, envelope
from native_helpers import HTTP
from test_qualified_gene_identity import GeneAdapters

from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.providers import NativeProviders
from biomedmcp.native.variants import Variants

OPERATIONS = ("gene", "normalize", "assertions", "specifications", "linked_data")
BAD = (None, {}, "unexpected", [None], [{}], {"error": "provider failure"})


async def invoke(operation, payload):
    http = HTTP(payload)
    variants = Variants(http)
    if operation == "gene":
        return await NativeProviders(GeneAdapters(), http).section(
            "gene", "673", "clingen", GetRequest(entity="gene", id="673"), {}
        )
    if operation == "normalize":
        return await variants.normalize("NC_000007.14:g.140753336A>T")
    if operation == "assertions":
        return await variants.assertions("CA1")
    if operation == "specifications":
        return await variants.specifications("BRAF")
    return await variants.linked_data("CA1")


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("payload", BAD)
async def test_malformed_clingen_payload_never_is_healthy_evidence(operation, payload):
    with pytest.raises(ResearchError) as caught:
        await invoke(operation, payload)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "payload",
    [
        [{"label": "BRAF"}],
        [{"hgnc": "HGNC:1097"}],
        [{"label": "BRAF", "hgnc": "1097"}],
        [{"label": "", "hgnc": "HGNC:1097"}],
        [{"label": "BRAF", "hgnc": "HGNC:1097"}, {}],
    ],
)
async def test_incomplete_gene_candidates_cannot_be_filtered_into_absence(payload):
    with pytest.raises(ResearchError) as caught:
        await invoke("gene", payload)
    assert caught.value.code == "invalid_source_response"


async def test_gene_identity_and_alias_are_retained_without_clinical_assertion():
    row = {"label": "BRAF1", "hgnc": "HGNC:1097", "alias": "BRAF"}
    result = await invoke("gene", [row, {"label": "BRAF", "hgnc": "HGNC:999"}])
    assert result["records"] == [row]
    assert result["qualified_identity"]["hgnc_id"] == "HGNC:1097"
    assert "autocomplete" in " ".join(result["warnings"])
    assert "gene-disease validity" in " ".join(result["warnings"])


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("gene", []),
        ("assertions", envelope([])),
        ("specifications", envelope([])),
        ("linked_data", envelope({})),
    ],
)
async def test_explicit_empty_clingen_collections_are_valid(operation, payload):
    result = await invoke(operation, payload)
    assert result["records"] == []
    assert "absence" in " ".join(result["warnings"])


@pytest.mark.parametrize(
    "operation,data",
    [
        ("assertions", [ASSERTION]),
        ("specifications", [SPECIFICATION]),
        ("linked_data", {"CivicEvidence": [LINK]}),
    ],
)
@pytest.mark.parametrize("damage", ["data", "status", "status_code", "metadata"])
async def test_partial_envelopes_are_not_success(operation, data, damage):
    payload = envelope(deepcopy(data))
    if damage == "status_code":
        payload["status"]["code"] = True
    else:
        payload.pop(damage)
    with pytest.raises(ResearchError) as caught:
        await invoke(operation, payload)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "operation,data",
    [
        ("assertions", [ASSERTION]),
        ("specifications", [SPECIFICATION]),
        ("linked_data", {"CivicEvidence": [LINK]}),
    ],
)
async def test_application_failure_cannot_mint_negative_evidence(operation, data):
    with pytest.raises(ResearchError) as caught:
        await invoke(operation, envelope(deepcopy(data), 503))
    assert caught.value.code == "upstream_error" and caught.value.retryable


@pytest.mark.parametrize("protein", [False, True])
async def test_normalization_retains_actual_canonical_namespace_and_representations(protein):
    payload = allele(protein)
    http = HTTP(payload)
    hgvs = "NP_004324.2:p.Val600Glu" if protein else "NC_000007.14:g.140753336A>T"
    result = await Variants(http).normalize(hgvs)
    assert result["canonical_allele_id"] == ("PA1" if protein else "CA1")
    assert result["@id"] == payload["@id"] and result["type"] == payload["type"]
    assert result["requested_hgvs"] == hgvs
    assert "cross-build" in " ".join(result["warnings"])


@pytest.mark.parametrize(
    "payload",
    [
        {"@id": "http://reg.genome.network/allele/CA1", "type": "nucleotide"},
        {**allele(), "@id": "https://example.org/allele/CA1"},
        {**allele(), "genomicAlleles": [{}]},
        {**allele(), "genomicAlleles": [{"hgvs": []}]},
        {**allele(), "type": "amino-acid"},
        {**allele(), "@id": "https://[invalid"},
        {**allele(), "@id": "http://reg.genome.network:invalid/allele/CA1"},
    ],
)
async def test_partial_or_inconsistent_normalization_is_invalid(payload):
    with pytest.raises(ResearchError) as caught:
        await invoke("normalize", payload)
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("assertions", envelope([{**ASSERTION, "caId": "CA999"}])),
        ("assertions", envelope([{"caId": "CA1"}])),
        ("specifications", envelope([{}])),
        ("specifications", envelope([{"@id": "not-a-reference"}])),
        ("linked_data", envelope({"CivicEvidence": [None]})),
        ("linked_data", envelope({"CivicEvidence": [{}]})),
        ("linked_data", envelope({"CivicEvidence": {"count": 0}})),
    ],
)
async def test_nested_identity_or_collection_failures_cannot_be_healthy(operation, payload):
    with pytest.raises(ResearchError) as caught:
        await invoke(operation, payload)
    assert caught.value.code == "invalid_source_response"


async def test_failed_gene_match_preserves_record_and_retries():
    row = {"label": "BRAF", "hgnc": "HGNC:1097"}
    http = HTTP([{}], [row])
    service = ResearchService(adapters=GeneAdapters(), http=http)
    request = GetRequest(entity="gene", id="673", sections=["record", "clingen"])
    bad = await service.get(request, scope="public")
    assert bad.outcome == "partial" and bad.sections["record"].outcome == "data"
    assert bad.sections["clingen"].outcome == "error" and not bad.sections["clingen"].evidence_ids
    good = await service.get(request, scope="public")
    assert good.sections["clingen"].data["records"] == [row]
    assert len(http.calls) == 2


async def test_protein_namespace_leading_zeros_are_preserved():
    payload = {**allele(True), "@id": "http://reg.genome.network/allele/PA094029"}
    result = await Variants(HTTP(payload)).normalize("NP_004324.2:p.Val600Glu")
    assert result["canonical_allele_id"] == "PA094029"


async def test_protein_query_cannot_become_a_genomic_identity():
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(allele())).normalize("NP_004324.2:p.Val600Glu")
    assert caught.value.code == "invalid_source_response"


async def test_conflicting_assertions_versions_and_retractions_remain_independent():
    rows = [
        {**ASSERTION, "retracted": False},
        {
            **ASSERTION,
            "classification": "Benign",
            "ep": "Other panel",
            "uuid": "other",
            "docVersion": "2.0",
            "retracted": True,
        },
    ]
    payload = envelope(rows)
    payload["metadata"] = {"rendered": {"when": "2026-10-10T00:00:00Z"}}
    result = await invoke("assertions", payload)
    assert [r["provider_record"] for r in result["records"]] == rows
    assert [r["classification"] for r in result["records"]] == [r["classification"] for r in rows]
    assert result["metadata"] == payload["metadata"]
    assert result["coverage"] == {"provider_page": 1, "requested_page_size": 25, "exhaustive": False}
    assert "no new clinical classification" in " ".join(result["warnings"])


@pytest.mark.parametrize(
    "operation,params,payload",
    [
        ("normalize", {"hgvs": "NC_000007.14:g.140753336A>T"}, allele()),
        ("assertions", {"caid": "CA1"}, envelope([ASSERTION])),
        ("specifications", {"gene": "BRAF"}, envelope([SPECIFICATION])),
        ("linked_data", {"caid": "CA1"}, envelope({"CivicEvidence": [LINK]})),
    ],
)
async def test_actual_mcp_advanced_failure_retry_and_cached_provenance(
    monkeypatch, operation, params, payload
):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    http = HTTP({}, payload)
    arguments = {"source": "clingen", "operation": operation, "params": params}
    async with Client(create_server(service=ResearchService(http=http))) as client:
        failed = (await client.call_tool("query_source", arguments, raise_on_error=False)).structured_content
        good = (await client.call_tool("query_source", arguments)).data
        cached = (await client.call_tool("query_source", arguments)).data
    assert failed["outcome"] == "error"
    assert failed["sections"]["clingen"]["error"]["code"] == "invalid_source_response"
    assert failed["sections"]["clingen"]["evidence_ids"] == [] and failed["provenance"] == []
    assert good["outcome"] == "data"
    assert good["sections"]["clingen"]["data"]["record_type"].startswith("clingen_")
    first, repeated = good["provenance"][0], cached["provenance"][0]
    assert first["evidence_id"] == repeated["evidence_id"]
    assert first["source_version"] is None and repeated["cached"]
    assert len(http.calls) == 2


async def test_linked_reference_recovery_keeps_types_versions_and_evidence(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    rows = [{**LINK, "entId": f"synthetic-{i}", "entContentSrc": {"ver": "synthetic-v1"}} for i in range(30)]
    http = HTTP(envelope({"CivicEvidence": rows}))
    async with Client(create_server(service=ResearchService(http=http))) as client:
        result = (
            await client.call_tool(
                "query_source", {"source": "clingen", "operation": "linked_data", "params": {"caid": "CA1"}}
            )
        ).data
        section = result["sections"]["clingen"]
        assert len(section["data"]["records"]) == 25 and section["truncated"]
        omitted = next(o for o in section["recovery"]["omissions"] if o["pointer"] == "/records")
        recovered = json.loads((await client.read_resource(omitted["uri"]))[0].text)
        assert recovered["value"] == [{"link_type": "CivicEvidence", "entity": row} for row in rows[25:]]
        assert recovered["evidence_ids"] == section["evidence_ids"]
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    "operation,data",
    [
        ("assertions", [ASSERTION]),
        ("specifications", [SPECIFICATION]),
        ("linked_data", {"CivicEvidence": [LINK]}),
    ],
)
async def test_application_error_marker_overrides_successful_envelope(operation, data):
    with pytest.raises(ResearchError) as caught:
        await invoke(operation, {**envelope(data), "errorType": "synthetic application failure"})
    assert caught.value.code == "invalid_source_response"


async def test_malformed_omitted_link_cannot_become_healthy_bounded_evidence():
    with pytest.raises(ResearchError) as caught:
        await invoke("linked_data", envelope({"CivicEvidence": [LINK] * 25 + [{}]}))
    assert caught.value.code == "invalid_source_response"
