"""Direct ClinVar is available without restricted aggregator annotations."""

from copy import deepcopy

import pytest
from native_helpers import HTTP
from clinvar_helpers import variant

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.clinvar import assertions
from biomedmcp.native.variants import Variants


def http(row=None):
    return HTTP({"esearchresult": {"count": "1", "idlist": ["13961"]}},
                {"result": {"uids": ["13961"], "13961": row or variant()}})


@pytest.mark.parametrize("identifier,assembly", [("BRAF V600E", None), ("rs113488022", None),
    ("NM_004333.6:c.1799T>A", None), ("chr7:140753336:A:T", "grch38"),
    ("chr7:140453136:A:T", "grch37"), ("NC_000007.14:g.140753336A>T", None)])
async def test_exact_variants_retain_independent_classifications_and_record_version(identifier, assembly):
    row = variant()
    if assembly == "grch37":
        row["variation_set"][0]["canonical_spdi"] = "NC_000007.13:140453135:A:T"
    wire = http(row)
    data = await assertions(Variants(wire), identifier, assembly)
    row = data["records"][0]
    assert row["id"] == data["source_release"] == "VCV000013961.143"
    assert row["classifications"]["germline_classification"]["description"] == "Pathogenic"
    assert row["classifications"]["clinical_impact_classification"]["description"] == "Tier I - Strong"
    assert row["classifications"]["oncogenicity_classification"]["description"] == "Oncogenic"
    assert all("eutils.ncbi.nlm.nih.gov" in c[1] for c in wire.calls)


@pytest.mark.parametrize("change", ["protein", "gene", "allele", "assembly", "rsid", "multiple"])
async def test_broad_candidates_cannot_substitute_other_alleles(change):
    row = variant()
    name, assembly = "BRAF V600E", None
    if change == "protein":
        row["variation_set"][0]["variation_name"] = "NM_004333.6(BRAF):c.1A>T (p.Val600Lys)"
    elif change == "gene":
        row["variation_set"][0]["variation_name"] = "NM_004333.6(OTHER):c.1A>T (p.Val600Glu)"
    elif change == "allele":
        name, assembly = "chr7:140753336:A:G", "grch38"
    elif change == "assembly":
        name, assembly = "chr7:140453136:A:T", "grch37"
    elif change == "rsid":
        name = "rs12345"
    else:
        row["variation_set"].append(deepcopy(row["variation_set"][0]))
    with pytest.raises(ResearchError) as error:
        await assertions(Variants(http(row)), name, assembly)
    assert error.value.code == "unresolved_identity"


@pytest.mark.parametrize("search", [{}, {"count": "1", "idlist": []}, {"count": True, "idlist": []},
                                   {"count": "0", "idlist": [], "errorlist": None},
                                   {"count": "0", "idlist": [], "errorlist": []},
                                   {"count": "0", "idlist": [], "errorlist": {"fieldsnotfound": ["bad"]}}])
async def test_malformed_search_never_means_no_variants(search):
    with pytest.raises(ResearchError) as error:
        await assertions(Variants(HTTP({"esearchresult": search})), "BRAF V600E", None)
    assert error.value.code == "invalid_source_response"


async def test_source_scoped_zero_and_missing_classifications_are_explicit():
    data = await assertions(Variants(HTTP({"esearchresult": {"count": "0", "idlist": []}})), "BRAF V600E", None)
    assert data["records"] == [] and data["coverage"]["candidates_checked"] == 0
    row = variant()
    row.pop("germline_classification")
    data = await assertions(Variants(http(row)), "BRAF V600E", None)
    assert data["records"][0]["classifications"]["germline_classification"] is None


@pytest.mark.parametrize("change", ["uids", "uid", "version", "location", "classification"])
async def test_corrupt_summary_metadata_is_not_released(change):
    row = variant()
    if change == "uid":
        row["uid"] = "other"
    elif change == "version":
        row["accession_version"] = "unversioned"
    elif change == "location":
        row["variation_set"][0]["variation_loc"][0]["assembly_name"] = None
    elif change == "classification":
        row["germline_classification"] = {"description": []}
    wire = http(row)
    if change == "uids":
        wire.responses[1]["result"]["uids"] = ["other"]
    with pytest.raises(ResearchError) as error:
        await assertions(Variants(wire), "chr7:140753336:A:T", "grch38")
    assert error.value.code == "invalid_source_response"


async def test_discovery_bound_does_not_claim_exact_identity_or_read_partial_candidates():
    wire = HTTP({"esearchresult": {"count": "26", "idlist": [str(n) for n in range(25)]}})
    with pytest.raises(ResearchError) as error:
        await assertions(Variants(wire), "BRAF V600E", None)
    assert error.value.code == "ambiguous_identifier"
    assert len(wire.calls) == 1


@pytest.mark.source_permissions
async def test_canonical_variant_task_releases_clinvar_without_myvariant():
    service = ResearchService(http=http())
    result = await execute(service, "variant_evidence", {"id": "BRAF V600E", "sections": ["clinvar"]}, scope="test")
    assert result.outcome == "data"
    assert result.sections["clinvar"].data["records"][0]["id"] == "VCV000013961.143"
    assert result.provenance[0].source == "ncbi"
    assert result.provenance[0].source_version == "VCV000013961.143"
    assert result.receipt.sources == ["ncbi"]
    assert not service.source_availability("myvariant")[0]
