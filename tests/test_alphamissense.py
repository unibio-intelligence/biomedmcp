"""AlphaMissense scores preserve licenses, exact identities and missingness."""

import copy

import pytest
from native_helpers import HTTP

from biomedmcp.contracts import GetRequest
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.alphamissense import acquire, plan, score
from biomedmcp.source_licensing import review

pytestmark = pytest.mark.source_permissions


def protein_inputs():
    return [
        {
            "results": [
                {
                    "primaryAccession": "P15056",
                    "entryType": "UniProtKB reviewed (Swiss-Prot)",
                    "organism": {"taxonId": 9606},
                    "genes": [{"geneName": {"value": "BRAF"}}],
                    "sequence": {"value": "MV"},
                    "entryAudit": {"sequenceVersion": 4},
                }
            ]
        },
        {
            "uniprotAccession": "P15056",
            "uniprotSequence": "MV",
            "uniprotStart": 1,
            "uniprotEnd": 2,
            "amAnnotationsUrl": "https://alphafold.ebi.ac.uk/files/AF-P15056-F1-aa-substitutions.csv",
        },
        "protein_variant,am_pathogenicity,am_class\nV2E,0.91,LPath\nV2A,0.2,LBen\n",
    ]


def protein_http():
    up, af, csv = protein_inputs()
    return HTTP(up, [af], csv)


def vep_row(value="7 10 10 A/T 1"):
    return {
        "input": value,
        "id": value,
        "assembly_name": "GRCh38",
        "seq_region_name": "7",
        "start": 10,
        "end": 10,
        "strand": 1,
        "allele_string": "A/T",
        "transcript_consequences": [
            {
                "transcript_id": "ENST123",
                "gene_id": "ENSG123",
                "gene_symbol": "BRAF",
                "variant_allele": "T",
                "consequence_terms": ["missense_variant"],
                "amino_acids": "V/E",
                "protein_start": 2,
                "protein_end": 2,
                "alphamissense": {"am_pathogenicity": 0.91, "am_class": "likely_pathogenic"},
                "polyphen_score": 0.9,
                "sift_score": 0.1,
                "cadd": {"score": 30},
            }
        ],
    }


async def test_canonical_protein_score_is_exact_bounded_attributed_and_content_bound():
    http = protein_http()
    value = await acquire(http, "BRAF V2E")
    assert len(http.calls) == 3
    assert value["records"][0]["score"] == 0.91
    assert value["records"][0]["protein_variant"] == "V2E"
    assert value["protein_identity"]["sequence_version"] == 4
    assert len(value["score_artifact_sha256"]) == 64
    assert value["score_artifact_sha256"] in value["source_release"]
    assert value["license"] == "CC-BY-4.0" and "DeepMind" in value["attribution"]
    assert not value["coverage"]["exact_dataset_release_reported"]
    assert "genomic allele" in value["coverage"]["scope"]
    assert not any("myvariant" in call[1] for call in http.calls)


@pytest.mark.parametrize("change", ["sequence", "accession", "range", "foreign_url", "missing_scores"])
async def test_protein_metadata_never_relabels_a_different_sequence_or_asset(change):
    up, af, csv = protein_inputs()
    if change == "sequence":
        af["uniprotSequence"] = "MA"
    if change == "accession":
        af["uniprotAccession"] = "P99999"
    if change == "range":
        af["uniprotEnd"] = 1
    if change == "foreign_url":
        af["amAnnotationsUrl"] = "https://evil.example/score.csv"
    if change == "missing_scores":
        af.pop("amAnnotationsUrl")
    http = HTTP(up, [af], csv)
    with pytest.raises(ResearchError) as error:
        await acquire(http, "BRAF V2E")
    assert error.value.code in {"identity_mismatch", "source_unavailable"}
    assert len(http.calls) == 2


@pytest.mark.parametrize("change", ["wrong_reference", "outside_sequence", "ambiguous_gene", "wrong_species"])
async def test_protein_identity_is_qualified_before_score_reads(change):
    up, af, csv = protein_inputs()
    query = (
        "BRAF A2E"
        if change == "wrong_reference"
        else "BRAF V3E"
        if change == "outside_sequence"
        else "BRAF V2E"
    )
    if change == "ambiguous_gene":
        up["results"].append(copy.deepcopy(up["results"][0]))
    if change == "wrong_species":
        up["results"][0]["organism"]["taxonId"] = 10090
    http = HTTP(up, [af], csv)
    with pytest.raises(ResearchError):
        await acquire(http, query)
    assert len(http.calls) == 1


@pytest.mark.parametrize(
    "csv",
    [
        "variant,score,class\nV2E,0.9,LPath\n",
        "protein_variant,am_pathogenicity,am_class\n",
        "protein_variant,am_pathogenicity,am_class\nV2E,nan,LPath\n",
        "protein_variant,am_pathogenicity,am_class\nV2E,1.1,LPath\n",
        "protein_variant,am_pathogenicity,am_class\nV2E,0.9,other\n",
        "protein_variant,am_pathogenicity,am_class\nA2E,0.9,LPath\n",
        "protein_variant,am_pathogenicity,am_class\nV2E,0.9,LPath\nV2E,0.8,LPath\n",
    ],
)
async def test_bad_score_files_never_become_predictions_or_negative_evidence(csv):
    up, af, _ = protein_inputs()
    with pytest.raises(ResearchError):
        await acquire(HTTP(up, [af], csv), "BRAF V2E")


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -0.1, 1.1, "0.5", None])
def test_score_values_are_finite_numbers_not_truthy_or_coerced_values(value):
    with pytest.raises(ResearchError):
        score(value, "likely_pathogenic")


