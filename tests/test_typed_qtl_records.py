"""QTL identity, population meaning and acquired source pointers through actual MCP."""

import json
from copy import deepcopy

import jsonschema
import pytest
from fastmcp import Client
from gtex_helpers import GENCODE, VARIANT, association, dynamic, page
from pydantic import ValidationError

from biomedmcp.mcp.server import create_server
from biomedmcp.receipts import verify_receipt
from biomedmcp.runtime import digest

pytest_plugins = ["test_gtex_pagination"]


def metasoft():
    return {
        "gencodeId": GENCODE,
        "datasetId": "gtex_v10",
        "metaP": 0.01,
        "variantId": VARIANT,
        "tissues": {
            "Thyroid": {"mValue": 0.9, "pValue": 0.01, "se": 0.1, "nes": -0.5},
            "Liver": {"mValue": None, "pValue": None, "se": None, "nes": None},
        },
    }


CASES = [
    ("eqtl", "gene_associations", "/association/singleTissueEqtl", association()),
    ("sqtl", "gene_associations", "/association/singleTissueSqtl", association(splicing=True)),
    ("eqtl", "metasoft", "/association/metasoft", metasoft()),
    ("eqtl", "dynamic", "/association/dyneqtl", dynamic()),
    ("sqtl", "dynamic", "/association/dynsqtl", dynamic(splicing=True)),
]


def arguments(section, mode="gene_associations", **extra):
    return {
        "entity": "gene",
        "id": GENCODE,
        "sources": ["gtex"],
        "sections": [section],
        "source_versions": {"gtex": "gtex_v10"},
        "section_parameters": {section: {"tissue_id": "Thyroid", "analysis_mode": mode, "limit": 2, **extra}},
    }


@pytest.mark.parametrize("section,mode,endpoint,raw", CASES)
async def test_public_qtl_families_keep_typed_identity_inputs_and_unknown_population(
    paged_gtex, section, mode, endpoint, raw
):
    service, state = paged_gtex
    state["pages"][endpoint] = raw if mode == "dynamic" else {0: page([raw], size=2)}
    state["pages"].setdefault("/association/singleTissueSqtl", {0: page([association(splicing=True)])})
    extra = {"variant_id": VARIANT} if mode != "gene_associations" else {}
    if section == "sqtl" and mode == "dynamic":
        extra["phenotype_id"] = raw["phenotypeId"]
    async with Client(create_server(service=service)) as client:
        result = (await client.call_tool_mcp("get", arguments(section, mode, **extra))).structured_content
    assert result["outcome"] == "data", result
    assert verify_receipt(result)
    data = result["sections"][section]["data"]
    row = data["records" if mode == "dynamic" else "data"][0]
    assert row["record_type"].startswith("qtl_")
    assert row["species"] == 9606 and row["gene_identity"]["gencode_id"] == GENCODE
    assert row["gene_identity"]["gencode_version"] == "v39"
    assert row["source_release"] == "gtex_v10"
    assert row["participant_count"] is row["missing_measurement_count"] is None
    assert row["effect_allele"] is None and row["transcript"] is None
    assert row["source_record_sha256"] == digest(raw)
    assert row["input_locator"]["endpoint"] == endpoint
    assert row["input_locator"]["record_pointer"] == ("" if mode == "dynamic" else "/data/0")
    json.dumps(result, allow_nan=False)


async def test_filtered_qtl_points_to_its_original_source_row(paged_gtex):
    service, state = paged_gtex
    raw = association()
    state["pages"]["/association/singleTissueEqtl"] = {0: page([{**raw, "pValue": 0.5}, raw], size=2)}
    async with Client(create_server(service=service)) as client:
        value = (await client.call_tool("get", arguments("eqtl", p_value_threshold=0.05))).structured_content
    row = value["sections"]["eqtl"]["data"]["data"][0]
    assert row["input_locator"]["row_index"] == 1
    assert row["input_locator"]["measurements"]["pValue"] == "/data/1/pValue"
    assert row["source_record_sha256"] == digest(raw)


async def test_skipped_qtl_pages_retain_the_actual_source_page(paged_gtex):
    service, state = paged_gtex
    raw = association()
    state["pages"]["/association/singleTissueEqtl"] = {
        n: page([{**raw, "pValue": 0.5} if n < 2 else raw], total=3, size=1, index=n) for n in range(3)
    }
    async with Client(create_server(service=service)) as client:
        value = (
            await client.call_tool("get", arguments("eqtl", p_value_threshold=0.05, limit=1))
        ).structured_content
    row = value["sections"]["eqtl"]["data"]["data"][0]
    assert row["input_locator"]["page"] == 2 and row["input_locator"]["row_index"] == 0
    assert row["source_record_sha256"] == digest(raw)


