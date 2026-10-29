"""Population denominators, exact identity and gene constraint source contracts."""

from copy import deepcopy

import pytest
from gnomad_helpers import GENE_IDENTITY, IDENTITY, constraint, population
from native_helpers import HTTP

from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.variants import Variants


async def gene_constraint(http):
    service = ResearchService(http=http)

    async def record(*args, **kwargs):
        return {"qualified_identity": deepcopy(GENE_IDENTITY)}

    service.providers.record = record
    request = GetRequest(entity="gene", id="BRAF", sections=["constraint"])
    return await service.providers.section("gene", "BRAF", "constraint", request, {})


@pytest.mark.parametrize("scope", ["population", "constraint"])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        None,
        [],
        {"data": None},
        {"data": {}},
        {"error": "credential-sentinel"},
        {"errors": [{"message": "credential-sentinel"}], "data": {"variant": None, "gene": None}},
    ],
)
async def test_invalid_graphql_response_is_never_healthy_absence(scope, payload, caplog):
    with pytest.raises(ResearchError) as caught:
        if scope == "population":
            await Variants(HTTP(payload)).population({"identity": IDENTITY})
        else:
            await gene_constraint(HTTP(payload))
    assert caught.value.code == "invalid_source_response"
    assert "credential-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("modality", ["exome", "genome", "joint"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("ac", True),
        ("ac", -1),
        ("ac", 101),
        ("an", "100"),
        ("an", -1),
        ("homozygote_count", 2),
        ("hemizygote_count", 3),
        ("filters", [None]),
        ("populations", [{}]),
    ],
)
async def test_bad_measurements_are_rejected_before_frequency_derivation(modality, field, value):
    data = population()
    data["data"]["variant"][modality][field] = value
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_modality",
        "missing_count",
        "missing_filter",
        "null_population",
        "wrong_population_count",
        "wrong_build",
        "wrong_position",
        "wrong_reference",
    ],
)
async def test_partial_counts_and_identity_cannot_establish_frequency(mutation):
    data = population()
    variant = data["data"]["variant"]
    branch = variant["exome"]
    if mutation == "missing_modality":
        del variant["genome"]
    elif mutation == "missing_count":
        del branch["an"]
    elif mutation == "missing_filter":
        del branch["filters"]
    elif mutation == "null_population":
        branch["populations"] = [None]
    elif mutation == "wrong_population_count":
        branch["populations"][0]["ac"] = 101
    elif mutation == "wrong_build":
        variant["reference_genome"] = "GRCh37"
    elif mutation == "wrong_position":
        variant["pos"] = 1
    else:
        variant["ref"] = "C"
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert caught.value.code in {"identity_mismatch", "invalid_source_response"}


@pytest.mark.parametrize("missing", ["null_variant", "null_modality", "null_counts", "zero_denominator"])
async def test_unavailable_measurements_are_not_measured_zero(missing):
    data = population()
    if missing == "null_variant":
        data["data"]["variant"] = None
    elif missing == "null_modality":
        data["data"]["variant"]["exome"] = None
    else:
        data["data"]["variant"]["exome"].update(
            ac=None if missing == "null_counts" else 0, an=None if missing == "null_counts" else 0
        )
        data["data"]["variant"]["exome"]["populations"] = []
    result = await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert "unavailable" in result["section_outcomes"].values()
    if missing not in {"null_variant", "null_modality"}:
        assert result["variant"]["exome"]["allele_frequency"] is None


async def test_measured_zero_is_zero_but_modalities_are_not_summed():
    data = population()
    data["data"]["variant"]["exome"].update(ac=0)
    data["data"]["variant"]["exome"]["populations"][0]["ac"] = 0
    result = await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert result["variant"]["exome"]["allele_frequency"] == 0
    assert result["variant"]["joint"]["an"] == 100
    assert result["release"] is None and result["dataset_selector"] == "gnomad_r4"
    assert result["reproducibility"] == "mutable_provider_alias"


@pytest.mark.parametrize(
    "field,value",
    [
        ("pli", 1.1),
        ("pli", -0.1),
        ("pli", True),
        ("mis_z", "unknown"),
        ("syn_z", float("nan")),
        ("oe_lof_upper", -1),
        ("flags", [None]),
    ],
)
async def test_constraint_metrics_are_typed_and_domain_checked(field, value):
    data = constraint()
    data["data"]["gene"]["gnomad_constraint"][field] = value
    with pytest.raises(ResearchError) as caught:
        await gene_constraint(HTTP(data))
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "field,value",
    [("gene_id", "ENSG00000000001"), ("symbol", "OTHER"), ("ncbi_id", "1"), ("reference_genome", "GRCh37")],
)
async def test_constraint_identity_matches_the_qualified_gene(field, value):
    data = constraint()
    data["data"]["gene"][field] = value
    with pytest.raises(ResearchError) as caught:
        await gene_constraint(HTTP(data))
    assert caught.value.code == "identity_mismatch"


