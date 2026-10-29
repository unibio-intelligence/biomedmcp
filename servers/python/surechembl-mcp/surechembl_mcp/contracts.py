"""Current SureChEMBL content-search metadata; underlying patent text is excluded."""

import re
from collections import Counter
from datetime import date as Date

from biomedmcp.errors import ResearchError
from biomedmcp.native.shapes import collection, invalid_shape
from biomedmcp.pagination import page_payload

DOCUMENT_ID = re.compile(r"[A-Z]{2}-[A-Z0-9]+-[A-Z][0-9]?")
MAX_PAGE = 100_000


def preflight(operation, params):
    if operation == "analyze_patent_chemistry":
        requested_document(params.get("patent_number"))
        return
    if operation == "search_similar_structures":
        search_parameters(
            params.get("smiles"),
            params.get("similarity_threshold", 0.85),
            params.get("limit", 50),
            params.get("search_cursor"),
        )
        return
    if operation == "query_patents" and params.get("query_type") == "content":
        raise ResearchError(
            "source_license_unavailable",
            "Underlying patent text is outside the released SureChEMBL data scope.",
        )
    if operation not in {"query_patents", "get_patent_statistics"}:
        return
    page, limit = params.get("page", 1), params.get("limit", 25)
    if type(page) is not int or not 1 <= page <= MAX_PAGE or type(limit) is not int or not 1 <= limit <= 100:
        raise ResearchError(
            "invalid_parameters", "SureChEMBL search requires a bounded page and record limit."
        )


def envelope(value):
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        invalid_shape()
    if value["status"] != "OK":
        raise ResearchError(
            "source_unavailable",
            "SureChEMBL could not complete the request; no absence can be inferred.",
            retryable=True,
        )
    if value.get("error_message") or value.get("errorMessage"):
        invalid_shape()
    if "data" not in value or not isinstance(value["data"], (dict, list)):
        invalid_shape()
    return value["data"]


def document(value):
    identifier = value.get("docId")
    metadata = value.get("metadata")
    if (
        not isinstance(identifier, str)
        or not DOCUMENT_ID.fullmatch(identifier)
        or not isinstance(metadata, dict)
    ):
        invalid_shape()
    if "pn" in metadata and metadata["pn"] != identifier:
        raise ResearchError("identity_mismatch", "SureChEMBL returned inconsistent document identifiers.")
    date = metadata.get("pd")
    if date in (None, "", "null"):
        date = None
    elif not isinstance(date, str) or not re.fullmatch(r"[0-9]{8}", date):
        invalid_shape()
    else:
        try:
            date = Date(int(date[:4]), int(date[4:6]), int(date[6:])).isoformat()
        except ValueError:
            invalid_shape()
    assignee = value.get("pa")
    if assignee in (None, "", "null"):
        assignee = None
    elif not isinstance(assignee, str) or not assignee.strip():
        invalid_shape()
    return {
        "document_id": identifier,
        "publication_date": date,
        "assignee": assignee,
        "url": f"https://www.surechembl.org/patent/{identifier}",
    }


def content_window(value, query, page, limit):
    data = envelope(value)
    if (
        not isinstance(data, dict)
        or data.get("type") != "CONTENT"
        or not isinstance(data.get("results"), dict)
    ):
        invalid_shape()
    source = data["results"]
    if source.get("query") != query:
        raise ResearchError("identity_mismatch", "SureChEMBL returned a different search query.")
    total = source.get("total_hits")
    rows = collection(source, ("documents",))
    if type(total) is not int or total < 0 or len(rows) > limit or len(rows) > total:
        invalid_shape()
    records = [document(row) for row in rows]
    if len({r["document_id"] for r in records}) != len(records):
        invalid_shape()
    offset = (page - 1) * limit
    if total < offset + len(rows) and rows:
        invalid_shape()
    exhausted = page * limit >= total
    result = page_payload(
        records,
        raw_count=len(rows),
        total=total,
        exhausted=exhausted,
        next_offset=None if exhausted else page * limit,
        exhaustion_basis="total",
    )
    result.update(
        query=query,
        page=page,
        limit=limit,
        source_input={
            "endpoint": "/search/content",
            "method": "POST",
            "query": query,
            "page": page,
            "itemsPerPage": limit,
        },
        coverage={
            "population": "SureChEMBL document records matching this source query",
            "unit": "document_records",
            "offset": offset,
            "acquired_count": len(rows),
            "provider_total": total,
            "all_matching_records_acquired": page == 1 and len(rows) == total,
        },
        warnings=[],
    )
    if not exhausted and page == MAX_PAGE:
        result["warnings"].append(
            "Acquired evidence is retained; further provider pages exceed the supported page bound."
        )
        result["section_outcomes"] = {"continuation": {"outcome": "unavailable", "sources": []}}
    return result