async def test_dynamic_splicing_retains_the_actual_qualified_gene_intron_join(paged_gtex):
    service, state = paged_gtex
    raw = association(splicing=True)
    state["pages"]["/association/singleTissueSqtl"] = {
        0: page([{**raw, "phenotypeId": "chr7:300:400:clu_2"}], total=2, size=1),
        1: page([raw], total=2, size=1, index=1),
    }
    state["pages"]["/association/dynsqtl"] = dynamic(splicing=True)
    async with Client(create_server(service=service)) as client:
        value = (
            await client.call_tool(
                "get", arguments("sqtl", "dynamic", variant_id=VARIANT, phenotype_id=raw["phenotypeId"])
            )
        ).structured_content
    row = value["sections"]["sqtl"]["data"]["records"][0]
    join = row["phenotype_qualification"]
    assert join["gencodeId"] == GENCODE and join["phenotypeId"] == row["phenotypeId"]
    assert join["source_record_sha256"] == digest(raw)
    assert join["input_locator"]["page"] == 1
    assert join["input_locator"]["endpoint"] == "/association/singleTissueSqtl"


def normalized(index, release="gtex_v10"):
    from biomedmcp.qtl_records import gene_identity, qtl_record

    section, mode, _, raw = CASES[index]
    raw = deepcopy(raw)
    if "datasetId" in raw:
        raw["datasetId"] = release
    join = None
    if index == 4:
        join = qtl_record(
            {**association(splicing=True), "datasetId": release},
            qtl_type="sqtl",
            mode="gene_associations",
            dataset=release,
            gene=gene_identity(GENCODE, release),
            tissue="Thyroid",
            page=0,
            row_index=0,
        )
    return qtl_record(
        raw,
        qtl_type=section,
        mode=mode,
        dataset=release,
        gene=gene_identity(GENCODE, release),
        tissue="Thyroid",
        page=None if mode == "dynamic" else 0,
        row_index=None if mode == "dynamic" else 0,
        phenotype_qualification=join,
    )


@pytest.mark.parametrize("index", range(len(CASES)))
def test_qtl_field_schemas_and_original_source_fields_agree(index):
    from biomedmcp.qtl_records import NORMALIZED_FIELDS, QTL_RECORDS

    row = normalized(index)
    assert {k: v for k, v in row.items() if k not in NORMALIZED_FIELDS} == CASES[index][3]
    jsonschema.validate(row, QTL_RECORDS.json_schema())


@pytest.mark.parametrize(
    "index,path,value",
    [
        (0, ("participant_count",), 3),
        (0, ("missing_measurement_count",), 0),
        (0, ("species",), 10090),
        (0, ("effect_allele",), "T"),
        (0, ("measurement_units",), "TPM"),
        (0, ("transcript",), "ENST00000288602.10"),
        (0, ("source_release",), "gtex_v8"),
        (0, ("source_release_basis",), "acquisition_parameter"),
        (0, ("gene_identity", "gencode_version"), "v26"),
        (0, ("identity_basis",), "provider_reported_gene"),
        (0, ("input_locator", "page"), None),
        (0, ("input_locator", "measurements", "pValue"), "/data/1/pValue"),
        (0, ("variant_identity", "reference"), "G"),
        (0, ("pValue",), True),
        (0, ("pValue",), "0.01"),
        (0, ("pValue",), -0.1),
        (0, ("pValue",), 1.1),
        (0, ("nes",), float("nan")),
        (0, ("nes",), float("inf")),
        (0, ("source_record_sha256",), "0" * 64),
        (0, ("method",), "Infer a causal effect"),
        (1, ("phenotype_namespace",), None),
        (2, ("tissues", "Thyroid", "mValue"), 1.1),
        (2, ("tissues", "Thyroid", "se"), -1),
        (2, ("tissue_scope",), "single_reported_tissue"),
        (3, ("paired_measurement_count",), 4),
        (3, ("genotypes", 0), True),
        (3, ("genotypes", 0), 3),
        (3, ("homoRefCount",), 2),
        (3, ("error",), -0.1),
        (3, ("input_locator", "page"), 0),
        (3, ("input_locator", "response_sha256"), "0" * 64),
        (3, ("source_release_basis",), "provider_row"),
        (4, ("phenotype_qualification", "phenotypeId"), "chr7:300:400:clu_2"),
        (4, ("pValueThreshold",), None),
    ],
)
def test_contradictory_qtl_science_cannot_validate_as_success(index, path, value):
    from biomedmcp.qtl_records import QTL_RECORDS

    row = normalized(index)
    target = row
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        QTL_RECORDS.validate_python(row)


