"""Bounded Europe PMC bibliographic edges; no S2 material or publisher excerpts."""

import re

from ..errors import ResearchError
from ..pagination import numeric_total
from .http import segment
from .shapes import collection, invalid_shape


async def graph(literature, identifier, relation, limit):
    from .literature import EPMC, article_id, normalize_epmc

    if relation not in {"citations", "references"} or type(limit) is not int or not 1 <= limit <= 25:
        raise ResearchError("invalid_parameters", "Select citations or references with a limit of 1–25.")
    kind, value = article_id(identifier)
    if kind == "paper_id":
        raise ResearchError("unsupported_identifier", "Use a PMID, PMCID or DOI for Europe PMC relations.")
    source = "MED" if kind == "pmid" else "PMC"
    if kind == "doi":
        found = await literature.http.get(f"{EPMC}/search", params={
            "query": f'DOI:"{value}"', "format": "json", "resultType": "lite", "pageSize": 2,
        })
        matches = collection(found, ("resultList", "result"))
        if len(matches) != 1 or str(matches[0].get("doi", "")).lower() != value:
            raise ResearchError("unresolved_identity", "DOI has no single exact Europe PMC identity.")
        source, value = matches[0].get("source"), matches[0].get("id")
    if (not isinstance(source, str) or not re.fullmatch(r"[A-Z]{2,8}", source)
            or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value)):
        invalid_shape()
    response = await literature.http.get(f"{EPMC}/{segment(source)}/{segment(value)}/{relation}",
                                         params={"format": "json", "pageSize": limit, "page": 1})
    if not isinstance(response, dict) or "hitCount" not in response:
        invalid_shape()
    total = numeric_total(response["hitCount"])
    if total is None:
        invalid_shape()
    field = "citation" if relation == "citations" else "reference"
    rows = ([] if total == 0 and field + "List" not in response
            else collection(response, (field + "List", field)))
    if len(rows) > limit or len(rows) > total or (total and not rows):
        invalid_shape()
    echo = response.get("request")
    if echo is not None and (not isinstance(echo, dict) or echo.get("id") != value or echo.get("source") != source):
        invalid_shape()
    records = []
    for row in rows:
        # A bibliography can contain an unlinked book or other unmatched item.
        # Keep its factual citation without inventing a get-able article ID.
        if relation == "references" and row.get("match") == "N" and not row.get("id"):
            position = row.get("citedOrder")
            if type(position) is not int or position < 1:
                invalid_shape()
            records.append({"article_identity": "unresolved", "reference_position": position,
                            **{k: row[k] for k in ("title", "authorString", "pubYear", "journalAbbreviation")
                               if k in row}})
            continue
        # Whitelist bibliographic fields; never copy an unexpected abstract,
        # citation context, recommendation score or third-party text projection.
        projected = {k: row[k] for k in ("id", "source", "pmid", "pmcid", "doi", "title", "authorString",
                                        "citedByCount") if k in row}
        if row.get("pubYear") is not None:
            year = row["pubYear"]
            if type(year) not in (str, int) or not re.fullmatch(r"\d{4}", str(year)):
                invalid_shape()
            projected["pubYear"] = str(year)
        projected["journalTitle"] = row.get("journalAbbreviation")
        records.append(normalize_epmc(projected))
    return {
        "relation": relation, "records": records, "api_version": response.get("version"),
        "coverage": {"scope": "Europe PMC indexed citation network", "source_total": total,
                     "returned": len(rows), "more_available": total > len(rows), "exhaustive": False},
        "interpretation": "Bibliographic citation links do not establish support, causality or scientific agreement. "
                          "Missing links are source-scoped, not evidence that no citations exist.",
    }
