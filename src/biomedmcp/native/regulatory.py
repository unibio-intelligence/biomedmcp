"""Native public EMA/WHO feed readers; no silent cross-region identity merge.

Names return candidates. EU authorisation, WHO prequalification and US approval
remain distinct regulatory facts, never a single inferred approval status.
"""

import csv
import io
import re

from ..errors import ResearchError
from .http import ProviderHTTP

EMA = "https://www.ema.europa.eu/en/documents/report/"
EMA_FEEDS = {
    "record": "medicines-output-medicines_json-report_en.json",
    "regulatory": "medicines-output-post_authorisation_json-report_en.json",
    "referrals": "referrals-output-json-report_en.json",
    "psusas": "medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json",
    "safety": "dhpc-output-json-report_en.json",
    "shortage": "shortages-output-json-report_en.json",
}
WHO = "https://extranet.who.int/prequal/"
WHO_FEEDS = {
    "finished_pharma": (
        "medicines/prequalified/finished-pharmaceutical-products/export?page&_format=csv",
        {"WHO REFERENCE NUMBER", "INN, DOSAGE FORM AND STRENGTH", "APPLICANT"},
    ),
    "api": (
        "medicines/prequalified/active-pharmaceutical-ingredients/export?page&_format=csv",
        {"WHO PRODUCT ID", "INN", "APPLICANT ORGANIZATION"},
    ),
    "vaccine": ("vaccines/prequalified/export", {"VACCINE TYPE", "COMMERCIAL NAME", "MANUFACTURER"}),
    "ivd": (
        "vitro-diagnostics/prequalified/in-vitro-diagnostics/export?page&_format=csv",
        {"product code", "product name", "pathogen/disease/marker", "manufacturer name"},
    ),
}


def plain(value):
    if isinstance(value, dict):
        return " ".join(plain(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(plain(v) for v in value)
    return re.sub(r"<[^>]*>", " ", str(value or "")).casefold()


def candidates(rows, query, limit, offset, manufacturer=None):
    tokens = re.findall(r"[\w-]+", query.casefold())
    if not tokens:
        raise ResearchError("invalid_parameters", "Use a nonempty product or active ingredient query.")
    matches = []
    for row in rows:
        # Word boundaries prevent polio from matching poliovirus-like names
        # accidentally by substring; candidates still require identity review.
        haystack = plain(row)
        if all(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", haystack) for t in tokens):
            if manufacturer:
                maker = " ".join(
                    plain(v)
                    for k, v in row.items()
                    if any(word in k.casefold() for word in ["manufacturer", "applicant", "holder"])
                )
                if manufacturer.casefold() not in maker:
                    continue
            matches.append(row)
    return matches[offset : offset + limit]


class Regulatory:
    def __init__(self, http=None):
        self.http = http or ProviderHTTP()

    async def ema(self, query, section="record", limit=10, offset=0):
        url = EMA + EMA_FEEDS[section]
        value = await self.http.get(url)
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = next(
                (
                    value[k]
                    for k in ["data", "medicines", "results", "rows"]
                    if isinstance(value.get(k), list)
                ),
                None,
            )
            if rows is None and value and all(isinstance(v, dict) for v in value.values()):
                rows = list(value.values())
        else:
            rows = None
        if rows is None:
            raise ResearchError(
                "invalid_source_response", "EMA feed shape changed; no negative evidence can be inferred."
            )
        return {
            "records": candidates(rows, query, limit, offset),
            "source": "ema",
            "url": url,
            "jurisdiction": "EU",
            "section": section,
            "match_policy": "Literal query terms; candidate records require ingredient/product identity review.",
            "regulatory_meaning": "EMA authorisation or post-authorisation activity; not US approval.",
        }

    async def who(self, query, product_type="finished_pharma", limit=10, offset=0, manufacturer=None):
        path, required = WHO_FEEDS[product_type]
        url = WHO + path
        text = await self.http.get(url, text=True)
        if len(text.encode()) > 4_000_000:
            raise ResearchError("response_too_large", "WHO export exceeded 4 MB.")
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
        headers = [" ".join(name.split()).casefold() for name in reader.fieldnames or []]
        expected = {" ".join(name.split()).casefold() for name in required}
        if len(set(headers)) != len(headers) or not expected <= set(headers):
            raise ResearchError(
                "invalid_source_response", "WHO export headers changed; no negative evidence can be inferred."
            )
        rows = list(reader)
        return {
            "records": candidates(rows, query, limit, offset, manufacturer),
            "source": "who-ivd" if product_type == "ivd" else "who",
            "url": url,
            "product_type": product_type,
            "regulatory_meaning": "WHO prequalification; this is not a national marketing authorisation.",
            "match_policy": "Literal query terms and optional manufacturer; review record identity.",
        }
