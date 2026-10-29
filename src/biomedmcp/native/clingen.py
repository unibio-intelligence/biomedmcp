"""ClinGen endpoint contracts: identities, assertions and references stay distinct.

Primary contracts: https://erepo.clinicalgenome.org/docs/cg-erepo/
https://ldh.clinicalgenome.org/ldh/ui/api-docs
https://reg.clinicalgenome.org/docs/cg-car/
"""

import re
from urllib.parse import urlsplit

from ..errors import ResearchError
from .shapes import collection, invalid_shape


def reject_errors(payload):
    if any(key in payload for key in ("error", "errors", "errorType")):
        invalid_shape()


def text(value, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        invalid_shape()
    return value


def reference(value, hosts):
    value = text(value, 2000)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        invalid_shape()
    if (
        parsed.scheme not in {"https", "http"}
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or port not in {None, 80, 443}
    ):
        invalid_shape()
    return parsed


def source_envelope(payload, expected):
    if (
        not isinstance(payload, dict)
        or any(key in payload for key in ("error", "errors", "errorType"))
        or not isinstance(payload.get("metadata"), dict)
        or not isinstance(payload.get("status"), dict)
        or type(payload["status"].get("code")) is not int
    ):
        invalid_shape()
    status = payload["status"]
    text(status.get("name"))
    code = status["code"]
    if not 100 <= code <= 599:
        invalid_shape()
    if code != 200:
        raise ResearchError(
            "upstream_error",
            "ClinGen reported an unsuccessful source status; absence cannot be inferred.",
            retryable=code == 429 or code >= 500,
        )
    if status["name"] != "OK":
        invalid_shape()
    if not isinstance(payload.get("data"), expected):
        invalid_shape()
    return payload["data"]


def gene_candidates(payload, identity):
    rows = collection(payload, ())
    for row in rows:
        reject_errors(row)
        text(row.get("label"))
        if (
            "error" in row
            or not isinstance(row.get("hgnc"), str)
            or not re.fullmatch(r"HGNC:[1-9]\d*", row["hgnc"])
        ):
            invalid_shape()
    matches = [row for row in rows if row["hgnc"] == identity["hgnc_id"]]
    return {
        "record_type": "clingen_gene_identity_candidates",
        "records": matches,
        "qualified_identity": identity,
        "warnings": [
            (
                "ClinGen autocomplete matches establish indexed gene identity, not gene-disease validity assertions. "
                "An empty match does not establish biological absence."
            ),
            "Provider labels and aliases are retained; matching uses the qualified HGNC identifier.",
        ],
    }


def normalization(payload, hgvs):
    if not isinstance(payload, dict):
        invalid_shape()
    reject_errors(payload)
    parsed = reference(payload.get("@id"), {"reg.genome.network", "reg.clinicalgenome.org"})
    matched = re.fullmatch(r"/allele/((CA|PA)\d+)", parsed.path)
    if not matched or parsed.query or parsed.fragment:
        invalid_shape()
    identifier, prefix = matched.groups()
    if prefix != ("PA" if ":p." in hgvs else "CA"):
        invalid_shape()
    kind = "nucleotide" if prefix == "CA" else "amino-acid"
    if payload.get("type") != kind:
        invalid_shape()
    fields = ("genomicAlleles", "transcriptAlleles") if prefix == "CA" else ("aminoAcidAlleles",)
    reported = False
    for field in fields:
        if field not in payload:
            continue
        alleles = collection(payload, (field,))
        reported |= bool(alleles)
        for allele in alleles:
            reject_errors(allele)
            values = collection(allele, ("hgvs",), element=str)
            if not values or any(":" not in text(value, 1000) for value in values):
                invalid_shape()
    if not reported:
        invalid_shape()
    return {
        **payload,
        "record_type": "clingen_allele_normalization",
        "canonical_allele_id": identifier,
        "requested_hgvs": hgvs,
        "warnings": [
            (
                "CA identifiers describe nucleotide alleles; PA identifiers describe amino-acid alleles. "
                "Protein identity does not establish a unique genomic allele."
            ),
            (
                "Representations are reported by the Allele Registry; no independent cross-build conversion "
                "or clinical classification is performed here."
            ),
        ],
    }


def assertions(payload, caid):
    rows = collection({"data": source_envelope(payload, list)}, ("data",))
    for row in rows:
        reject_errors(row)
        if row.get("caId") != caid or "error" in row:
            invalid_shape()
        for field in ("classification", "ep", "uuid", "docVersion"):
            text(row.get(field))
        if "retracted" in row and type(row["retracted"]) is not bool:
            invalid_shape()
    from ..variant_assertion_records import expert_variant_assertion

    normalized = [expert_variant_assertion(row, caid, index) for index, row in enumerate(rows)]
    return {
        "record_type": "clingen_expert_assertions",
        "records": normalized,
        "requested_caid": caid,
        "metadata": payload["metadata"],
        "source_status": payload["status"],
        "coverage": {"provider_page": 1, "requested_page_size": 25, "exhaustive": False},
        "warnings": [
            (
                "Expert-panel assertions and document versions are retained independently, including conflicts "
                "and reported retractions; no new clinical classification is inferred. "
                "An empty repository result does not establish biological absence."
            ),
            "This is the requested first provider page, not an exhaustive inventory of assertions.",
        ],
    }


def specifications(payload, gene):
    rows = collection({"data": source_envelope(payload, list)}, ("data",))
    for row in rows:
        reject_errors(row)
        reference(row.get("@id"), {"cspec.genome.network", "cspec.clinicalgenome.org"})
    return {
        "record_type": "clingen_specification_references",
        "records": rows,
        "requested_gene_symbol": gene,
        "metadata": payload["metadata"],
        "source_status": payload["status"],
        "warnings": [
            (
                "The low-detail CSpec response contains specification references, not extracted criteria "
                "or applied variant classifications. An empty response does not establish biological absence."
            ),
        ],
    }


def linked_data(payload, caid):
    groups = source_envelope(payload, dict)
    records = []
    for group, rows in groups.items():
        text(group)
        for row in collection({"rows": rows}, ("rows",)):
            reject_errors(row)
            text(row.get("entType"))
            identifiers = [row.get(key) for key in ("entId", "ldhId") if key in row]
            if not identifiers:
                invalid_shape()
            for value in identifiers:
                if type(value) is int and value >= 0:
                    continue
                text(value)
            records.append({"link_type": group, "entity": row})
    return {
        "record_type": "clingen_linked_data_references",
        "records": records,
        "requested_caid": caid,
        "metadata": payload["metadata"],
        "source_status": payload["status"],
        "warnings": [
            (
                "Linked-data references retain their entity type and source identifiers. A link does not "
                "establish identity equivalence, clinical classification or a measured frequency. "
                "An empty link collection does not establish biological absence."
            ),
        ],
    }
