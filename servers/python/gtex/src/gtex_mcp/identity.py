"""Supported release and GTEx variant namespaces for safe scientific joins."""

import re

from biomedmcp.errors import ResearchError

from .config import DATASET_GENCODE_VERSION

GENOME_BUILD = "GRCh38/hg38"
VARIANT_ID = re.compile(r"(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M))_([1-9][0-9]*)_([^_\s]+)_([^_\s]+)_b38")
SNP_ID = re.compile(r"rs[1-9][0-9]*")


def release_parameters(dataset_id):
    if dataset_id not in {"gtex_v8", "gtex_v10"}:
        raise ResearchError("unsupported_release", "Supported GTEx releases are gtex_v8 and gtex_v10.")
    return {"gencodeVersion": DATASET_GENCODE_VERSION[dataset_id], "genomeBuild": GENOME_BUILD}


def variant_selector(identifier):
    if isinstance(identifier, str) and SNP_ID.fullmatch(identifier):
        return {"snpId": identifier}
    if isinstance(identifier, str) and (match := VARIANT_ID.fullmatch(identifier)) and match[3] != match[4]:
        return {"variantId": identifier}
    raise ResearchError(
        "invalid_variant_identity", "Use an rsID or an explicit GRCh38 GTEx variant ID ending in _b38."
    )
