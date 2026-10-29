"""Reviewed identity/GO fields; UMLS and disease annotations never propagate."""

from ..errors import ResearchError
from .shapes import collection

FIELDS = frozenset({"symbol", "name", "taxid", "entrezgene", "ensembl", "HGNC", "alias", "uniprot", "go"})


def check_fields(value):
    if not isinstance(value, str) or not value or not set(value.split(",")) <= FIELDS:
        raise ResearchError(
            "source_license_unreleased", "Only reviewed gene identity and GO fields are enabled."
        )


def projection(value):
    rows = collection(value, ("hits",))
    return {
        **{key: value[key] for key in ("success", "total", "took") if key in value},
        "hits": [{key: row[key] for key in (*FIELDS, "_id", "_score") if key in row} for row in rows],
    }
