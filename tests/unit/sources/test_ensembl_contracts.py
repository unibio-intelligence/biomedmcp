"""Advertised Ensembl operations against pinned official routes/serializers.

All records and source permissions are synthetic; no biological data is fetched.
"""

from copy import deepcopy

import httpx
import pytest
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server

GENE = "ENSG00000157764"
TRANSCRIPT = "ENST00000000001"
PROTEIN = "ENSP00000000001"
IDENTITY = {
    "id": GENE,
    "species": "homo_sapiens",
    "object_type": "Gene",
    "version": 2,
    "assembly_name": "SyntheticAssembly",
}
FEATURE = {
    "id": "synthetic",
    "feature_type": "regulatory",
    "seq_region_name": "1",
    "start": 15,
    "end": 25,
    "strand": 0,
    "assembly_name": "SyntheticAssembly",
}
PARTNER = {
    "id": GENE,
    "species": "homo_sapiens",
    "protein_id": PROTEIN,
    "perc_id": 95.0,
    "perc_pos": 98.0,
    "align_seq": "M-A",
}
HOMOLOGY = {
    "data": [
        {
            "id": GENE,
            "homologies": [
                {
                    "type": "ortholog_one2one",
                    "method_link_type": "ENSEMBL_ORTHOLOGUES",
                    "dn_ds": None,
                    "source": PARTNER,
                    "target": {
                        **PARTNER,
                        "id": "ENSMUSG00000000001",
                        "species": "mus_musculus",
                        "protein_id": "ENSMUSP00000000001",
                    },
                }
            ],
        }
    ]
}
LEAF = {
    "id": {"source": "EnsEMBL", "accession": GENE},
    "branch_length": 0.1,
    "taxonomy": {"id": 9606, "scientific_name": "Homo sapiens"},
    "confidence": {},
    "sequence": {
        "id": [{"source": "EnsEMBL", "accession": PROTEIN}],
        "location": "1:10-30",
        "mol_seq": {"is_aligned": 1, "seq": "MA"},
    },
}
TREE = {"type": "gene tree", "rooted": 1, "id": "ENSGT00000000001", "tree": LEAF}
COORD = {
    "seq_region_name": "1",
    "start": 10,
    "end": 30,
    "strand": 1,
    "coord_system": "chromosome",
    "assembly": "SyntheticOld",
}
MAP = {"mappings": [{"original": COORD, "mapped": {**COORD, "assembly": "SyntheticNew"}}]}
VEP = [
    {
        "input": "rs123",
        "assembly_name": "SyntheticAssembly",
        "seq_region_name": "1",
        "start": 15,
        "end": 15,
        "strand": 1,
        "most_severe_consequence": "intergenic_variant",
        "intergenic_consequences": [{"consequence_terms": ["intergenic_variant"]}],
    }
]


def sequence(kind):
    return [
        {
            "id": GENE if kind == "genomic" else PROTEIN if kind == "protein" else TRANSCRIPT,
            "version": 2,
            "seq": "MA" if kind == "protein" else "ACGN",
            "molecule": "protein" if kind == "protein" else "dna",
            "query": GENE,
            "desc": None,
        }
    ]


CASES = (
    [
        ("get_sequences", {"gene_id": GENE, "sequence_type": kind}, f"/sequence/id/{GENE}", sequence(kind))
        for kind in ("genomic", "cdna", "cds", "protein")
    ]
    + [
        (
            "analyze_evolution",
            {"gene_id": GENE, "analysis_type": kind},
            f"/genetree/member/id/homo_sapiens/{GENE}"
            if kind == "gene_tree"
            else f"/homology/id/homo_sapiens/{GENE}",
            TREE
            if kind == "gene_tree"
            else HOMOLOGY
            if kind != "paralogs"
            else {
                "data": [
                    {
                        "id": GENE,
                        "homologies": [
                            {**HOMOLOGY["data"][0]["homologies"][0], "type": "within_species_paralog"}
                        ],
                    }
                ]
            },
        )
        for kind in ("homologs", "orthologs", "paralogs", "gene_tree")
    ]
    + [
        (
            "get_regulatory_elements",
            {"region": "1:10-30", "element_type": kind},
            "/overlap/region/homo_sapiens/1:10-30",
            [{**FEATURE, "feature_type": "motif" if kind == "motif" else "regulatory"}],
        )
        for kind in ("regulatory", "motif", "both")
    ]
    + [
        (
            "map_coordinates",
            {"region": "1:10-30", "source_assembly": "SyntheticOld", "target_assembly": "SyntheticNew"},
            "/map/homo_sapiens/SyntheticOld/1:10-30/SyntheticNew",
            MAP,
        ),
        (
            "analyze_variants",
            {"region_or_id": "1:10-30"},
            "/overlap/region/homo_sapiens/1:10-30",
            [{**FEATURE, "feature_type": "variation", "start": 16, "end": 15}],
        ),
        (
            "analyze_variants",
            {"region_or_id": "rs123", "analysis_type": "consequences"},
            "/vep/homo_sapiens/id/rs123",
            VEP,
        ),
    ]
)


