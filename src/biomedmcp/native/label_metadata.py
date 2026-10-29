"""SPL label prose and factual metadata; attachments are never fetched."""

import re
from datetime import date

from .shapes import invalid_shape

FACTS = (
    "application_number",
    "brand_name",
    "generic_name",
    "manufacturer_name",
    "product_ndc",
    "substance_name",
    "route",
    "dosage_form",
    "product_type",
    "marketing_category",
    "spl_set_id",
    "spl_id",
    "unii",
    "rxcui",
)
TEXT_FIELDS = (
    "indications_and_usage",
    "dosage_and_administration",
    "boxed_warning",
    "warnings",
    "warnings_and_cautions",
    "contraindications",
    "adverse_reactions",
    "drug_interactions",
    "use_in_specific_populations",
    "pregnancy",
    "nursing_mothers",
    "lactation",
    "pediatric_use",
    "geriatric_use",
    "overdosage",
    "description",
    "clinical_pharmacology",
    "mechanism_of_action",
    "pharmacodynamics",
    "pharmacokinetics",
    "nonclinical_toxicology",
    "carcinogenesis_and_mutagenesis_and_impairment_of_fertility",
    "clinical_studies",
    "how_supplied",
    "storage_and_handling",
    "patient_counseling_information",
    "information_for_patients",
    "spl_medguide",
    "spl_patient_package_insert",
    "instructions_for_use",
    "do_not_use",
    "ask_doctor",
    "ask_doctor_or_pharmacist",
    "stop_use",
    "keep_out_of_reach_of_children",
    "purpose",
    "active_ingredient",
    "inactive_ingredient",
    "directions",
    "other_safety_information",
    "other_information",
    "when_using",
    "questions",
    "general_precautions",
    "precautions",
    "drug_abuse_and_dependence",
    "controlled_substance",
    "abuse",
    "dependence",
    "labor_and_delivery",
    "teratogenic_effects",
    "nonteratogenic_effects",
    "pregnancy_or_breast_feeding",
    "spl_unclassified_section",
    "recent_major_changes",
)

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def project(rows):
    out = []
    for row in rows:
        if not isinstance(row, dict):
            invalid_shape()
        values = [row.get(k) for k in ("id", "set_id")]
        if any(not isinstance(v, str) or not re.fullmatch(UUID, v) for v in values):
            invalid_shape()
        effective, version = row.get("effective_time"), row.get("version")
        if not isinstance(effective, str) or not re.fullmatch(r"\d{8}", effective):
            invalid_shape()
        try:
            date(int(effective[:4]), int(effective[4:6]), int(effective[6:]))
        except ValueError:
            invalid_shape()
        if not isinstance(version, str) or not re.fullmatch(r"[1-9]\d{0,8}", version):
            invalid_shape()
        data = row.get("openfda", {})
        if not isinstance(data, dict):
            invalid_shape()
        facts = {}
        for field in FACTS:
            if field not in data:
                continue
            value = data[field]
            if (
                not isinstance(value, list)
                or len(value) > 1000
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2048 for v in value)
            ):
                invalid_shape()
            facts[field] = value
        sections = {}
        for field in TEXT_FIELDS:
            if field not in row:
                continue
            value = row[field]
            if (
                not isinstance(value, list)
                or len(value) > 1000
                or any(not isinstance(v, str) or len(v) > 1_000_000 for v in value)
            ):
                invalid_shape()
            sections[field] = value
        out.append(
            {
                "id": row["id"],
                "set_id": row["set_id"],
                "version": version,
                "effective_time": effective,
                "product_metadata": facts,
                "label_url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=" + row["set_id"],
                "content_scope": "label_text_and_metadata",
                "label_sections": sections,
                "text_availability": "Manufacturer-submitted label prose; tables, images and attachments are not fetched.",
                "interpretation": "Manufacturer-submitted listing metadata; not proof of FDA approval, current distributed labeling, or verified clinical guidance.",
            }
        )
    if len({r["id"] for r in out}) != len(out):
        invalid_shape()
    return out