def statistics(window, group_by):
    key = {"year": "publication_date", "assignee": "assignee", "class": None}[group_by]
    groups = Counter()
    locators = {}
    missing = 0
    for i, record in enumerate(window["records"]):
        value = record.get(key) if key else None
        if value is None:
            missing += 1
            continue
        value = value[:4] if group_by == "year" else value
        groups[value] += 1
        locators.setdefault(value, []).append(f"/records/{i}/{key}")
    complete = window["coverage"]["all_matching_records_acquired"] and missing == 0
    return {
        **window,
        "group_by": group_by,
        "method": "Count acquired document records by reported publication year or literal assignee; no deduplication into patent families, interpretation of assignee aliases, or extrapolation beyond this window.",
        "groups": [
            {"value": value, "count_within_window": count, "input_locators": locators[value]}
            for value, count in sorted(groups.items())
        ],
        "denominator": {
            "unit": "acquired_document_records",
            "total": len(window["records"]),
            "with_reported_group": len(window["records"]) - missing,
            "missing_group": missing,
            "provider_matching_document_total": window["coverage"]["provider_total"],
        },
        "population_statistics_status": "complete" if complete else "partial",
        "section_outcomes": {
            **window.get("section_outcomes", {}),
            "statistics": {"outcome": "data" if complete else "partial", "sources": ["surechembl"]},
        },
        "warnings": [
            *window["warnings"],
            *(
                []
                if complete
                else [
                    "These counts describe the acquired window. Continue source pagination for all matching records; missing dates/assignees remain unknown. Classification fields are not supplied by this response contract."
                ]
            ),
        ],
    }


def search_parameters(smiles, threshold, limit, cursor=None):
    import math

    if (
        not isinstance(smiles, str)
        or not 1 <= len(smiles) <= 8192
        or any(not 33 <= ord(c) <= 126 for c in smiles)
    ):
        raise ResearchError(
            "invalid_parameters", "Provide bounded SMILES without whitespace/control characters."
        )
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0.5 <= threshold <= 1:
        raise ResearchError(
            "invalid_parameters", "SureChEMBL similarity threshold must be between 0.5 and 1."
        )
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ResearchError(
            "invalid_parameters", "SureChEMBL similarity windows contain at most 100 records."
        )
    if cursor is not None and (not isinstance(cursor, str) or not 1 <= len(cursor) <= 8192):
        raise ResearchError("invalid_parameters", "Use the returned bounded search continuation.")


def job_hash(value):
    import uuid

    if not isinstance(value, str):
        invalid_shape()
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        invalid_shape()
    if str(parsed) != value:
        invalid_shape()
    return value


def job_control(raw):
    import json

    try:
        control = json.loads(raw)
        if not isinstance(control, dict) or set(control) != {"hash", "page"}:
            invalid_shape()
        job_hash(control["hash"])
        if type(control["page"]) is not int or not 1 <= control["page"] <= MAX_PAGE:
            invalid_shape()
        return control
    except (TypeError, ValueError, ResearchError):
        raise ResearchError(
            "invalid_cursor", "Source search continuation is invalid; restart the original request."
        ) from None