@pytest.fixture
def ensembl_http(monkeypatch):
    original = httpx.AsyncClient
    state = {"requests": [], "payloads": {f"/lookup/id/{GENE}": deepcopy(IDENTITY)}}

    def respond(request):
        assert request.url.host == "rest.ensembl.org"
        state["requests"].append(request)
        assert request.url.path in state["payloads"], request.url.path
        return httpx.Response(200, json=state["payloads"][request.url.path])

    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond))
    )
    return state


@pytest.mark.parametrize("operation,params,path,payload", CASES)
async def test_every_advertised_mode_preserves_populated_source(
    ensembl_http, operation, params, path, payload
):
    ensembl_http["payloads"][path] = deepcopy(payload)
    result = await SourceAdapters().call("ensembl", operation, params)
    assert isinstance(result, dict) and result
    request = ensembl_http["requests"][-1]
    assert request.url.path == path
    if operation == "get_sequences":
        assert result["sequences"] == payload
        assert (
            request.url.params["multiple_sequences"] == "1"
            and request.url.params["type"] == params["sequence_type"]
        )
    if operation == "analyze_evolution" and params["analysis_type"] != "gene_tree":
        assert (
            request.url.params["type"]
            == {"homologs": "all", "orthologs": "orthologues", "paralogs": "paralogues"}[
                params["analysis_type"]
            ]
        )
        assert request.url.params["sequence"] == "protein"
        assert result["homology"] == payload
    if operation == "get_regulatory_elements":
        assert request.url.params.get_list("feature") == (
            ["regulatory", "motif"] if params["element_type"] == "both" else [params["element_type"]]
        )


@pytest.mark.parametrize("operation,params,path,valid", CASES)
@pytest.mark.parametrize("malformed", [{}, None, "bad", {"error": "synthetic-key-sentinel"}, [None]])
async def test_advertised_modes_reject_malformed_source(
    ensembl_http, operation, params, path, valid, malformed
):
    ensembl_http["payloads"][path] = malformed
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("ensembl", operation, params)
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize(
    "operation,params,path,valid",
    [c for c in CASES if c[0] not in {"get_sequences"} and c[1].get("analysis_type") != "gene_tree"],
)
async def test_explicit_empty_supported_where_provider_can_return_it(
    ensembl_http, operation, params, path, valid
):
    ensembl_http["payloads"][path] = (
        {"data": []}
        if operation == "analyze_evolution"
        else {"mappings": []}
        if operation == "map_coordinates"
        else []
    )
    result = await SourceAdapters().call("ensembl", operation, params)
    assert result


@pytest.mark.parametrize(
    "operation,params,path,valid", [CASES[0], CASES[4], CASES[7], CASES[8], CASES[11], CASES[13]]
)
async def test_public_mcp_failure_retries_with_success_and_provenance(
    ensembl_http, monkeypatch, operation, params, path, valid
):
    monkeypatch.setenv("UBI_PROFILE", "local")
    ensembl_http["payloads"][path] = {}
    args = {"source": "ensembl", "operation": operation, "params": params}
    async with Client(create_server(service=ResearchService())) as client:
        failed = (await client.call_tool("query_source", args, raise_on_error=False)).structured_content
        assert failed["outcome"] == "error" and failed["provenance"] == []
        assert failed["sections"]["ensembl"]["error"]["code"] == "invalid_source_response"
        ensembl_http["payloads"][path] = deepcopy(valid)
        good = (await client.call_tool("query_source", args)).structured_content
        assert good["outcome"] == "data" and good["provenance"]
    assert sum(request.url.path == path for request in ensembl_http["requests"]) == 2


