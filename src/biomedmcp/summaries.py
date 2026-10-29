"""Bounded search excerpts; scientific identities and source assertions remain intact."""

import json
from copy import deepcopy

from .evidence import bound
from .scientific_records import LiteratureRecord
from .trial_records import TrialRecord


def summarize_records(records):
    output, cut = [], False
    attribution = {
        "sources",
        "primary_source",
        "evidence_ids",
        "ranking",
        "url",
        "date_validation",
        "journal",
        "book_title",
        "publication_form",
    }
    for record in records:
        kind = record.get("record_type")
        if kind and kind not in {"literature", "trial"}:
            # Other typed scientific families carry checked denominators,
            # coding and aligned input arrays. Retain their complete contract.
            output.append(deepcopy(record))
            continue
        protected = attribution | {"id", "_id", "primaryAccession", "safetyreportid"}
        if kind in {"literature", "trial"}:
            model = LiteratureRecord if kind == "literature" else TrialRecord
            protected |= set(model.model_fields)
            row = {key: deepcopy(value) for key, value in record.items() if key in protected}
            if kind == "literature":
                abstract = row.get("abstract")
                if isinstance(abstract, str) and len(abstract) > 500:
                    row["abstract"] = abstract[:500]
                if len(row.get("authors", [])) > 5:
                    row["authors"] = row["authors"][:5]
                    row["author_completeness"] = "source_limited"
            else:
                row["conditions"] = deepcopy(record.get("conditions", []))[:5]
        else:
            row, _ = bound(record, rows=3, string_limit=300)
            # Generic large nested fields are excerpted, never promoted into a
            # new scientific schema or a claimed complete measurement.
            for key in sorted(row, key=lambda k: len(json.dumps(row[k])), reverse=True):
                if len(json.dumps(row).encode()) <= 2000:
                    break
                if key not in protected:
                    row.pop(key)
        if row != record:
            cut = True
            row["record_view"] = "summary"
            row["summary_omissions"] = True
        output.append(row)
    return output, cut