@pytest.mark.parametrize("splicing", [False, True])
def test_gene_summary_keeps_nominal_empirical_and_adjusted_probabilities_separate(splicing):
    from gtex_helpers import egene

    from biomedmcp.qtl_records import QTL_RECORDS, qtl_record

    raw = egene(splicing=splicing)
    raw.update(pValue=0.5, empiricalPValue=0.01, qValue=0.02)
    if not splicing:
        raw["log2AllelicFoldChange"] = None
    row = qtl_record(
        raw,
        qtl_type="sqtl" if splicing else "eqtl",
        mode="genes_list",
        dataset="gtex_v10",
        tissue="Thyroid",
        page=2,
        row_index=3,
    )
    assert row["variant_identity"] is None and row["identity_basis"] == "provider_reported_gene"
    assert row["pValue"] == 0.5 and row["empiricalPValue"] == 0.01 and row["qValue"] == 0.02
    assert row["participant_count"] is None
    jsonschema.validate(row, QTL_RECORDS.json_schema())


def test_metasoft_retains_null_missing_and_independent_tissue_probabilities():
    from biomedmcp.qtl_records import gene_identity, qtl_record

    raw = metasoft()
    raw["tissues"]["Whole_Blood"] = {}
    row = qtl_record(
        raw,
        qtl_type="eqtl",
        mode="metasoft",
        dataset="gtex_v10",
        gene=gene_identity(GENCODE, "gtex_v10"),
        page=0,
        row_index=0,
    )
    assert row["tissues"]["Whole_Blood"] == {}
    assert all(v is None for v in row["tissues"]["Liver"].values())
    assert row["tissues"]["Thyroid"]["mValue"] == 0.9
    assert row["source_record_sha256"] == digest(raw)


@pytest.mark.parametrize("present", [False, True])
def test_dynamic_eqtl_preserves_absent_versus_null_source_threshold(present):
    from biomedmcp.qtl_records import gene_identity, qtl_record

    raw = dynamic()
    if present:
        raw["pValueThreshold"] = None
    else:
        del raw["pValueThreshold"]
    row = qtl_record(
        raw,
        qtl_type="eqtl",
        mode="dynamic",
        dataset="gtex_v10",
        gene=gene_identity(GENCODE, "gtex_v10"),
        tissue="Thyroid",
    )
    assert ("pValueThreshold" in row) == present
    assert row["source_record_sha256"] == digest(raw)


async def test_filtered_provider_annotation_cannot_spoof_a_population_or_become_empty_evidence(
    paged_gtex, caplog
):
    service, state = paged_gtex
    state["pages"]["/association/singleTissueEqtl"] = {
        0: page(
            [
                {
                    **association(),
                    "pValue": 0.5,
                    "participant_count": 100,
                    "method": "synthetic-qtl-credential-sentinel",
                }
            ],
            size=2,
        )
    }
    args = arguments("eqtl", p_value_threshold=0.05)
    async with Client(create_server(service=service)) as client:
        failed = (await client.call_tool_mcp("get", args)).structured_content
        section = failed["sections"]["eqtl"]
        assert section["error"]["code"] == "invalid_source_response"
        assert section["data"] is None and section["evidence_ids"] == []
        assert failed["provenance"] == []
        state["pages"]["/association/singleTissueEqtl"][0] = page([association()], size=2)
        valid = (await client.call_tool("get", args)).structured_content
    assert valid["outcome"] == "data"
    assert "synthetic-qtl-credential-sentinel" not in json.dumps(failed) + caplog.text
    assert len([r for r in state["requests"] if r.url.path.endswith("singleTissueEqtl")]) == 2


