import pytest
from native_helpers import BRAF, HTTP

from biomedmcp.errors import ResearchError
from biomedmcp.native.variants import Variants, exact_annotations, protein_change


@pytest.mark.parametrize(
    "input,expected",
    [
        ("p.Val600Glu", "V600E"),
        ("NP_004324.2:p.Val600Glu", "V600E"),
        ("V600E", "V600E"),
        ("p.Trp24Ter", "W24*"),
        ("banana", None),
    ],
)
def test_protein_normalization(input, expected):
    assert protein_change(input) == expected


def test_annotation_matching_does_not_make_cross_product():
    hit = {
        "snpeff": {
            "ann": [
                {"genename": "OTHER", "hgvs_p": "p.Val600Glu"},
                {"genename": "BRAF", "hgvs_p": "p.Val600Lys"},
            ]
        },
        "dbnsfp": {"genename": ["BRAF", "OTHER"], "hgvsp": ["p.Val600Glu", "p.Val600Lys"]},
    }
    assert not exact_annotations(hit, "BRAF", "V600E")
    assert exact_annotations(BRAF, "BRAF", "V600E")


async def test_variant_resolution_filters_fuzzy_provider_hits():
    wrong = {
        **BRAF,
        "_id": "chr7:g.140453136A>C",
        "snpeff": {"ann": [{"genename": "BRAF", "hgvs_p": "p.Val600Lys"}]},
        "dbnsfp": {"genename": "OTHER", "hgvsp": "p.Val600Glu"},
    }
    http = HTTP({"hits": [wrong, BRAF], "total": 2})
    data = await Variants(http).resolve("BRAF V600E")
    assert data["resolution"] == "exact" and data["annotation"] == {
        **BRAF,
        "matched_annotations": BRAF["snpeff"]["ann"],
    }
    assert data["assembly"] == "grch37"


async def test_multiple_alleles_for_same_protein_change_remain_ambiguous():
    data = await Variants(HTTP({"hits": [BRAF, {**BRAF, "_id": "chr7:g.140453136A>C"}], "total": 2})).resolve(
        "BRAF V600E"
    )
    assert data["resolution"] == "ambiguous" and len(data["candidates"]) == 2


async def test_wrong_rs_id_is_not_credited_as_an_exact_match():
    data = await Variants(HTTP({"hits": [{"_id": "x", "dbsnp": {"rsid": "rs2"}}], "total": 1})).resolve("rs1")
    assert data["resolution"] == "empty"


async def test_genomic_assembly_and_alleles_are_explicit():
    http = HTTP([{"_id": "chr7:g.140753336A>T"}, {"_id": "chr7:g.140753336A>C"}])
    data = await Variants(http).resolve("chr7:140753336:A:T", "grch38")
    assert http.calls[0][2]["params"]["assembly"] == "hg38"
    assert "/variant/" in http.calls[0][1]
    assert data["id"] == "chr7:g.140753336A>T"
    assert data["identity"]["reference"] == "A"


@pytest.mark.parametrize("value", ["BRAF V600E", "rs113488022", "NM_004333.6:c.1799T>A"])
def test_assembly_cannot_relabel_a_transcript_or_protein(value):
    with pytest.raises(ResearchError, match="Assembly"):
        Variants().validate(value, "grch38")


async def test_gnomad_zero_denominator_and_exact_allele():
    from gnomad_helpers import frequency, population

    response = population()
    response["data"]["variant"]["exome"] = frequency(0, 0)
    http = HTTP(response)
    data = await Variants(http).population(
        {
            "identity": {
                "chromosome": "7",
                "position": 140753336,
                "reference": "A",
                "alternate": "T",
                "assembly": "grch38",
            }
        }
    )
    assert data["variant"]["exome"]["allele_frequency"] is None
    assert data["variant"]["genome"]["allele_frequency"] == 0.02
    assert data["release"] is None and data["dataset_selector"] == "gnomad_r4"


async def test_gnomad_refuses_wrong_returned_allele():
    from gnomad_helpers import population

    response = population()
    response["data"]["variant"].update(variant_id="7-140753336-A-C", alt="C")
    http = HTTP(response)
    with pytest.raises(ResearchError, match="different allele"):
        await Variants(http).population(
            {
                "identity": {
                    "chromosome": "7",
                    "position": 140753336,
                    "reference": "A",
                    "alternate": "T",
                    "assembly": "grch38",
                }
            }
        )


async def test_civic_excludes_compound_and_other_allele_profiles():
    from copy import deepcopy

    from civic_helpers import EVIDENCE, response

    compound, other = deepcopy(EVIDENCE), deepcopy(EVIDENCE)
    compound["id"], other["id"] = 2, 3
    compound["molecularProfile"].update(name="BRAF V600E + TP53 R175H", isComplex=True, isMultiVariant=True)
    other["molecularProfile"]["name"] = "BRAF V600K"
    other["molecularProfile"]["variants"][0]["name"] = "V600K"
    http = HTTP(response((EVIDENCE, compound, other), ()))
    data = await Variants(http).civic("BRAF p.Val600Glu")
    assert [r["id"] for r in data["evidenceItems"]["nodes"]] == [1]
    assert http.calls[0][2]["body"]["variables"]["name"] == "BRAF V600E"
    assert "status:ACCEPTED" in http.calls[0][2]["body"]["query"]


async def test_clingen_normalization_and_expert_endpoints():
    from clingen_helpers import ASSERTION, SPECIFICATION, allele, envelope

    http = HTTP(allele(), envelope([ASSERTION]), envelope([SPECIFICATION]))
    client = Variants(http)
    await client.normalize("NM_004333.6:c.1799T>A")
    await client.assertions("CA1")
    await client.specifications("BRAF")
    assert http.calls[0][2]["params"]["hgvs"] == "NM_004333.6:c.1799T>A"
    assert http.calls[1][2]["params"]["matchTypes"] == "exact"
    assert http.calls[2][1].startswith("https://cspec.clinicalgenome.org/")


@pytest.mark.parametrize(
    "accession,build", [("NC_000007.13:g.140453136A>T", "grch37"), ("NC_000007.14:g.140753336A>T", "grch38")]
)
def test_refseq_chromosome_accession_preserves_assembly(accession, build):
    kind, identity = Variants().validate(accession)
    assert kind == "genomic" and identity["assembly"] == build and identity["chromosome"] == "7"


async def test_transcript_hgvs_uses_conjunctive_query_and_annotation_match():
    http = HTTP({"hits": [BRAF], "total": 1})
    result = await Variants(http).resolve("NM_004333.6:c.1799T>A")
    assert result["resolution"] == "exact"
    assert 'snpeff.ann.feature_id:"NM_004333.6"' in http.calls[0][2]["params"]["q"]
    assert 'snpeff.ann.hgvs_c:"c.1799T>A"' in http.calls[0][2]["params"]["q"]