async def test_exact_genomic_score_discards_unreviewed_predictor_fields():
    http = HTTP([vep_row()], {"release": 116})
    value = await acquire(http, "chr7:10:A:T", "grch38")
    row = value["records"][0]
    assert row["score"] == 0.91 and row["variant_allele"] == "T"
    assert row["transcript_id"] == "ENST123" and row["protein_variant"] == "V2E"
    assert not {"polyphen_score", "sift_score", "cadd"} & set(row)
    assert "116" in value["source_release"] and "not reported" in value["source_release"]
    assert http.calls[0][2]["params"]["AlphaMissense"] == 1
    assert http.calls[0][1] == "https://rest.ensembl.org/vep/human/region/7%3A10-10%3A1/T"
    assert "vep_region_get" in value["source_url"]


async def test_rsid_preserves_multiple_alleles_and_transcripts_without_averaging():
    raw = vep_row("rs123")
    raw["allele_string"] = "A/C/T"
    extra = copy.deepcopy(raw["transcript_consequences"][0])
    extra["variant_allele"] = "C"
    extra["alphamissense"]["am_pathogenicity"] = 0.87
    raw["transcript_consequences"].append(extra)
    value = await acquire(HTTP([raw], {"release": 116}), "rs123")
    assert {r["variant_allele"] for r in value["records"]} == {"C", "T"}
    assert {r["score"] for r in value["records"]} == {0.87, 0.91}
    assert "multiallelic" in value["coverage"]["scope"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("input", "other"),
        ("assembly_name", "GRCh37"),
        ("start", 11),
        ("end", 11),
        ("seq_region_name", "8"),
        ("allele_string", "G/T"),
        ("strand", -1),
    ],
)
async def test_vep_cannot_substitute_a_different_input_build_coordinate_or_reference(key, value):
    row = vep_row()
    row[key] = value
    with pytest.raises(ResearchError) as error:
        await acquire(HTTP([row]), "chr7:10:A:T")
    assert error.value.code == "identity_mismatch"


async def test_absent_missense_score_is_explicit_and_not_a_zero_score():
    row = vep_row()
    row["transcript_consequences"][0].pop("alphamissense")
    value = await acquire(HTTP([row], {"release": 116}), "chr7:10:A:T")
    assert value["records"] == []
    assert value["coverage"]["score_status"] == "no_missense_prediction_supplied"


async def test_grch37_is_routed_to_the_correct_official_reference():
    row = vep_row()
    row["assembly_name"] = "GRCh37"
    http = HTTP([row], {"release": 115})
    await acquire(http, "chr7:10:A:T", "grch37")
    assert all(c[1].startswith("https://grch37.rest.ensembl.org/") for c in http.calls)


@pytest.mark.parametrize("identifier", ["BRAF V2V", "BRAF V2*", "chr7:10:A:AT"])
def test_nonmissense_queries_fail_before_network(identifier):
    with pytest.raises(ResearchError):
        plan(identifier)


async def test_real_public_permission_dispatch_has_no_myvariant_identity_dependency():
    from biomedmcp.dispatch import execute
    from biomedmcp.receipts import verify_receipt

    service = ResearchService(http=protein_http())
    req = GetRequest(entity="variant", id="BRAF V2E", sections=["predictions"])
    assert service._get_plan(req) == {"predictions": ("alphamissense", ["uniprot"])}
    value = (
        await execute(
            service, "variant_evidence", {"id": "BRAF V2E", "sections": ["predictions"]}, scope="test"
        )
    ).model_dump(mode="json")
    assert value["outcome"] == "data" and verify_receipt(value)
    assert value["provenance"][0]["source"] == "alphamissense"
    assert value["provenance"][0]["sources"] == ["alphamissense", "uniprot"]
    assert value["provenance"][0]["source_version"]
    assert review("myvariant")["release_status"] == "unreleased"
    assert review("alphamissense")["release_status"] == "eligible"


@pytest.mark.parametrize(
    "value,classification",
    [(0.9, "likely_benign"), (0.1, "likely_pathogenic"), (0.9, "ambiguous"), (0.5, {}), (0.5, [])],
)
def test_contradictory_or_malformed_classes_fail_without_reclassification(value, classification):
    with pytest.raises(ResearchError):
        score(value, classification)


@pytest.mark.parametrize(
    "value,classification",
    [(0.34, "likely_benign"), (0.34, "ambiguous"), (0.564, "likely_pathogenic"), (0.564, "ambiguous")],
)
def test_rounded_boundary_classes_remain_provider_reported(value, classification):
    assert score(value, classification)["classification"] == classification


@pytest.mark.parametrize(
    "field,value", [("genes", None), ("sequence", []), ("entryAudit", None), ("organism", "human")]
)
async def test_malformed_nested_identity_fields_are_source_errors(field, value):
    up, af, csv = protein_inputs()
    up["results"][0][field] = value
    with pytest.raises(ResearchError) as error:
        await acquire(HTTP(up, [af], csv), "BRAF V2E")
    assert error.value.code == "invalid_source_response"


async def test_mixed_case_human_gene_symbols_keep_the_source_canonical_spelling():
    up, af, csv = protein_inputs()
    up["results"][0]["genes"][0]["geneName"]["value"] = "C1orf43"
    value = await acquire(HTTP(up, [af], csv), "C1orf43 V2E")
    assert value["records"][0]["gene"] == "C1orf43"
    assert value["protein_identity"]["gene"] == "C1orf43"
