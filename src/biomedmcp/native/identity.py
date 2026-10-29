"""Species-qualified gene identity shared across scientific joins."""

import re
from typing import Annotated

from pydantic import Field

from ..contracts import StrictModel
from ..errors import ResearchError

EnsemblGene = Annotated[str, Field(pattern=r"^ENS[A-Z]*G\d+(?:\.\d+)?$")]


class QualifiedGene(StrictModel):
    symbol: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    species: int = Field(gt=0)
    source_record_id: str = Field(pattern=r"^(?:\d+|ENS[A-Z]*G\d+(?:\.\d+)?)$")
    entrez_id: str | None = Field(default=None, pattern=r"^\d+$")
    ensembl_ids: list[EnsemblGene] = Field(default_factory=list, max_length=32)
    hgnc_id: str | None = Field(default=None, pattern=r"^HGNC:\d+$")


def gene_matches(row, value, species):
    """Exact symbol or stable identifier; aliases remain resolution candidates."""
    ensembl = row.get("ensembl") or []
    if isinstance(ensembl, dict):
        ensembl = [ensembl]
    ids = {str(row.get(key, "")).casefold() for key in ("_id", "entrezgene", "symbol")}
    if isinstance(ensembl, list):
        ids.update(str(item.get("gene", "")).casefold() for item in ensembl if isinstance(item, dict))
    return value.casefold() in ids and row.get("taxid") == species


def qualify_gene(row, species):
    ensembl = row.get("ensembl") or []
    if isinstance(ensembl, dict):
        ensembl = [ensembl]
    if not isinstance(ensembl, list) or any(not isinstance(item, dict) for item in ensembl):
        raise ResearchError("invalid_source_response", "Gene identity has invalid Ensembl annotations.")
    entrez = row.get("entrezgene")
    hgnc = row.get("HGNC") or row.get("hgnc")
    try:
        record_id = str(row["_id"])
        if record_id.isdecimal():
            if entrez is not None and str(entrez) != record_id:
                raise ValueError("Contradictory Entrez identity")
            entrez = record_id
        ensembl_ids = {item["gene"] for item in ensembl if item.get("gene")}
        if re.fullmatch(r"ENS[A-Z]*G\d+(?:\.\d+)?", record_id):
            ensembl_ids.add(record_id)
        return QualifiedGene(
            symbol=row.get("symbol"),
            species=row.get("taxid") if row.get("taxid") == species else None,
            source_record_id=record_id,
            entrez_id=str(entrez) if entrez is not None else None,
            ensembl_ids=sorted(ensembl_ids),
            hgnc_id="HGNC:" + str(hgnc).removeprefix("HGNC:") if hgnc else None,
        ).model_dump(mode="json")
    except (ValueError, KeyError, TypeError):
        raise ResearchError(
            "invalid_source_response", "Provider returned an invalid qualified gene identity."
        ) from None
