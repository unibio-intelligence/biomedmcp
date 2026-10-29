"""Validate HPA's single-gene XML identity envelope, not its assay results.

The raw document remains source data. Its entry/schema/annotation versions are
reported independently; neither an entry URL nor a version proves exact replay.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Literal
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ResearchError

GENE = re.compile(r"ENSG\d{11}")
XML_BYTES = 8_000_000
XML_ELEMENTS = 100_000
XML_DEPTH = 64


def ensembl_gene(value):
    if not isinstance(value, str) or not GENE.fullmatch(value):
        raise ResearchError("invalid_identifier", "Use a complete human Ensembl gene identifier.")
    return value


def invalid():
    raise ResearchError("invalid_source_response", "HPA returned an invalid single-gene XML envelope.")


class HPAAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    database: Literal["Ensembl"] = "Ensembl"
    version: str = Field(min_length=1, max_length=64)
    assembly: str = Field(min_length=1, max_length=128)
    gencode_version: int = Field(ge=1)

    @field_validator("version", "assembly")
    @classmethod
    def reported(cls, value):
        if not value.strip():
            raise ValueError("Annotation version/build is unavailable")
        return value


class HPASourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    record_type: Literal["hpa_source_xml"] = "hpa_source_xml"
    assertion_type: Literal["source_annotations"] = "source_annotations"
    source: Literal["protein-atlas"] = "protein-atlas"
    species: Literal[9606] = 9606
    ensembl_id: str = Field(pattern=r"^ENSG\d{11}$")
    gene_symbol: str = Field(min_length=1, max_length=256)
    source_release: str = Field(pattern=r"^\d+(?:\.\d+)*$", max_length=64)
    source_schema_version: str = Field(pattern=r"^\d+(?:\.\d+)*$", max_length=64)
    annotation: HPAAnnotation
    source_entry_url: str = Field(max_length=2048)
    url: str
    data: str
    xml_utf8_bytes: int = Field(ge=1, le=XML_BYTES)
    xml_utf8_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    validation_scope: Literal["single_gene_identity_envelope"] = "single_gene_identity_envelope"
    full_xsd_validated: Literal[False] = False
    measurements_normalized: Literal[False] = False
    time_dependent: Literal[True] = True
    status: Literal["success"] = "success"


def source_record(text, requested_id):
    """Reject wrong documents/identities before they can become healthy data."""
    requested_id = ensembl_gene(requested_id)
    if not isinstance(text, str) or not text or len(text) > XML_BYTES:
        invalid()
    raw = text.encode("utf-8")
    if len(raw) > XML_BYTES:
        invalid()
    try:
        depth = count = 0
        parser = ElementTree.iterparse(
            io.BytesIO(raw),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for event, _ in parser:
            if event == "start":
                depth += 1
                count += 1
                if depth > XML_DEPTH or count > XML_ELEMENTS:
                    invalid()
            else:
                depth -= 1
        root = parser.root
    except (ParseError, DefusedXmlException, ValueError):
        invalid()
    if root.tag != "proteinAtlas" or any(e.tag in {"error", "errors"} for e in root.iter()):
        invalid()
    entries = root.findall("entry")
    if len(entries) != 1:
        invalid()
    entry = entries[0]
    names = entry.findall("name")
    identifiers = entry.findall("identifier")
    if len(names) != 1 or list(names[0]) or not (names[0].text or "").strip():
        invalid()
    if len(identifiers) != 1 or identifiers[0].get("db") != "Ensembl":
        invalid()
    identity = identifiers[0]
    actual_id = identity.get("id")
    if not isinstance(actual_id, str) or not GENE.fullmatch(actual_id):
        invalid()
    if actual_id != requested_id:
        raise ResearchError("identity_mismatch", "HPA returned a different Ensembl gene identity.")
    url = entry.get("url", "")
    try:
        parsed = urlsplit(url)
        valid_url = (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port is None
            and re.fullmatch(r"(?:www|v\d+(?:\.\d+)*)\.proteinatlas\.org", parsed.hostname or "")
            and parsed.path == "/" + actual_id
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        invalid()
    if not valid_url:
        invalid()
    gencode = identity.get("gencodeVersion", "")
    if not re.fullmatch(r"[1-9]\d{0,8}", gencode):
        invalid()
    try:
        return HPASourceRecord(
            ensembl_id=actual_id,
            gene_symbol=(names[0].text or "").strip(),
            source_release=entry.get("version"),
            source_schema_version=root.get("schemaVersion"),
            annotation=HPAAnnotation(
                version=identity.get("version"),
                assembly=identity.get("assembly"),
                gencode_version=int(gencode),
            ),
            source_entry_url=url,
            url="https://www.proteinatlas.org/" + requested_id + ".xml",
            data=text,
            xml_utf8_bytes=len(raw),
            xml_utf8_sha256=hashlib.sha256(raw).hexdigest(),
        ).model_dump(mode="json")
    except ValidationError:
        invalid()
