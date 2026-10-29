"""Bounded projection of FDA's official complete Orange Book JSON export.

The media ZIP remains the primary route. This independent official distribution
retains its own release identity; it must never masquerade as the media ZIP.
"""

import hashlib
import io
import json
import re
import zipfile

import pandas as pd

from biomedmcp import transport
from biomedmcp.errors import ResearchError
from biomedmcp.native.shapes import collection, invalid_shape

URL = "https://download.open.fda.gov/drug/orangebook/drug-orangebook-0001-of-0001.json.zip"
MEMBER = "drug-orangebook-0001-of-0001.json"


def string(row, key, pattern=None):
    value = row.get(key)
    if not isinstance(value, str) or not value.strip() or (pattern and not re.fullmatch(pattern, value)):
        invalid_shape()
    return value


def strings(row, key):
    return collection(row, (key,), element=str) if key in row else []


def flag(row, key):
    if type(row.get(key)) is not bool:
        invalid_shape()
    return "Yes" if row[key] else "No"


def strength(row):
    # FDA omits strength for a small number of otherwise identified products.
    # Preserve that missing value, never substitute a dose or reject the dataset.
    value = row.get("strength", "")
    if not isinstance(value, str):
        invalid_shape()
    return value


async def fetch(filename):
    if filename not in {"products.txt", "patent.txt", "exclusivity.txt"}:
        invalid_shape()
    async with transport.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(URL)
        response.raise_for_status()
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            infos = archive.infolist()
            if len(infos) != 1 or infos[0].filename != MEMBER:
                invalid_shape()
            if infos[0].file_size > 80_000_000:
                raise ResearchError(
                    "source_response_budget", "Orange Book export exceeds its archive budget."
                )
            payload = json.loads(archive.read(MEMBER))
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeError):
        invalid_shape()
    records = collection(payload, ("results",))
    meta = payload.get("meta")
    if not isinstance(meta, dict) or not isinstance(meta.get("results"), dict):
        invalid_shape()
    total = meta["results"].get("total")
    if type(total) is not int or total <= 0 or len(records) != total:
        invalid_shape()
    updated = string(meta, "last_updated", r"\d{4}-\d{2}-\d{2}")
    products, patents, exclusivity, seen = [], [], [], set()
    for record in records:
        number = string(record, "product_number", r"\d{3}")
        rows = collection(record, ("products",))
        if len(rows) != 1:
            invalid_shape()
        product = rows[0]
        app = string(product, "application_number", r"\d{6}")
        kind = string(product, "application_type", r"[NA]")
        identity = (kind, app, number)
        if identity in seen:
            invalid_shape()
        seen.add(identity)
        ingredients = collection(product, ("active_ingredients",))
        if not ingredients:
            invalid_shape()
        common = {"Appl_Type": kind, "Appl_No": app, "Product_No": number}
        approval = record.get("approval_date")
        if approval is not None:
            approval = string(record, "approval_date", r"\d{8}")
        elif record.get("approved_prior_to_1982") is True:
            approval = "Approved Prior to Jan 1, 1982"
        else:
            invalid_shape()
        codes = strings(product, "therapeutic_equivalence_codes")
        products.append(
            {
                **common,
                "Ingredient": "; ".join(string(i, "name") for i in ingredients),
                "Strength": "; ".join(strength(i) for i in ingredients),
                "Trade_Name": string(product, "brand_name"),
                "Applicant": string(product, "application_name"),
                "Applicant_Full_Name": string(product, "application_full_name"),
                "DF;Route": string(product, "dosage_form") + ";" + string(product, "route"),
                "Dosage_Form": product["dosage_form"],
                "Route": product["route"],
                "TE_Code": "; ".join(codes),
                "Approval_Date": approval,
                "RLD": flag(product, "reference_listed_drug"),
                "RS": flag(product, "reference_standard"),
                "Type": string(product, "marketing_status"),
                "openfda_record": record,
            }
        )
        for patent in collection(record, ("patents",)) if "patents" in record else []:
            patents.append(
                {
                    **common,
                    "Patent_No": string(patent, "patent_number"),
                    "Patent_Expire_Date_Text": string(patent, "expiration_date", r"\d{8}"),
                    "openfda_patent": patent,
                }
            )
        for item in collection(record, ("exclusivity",)) if "exclusivity" in record else []:
            exclusivity.append(
                {
                    **common,
                    "Exclusivity_Code": string(item, "exclusivity_code"),
                    "Exclusivity_Date": string(item, "exclusivity_expiration_date", r"\d{8}"),
                    "openfda_exclusivity": item,
                }
            )
    selected, columns = {
        "products.txt": (products, ["Appl_No", "Product_No"]),
        "patent.txt": (patents, ["Appl_No", "Product_No", "Patent_No"]),
        "exclusivity.txt": (exclusivity, ["Appl_No", "Product_No", "Exclusivity_Code"]),
    }[filename]
    frame = pd.DataFrame(selected) if selected else pd.DataFrame(columns=columns)
    frame.attrs["source_release"] = {
        "url": URL,
        "format": "openfda-orangebook-json",
        "last_updated": updated,
        "records": total,
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }
    return frame