def checked_job_query(query, smiles):
    import json

    if isinstance(query, str):
        try:
            query = json.loads(query)
        except ValueError:
            invalid_shape()
    if not isinstance(query, dict):
        invalid_shape()
    if (
        query.get("structure") != smiles
        or query.get("structure_format") != "SMILES"
        or query.get("search_type") != "SIMILARITY"
    ):
        raise ResearchError(
            "identity_mismatch", "SureChEMBL search belongs to a different structure or method."
        )
    if any(k not in query for k in ("dataset", "query", "doc_section_filter", "chem_term_filter")):
        invalid_shape()
    if any(
        query.get(k) not in (None, "") for k in ("dataset", "query", "doc_section_filter", "chem_term_filter")
    ):
        raise ResearchError("identity_mismatch", "SureChEMBL search contains different source filters.")
    return query


def checked_job_metadata(value, smiles):
    data = envelope(value)
    if not isinstance(data, dict) or data.get("type") != "STRUCTURE":
        invalid_shape()
    checked_job_query(data.get("query"), smiles)


def checked_job_status(value):
    if not isinstance(value, dict) or value.get("status") not in {"OK", "QUEUED", "RUNNING", "ERROR"}:
        invalid_shape()
    if value["status"] == "ERROR" or value.get("error_message") or value.get("errorMessage"):
        raise ResearchError(
            "source_unavailable",
            "SureChEMBL source search failed; no absence can be inferred.",
            retryable=True,
        )
    data = value.get("data")
    if not isinstance(data, dict):
        invalid_shape()
    if value["status"] in {"QUEUED", "RUNNING"}:
        return value["status"].lower(), None
    if data.get("message") != "Searching finished.":
        invalid_shape()
    count = data.get("resultCount")
    if type(count) is not int or count < 0:
        invalid_shape()
    return "finished", count


def compound(value, *, require_score=False, threshold=0):
    import math

    if not isinstance(value, dict):
        invalid_shape()
    identifier = value.get("chemical_id")
    if (
        not isinstance(identifier, str)
        or not re.fullmatch(r"[1-9][0-9]{0,15}", identifier)
        or value.get("id") != identifier
    ):
        invalid_shape()
    smiles = value.get("smiles")
    if (
        not isinstance(smiles, str)
        or not 1 <= len(smiles) <= 16384
        or any(not 33 <= ord(c) <= 126 for c in smiles)
    ):
        invalid_shape()
    result = {
        "chemical_id": "SCHEMBL" + identifier,
        "source_numeric_id": identifier,
        "smiles": smiles,
        "url": f"https://www.surechembl.org/chemical/{identifier}",
    }
    for key in ("name", "inchi", "inchi_key", "mol_formula"):
        if key in value:
            if not isinstance(value[key], str) or not value[key].strip():
                invalid_shape()
            result[key] = value[key]
    if "inchi_key" in result and not re.fullmatch(r"[A-Z]{14}-[A-Z]{10}-[A-Z]", result["inchi_key"]):
        invalid_shape()
    if "inchi" in result and not result["inchi"].startswith("InChI="):
        invalid_shape()
    for key in ("mol_weight", "log_p", "psa", "qed_weighted"):
        if key in value:
            number = value[key]
            if (
                type(number) not in (int, float)
                or not math.isfinite(number)
                or key == "mol_weight"
                and number <= 0
                or key == "psa"
                and number < 0
                or key == "qed_weighted"
                and not 0 <= number <= 1
            ):
                invalid_shape()
            result[key] = number
    for key in (
        "global_frequency",
        "hbd",
        "hba",
        "heavy_atoms",
        "aromatic_rings",
        "rtb",
        "num_ro5_violations",
    ):
        if key in value:
            if type(value[key]) is not int or value[key] < 0:
                invalid_shape()
            result[key] = value[key]
    score = value.get("similarity")
    if score in (None, "") and not require_score:
        result["similarity"] = None
    else:
        if (
            type(score) not in (int, float, str)
            or isinstance(score, str)
            and not re.fullmatch(r"(?:0(?:\.[0-9]+)?|1(?:\.0+)?)", score)
        ):
            invalid_shape()
        score = float(score)
        if not math.isfinite(score) or not threshold <= score <= 1:
            invalid_shape()
        result["similarity"] = score
    return result


