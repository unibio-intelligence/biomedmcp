"""Normalize ChEMBL descriptors without turning absent values into measurements."""

import math
from decimal import Decimal, InvalidOperation

from biomedmcp.errors import ResearchError


def number(value, *, integer=False, minimum=None, maximum=None):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ResearchError("invalid_source_response", "Invalid ChEMBL numeric descriptor.")
    try:
        parsed = Decimal(str(value))
        normalized = float(parsed)
    except (InvalidOperation, OverflowError, ValueError):
        raise ValueError("Invalid ChEMBL numeric descriptor.") from None
    if (
        not math.isfinite(normalized)
        or (minimum is not None and normalized < minimum)
        or (maximum is not None and normalized > maximum)
        or (integer and parsed != parsed.to_integral_value())
    ):
        raise ValueError("Invalid ChEMBL numeric descriptor.")
    return int(parsed) if integer else normalized


def analyze_properties(compound, identifier, property_type):
    if not isinstance(compound, dict) or compound.get("molecule_chembl_id") != identifier:
        raise ValueError("ChEMBL compound identity was not confirmed.")
    properties = compound.get("molecule_properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise ResearchError("invalid_source_response", "Invalid ChEMBL property record.")
    result = {
        "compound_info": compound,
        "properties": properties,
        "section_outcomes": {"compound": "data", "properties": "data" if properties else "unavailable"},
        "warnings": [],
    }
    if not properties:
        result["warnings"].append("ChEMBL supplied no physicochemical descriptors for this compound.")
    if property_type in {"all", "drug_likeness"}:
        definitions = (
            ("molecular_weight", "full_mwt", 500, "g/mol", False, 0),
            ("logp", "alogp", 5, "dimensionless", False, None),
            ("hbd", "hbd", 5, "count", True, 0),
            ("hba", "hba", 10, "count", True, 0),
        )
        checks, missing = {}, []
        for name, field, threshold, unit, integer, minimum in definitions:
            value = number(properties.get(field), integer=integer, minimum=minimum)
            if name == "molecular_weight" and value == 0:
                raise ValueError("Invalid ChEMBL molecular weight.")
            if value is None:
                missing.append(field)
            checks[name] = {
                "value": value,
                "unit": unit,
                "threshold": threshold,
                "pass": value <= threshold if value is not None else None,
            }
        provider_violations = number(properties.get("num_ro5_violations"), integer=True, minimum=0, maximum=4)
        violations = sum(check["pass"] is False for check in checks.values()) if not missing else None
        result["drug_likeness"] = {
            "method": "Four physicochemical threshold checks; drug_like requires at most one violation and all four descriptors.",
            "interpretation": "A physicochemical heuristic; efficacy, safety, ADMET and clinical suitability are not established.",
            "coverage": {"observed": 4 - len(missing), "required": 4, "missing": missing},
            "lipinski_rule_of_five": {
                **checks,
                "violations": violations,
                "provider_violations": provider_violations,
                "drug_like": violations <= 1 if violations is not None else None,
            },
            "ro3_pass": properties.get("ro3_pass"),
        }
        result["section_outcomes"]["drug_likeness"] = "unavailable" if missing else "data"
        if missing:
            result["warnings"].append(
                "Rule-of-five assessment unavailable: missing " + ", ".join(missing) + "."
            )
        if violations is not None and provider_violations is not None and violations != provider_violations:
            result["warnings"].append(
                "The provider's violation count differs from the local descriptor checks; both assertions are retained."
            )
    if property_type == "admet":
        result["section_outcomes"]["admet"] = "unavailable"
        result["warnings"].append(
            "This acquisition supplies physicochemical descriptors, not ADMET measurements."
        )
    return result