@pytest.mark.parametrize(
    "patch",
    [{"species": "mus_musculus"}, {"id": "ENSG00000000001"}, {"version": 3}, {"object_type": "Transcript"}],
)
async def test_qualified_identity_rejects_wrong_source_before_sequence(ensembl_http, patch):
    ensembl_http["payloads"][f"/lookup/id/{GENE}"] = {**IDENTITY, **patch}
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("ensembl", "get_sequences", {"gene_id": GENE + ".2"})
    assert error.value.code == "invalid_source_response" and len(ensembl_http["requests"]) == 1


async def test_all_proteins_and_derived_fasta_retained(ensembl_http):
    rows = sequence("protein") + [{**sequence("protein")[0], "id": "ENSP00000000002", "seq": "MX"}]
    ensembl_http["payloads"][f"/sequence/id/{GENE}"] = rows
    result = await SourceAdapters().call(
        "ensembl", "get_sequences", {"gene_id": GENE, "sequence_type": "protein", "output_format": "fasta"}
    )
    assert result["sequences"] == rows
    assert result["data"] == f">{PROTEIN}.2\nMA\n>ENSP00000000002.2\nMX\n"
    assert result["format_origin"] == "derived_from_validated_json"


@pytest.mark.parametrize(
    "operation,params",
    [
        ("analyze_evolution", {"gene_id": GENE, "analysis_type": "gene_tree", "target_species": "mouse"}),
        ("get_sequences", {"gene_id": GENE + "/other"}),
        ("map_coordinates", {"region": "1:20-10", "source_assembly": "a", "target_assembly": "b"}),
        ("get_regulatory_elements", {"region": "1:1-5000001"}),
        ("batch_gene_lookup", {"gene_ids": [GENE, GENE]}),
    ],
)
async def test_unsupported_selectors_fail_before_http(ensembl_http, operation, params):
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("ensembl", operation, params)
    assert error.value.code == "invalid_parameters" and ensembl_http["requests"] == []


@pytest.mark.parametrize(
    "case,keys,value",
    [
        (3, [0, "query"], "ENSG00000000001"),
        (3, [0, "id"], "ENSMUSP00000000001"),
        (3, [0, "seq"], ""),
        (3, [0, "version"], True),
        (4, ["data", 0, "homologies"], None),
        (4, ["data", 0, "homologies", 0, "source"], {}),
        (4, ["data", 0, "homologies", 0, "source", "perc_id"], 101),
        (4, ["data", 0, "homologies", 0, "source", "id"], "ENSG00000000001"),
        (7, ["id"], GENE),
        (7, ["tree", "taxonomy", "scientific_name"], "Mus musculus"),
        (7, ["tree", "sequence", "id"], []),
        (7, ["tree", "confidence"], None),
        (8, [0, "start"], 100),
        (8, [0, "strand"], True),
        (11, ["mappings", 0, "mapped", "assembly"], "ForeignAssembly"),
        (11, ["mappings", 0, "original", "start"], 1),
        (11, ["mappings", 0, "mapped"], None),
        (13, [0, "input"], "rs999"),
        (13, [0, "intergenic_consequences"], []),
        (13, [0, "intergenic_consequences", 0, "consequence_terms"], None),
    ],
)
async def test_partial_nested_and_foreign_identity_fail(ensembl_http, case, keys, value):
    operation, params, path, payload = CASES[case]
    payload = deepcopy(payload)
    current = payload
    for key in keys[:-1]:
        current = current[key]
    current[keys[-1]] = value
    ensembl_http["payloads"][path] = payload
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("ensembl", operation, params)
    assert error.value.code == "invalid_source_response"


async def test_mouse_followup_and_homology_partner_order(ensembl_http):
    mouse = "ENSMUSG00000000001"
    ensembl_http["payloads"][f"/lookup/id/{mouse}"] = {**IDENTITY, "id": mouse, "species": "mus_musculus"}
    path = f"/homology/id/mus_musculus/{mouse}"
    payload = deepcopy(HOMOLOGY)
    payload["data"][0]["id"] = mouse
    ensembl_http["payloads"][path] = payload
    result = await SourceAdapters().call(
        "ensembl",
        "analyze_evolution",
        {"gene_id": mouse, "species": "mouse", "target_species": "human", "sequence_type": "cdna"},
    )
    assert result["query"]["species"] == "mus_musculus"
    request = ensembl_http["requests"][-1]
    assert request.url.params["target_species"] == "homo_sapiens" and request.url.params["sequence"] == "cdna"
    assert result["homology"] == payload