def structure_window(value, smiles, threshold, limit, control):
    import json

    data = envelope(value)
    if not isinstance(data, dict) or data.get("type") != "STRUCTURE":
        invalid_shape()
    query = checked_job_query(data.get("query"), smiles)
    page = data.get("pagination")
    results = data.get("results")
    if not isinstance(page, dict) or not isinstance(results, dict):
        invalid_shape()
    for key in ("current_page", "max_results", "num_pages", "start_on"):
        if type(page.get(key)) is not int or page[key] < (0 if key == "num_pages" else 1):
            invalid_shape()
    if page["current_page"] != control["page"] or page["max_results"] != limit:
        raise ResearchError("identity_mismatch", "SureChEMBL returned a different source window.")
    total = results.get("total_hits")
    rows = collection(results, ("structures",))
    if type(total) is not int or total < 0 or len(rows) > min(total, limit):
        invalid_shape()
    if page["num_pages"] not in ({0, 1} if total == 0 else {(total + limit - 1) // limit}):
        invalid_shape()
    records = [compound(row, require_score=True, threshold=threshold) for row in rows]
    identifiers = [r["source_numeric_id"] for r in records]
    if len(set(identifiers)) != len(identifiers):
        invalid_shape()
    if "structures" in query:
        ids = query["structures"]
        if (
            not isinstance(ids, list)
            or any(type(i) not in (int, str) for i in ids)
            or {str(i) for i in ids} != set(identifiers)
            or len(ids) != len(identifiers)
        ):
            invalid_shape()
    following = control["page"] + 1 if control["page"] < page["num_pages"] else None
    payload = {
        "record_type": "surechembl_similarity_window",
        "query": {"smiles": smiles, "similarity_threshold": threshold},
        "search_status": "finished",
        "records": records,
        "method": "Source-reported Tanimoto similarity over hashed binary chemical fingerprints. Fingerprint algorithm/version and structure normalization are not independently qualified; scores do not establish bioactivity or target binding.",
        "coverage": {
            "provider_total": total,
            "acquired_count": len(records),
            "provider_page": control["page"],
            "provider_pages": page["num_pages"],
            "source_start_on": page["start_on"],
            "window_size": limit,
            "all_matching_records_acquired": control["page"] == 1 and len(records) == total,
            "continuation_status": "available" if following else "terminal",
        },
        "source_input": {
            "endpoint": "/search/structure",
            "structSearchType": "similarity",
            "options": f"DISSIMILARITY={1 - float(threshold):.17g}",
            "requested_threshold_binding": "Signed query/account cursor with server-stored source-job context; source metadata does not echo the threshold. Every emitted score is checked against it.",
        },
        "warnings": [
            "This window contains source compound records, not distinct patent families. Source data are live and unpinned; completed job status does not establish exhaustive acquisition."
        ],
    }
    if not records and (total > 0 or control["page"] > 1):
        payload["section_outcomes"] = {"empty_window": {"outcome": "partial", "sources": ["surechembl"]}}
    if following is not None:
        if following > MAX_PAGE:
            payload["coverage"]["continuation_status"] = "unavailable"
            payload["section_outcomes"] = {"continuation": {"outcome": "partial", "sources": []}}
        else:
            payload["_provider_pages"] = {
                "surechembl_search": {
                    "next_token": json.dumps({"hash": control["hash"], "page": following}),
                    "raw_count": len(rows),
                    "last_page": control["page"],
                }
            }
    return payload


def pending_search(control, smiles, threshold, status, limit):
    import json

    return {
        "record_type": "surechembl_search_status",
        "query": {"smiles": smiles, "similarity_threshold": threshold},
        "search_status": status,
        "records": [],
        "coverage": {
            "provider_total": None,
            "acquired_count": 0,
            "window_size": limit,
            "all_matching_records_acquired": False,
            "continuation_status": "awaiting_source",
        },
        "retry_after_seconds": 2,
        "section_outcomes": {"search": {"outcome": "unavailable", "sources": []}},
        "warnings": [
            "Source search is pending; no matching-compound count or absence is established. Resume the returned action after the indicated delay; it does not create another search."
        ],
        "_provider_pages": {
            "surechembl_search": {
                "next_token": json.dumps(control),
                "raw_count": 0,
                "last_page": control["page"] - 1,
            }
        },
    }


def requested_document(value):
    if (
        not isinstance(value, str)
        or not 3 <= len(value) <= 64
        or not re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]+-[A-Z][0-9]?|[A-Z0-9]+)", value)
    ):
        raise ResearchError(
            "invalid_parameters", "Provide an explicit bounded patent publication identifier."
        )
    return value


