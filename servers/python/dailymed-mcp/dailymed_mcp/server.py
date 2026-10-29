#!/usr/bin/env python3
"""DailyMed MCP Server - Access NLM DailyMed drug labels.

Provides access to the National Library of Medicine's DailyMed database
for drug labels, SPL documents, and pharmaceutical information.
"""

import asyncio
import re
import xml.etree.ElementTree as ET

from biomedmcp import transport as httpx
from fastmcp import FastMCP

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query DailyMed",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Create FastMCP server
mcp = FastMCP("dailymed")

_DAILYMED_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
_HL7_NS = {"hl7": "urn:hl7-org:v3"}

_SECTION_ALIASES = {
    "ADVERSE_REACTIONS": {"ADVERSE REACTIONS"},
    "BOXED_WARNING": {"BOXED WARNING", "WARNING"},
    "CONTRAINDICATIONS": {"CONTRAINDICATIONS"},
    "DOSAGE": {"DOSAGE", "DOSAGE AND ADMINISTRATION", "DOSAGE & ADMINISTRATION"},
    "DRUG_INTERACTIONS": {"DRUG INTERACTIONS"},
    "INDICATIONS": {"INDICATIONS", "INDICATIONS AND USAGE", "INDICATIONS & USAGE"},
    "WARNINGS": {"WARNINGS", "WARNINGS AND PRECAUTIONS", "BOXED WARNING"},
}


def _compact_text(value: str | None, max_chars: int | None = None) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _parse_spl_xml(xml_text: str, set_id: str) -> dict:
    root = ET.fromstring(xml_text)
    document_id = root.find("hl7:id", _HL7_NS)
    document_code = root.find("hl7:code", _HL7_NS)
    effective_time = root.find("hl7:effectiveTime", _HL7_NS)
    sections = []

    for section in root.findall(".//hl7:section", _HL7_NS):
        code = section.find("hl7:code", _HL7_NS)
        text_node = section.find("hl7:text", _HL7_NS)
        sections.append(
            {
                "code": code.get("code") if code is not None else None,
                "display_name": code.get("displayName") if code is not None else None,
                "title": _compact_text(section.findtext("hl7:title", namespaces=_HL7_NS)),
                "text": _compact_text(
                    "".join(text_node.itertext()) if text_node is not None else "",
                    max_chars=12000,
                ),
            }
        )

    return {
        "setid": set_id,
        "document_id": document_id.get("root") if document_id is not None else None,
        "document_code": document_code.get("code") if document_code is not None else None,
        "document_type": document_code.get("displayName") if document_code is not None else None,
        "title": _compact_text(root.findtext("hl7:title", namespaces=_HL7_NS)),
        "effective_time": effective_time.get("value") if effective_time is not None else None,
        "sections": sections,
        "section_count": len(sections),
        "source_format": "xml",
    }


def _section_matches(section: dict, requested_type: str) -> bool:
    requested = requested_type.upper().replace("-", "_").strip()
    aliases = _SECTION_ALIASES.get(requested, {requested.replace("_", " ")})
    haystack = " ".join(
        str(section.get(key) or "").upper().replace("&", "AND")
        for key in ("code", "display_name", "title")
    )
    return any(alias.replace("&", "AND") in haystack for alias in aliases)


async def _get_spl_xml(client: httpx.AsyncClient, set_id: str) -> str:
    url = f"{_DAILYMED_BASE}/spls/{set_id}.xml"
    response = await client.get(url)
    response.raise_for_status()
    return response.text


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_drug_labels(
    drug_name: str,
    limit: int = 50
) -> dict:
    """
    Search for drug labels by drug name.

    Args:
        drug_name: Drug name to search for
        limit: Maximum number of results (default: 50, max: 100)

    Returns:
        List of matching drug labels with set_id, title, and other metadata

    Examples:
        search_drug_labels(drug_name="warfarin")
        search_drug_labels(drug_name="ibuprofen", limit=10)
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{_DAILYMED_BASE}/spls.json"
        params = {
            "drug_name": drug_name,
            "page": 1,
            "pagesize": min(limit, 100)
        }
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        return {
            "total": data.get("metadata", {}).get("total_elements", 0),
            "results": data.get("data", []),
            "query": drug_name
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_drug_label_by_setid(
    set_id: str
) -> dict:
    """
    Get detailed drug label information by SPL set_id.

    Args:
        set_id: SPL set_id (e.g., "f232c325-0ef5-4e3a-9c0e-3f9b8c8f8e6a")

    Returns:
        Complete drug label information including all sections

    Examples:
        get_drug_label_by_setid(set_id="f232c325-0ef5-4e3a-9c0e-3f9b8c8f8e6a")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        xml_text = await _get_spl_xml(client, set_id)
        return _parse_spl_xml(xml_text, set_id)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_drug_label_sections(
    set_id: str,
    section_types: list[str] = None
) -> dict:
    """
    Get specific sections from a drug label.

    Args:
        set_id: SPL set_id
        section_types: List of section types to retrieve (optional)
                      Common: INDICATIONS, CONTRAINDICATIONS, WARNINGS,
                              ADVERSE_REACTIONS, DOSAGE, DRUG_INTERACTIONS

    Returns:
        Drug label sections with structured content

    Examples:
        get_drug_label_sections(set_id="abc123")
        get_drug_label_sections(set_id="abc123", section_types=["WARNINGS", "DOSAGE"])
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        xml_text = await _get_spl_xml(client, set_id)
        data = _parse_spl_xml(xml_text, set_id)

        # Filter by section types if specified
        if section_types:
            sections = [
                s for s in data.get("sections", [])
                if any(_section_matches(s, section_type) for section_type in section_types)
            ]
            data["sections"] = sections
            data["section_count"] = len(sections)
            data["requested_section_types"] = section_types

        return data


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_by_ndc(
    ndc: str
) -> dict:
    """
    Search for drug labels by NDC (National Drug Code).

    Args:
        ndc: National Drug Code (e.g., "0002-3229-30")

    Returns:
        Drug label information for the specified NDC

    Examples:
        search_by_ndc(ndc="0002-3229-30")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{_DAILYMED_BASE}/spls.json"
        params = {"ndc": ndc}
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_by_application_number(
    application_number: str
) -> dict:
    """
    Search for drug labels by FDA application number.

    Args:
        application_number: FDA application number (e.g., "NDA021462")

    Returns:
        Drug labels associated with the application number

    Examples:
        search_by_application_number(application_number="NDA021462")
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{_DAILYMED_BASE}/spls.json"
        params = {"application_number": application_number}
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def main():
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