async def test_conflicting_acquired_associations_keep_independent_hashes_and_row_locators(paged_gtex):
    service, state = paged_gtex
    rows = [association(), {**association(), "nes": 0.5}]
    state["pages"]["/association/singleTissueEqtl"] = {0: page(rows, size=2)}
    async with Client(create_server(service=service)) as client:
        result = (await client.call_tool("get", arguments("eqtl"))).structured_content
        schema = (await client.call_tool("capabilities", {"source": "gtex"})).structured_content[
            "record_schemas"
        ]["qtl"]
    data = result["sections"]["eqtl"]["data"]["data"]
    assert [r["nes"] for r in data] == [-0.5, 0.5]
    assert [r["source_record_sha256"] for r in data] == [digest(r) for r in rows]
    assert [r["input_locator"]["row_index"] for r in data] == [0, 1]
    assert all(r["input_locator"]["response_sha256"] == digest(page(rows, size=2)) for r in data)
    for row in data:
        jsonschema.validate(row, schema)
    assert verify_receipt(result)


async def test_bounded_dynamic_arrays_recover_aligned_values_with_the_same_evidence(paged_gtex):
    service, state = paged_gtex
    raw = dynamic()
    raw["data"] = list(range(31))
    raw["genotypes"] = [i % 3 for i in range(31)]
    for category, field in ((0, "homoRefCount"), (1, "hetCount"), (2, "homoAltCount")):
        raw[field] = raw["genotypes"].count(category)
    state["pages"]["/association/dyneqtl"] = raw
    async with Client(create_server(service=service)) as client:
        result = (
            await client.call_tool("get", arguments("eqtl", "dynamic", variant_id=VARIANT))
        ).structured_content
        section = result["sections"]["eqtl"]
        row = section["data"]["records"][0]
        assert row["paired_measurement_count"] == 31 and row["participant_count"] is None
        assert len(row["data"]) == len(row["genotypes"]) == 25
        for field in ("data", "genotypes"):
            omission = next(
                x for x in section["recovery"]["omissions"] if x["pointer"] == f"/records/0/{field}"
            )
            recovered = json.loads((await client.read_resource(omission["uri"]))[0].text)
            assert recovered["value"] == raw[field][25:]
            assert recovered["evidence_ids"] == section["evidence_ids"]
    assert row["source_record_sha256"] == digest(raw) and verify_receipt(result)
    assert len([r for r in state["requests"] if r.url.path.endswith("dyneqtl")]) == 1


@pytest.mark.parametrize("release", ["gtex_v8", "gtex_v10"])
@pytest.mark.parametrize("index", range(len(CASES)))
def test_qtl_family_keeps_the_supported_release_and_its_reference_annotation(index, release):
    row = normalized(index, release)
    assert row["source_release"] == row["gene_identity"]["dataset_id"] == release
    assert row["gene_identity"]["gencode_version"] == ("v26" if release == "gtex_v8" else "v39")
    assert row["variant_identity"]["dataset_id"] == release
    if index == 4:
        assert row["phenotype_qualification"]["source_release"] == release


async def test_gene_association_preserves_long_source_alleles_within_the_result_budget(paged_gtex):
    service, state = paged_gtex
    raw = association()
    reference = "A" * 512
    raw["variantId"] = f"chr7_{raw['pos']}_{reference}_T_b38"
    state["pages"]["/association/singleTissueEqtl"] = {0: page([raw], size=2)}
    async with Client(create_server(service=service)) as client:
        result = (await client.call_tool_mcp("get", arguments("eqtl"))).structured_content
    assert result["outcome"] == "data", result
    row = result["sections"]["eqtl"]["data"]["data"][0]
    assert row["variantId"] == row["variant_identity"]["variant_id"] == raw["variantId"]
    assert row["variant_identity"]["reference"] == reference
    assert row["source_record_sha256"] == digest(raw)


def test_dynamic_splicing_retains_signed_provider_values_without_inventing_units():
    from biomedmcp.qtl_records import gene_identity, qtl_record

    raw = dynamic(splicing=True)
    raw["data"] = [-0.5, 0, 1.0]
    row = qtl_record(
        raw,
        qtl_type="sqtl",
        mode="dynamic",
        dataset="gtex_v10",
        gene=gene_identity(GENCODE, "gtex_v10"),
        tissue="Thyroid",
        phenotype_qualification=normalized(1),
    )
    assert row["data"] == [-0.5, 0, 1.0] and type(row["data"][1]) is int
    assert row["measurement_units"] is None
    assert row["source_record_sha256"] == digest(raw)
