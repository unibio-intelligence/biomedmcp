"""CC0 bibliographic discovery; source-qualified identities, never S2 equivalence."""

import re

from ..errors import ResearchError
from ..pagination import numeric_total, page_payload
from ..scientific_records import literature_record, source_count
from .http import segment
from .shapes import collection, invalid_shape

BASE = "https://api.openalex.org"
WORK_FIELDS = (
    "id,ids,doi,title,publication_date,authorships,cited_by_count,is_retracted,open_access,related_works"
)
AUTHOR_FIELDS = "id,display_name,orcid,works_count,cited_by_count"


def identity(value, kind):
    if not isinstance(value, str):
        invalid_shape()
    value = value.removeprefix("openalex:").removeprefix("https://openalex.org/")
    if not re.fullmatch(kind + r"[1-9]\d{0,19}", value):
        raise ResearchError("invalid_identifier", "Use a source-qualified OpenAlex " + kind + " identifier.")
    return value


def author(row):
    if not isinstance(row, dict):
        invalid_shape()
    oid = identity(row.get("id"), "A")
    name = row.get("display_name")
    if not isinstance(name, str) or not name.strip():
        invalid_shape()
    orcid = row.get("orcid")
    if orcid is not None and (
        not isinstance(orcid, str)
        or not re.fullmatch(r"https://orcid.org/\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid)
    ):
        invalid_shape()
    return {
        "id": "openalex:" + oid,
        "name": name,
        "orcid": orcid,
        "works_count": source_count(row.get("works_count")),
        "citation_count": source_count(row.get("cited_by_count")),
        "source": "openalex",
        "url": "https://openalex.org/" + oid,
        "identity_warning": "OpenAlex author disambiguation may merge or split people; verify ORCID and works.",
    }


def work(row):
    if not isinstance(row, dict) or not isinstance(row.get("ids", {}), dict):
        invalid_shape()
    oid = identity(row.get("id"), "W")
    ids = row.get("ids", {})
    out = {
        "openalex_id": "openalex:" + oid,
        "title": row.get("title"),
        "date": row.get("publication_date"),
        "url": "https://openalex.org/" + oid,
        "sources": ["openalex"],
        "citation_count": source_count(row.get("cited_by_count")),
        "is_retracted": row.get("is_retracted"),
    }
    for field, pattern in [
        ("pmid", r"https?://(?:pubmed\.ncbi\.nlm\.nih\.gov/|(?:www\.)?ncbi\.nlm\.nih\.gov/pubmed/)(\d+)/?"),
        (
            "pmcid",
            r"https?://(?:pmc\.ncbi\.nlm\.nih\.gov/articles/|(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/)(PMC\d+)/?",
        ),
        ("doi", r"https://doi.org/(10\.\d{4,9}/\S+)"),
    ]:
        value = ids.get(field) or (row.get("doi") if field == "doi" else None)
        if value is not None:
            match = re.fullmatch(pattern, value, re.IGNORECASE) if isinstance(value, str) else None
            if not match:
                invalid_shape()
            out[field] = (
                match[1].lower() if field == "doi" else match[1].upper() if field == "pmcid" else match[1]
            )
    authorships = row.get("authorships", [])
    if not isinstance(authorships, list) or any(
        not isinstance(a, dict) or not isinstance(a.get("author"), dict) for a in authorships
    ):
        invalid_shape()
    out["authors"] = [a["author"].get("display_name") for a in authorships]
    oa = row.get("open_access")
    if oa is not None and not isinstance(oa, dict):
        invalid_shape()
    out["is_open_access"] = oa.get("is_oa") if oa else None
    return literature_record(out, "openalex", provider_identity=oid)


def listing(response, limit, offset, normalize):
    if not isinstance(response, dict) or not isinstance(response.get("meta"), dict):
        invalid_shape()
    total = numeric_total(response["meta"].get("count"))
    rows = response.get("results")
    if (
        total is None
        or not isinstance(rows, list)
        or len(rows) > limit
        or len(rows) > total
        or (offset < total and not rows)
    ):
        invalid_shape()
    records = [normalize(row) for row in rows]
    keys = [r.get("id") or r.get("openalex_id") for r in records]
    if len(set(keys)) != len(keys):
        invalid_shape()
    return page_payload(
        records,
        raw_count=len(rows),
        total=total,
        exhausted=offset + len(rows) >= total,
        next_offset=None if offset + len(rows) >= total else offset + len(rows),
        exhaustion_basis="total",
    )


class OpenAlex:
    def __init__(self, http):
        self.http = http

    async def search_authors(self, query, limit, offset):
        # The service's cursor preserves the original page size.
        if offset % limit:
            raise ResearchError("invalid_cursor", "OpenAlex page alignment changed; restart the search.")
        value = await self.http.get(
            BASE + "/authors",
            params={"search": query, "per_page": limit, "page": offset // limit + 1, "select": AUTHOR_FIELDS},
        )
        return listing(value, limit, offset, author)

    async def get_author(self, value):
        oid = identity(value, "A")
        row = await self.http.get(BASE + "/authors/" + oid, params={"select": AUTHOR_FIELDS})
        out = author(row)
        if out["id"] != "openalex:" + oid:
            raise ResearchError("identity_mismatch", "OpenAlex returned another author identity.")
        return out

    async def author_works(self, value, limit):
        oid = identity(value, "A")
        value = await self.http.get(
            BASE + "/works",
            params={"filter": "authorships.author.id:" + oid, "per_page": limit, "select": WORK_FIELDS},
        )
        # Verify the requested author is actually present in every returned row.
        if isinstance(value, dict) and isinstance(value.get("results"), list):
            for row in value["results"]:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("authorships"), list)
                    or not any(
                        isinstance(a, dict)
                        and isinstance(a.get("author"), dict)
                        and a["author"].get("id") == "https://openalex.org/" + oid
                        for a in row["authorships"]
                    )
                ):
                    invalid_shape()
        out = listing(value, limit, 0, work)
        out.pop("_provider_page")
        out["coverage"] = {
            "source_total": value["meta"]["count"],
            "returned": len(out["records"]),
            "exhaustive": False,
            "scope": "First bounded OpenAlex author-work window",
        }
        return out

    async def recommendations(self, value, limit):
        from .literature import EPMC, article_id

        bridge = None
        if value.startswith(("openalex:", "https://openalex.org/")) or re.fullmatch(r"W\d+", value):
            path = identity(value, "W")
            kind, expected = "openalex", path
        else:
            kind, expected = article_id(value)
            if kind == "paper_id":
                raise ResearchError(
                    "unsupported_identifier",
                    "Use PMID, PMCID, DOI or openalex:W… for open related-work discovery.",
                )
            if kind == "pmcid":
                response = await self.http.get(
                    EPMC + "/search",
                    params={
                        "query": f"PMCID:{expected}",
                        "format": "json",
                        "resultType": "lite",
                        "pageSize": 2,
                    },
                )
                rows = collection(response, ("resultList", "result"))
                if len(rows) != 1 or rows[0].get("pmcid") != expected:
                    raise ResearchError(
                        "unresolved_identity", "PMCID has no single exact Europe PMC identity."
                    )
                item = rows[0]
                bridge = {"source": "europepmc", "pmcid": expected}
                if item.get("doi"):
                    kind, expected = article_id(item["doi"])
                    if kind != "doi":
                        invalid_shape()
                elif (
                    item.get("source") == "MED"
                    and isinstance(item.get("id"), str)
                    and item["id"].isascii()
                    and item["id"].isdigit()
                ):
                    kind, expected = "pmid", item["id"]
                else:
                    raise ResearchError(
                        "unresolved_identity", "PMCID has no qualified DOI or PMID bridge to OpenAlex."
                    )
                bridge[kind] = expected
            path = "https://doi.org/" + expected if kind == "doi" else "pmid:" + expected
        row = await self.http.get(BASE + "/works/" + segment(path), params={"select": WORK_FIELDS})
        seed = work(row)
        if (
            kind == "openalex"
            and seed["openalex_id"] != "openalex:" + expected
            or kind != "openalex"
            and seed.get(kind) != expected
        ):
            raise ResearchError(
                "identity_mismatch", "OpenAlex did not confirm the requested article identity."
            )
        related = row.get("related_works")
        if not isinstance(related, list) or len(related) > 1000:
            invalid_shape()
        ids = [identity(v, "W") for v in related]
        if len(set(ids)) != len(ids) or identity(row["id"], "W") in ids:
            invalid_shape()
        selected = ids[:limit]
        records = []
        unresolved = []
        if selected:
            response = await self.http.get(
                BASE + "/works",
                params={
                    "filter": "openalex:" + "|".join(selected),
                    "per_page": len(selected),
                    "select": WORK_FIELDS,
                },
            )
            out = listing(response, len(selected), 0, work)
            mapped = {r["openalex_id"].removeprefix("openalex:"): r for r in out["records"]}
            if not set(mapped) <= set(selected):
                invalid_shape()
            records = [mapped[v] for v in selected if v in mapped]
            unresolved = ["openalex:" + v for v in selected if v not in mapped]
        return {
            "relation": "recommendations",
            "method": "OpenAlex related_works (shared topics)",
            "seed_identity": seed["identities"],
            **({"identity_bridge": bridge} if bridge else {}),
            "records": records,
            "unresolved_related_work_ids": unresolved,
            "section_outcomes": {"related_metadata": "partial"} if unresolved else {},
            "coverage": {
                "source_total": len(ids),
                "returned": len(records),
                "more_available": len(ids) > limit,
                "requested_window": len(selected),
                "unresolved": len(unresolved),
                "exhaustive": False,
                "scope": "Provider related-work suggestions",
            },
            "interpretation": "Discovery suggestions, not scientific agreement or validated relevance. Unresolved related IDs may be removed or merged; missing metadata is not evidence of absence.",
        }
