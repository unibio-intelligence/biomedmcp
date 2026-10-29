"""Validate current GTEx response contracts before any scientific extraction."""

import json
import math
import re
from importlib.resources import files

from jsonschema import Draft202012Validator

from biomedmcp.errors import ResearchError

from .identity import SNP_ID, VARIANT_ID, release_parameters

CONTRACT = json.loads(files("gtex_mcp").joinpath("contracts.json").read_text())
VALIDATORS = {
    endpoint: Draft202012Validator({**schema, "components": CONTRACT["components"]})
    for endpoint, schema in CONTRACT["endpoints"].items()
}
REQUEST_VALIDATORS = {
    endpoint: Draft202012Validator({**schema, "components": CONTRACT["components"]})
    for endpoint, schema in CONTRACT["requests"].items()
}
PROBABILITIES = {"pValue", "qValue", "pValueThreshold", "empiricalPValue", "metaP", "maf", "mValue"}
NONNEGATIVE = {
    "median",
    "error",
    "se",
    "pos",
    "start",
    "end",
    "tss",
    "nPhenotypes",
    "dbSnpBuild",
    "numberOfPages",
    "page",
    "maxItemsPerPage",
    "totalNumberOfItems",
    "count",
    "femaleCount",
    "maleCount",
}


def invalid():
    # Raw validation errors contain submitted fields and provider values.
    raise ResearchError("invalid_source_response", "GTEx returned an invalid scientific response.")


def validate_request(endpoint, params):
    schema = CONTRACT["requests"].get(endpoint)
    if schema is None:
        raise ResearchError("invalid_provider_request", "GTEx acquisition has no qualified request contract.")
    normalized = {
        key: [value]
        if schema["properties"].get(key, {}).get("type") == "array" and not isinstance(value, list)
        else value
        for key, value in (params or {}).items()
    }
    if next(REQUEST_VALIDATORS[endpoint].iter_errors(normalized), None) is not None:
        raise ResearchError(
            "invalid_provider_request", "GTEx acquisition parameters violate the provider contract."
        )


def scientific_values(value, *, expression_data=False):
    if isinstance(value, dict):
        for key, item in value.items():
            if item is not None and isinstance(item, (int, float)) and not isinstance(item, bool):
                if key in PROBABILITIES and not 0 <= item <= 1:
                    invalid()
                if (key in NONNEGATIVE or key.endswith("Count")) and item < 0:
                    invalid()
            if key in {"gencodeId", "geneSymbol", "variantId", "sampleId", "phenotypeId"}:
                if not isinstance(item, str) or not item.strip():
                    invalid()
                if key == "gencodeId" and not re.fullmatch(r"ENSG[0-9]{11}\.[0-9]+(?:_PAR_Y)?", item):
                    invalid()
            if (
                key == "data"
                and expression_data
                and (
                    not isinstance(item, list)
                    or not item
                    or any(type(x) not in (int, float) or x < 0 for x in item)
                )
            ):
                invalid()
            scientific_values(item, expression_data=expression_data)
        if "start" in value and "end" in value and value["start"] > value["end"]:
            invalid()
    elif isinstance(value, list):
        for item in value:
            scientific_values(item, expression_data=expression_data)
    elif isinstance(value, float) and not math.isfinite(value):
        invalid()


def validate_response(endpoint, payload, params=None):
    validator = VALIDATORS.get(endpoint)
    if validator is None or next(validator.iter_errors(payload), None) is not None:
        invalid()
    params = params or {}
    if endpoint == "/reference/exon" and "datasetId" in params:
        params = {**params, **release_parameters(params["datasetId"])}
    if isinstance(payload, dict) and (
        any(key in payload for key in ("detail", "errors"))
        or ("error" in payload and endpoint not in {"/association/dyneqtl", "/association/dynsqtl"})
    ):
        invalid()
    scientific_values(payload)
    if endpoint in {"/expression/geneExpression", "/association/dyneqtl"}:
        rows = payload["data"] if endpoint.startswith("/expression/") else [payload]
        for row in rows:
            scientific_values(row, expression_data=True)
    if isinstance(payload, dict) and "paging_info" in payload:
        paging = payload["paging_info"]
        size, total, index, pages = (
            paging[key] for key in ("maxItemsPerPage", "totalNumberOfItems", "page", "numberOfPages")
        )
        if size < 1 or len(payload["data"]) > size or index * size + len(payload["data"]) > total:
            invalid()
        if (total and (not pages or index >= pages)) or (not total and (pages or index)):
            invalid()
        if "page" in params and index != params["page"]:
            invalid()
        if "itemsPerPage" in params and size > params["itemsPerPage"]:
            invalid()
        rows = payload["data"]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = [payload]
    for row in rows:
        if "variantId" in row:
            match = VARIANT_ID.fullmatch(row["variantId"])
            if (
                not match
                or ("pos" in row and row["pos"] != int(match[2]))
                or ("chromosome" in row and row["chromosome"] != match[1])
            ):
                invalid()
        if endpoint in {"/reference/transcript", "/reference/exon"}:
            feature = "exon" if endpoint.endswith("exon") else "transcript"
            if row["featureType"] != feature or row["start"] < 1:
                invalid()
            if not re.fullmatch(r"ENST[0-9]{11}\.[0-9]+(?:_PAR_Y)?", row["transcriptId"]):
                invalid()
            if feature == "exon" and (
                not re.fullmatch(r"ENSE[0-9]{11}(?:\.[0-9]+)?", row["exonId"])
                or not row["exonNumber"].isdecimal()
                or int(row["exonNumber"]) < 1
            ):
                invalid()
        if endpoint == "/dataset/variant":
            match = VARIANT_ID.fullmatch(row["variantId"])
            if (
                not match
                or (match[1], int(match[2]), match[3], match[4])
                != (row["chromosome"], row["pos"], row["ref"], row["alt"])
                or row["ref"] == row["alt"]
            ):
                invalid()
            # Some cohort variants have no dbSNP mapping. Preserve that absence;
            # it cannot be used to qualify an rsID request.
            if row["snpId"] and not SNP_ID.fullmatch(row["snpId"]):
                invalid()
            if row["snpIdUpper"] != row["snpId"].upper():
                invalid()
        for field in (
            "datasetId",
            "gencodeId",
            "tissueSiteDetailId",
            "variantId",
            "sampleId",
            "phenotypeId",
            "gencodeVersion",
            "genomeBuild",
            "snpId",
        ):
            expected = params.get(field)
            if expected is not None and field in row and row[field] != expected:
                invalid()
        # Dynamic QTL data are paired donor measurements, not a record collection.
        if endpoint in {"/association/dyneqtl", "/association/dynsqtl"}:
            genotypes = row["genotypes"]
            if (
                len(row["data"]) != len(genotypes)
                or not genotypes
                or any(x not in (0, 1, 2) for x in genotypes)
            ):
                invalid()
            if any(
                row[field] != genotypes.count(genotype)
                for field, genotype in (("homoRefCount", 0), ("hetCount", 1), ("homoAltCount", 2))
            ):
                invalid()
    return payload