@pytest.mark.parametrize("missing", ["null_gene", "null_constraint", "null_metrics"])
async def test_missing_constraint_is_unavailable_not_unconstrained(missing):
    data = constraint()
    if missing == "null_gene":
        data["data"]["gene"] = None
    elif missing == "null_constraint":
        data["data"]["gene"]["gnomad_constraint"] = None
    else:
        data["data"]["gene"]["gnomad_constraint"].update(pli=None, oe_lof_upper=None, mis_z=None, syn_z=None)
    result = await gene_constraint(HTTP(data))
    assert "unavailable" in result["section_outcomes"].values() and result["release"] is None


async def test_actual_queries_validate_against_full_official_schema():
    import json
    from pathlib import Path

    from graphql import build_schema, parse, validate

    fixture = json.loads((Path(__file__).parent / "fixtures/gnomad-schema-2026-10-09.json").read_text())
    schema = build_schema(fixture["sdl"])
    for method, data in [("population", population()), ("constraint", constraint())]:
        http = HTTP(data)
        if method == "population":
            await Variants(http).population({"identity": IDENTITY})
        else:
            await gene_constraint(http)
        assert validate(schema, parse(http.calls[0][2]["body"]["query"])) == []


@pytest.fixture
async def actual_gnomad(monkeypatch):
    import httpx

    from biomedmcp import transport

    monkeypatch.setenv("UBI_PROFILE", "local")
    state = {"calls": [], "responses": [], "identity_calls": []}
    original = httpx.AsyncClient

    def handler(request):
        state["calls"].append(request)
        assert request.url.host == "gnomad.broadinstitute.org"
        return httpx.Response(200, json=deepcopy(state["responses"].pop(0)))

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    service = ResearchService()

    async def call(source, operation, params):
        state["identity_calls"].append((source, operation, params))
        assert source in {"myvariant", "mygene"}
        return {
            "hits": [
                {
                    "_id": "673",
                    "symbol": "BRAF",
                    "taxid": 9606,
                    "entrezgene": 673,
                    "ensembl": {"gene": "ENSG00000157764"},
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(service.adapters, "call", call)

    # Exact genomic inputs use the native MyVariant reader. Isolate only the
    # already-qualified identity record; gnomAD remains actual HTTP/MCP.
    async def resolve(identifier, assembly=None):
        return {"resolution": "exact", "id": "chr7:g.140753336A>T", "identity": deepcopy(IDENTITY)}

    monkeypatch.setattr(service.providers.variants, "resolve", resolve)
    return service, state


@pytest.mark.parametrize("scope", ["population", "constraint"])
async def test_actual_mcp_invalid_data_is_uncached_and_recovery_retains_sources(actual_gnomad, scope):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    service, state = actual_gnomad
    state["responses"] = [{"data": {}}, population() if scope == "population" else constraint()]
    tool = "variant_evidence" if scope == "population" else "get"
    arguments = (
        {"id": "chr7:140753336:A:T", "assembly": "grch38", "sections": ["population"]}
        if scope == "population"
        else {"entity": "gene", "id": "673", "sections": ["constraint"]}
    )
    async with Client(create_server(service=service)) as client:
        failed = (await client.call_tool(tool, arguments, raise_on_error=False)).structured_content
        recovered = (await client.call_tool(tool, arguments)).data
        cached = (await client.call_tool(tool, arguments)).data
    section = "population" if scope == "population" else "constraint"
    assert failed["sections"][section]["error"]["code"] == "invalid_source_response"
    assert recovered["outcome"] == cached["outcome"] == "data"
    assert recovered["provenance"][0]["source"] == "gnomad"
    assert recovered["provenance"][0]["source_version"] is None
    expected_sources = {"gnomad"} if scope == "population" else {"gnomad", "mygene"}
    assert set(recovered["provenance"][0]["sources"]) == expected_sources
    assert cached["provenance"][0]["cached"] and len(state["calls"]) == 2


@pytest.mark.parametrize("scope", ["population", "constraint"])
async def test_actual_mcp_unknown_measurements_stay_partial_and_uncached(actual_gnomad, scope):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    service, state = actual_gnomad
    data = population() if scope == "population" else constraint()
    if scope == "population":
        data["data"]["variant"]["exome"] = None
    else:
        data["data"]["gene"]["gnomad_constraint"] = None
    state["responses"] = [data, data]
    arguments = (
        {"id": "chr7:140753336:A:T", "assembly": "grch38", "sections": ["population"]}
        if scope == "population"
        else {"entity": "gene", "id": "BRAF", "sections": ["constraint"]}
    )
    async with Client(create_server(service=service)) as client:
        first = (
            await client.call_tool("variant_evidence" if scope == "population" else "get", arguments)
        ).data
        second = (
            await client.call_tool("variant_evidence" if scope == "population" else "get", arguments)
        ).data
    assert first["outcome"] == second["outcome"] == "partial"
    assert not second["provenance"][0]["cached"] and len(state["calls"]) == 2


async def test_successful_primary_variant_evidence_survives_gnomad_failure(actual_gnomad):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    service, state = actual_gnomad
    state["responses"] = [{"errors": [{"message": "credential-sentinel"}], "data": {"variant": None}}]
    async with Client(create_server(service=service)) as client:
        value = (
            await client.call_tool(
                "variant_evidence",
                {"id": "chr7:140753336:A:T", "assembly": "grch38", "sections": ["record", "population"]},
            )
        ).data
    assert value["outcome"] == "partial" and value["sections"]["record"]["outcome"] == "data"
    assert value["sections"]["population"]["outcome"] == "error"
    assert value["provenance"][0]["source"] == "myvariant"
    assert "credential-sentinel" not in str(value)


@pytest.mark.parametrize("scope", ["population", "constraint"])
@pytest.mark.parametrize(
    "case,code",
    [
        ("connect", "source_unavailable"),
        ("json", "invalid_source_response"),
        (401, "source_authentication_failed"),
        (403, "source_access_denied"),
        (429, "source_rate_limited"),
    ],
)
async def test_real_http_failures_never_echo_credentials(monkeypatch, caplog, scope, case, code):
    import httpx

    from biomedmcp import transport

    original = httpx.AsyncClient

    def handler(request):
        if case == "connect":
            raise httpx.ConnectError("credential-sentinel", request=request)
        if case == "json":
            return httpx.Response(200, content=b"credential-sentinel")
        return httpx.Response(case, json={"error": "credential-sentinel"})

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ResearchError) as caught:
        if scope == "population":
            await Variants().population({"identity": IDENTITY})
        else:
            from biomedmcp.native.gnomad import constraint as read
            from biomedmcp.native.http import ProviderHTTP

            await read(ProviderHTTP(), GENE_IDENTITY)
    assert caught.value.code == code
    assert "credential-sentinel" not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "identity",
    [
        {**IDENTITY, "position": True},
        {**IDENTITY, "chromosome": []},
        {**IDENTITY, "reference": "T"},
        {**IDENTITY, "alternate": None},
        {**IDENTITY, "assembly": "grch37"},
    ],
)
async def test_invalid_allele_identity_fails_before_http(identity):
    http = HTTP(population())
    with pytest.raises(ResearchError) as caught:
        await Variants(http).population({"identity": identity})
    assert caught.value.code in {"unresolved_identity", "unsupported_assembly"} and not http.calls


@pytest.mark.parametrize(
    "identity",
    [
        {**GENE_IDENTITY, "species": 10090},
        {**GENE_IDENTITY, "ensembl_ids": []},
        {**GENE_IDENTITY, "ensembl_ids": ["ENSG00000157764", "ENSG00000000001"]},
        {**GENE_IDENTITY, "ensembl_ids": None},
    ],
)
async def test_unqualified_gene_identity_fails_before_http(identity):
    from biomedmcp.native.gnomad import constraint as read

    http = HTTP(constraint())
    with pytest.raises(ResearchError) as caught:
        await read(http, identity)
    assert caught.value.code in {"unresolved_identity", "ambiguous_identifier"} and not http.calls


@pytest.mark.parametrize("field", ["canonical_transcript_id", "gene_id", "gnomad_constraint"])
async def test_missing_selected_gene_fields_fail_instead_of_inventing_missingness(field):
    data = constraint()
    del data["data"]["gene"][field]
    with pytest.raises(ResearchError) as caught:
        await gene_constraint(HTTP(data))
    assert caught.value.code == "invalid_source_response"


async def test_missing_genotype_count_cannot_contradict_known_denominator():
    data = population()
    data["data"]["variant"]["exome"].update(ac=None, an=0, homozygote_count=1, populations=[])
    with pytest.raises(ResearchError) as caught:
        await Variants(HTTP(data)).population({"identity": IDENTITY})
    assert caught.value.code == "invalid_source_response"


@pytest.mark.parametrize("canonical", [None, "ENST00000288602"])
async def test_constraint_prefers_mane_without_relabeling_metrics_as_canonical(canonical):
    data = constraint()
    data["data"]["gene"].update(
        canonical_transcript_id=canonical,
        mane_select_transcript={
            "ensembl_id": "ENST00000646891",
            "ensembl_version": "2",
            "refseq_id": "NM_004333",
            "refseq_version": "6",
        },
    )
    result = await gene_constraint(HTTP(data))
    selected = result["constraint_transcript"]
    assert selected["id"] == "ENST00000646891" and selected["version"] == "2"
    assert (
        selected["selection"] == "mane_select"
        and selected["attribution"] == "inferred_from_dated_provider_annotation_policy"
    )
    assert result["gene"]["canonical_transcript_id"] == canonical
    assert result["section_outcomes"]["constraint"] == "data"


async def test_constraint_fallback_does_not_invent_transcript_version():
    result = await gene_constraint(HTTP(constraint()))
    assert result["constraint_transcript"]["id"] == "ENST00000288602"
    assert result["constraint_transcript"]["version"] is None
    assert result["constraint_transcript"]["selection"] == "canonical_fallback"


async def test_missing_preferred_transcript_does_not_discard_valid_metrics():
    data = constraint()
    data["data"]["gene"]["canonical_transcript_id"] = None
    result = await gene_constraint(HTTP(data))
    assert result["constraint_transcript"] is None and result["section_outcomes"]["constraint"] == "partial"
    assert result["gene"]["gnomad_constraint"]["pli"] == 0.9
