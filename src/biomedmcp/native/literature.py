"""Native source-aware literature acquisition, ranking, identity and article reading.

Provider acquisition, ranking and article reading run in Python. Regression
cases use synthetic provider responses.
"""

import math
import os
import re
from collections import Counter

from pydantic import ValidationError

from ..contracts import FulltextWindow
from ..errors import ResearchError, invalid_parameters
from ..evidence import article_identifiers, deduplicate_articles
from ..pagination import numeric_total, page_payload
from ..scientific_records import epmc_flag, literature_record, source_count, source_pmid
from .http import ProviderHTTP, segment
from .shapes import collection, invalid_shape

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PUBTATOR = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
SOURCES = ("pubmed", "europepmc", "pubtator", "litsense2")
FILTERS = {
    "pubmed": {
        "gene",
        "disease",
        "drug",
        "date_from",
        "date_to",
        "author",
        "journal",
        "article_type",
        "sort",
    },
    "europepmc": {
        "gene",
        "disease",
        "drug",
        "date_from",
        "date_to",
        "author",
        "journal",
        "article_type",
        "open_access",
        "no_preprints",
        "sort",
    },
    "pubtator": {"gene", "disease", "drug"},
    "litsense2": {"gene", "disease", "drug"},
}


def terms(query, filters):
    return " ".join(
        [
            query,
            *([filters["gene"]] if filters.get("gene") else []),
            *filters.get("disease", []),
            *filters.get("drug", []),
        ]
    )


def plan_sources(filters):
    selected = filters.get("source") or "all"
    if selected not in {*SOURCES, "all"}:
        raise ResearchError("unsupported_source", "Article source must be all, " + ", ".join(SOURCES))
    active = {
        k
        for k, v in filters.items()
        if v not in (None, [], False) and k not in {"source", "species", "ranking_mode", "include_retracted"}
    }
    if filters.get("sort") == "relevance":
        active.discard("sort")
    candidates = list(SOURCES[:-1]) if selected == "all" else [selected]
    eligible = [
        s
        for s in candidates
        if active <= FILTERS[s]
        and not (filters.get("sort") == "citations" and s == "pubmed")
    ]
    if not eligible:
        raise ResearchError(
            "unsupported_filter",
            "The selected source cannot honor these filters; inspect capabilities(entity='article').",
        )
    if selected != "all" and eligible != candidates:
        raise ResearchError("unsupported_filter", "The selected source cannot honor these filters.")
    if filters.get("ranking_mode") and filters.get("sort") not in (None, "relevance"):
        raise ResearchError("invalid_parameters", "Ranking mode requires sort=relevance.")
    return eligible


def article_id(value):
    value = value.strip().removeprefix("https://doi.org/")
    qualified_pmid = re.fullmatch(r"PMID:([0-9]+)", value, re.IGNORECASE)
    if qualified_pmid:
        return "pmid", qualified_pmid.group(1)
    if value.isdigit():
        return "pmid", value
    if re.fullmatch(r"PMC\d+", value, re.IGNORECASE):
        return "pmcid", value.upper()
    if re.fullmatch(r"10\.\d{4,9}/\S+", value, re.IGNORECASE):
        return "doi", value.lower()
    raise ResearchError("invalid_identifier", "Use a PMID, PMCID or DOI.")


