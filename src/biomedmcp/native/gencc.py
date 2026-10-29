"""Current versioned GenCC export; independent assertions, never consensus."""

import csv
import hashlib
import io
import re

from ..errors import ResearchError
from ..study_workers import StudyWorkers

URL = "https://thegencc.org/download/action/submissions-export-csv"
MAX_BYTES = 33_554_432
MAX_ROWS = 100_000
HEADERS = (
    "sgc_id", "version_number", "gene_curie", "gene_symbol", "disease_curie",
    "disease_title", "disease_original_curie", "disease_original_title",
    "classification_curie", "classification_title", "moi_curie", "moi_title",
    "submitter_curie", "submitter_title", "submitted_as_hgnc_id",
    "submitted_as_hgnc_symbol", "submitted_as_disease_id", "submitted_as_disease_name",
    "submitted_as_moi_id", "submitted_as_moi_name", "submitted_as_submitter_id",
    "submitted_as_submitter_name", "submitted_as_classification_id",
    "submitted_as_classification_name", "submitted_as_date", "submitted_as_public_report_url",
    "submitted_as_notes", "submitted_as_pmids", "submitted_as_assertion_criteria_url",
    "submitted_as_submission_id", "submitted_run_date",
)
workers = StudyWorkers(workers=1, max_pending=1, thread_name="ubi-gencc",
                       busy_message="GenCC export validation is busy; retry later.")


def invalid():
    raise ResearchError("invalid_source_response", "GenCC returned an invalid versioned export.")


def parse_export(text, gene):
    if not isinstance(text, str) or not text or "\x00" in text:
        invalid()
    try:
        raw = text.encode("utf-8")
    except UnicodeError:
        invalid()
    if len(raw) > MAX_BYTES:
        raise ResearchError("source_resource_limit", "GenCC export exceeds its bounded byte budget.")
    export_sha256 = hashlib.sha256(raw).hexdigest()
    del raw
    matched, seen, count = [], set(), 0
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) > 64 or len(set(headers)) != len(headers) or not set(HEADERS) <= set(headers):
            invalid()
        for row in reader:
            count += 1
            if count > MAX_ROWS:
                raise ResearchError("source_resource_limit", "GenCC export exceeds its bounded row budget.")
            if None in row or any(not isinstance(value, str) for value in row.values()):
                invalid()
            patterns = {
                "sgc_id": r"SGC-[1-9][0-9]*", "version_number": r"[1-9][0-9]*",
                "gene_curie": r"HGNC:[1-9][0-9]*", "gene_symbol": r"[A-Za-z0-9_.-]{1,64}",
                "disease_curie": r"MONDO:[0-9]{7}", "classification_curie": r"GENCC:[0-9]{6}",
                "moi_curie": r"HP:[0-9]{7}", "submitter_curie": r"GENCC:[0-9]{6}",
            }
            if any(re.fullmatch(pattern, row[field]) is None for field, pattern in patterns.items()):
                invalid()
            if any(not row[field].strip() for field in (
                "disease_title", "classification_title", "moi_title", "submitter_title", "submitted_as_date"
            )):
                invalid()
            identity = (row["sgc_id"], row["version_number"])
            if identity in seen:
                invalid()
            seen.add(identity)
            if row["gene_symbol"] == gene:
                matched.append(row)
    except (csv.Error, ValueError, OverflowError):
        invalid()
    return {
        "record_type": "gencc_gene_disease_assertions", "source": "gencc", "species": 9606,
        "gene_symbol": gene, "export_format": "new", "source_release": None,
        "export_sha256": export_sha256, "records": matched,
        "coverage": {"export_rows_validated": count, "matched_rows": len(matched),
                     "export_complete": True, "match_policy": "exact_gene_symbol"},
        "warnings": [
            "GenCC and contributing submitters retain separate SGC/version, disease, inheritance and classification assertions; no consensus or causal/clinical conclusion is computed.",
            "A completed export has no matching assertion only within this downloaded snapshot; it does not establish biological absence or exhaustive biomedical evidence.",
            "Reported identifiers are source assertions, not cross-source identity repairs. Linked reports are not retrieved or licensed by the GenCC CC0 export permission.",
        ],
    }


async def acquire(http, gene):
    text = await http.get(URL, params={"format": "new"}, text=True)
    return await workers.run(parse_export, text, gene)