@pytest.mark.parametrize("kind", ["genomic", "cdna", "cds", "protein"])
async def test_empty_sequence_is_not_a_successful_sequence(ensembl_http, kind):
    ensembl_http["payloads"][f"/sequence/id/{GENE}"] = []
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("ensembl", "get_sequences", {"gene_id": GENE, "sequence_type": kind})
    assert error.value.code == "invalid_source_response"


async def test_translation_lookup_does_not_invent_missing_assembly(ensembl_http):
    ensembl_http["payloads"][f"/lookup/id/{PROTEIN}"] = {
        "id": PROTEIN,
        "version": 2,
        "species": "homo_sapiens",
        "object_type": "Translation",
        "Parent": TRANSCRIPT,
    }
    ensembl_http["payloads"][f"/sequence/id/{PROTEIN}"] = [{**sequence("protein")[0], "query": PROTEIN}]
    result = await SourceAdapters().call(
        "ensembl", "get_sequences", {"gene_id": PROTEIN, "sequence_type": "protein"}
    )
    assert "assembly_name" not in result["query"]


async def test_gene_transcripts_need_explicit_collection_and_parent(ensembl_http):
    transcript = {**IDENTITY, "id": TRANSCRIPT, "object_type": "Transcript", "Parent": GENE}
    ensembl_http["payloads"][f"/lookup/id/{GENE}"] = {**IDENTITY, "Transcript": [transcript]}
    result = await SourceAdapters().call(
        "ensembl", "query_genes", {"query": GENE, "query_type": "id", "include_transcripts": True}
    )
    assert result["transcripts"] == [transcript] and len(ensembl_http["requests"]) == 1
    ensembl_http["payloads"][f"/lookup/id/{GENE}"]["Transcript"] = None
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call(
            "ensembl", "query_genes", {"query": GENE, "query_type": "id", "include_transcripts": True}
        )
    assert error.value.code == "invalid_source_response"


async def test_xrefs_preserve_requested_identity(ensembl_http):
    ensembl_http["payloads"][f"/xrefs/id/{GENE}"] = [{"primary_id": "1097", "dbname": "HGNC"}]
    result = await SourceAdapters().call("ensembl", "get_xrefs", {"gene_id": GENE, "external_db": "HGNC"})
    assert result["query"] == IDENTITY and result["records"][0]["dbname"] == "HGNC"


async def test_batch_lookup_keeps_every_input_without_slicing(ensembl_http):
    other = "ENSG00000000001"
    ensembl_http["payloads"]["/lookup/id"] = {GENE: IDENTITY, other: {**IDENTITY, "id": other}}
    result = await SourceAdapters().call("ensembl", "batch_gene_lookup", {"gene_ids": [GENE, other]})
    assert {row["id"] for row in result["records"]} == {GENE, other}
    assert set(result["source_response"]) == {GENE, other}
    request = ensembl_http["requests"][-1]
    assert request.method == "POST" and other.encode() in request.content and GENE.encode() in request.content


async def test_batch_null_lookup_retains_peer_without_healthy_cache(ensembl_http):
    from biomedmcp.evidence import scientific_outcome
    from biomedmcp.runtime import ProviderRuntime

    other = "ENSG00000000001"
    ensembl_http["payloads"]["/lookup/id"] = {GENE: IDENTITY, other: None}
    adapters, runtime = SourceAdapters(), ProviderRuntime()

    async def retrieve():
        return await adapters.call("ensembl", "batch_gene_lookup", {"gene_ids": [GENE, other]})

    first, cached = await runtime.invoke("ensembl", {"synthetic": "null-batch"}, retrieve, scope="test")
    assert not cached and scientific_outcome(first["payload"]) == "partial"
    assert first["payload"]["records"] == [IDENTITY]
    assert first["payload"]["section_outcomes"][other]["outcome"] == "unavailable"
    second, cached = await runtime.invoke("ensembl", {"synthetic": "null-batch"}, retrieve, scope="test")
    assert not cached and len(ensembl_http["requests"]) == 2
    assert second["payload"]["section_outcomes"] == first["payload"]["section_outcomes"]