def normalize_epmc(row):
    if (
        not isinstance(row, dict)
        or not isinstance(row.get("id"), str)
        or not row["id"]
        or not isinstance(row.get("source"), str)
    ):
        invalid_shape()
    author_list = row.get("authorList", {})
    if (
        not isinstance(author_list, dict)
        or not isinstance(author_list.get("author", []), list)
        or any(not isinstance(author, dict) for author in author_list.get("author", []))
    ):
        invalid_shape()
    pmid = str(row.get("id", "")) if row.get("source") == "MED" else row.get("pmid")
    return literature_record(
        {
            "pmid": pmid or None,
            "pmcid": row.get("pmcid"),
            "doi": row.get("doi"),
            "title": row.get("title"),
            "abstract": row.get("abstractText"),
            "date": row.get("firstPublicationDate") or row.get("pubYear"),
            "authors": [x.get("fullName") for x in row.get("authorList", {}).get("author", [])]
            or ([row["authorString"]] if row.get("authorString") else []),
            "author_completeness": "complete" if row.get("authorList") else "source_limited",
            "author_records": row.get("authorList", {}).get("author", []),
            "journal": row.get("journalTitle") or row.get("journalInfo", {}).get("journal", {}).get("title"),
            "is_open_access": epmc_flag(row.get("isOpenAccess")),
            "is_retracted": epmc_flag(row.get("isRetracted")),
            "citation_count": source_count(row.get("citedByCount"), decimal_text=True),
            "sources": ["europepmc"],
            "url": f"https://europepmc.org/article/{row.get('source', 'MED')}/{row.get('id', '')}",
        },
        "europepmc",
        provider_identity=f"{row['source']}:{row['id']}",
    )


def rank_articles(rows, query, mode="hybrid", sort="relevance", limit=25, *, retain_overflow=False):
    merged = deduplicate_articles(rows)
    tokens = set(re.findall(r"\w+", query.casefold()))
    for row in merged:
        words = set(
            re.findall(r"\w+", ((row.get("title") or "") + " " + (row.get("abstract") or "")).casefold())
        )
        lexical = len(tokens & words) / max(1, len(tokens))
        provider_score = sum(1 / (60 + rank) for rank in row.get("_provider_ranks", {}).values())
        if not provider_score:
            provider_score = 1 / (60 + row.get("_provider_rank", 1))
        # Reciprocal-rank fusion is explicit; no pretend locally computed embeddings.
        score = (
            lexical
            if mode == "lexical"
            else provider_score
            if mode == "provider"
            else lexical * 0.5 + provider_score * 30
        )
        row["ranking"] = {
            "method": mode,
            "lexical_overlap": lexical,
            "provider_rank_fusion": provider_score,
            "score": score,
        }

    def key(row):
        stable = sorted(article_identifiers(row)) or [row.get("title") or ""]
        if sort == "date":
            return (str(row.get("date") or ""), stable[0])
        if sort == "citations":
            return (int(row.get("citation_count") or 0), stable[0])
        return (row["ranking"]["score"], stable[0])

    merged.sort(key=key, reverse=True)
    if sort != "relevance" or len({r.get("primary_source") for r in merged}) < 3:
        return merged if retain_overflow else merged[:limit]
    counts = Counter()
    cap = max(1, math.ceil(limit * 0.4))
    chosen = []
    remaining = []
    for row in merged:
        source = row.get("primary_source")
        if counts[source] < cap:
            chosen.append(row)
            counts[source] += 1
        else:
            remaining.append(row)
    return chosen + remaining if retain_overflow else (chosen + remaining)[:limit]