def normalized_document(value, requested):
    data = envelope(value)
    if (
        not isinstance(data, dict)
        or set(data) != {requested}
        or not isinstance(data[requested], list)
        or not data[requested]
    ):
        invalid_shape()
    identifiers = data[requested]
    if any(not isinstance(i, str) or not DOCUMENT_ID.fullmatch(i) for i in identifiers) or len(
        set(identifiers)
    ) != len(identifiers):
        invalid_shape()
    if len(identifiers) != 1:
        raise ResearchError(
            "ambiguous_identity",
            "SureChEMBL returned multiple publications; provide a normalized identifier including kind code.",
        )
    return identifiers[0]


def patent_annotations(value, requested, normalized, mode):
    from hashlib import sha256

    data = envelope(value)
    if not isinstance(data, dict) or data.get("doc_id") != normalized:
        raise ResearchError("identity_mismatch", "SureChEMBL returned a different publication.")
    contents = data.get("contents")
    if not isinstance(contents, dict) or not isinstance(contents.get("patentDocument"), dict):
        invalid_shape()
    source = contents["patentDocument"]
    if not source or any(key in source for key in ("error", "errors", "messages")):
        invalid_shape()
    version = data.get("doc_version")
    if version is not None and (
        type(version) not in (str, int)
        or isinstance(version, str)
        and not version.strip()
        or isinstance(version, int)
        and version < 0
    ):
        invalid_shape()
    records, sections, statuses = [], [], {}
    for collection_key in ("abstracts", "descriptions", "claimResponses"):
        if collection_key not in source:
            statuses[collection_key] = {"outcome": "unavailable", "sources": []}
            sections.append({"collection": collection_key, "status": "not_reported"})
            continue
        chunks = source[collection_key]
        if not isinstance(chunks, list) or len(chunks) > 1000:
            invalid_shape()
        reported = True
        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict) or not isinstance(chunk.get("section"), dict):
                invalid_shape()
            section = chunk["section"]
            section_record = {
                "collection": collection_key,
                "index": index,
                "language": chunk.get("lang"),
                "source_section_id": chunk.get("mxwid"),
            }
            if any(
                v is not None and (not isinstance(v, str) or not v.strip())
                for v in (section_record["language"], section_record["source_section_id"])
            ):
                invalid_shape()
            if "annotations" not in section:
                reported = False
                sections.append(
                    {**section_record, "annotation_status": "not_reported", "annotation_count": None}
                )
                continue
            annotations = collection(section, ("annotations",))
            text = section.get("content")
            if not isinstance(text, str):
                invalid_shape()
            try:
                units = len(text.encode("utf-16-le")) // 2
                text_hash = sha256(text.encode()).hexdigest()
            except UnicodeError:
                raise ResearchError(
                    "invalid_source_response", "Source annotation text encoding is invalid."
                ) from None
            if len(records) + len(annotations) > 20000:
                raise ResearchError(
                    "source_response_budget", "Document annotations exceed the bounded source projection."
                )
            sections.append(
                {
                    **section_record,
                    "annotation_status": "reported",
                    "annotation_count": len(annotations),
                    "source_html_utf16_length": units,
                    "source_html_sha256": text_hash,
                }
            )
            for annotation in annotations:
                start, end, category = (
                    annotation.get("start"),
                    annotation.get("end"),
                    annotation.get("category"),
                )
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= units
                    or not isinstance(category, str)
                    or not 1 <= len(category) <= 64
                ):
                    invalid_shape()
                ids = annotation.get("chemicalIds")
                if ids is not None and (
                    not isinstance(ids, list)
                    or any(type(i) is not int or not 0 < i < 10**16 for i in ids)
                    or len(set(ids)) != len(ids)
                ):
                    invalid_shape()
                frequency = annotation.get("globalFrequency")
                if frequency is not None and (type(frequency) is not int or frequency < 0):
                    invalid_shape()
                records.append(
                    {
                        "section_collection": collection_key,
                        "section_index": index,
                        "start": start,
                        "end": end,
                        "category": category,
                        "chemical_ids": ["SCHEMBL" + str(i) for i in ids] if ids is not None else None,
                        "chemical_mapping_status": "not_reported"
                        if not ids
                        else "multiple_source_identifiers"
                        if len(ids) > 1
                        else "single_source_identifier",
                        "source_annotation_global_frequency": frequency,
                    }
                )
        statuses[collection_key] = {
            "outcome": "data" if reported else "unavailable",
            "sources": ["surechembl"] if reported else [],
        }
    chemical_records = [r for r in records if r["category"] == "chemical"]
    counts = Counter(r["category"] for r in records)
    memberships = Counter(i for r in chemical_records for i in r["chemical_ids"] or [])
    result = {
        "record_type": "surechembl_patent_annotation_projection",
        "requested_publication": requested,
        "publication_id": normalized,
        "source_document_version": str(version) if version is not None else None,
        "url": f"https://www.surechembl.org/patent/{normalized}",
        "analysis_type": mode,
        "sections": sections,
        "records": records,
        "denominator": {
            "unit": "source_annotation_occurrences_in_selected_sections",
            "acquired": len(records),
            "chemical_occurrences": len(chemical_records),
            "chemical_mapping_missing": sum(not r["chemical_ids"] for r in chemical_records),
            "chemical_mapping_multiple_ids": sum(len(r["chemical_ids"] or []) > 1 for r in chemical_records),
        },
        "coverage": {
            "included_collections": ["abstracts", "descriptions", "claimResponses"],
            "all_selected_section_annotations_reported": all(
                s["outcome"] == "data" for s in statuses.values()
            ),
            "whole_document_chemistry_exhaustive": False,
        },
        "method": "Project source annotation identifiers, categories and source HTML offsets; count source occurrences or identifier memberships only. No compound identity resolution, target binding, novelty, claim scope, legal status or patent-family frequency is inferred.",
        "position_units": "JavaScript UTF-16 code units over source HTML; zero-based start and exclusive end. Source text is excluded.",
        "section_outcomes": statuses,
        "warnings": [
            "Underlying patent text, matched text, titles, drawings and attachments are excluded from this projection. Annotation counts describe the selected source section collections, not exhaustive document or family chemistry.",
            "Source annotation globalFrequency is preserved as its own field; its definition/release alignment with compound-card global_frequency is unqualified. Identifier memberships can overlap for annotations with multiple mappings.",
        ],
    }
    if (
        result["denominator"]["chemical_mapping_missing"]
        or result["denominator"]["chemical_mapping_multiple_ids"]
    ):
        result["section_outcomes"]["chemical_mapping"] = {"outcome": "partial", "sources": ["surechembl"]}
    if mode == "categories":
        result["category_counts"] = [
            {
                "category": key,
                "count": count,
                "input_locators": [
                    f"/records/{i}/category" for i, r in enumerate(records) if r["category"] == key
                ],
            }
            for key, count in sorted(counts.items())
        ]
    elif mode == "frequency":
        result["chemical_identifier_memberships"] = [
            {
                "chemical_id": identifier,
                "membership_count": count,
                "input_locators": [
                    f"/records/{i}/chemical_ids"
                    for i, r in enumerate(records)
                    if r["category"] == "chemical" and identifier in (r["chemical_ids"] or [])
                ],
            }
            for identifier, count in sorted(memberships.items())
        ]
    return result


from biomedmcp.study_workers import StudyWorkers

annotation_workers = StudyWorkers(
    thread_name="ubi-surechembl", busy_message="Source annotation workers are busy; retry later."
)