class Literature:
    def __init__(self, http=None):
        self.http = http or ProviderHTTP()

    async def eutils(self, operation, params, xml=False):
        params = {**params, "tool": "biomedmcp"}
        if os.getenv("NCBI_API_KEY"):
            params["api_key"] = os.environ["NCBI_API_KEY"]
        return await (self.http.xml if xml else self.http.get)(f"{EUTILS}/{operation}.fcgi", params=params)

    async def search_source(
        self, source, query, filters, limit, offset=0, *, continuation=None, include_page=False
    ):
        if source not in SOURCES:
            raise ResearchError("unsupported_source", "Choose an available literature source.")
        def output(rows, **metadata):
            return page_payload(rows, **metadata) if include_page else rows

        text = terms(query, filters)
        if source == "pubmed":
            clauses = [f"({text})"]
            for field, tag in [("author", "Author"), ("journal", "Journal")]:
                clauses += [f'"{v.replace(chr(34), "")}"[{tag}]' for v in filters.get(field, [])]
            if filters.get("article_type"):
                clauses.append(f'"{filters["article_type"]}"[Publication Type]')
            params = {
                "db": "pubmed",
                "term": " AND ".join(clauses),
                "retmode": "json",
                "retmax": limit,
                "retstart": offset,
                "sort": "pub date" if filters.get("sort") == "date" else "relevance",
            }
            if filters.get("date_from") or filters.get("date_to"):
                params.update(
                    datetype="pdat",
                    mindate=filters.get("date_from") or "1800",
                    maxdate=filters.get("date_to") or "3000",
                )
            value = await self.eutils("esearch", params)
            ids = collection(value, ("esearchresult", "idlist"), element=str)
            total = numeric_total(value["esearchresult"].get("count"))
            exhausted = offset + len(ids) >= total if total is not None else len(ids) < limit
            if not ids:
                return output(
                    [],
                    raw_count=0,
                    total=total,
                    exhausted=True,
                    exhaustion_basis="total" if total is not None else "short_window",
                )
            root = await self.eutils(
                "efetch", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}, xml=True
            )
            return output(
                self.parse_pubmed(root),
                raw_count=len(ids),
                total=total,
                exhausted=exhausted,
                next_offset=None if exhausted else offset + len(ids),
                exhaustion_basis="total" if total is not None else "short_window",
            )
        if source == "europepmc":
            clauses = [f"({text})"]
            for field, tag in [("author", "AUTH_FULL"), ("journal", "JOURNAL")]:
                clauses += [f'{tag}:"{v.replace(chr(34), "")}"' for v in filters.get(field, [])]
            if filters.get("article_type"):
                clauses.append(f'PUB_TYPE:"{filters["article_type"]}"')
            if filters.get("open_access"):
                clauses.append("OPEN_ACCESS:Y")
            if filters.get("no_preprints"):
                clauses.append("NOT SRC:PPR")
            if filters.get("date_from") or filters.get("date_to"):
                clauses.append(
                    f"FIRST_PDATE:[{filters.get('date_from') or '1800-01-01'} TO {filters.get('date_to') or '3000-01-01'}]"
                )
            if filters.get("sort") == "date":
                clauses.append("sort_date:y")
            if filters.get("sort") == "citations":
                clauses.append("sort_cited:y")
            if offset and not continuation:
                raise ResearchError("unsupported_cursor", "Europe PMC requires its returned cursor mark.")
            value = await self.http.get(
                f"{EPMC}/search",
                params={
                    "query": " AND ".join(clauses),
                    "format": "json",
                    "resultType": "core",
                    "pageSize": limit,
                    "cursorMark": continuation or "*",
                },
            )
            rows = [normalize_epmc(r) for r in collection(value, ("resultList", "result"))]
            token = value.get("nextCursorMark")
            total = numeric_total(value.get("hitCount"))
            exhausted = not token or token == (continuation or "*") or not rows
            if total is not None and offset + len(rows) >= total:
                exhausted = True
            return output(
                rows,
                raw_count=len(rows),
                total=total,
                exhausted=exhausted,
                continuation=None if exhausted else token,
            )
        if source == "pubtator":
            rows = []
            first = offset // 10 + 1
            last = (offset + limit - 1) // 10 + 1
            for page in range(first, last + 1):
                params = {"text": text, "page": page}
                if filters.get("date_from"):
                    params["start_date"] = filters["date_from"]
                if filters.get("date_to"):
                    params["end_date"] = filters["date_to"]
                value = await self.http.get(f"{PUBTATOR}/search/", params=params)
                rows.extend(collection(value, ("results",)))
            normalized = [
                literature_record(
                    {
                        "pmid": source_pmid(r.get("pmid")),
                        "title": r.get("title"),
                        "abstract": r.get("abstract"),
                        "date": r.get("date"),
                        "sources": [source],
                        "is_retracted": None,
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{r.get('pmid')}/",
                    },
                    source,
                )
                for r in rows
            ][offset % 10 : offset % 10 + limit]
            exhausted = len(normalized) < limit
            return output(
                normalized,
                raw_count=len(normalized),
                exhausted=exhausted,
                next_offset=None if exhausted else offset + len(normalized),
                exhaustion_basis="short_window",
            )
        value = await self.http.get(
            "https://www.ncbi.nlm.nih.gov/research/litsense2-api/api/sentences/",
            params={"query": text, "rerank": "true"},
        )
        rows = collection(value, ()) if isinstance(value, list) else collection(value, ("results",))
        normalized = [
            literature_record(
                {
                    "pmid": source_pmid(r.get("pmid")),
                    "title": r.get("title"),
                    "abstract": r.get("text") or r.get("sentence"),
                    "sources": [source],
                    "is_retracted": None,
                },
                source,
            )
            for r in rows
        ][offset : offset + limit]
        exhausted = offset + len(normalized) >= len(rows)
        return output(
            normalized,
            raw_count=len(normalized),
            total=len(rows),
            exhausted=exhausted,
            next_offset=None if exhausted else offset + len(normalized),
            exhaustion_basis="bounded_snapshot",
            sort_scope="bounded_snapshot",
        )

    @staticmethod
    def parse_pubmed(root):
        if root.tag != "PubmedArticleSet" or any(
            child.tag not in {"PubmedArticle", "PubmedBookArticle"} for child in root
        ):
            invalid_shape()
        rows = []
        for entry in root:
            book = entry.tag == "PubmedBookArticle"
            citation = entry.find("BookDocument" if book else "MedlineCitation")
            article = citation if book else citation.find("Article") if citation is not None else None
            if article is None:
                invalid_shape()
            flatten = lambda node: "".join(node.itertext()).strip() if node is not None else None
            # ReferenceList also contains ArticleId nodes; never use cited identities.
            id_nodes = (
                entry.findall("./PubmedData/ArticleIdList/ArticleId")
                if not book
                else (
                    article.findall("./ArticleIdList/ArticleId")
                    + entry.findall("./PubmedBookData/ArticleIdList/ArticleId")
                )
            )
            ids = {node.attrib.get("IdType"): node.text for node in id_nodes}
            authors = []
            author_records = []
            for author in article.findall("./AuthorList/Author"):
                name = author.findtext("CollectiveName") or " ".join(
                    filter(None, [author.findtext("ForeName"), author.findtext("LastName")])
                )
                authors.append(name)
                author_records.append(
                    {
                        "name": name,
                        "affiliations": [flatten(n) for n in author.findall("./AffiliationInfo/Affiliation")],
                        "identifiers": [{**n.attrib, "value": n.text} for n in author.findall("Identifier")],
                    }
                )
            types = [
                n.text
                for n in article.findall(
                    "./PublicationType" if book else "./PublicationTypeList/PublicationType"
                )
            ]
            pmid = citation.findtext("PMID")
            if not pmid or not re.fullmatch(r"[1-9][0-9]*", pmid):
                invalid_shape()
            retracted = (
                True
                if "Retracted Publication" in types
                or any(
                    n.attrib.get("RefType") == "RetractionIn"
                    for n in citation.findall("./CommentsCorrectionsList/CommentsCorrections")
                )
                else False
                if not book and article.find("./PublicationTypeList") is not None
                else None
            )
            rows.append(
                literature_record(
                    {
                        "pmid": pmid,
                        "pmcid": ids.get("pmc"),
                        "doi": ids.get("doi"),
                        "title": flatten(article.find("ArticleTitle")),
                        "abstract": "\n".join(
                            filter(None, [flatten(n) for n in article.findall("./Abstract/AbstractText")])
                        )
                        or None,
                        "date": article.findtext("./Book/PubDate/Year")
                        if book
                        else (
                            article.findtext("./Journal/JournalIssue/PubDate/Year")
                            or article.findtext("./Journal/JournalIssue/PubDate/MedlineDate")
                        ),
                        "journal": article.findtext("./Journal/Title"),
                        **(
                            {
                                "publication_form": "book_chapter",
                                "book_title": flatten(article.find("./Book/BookTitle")),
                            }
                            if book
                            else {}
                        ),
                        "authors": authors,
                        "author_records": author_records,
                        "author_completeness": "complete"
                        if article.find("./AuthorList") is not None
                        and article.find("./AuthorList").get("CompleteYN") != "N"
                        else "source_limited",
                        "publication_types": types,
                        "is_retracted": retracted,
                        "mesh": [flatten(n) for n in citation.findall("./MeshHeadingList/MeshHeading")],
                        "sources": ["pubmed"],
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    },
                    "pubmed",
                )
            )
        return rows

    async def get(self, identifier, source=None):
        kind, value = article_id(identifier)
        source = source or (
            "pubmed" if kind == "pmid" else "europepmc"
        )
        if source == "pubmed":
            if kind != "pmid":
                result = await self.eutils(
                    "esearch",
                    {
                        "db": "pubmed",
                        "term": f'"{value}"[Article Identifier]',
                        "retmode": "json",
                        "retmax": 2,
                    },
                )
                ids = collection(result, ("esearchresult", "idlist"), element=str)
                if len(ids) != 1:
                    raise ResearchError(
                        "ambiguous_identifier", "Identifier did not resolve to one PubMed record."
                    )
                value = ids[0]
            rows = self.parse_pubmed(
                await self.eutils("efetch", {"db": "pubmed", "id": value, "retmode": "xml"}, xml=True)
            )
            return rows[0] if rows else {}
        if source != "europepmc":
            raise ResearchError("unsupported_source", "Article records support pubmed or europepmc.")
        tag = {"pmid": "EXT_ID", "pmcid": "PMCID", "doi": "DOI"}[kind]
        data = await self.http.get(
            f"{EPMC}/search",
            params={"query": f"{tag}:{value}" if kind == "pmcid" else f'{tag}:"{value}"', "format": "json", "resultType": "core", "pageSize": 2},
        )
        rows = collection(data, ("resultList", "result"))
        if len(rows) > 1:
            raise ResearchError("ambiguous_identifier", "Identifier resolved to multiple article records.")
        return normalize_epmc(rows[0]) if rows else {}

    async def fulltext(self, identifier, view="text", start=1, end=100, limit=25, offset=0, *, source="europepmc"):
        if source not in {"europepmc", "pmc"}:
            raise ResearchError("unsupported_source", "Full text supports europepmc or pmc.")
        try:
            window = FulltextWindow(view="lines" if view == "text" else view, start=start, end=end)
        except ValidationError:
            raise invalid_parameters() from None
        start, end = window.start, window.end
        kind, value = article_id(identifier)
        if kind != "pmcid":
            article = await self.get(identifier, source="pubmed" if source == "pmc" else "europepmc")
            value = article.get("pmcid")
        if not value:
            raise ResearchError(
                "source_unavailable", "No PMC full-text accession is available for this article."
            )
        if not re.fullmatch(r"PMC[0-9]+", value):
            raise ResearchError("invalid_source_response", "Article metadata returned an invalid PMC accession.")
        if source == "pmc":
            root = await self.eutils("efetch", {"db": "pmc", "id": value[3:], "retmode": "xml"}, xml=True)
            articles = [root] if root.tag == "article" else root.findall("./article") if root.tag == "pmc-articleset" else []
            if len(articles) != 1:
                raise ResearchError("invalid_source_response", "PMC did not return exactly one article.")
            root = articles[0]
            accessions = {
                (node.text or "").strip().removeprefix("PMC")
                for node in root.findall("./front/article-meta/article-id")
                if node.get("pub-id-type") in {"pmc", "pmcid"}
            }
            if accessions != {value[3:]}:
                raise ResearchError("identity_mismatch", "PMC full text does not prove the requested accession.")
        else:
            root = await self.http.xml(f"{EPMC}/{segment(value)}/fullTextXML")
        if root.find("body") is None:
            raise ResearchError(
                "source_unavailable", "The retrieved record does not include article body text."
            )
        if view == "assets":
            assets = []
            for node in root.findall(".//supplementary-material"):
                for link in [node, *node.findall(".//media"), *node.findall(".//ext-link")]:
                    href = link.attrib.get("{http://www.w3.org/1999/xlink}href")
                    if href:
                        assets.append(
                            {
                                "id": node.attrib.get("id"),
                                "label": " ".join(node.itertext()).strip()[:300],
                                "href": href,
                                "retrieval": "metadata_only",
                                "source": source,
                                "pmcid": value,
                            }
                        )
            return {
                "pmcid": value,
                "assets": assets[offset : offset + limit],
                "total": len(assets),
                "rights": "Article-specific license and access conditions apply.",
            }
        lines = []
        outline = []

        def text_of(node):
            return " ".join(" ".join(node.itertext()).split())

        def append(text, *, heading=False):
            if text:
                if heading:
                    outline.append({"line": len(lines) + 1, "title": text})
                lines.append(text)

        def table(node):
            # JATS permits tables in a floats-group outside body. Preserve row
            # boundaries and spanning headers so subgroup columns stay distinct.
            label = node.find("label")
            caption = node.find("caption")
            append(" ".join(text_of(n) for n in (label, caption) if n is not None), heading=True)
            rows = node.findall(".//tr")
            for row in rows:
                cells = []
                for cell in row:
                    if cell.tag not in {"th", "td"}:
                        continue
                    spans = [f"{key}={cell.get(key)}" for key in ("rowspan", "colspan")
                             if cell.get(key) not in (None, "1")]
                    cells.append(text_of(cell) + (" [" + ", ".join(spans) + "]" if spans else ""))
                if cells:
                    append(" | ".join(cells))
            for foot in node.findall("table-wrap-foot"):
                append(text_of(foot))
            if not rows:
                append("Table body is not supplied as text in this XML.")

        def body(node):
            if node.tag == "table-wrap":
                table(node)
            elif node.tag in {"title", "p"}:
                append(text_of(node), heading=node.tag == "title")
            else:
                for child in node:
                    body(child)

        body(root.find("body"))
        for floating in root.findall("floats-group"):
            for node in floating.findall(".//table-wrap"):
                table(node)
        if view == "outline":
            return {"pmcid": value, "outline": outline, "line_count": len(lines)}
        return {
            "pmcid": value,
            "start": start,
            "end": min(end, len(lines)),
            "line_count": len(lines),
            "lines": [{"number": i + 1, "text": lines[i]} for i in range(start - 1, min(end, len(lines)))],
            "truncated": len(lines) > end,
            "license": (root.findtext(".//license-p") or "").strip(),
        }

    async def open_graph(self, identifier, relation, limit=10):
        from .open_citations import graph

        return await graph(self, identifier, relation, limit)



def focus_matches(row, focus):
    """Filter broad discovery suggestions without claiming biological causality."""
    phrase = r"\b" + r"\s+".join(re.escape(t) for t in focus.casefold().split()) + r"\b"
    title, abstract = str(row.get("title") or "").casefold(), str(row.get("abstract") or "").casefold()
    if re.search(phrase, title):
        return True
    mechanisms = r"\b(?:pathway|signaling|signalling|mechanism|caspase|regulat\w*|activat\w*|inhibit\w*)\b"
    return bool(re.search(phrase, abstract) and re.search(mechanisms, abstract))
