"""Dated RCSB entry/search/file contracts; failures never mean no structures.

Entry validation keywords are projected from the official 2026-10-11 schema.
Primary contracts: https://data.rcsb.org/rest/v1/schema/entry,
https://search.rcsb.org/, and RCSB file-download-services documentation.
"""

import hashlib
import json
import math
import re
from datetime import datetime
from functools import lru_cache
from importlib.resources import files

import pdbx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from jsonschema import Draft4Validator

from biomedmcp.errors import ResearchError
from biomedmcp.native.shapes import invalid_shape
from biomedmcp.pagination import page_payload
from biomedmcp.study_workers import StudyWorkers

METHODS = (
    "ELECTRON CRYSTALLOGRAPHY",
    "ELECTRON MICROSCOPY",
    "EPR",
    "FIBER DIFFRACTION",
    "FLUORESCENCE TRANSFER",
    "INFRARED SPECTROSCOPY",
    "NEUTRON DIFFRACTION",
    "POWDER DIFFRACTION",
    "SOLID-STATE NMR",
    "SOLUTION NMR",
    "SOLUTION SCATTERING",
    "THEORETICAL MODEL",
    "X-RAY DIFFRACTION",
)
SORTS = ("score", "rcsb_accession_info.initial_release_date", "rcsb_entry_info.resolution_combined")
MAX_OFFSET = 100_000_000
FILE_BYTES = 4_000_000
NO_CONTENT = object()
workers = StudyWorkers(
    thread_name="ubi-pdb", busy_message="Structure validation workers are busy; retry later."
)


def pdb_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[1-9][A-Za-z0-9]{3}|pdb_[A-Za-z0-9]{8})", value, flags=re.IGNORECASE
    ):
        raise ResearchError("invalid_parameters", "Use a PDB entry identifier.")
    return value.lower()


def identity(value):
    value = pdb_id(value)
    return value.removeprefix("pdb_0000") if value.startswith("pdb_0000") else value


def resolution_range(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?", value):
        raise ResearchError("invalid_parameters", "Use an ordered nonnegative resolution range in angstroms.")
    low, high = map(float, value.split("-"))
    if not all(math.isfinite(x) for x in (low, high)) or not 0 <= low <= high or high <= 0:
        raise ResearchError("invalid_parameters", "Use an ordered nonnegative resolution range in angstroms.")
    return low, high


def preflight(operation, params):
    if operation in {"search_structures", "search_by_uniprot"}:
        limit, offset = params.get("limit", 25), params.get("offset", 0)
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= MAX_OFFSET
        ):
            raise ResearchError("invalid_parameters", "PDB search requires a bounded limit and offset.")
        if operation == "search_structures":
            query = params.get("query")
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 256:
                raise ResearchError("invalid_parameters", "Use a bounded nonempty structure query.")
            if params.get("sort_by", "score") not in SORTS:
                raise ResearchError("invalid_parameters", "Select a documented RCSB sort field.")
            if params.get("sort_direction", "desc") not in {"asc", "desc"}:
                raise ResearchError("invalid_parameters", "Select ascending or descending RCSB sorting.")
            if params.get("experimental_method") is not None and params["experimental_method"] not in METHODS:
                raise ResearchError("invalid_parameters", "Select a documented experimental method.")
            resolution_range(params.get("resolution_range"))
        elif not isinstance(params.get("uniprot_id"), str) or not re.fullmatch(
            r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?",
            params["uniprot_id"],
        ):
            raise ResearchError("invalid_parameters", "Use a qualified UniProt accession.")
    else:
        pdb_id(params.get("pdb_id"))
        assembly = params.get("assembly_id")
        if assembly is not None and (
            not isinstance(assembly, str) or not re.fullmatch(r"[1-9]\d{0,5}", assembly)
        ):
            raise ResearchError("invalid_parameters", "Use a positive biological assembly identifier.")
        if assembly is not None and params.get("format", "pdb") == "xml":
            raise ResearchError(
                "unsupported_filter", "Biological assembly downloads support mmCIF or legacy PDB."
            )


@lru_cache(maxsize=1)
def entry_validator():
    schema = json.loads(files("pdb_mcp").joinpath("entry-schema.json").read_text())
    Draft4Validator.check_schema(schema)
    return Draft4Validator(schema)


def entry(value, requested):
    if not isinstance(value, dict) or not entry_validator().is_valid(value):
        invalid_shape()
    expected = identity(requested)
    locators = [value["rcsb_id"], value["rcsb_entry_container_identifiers"]["entry_id"]]
    if "entry" in value:
        locators.append(value["entry"]["id"])
    if "rcsb_id" in value["rcsb_entry_container_identifiers"]:
        locators.append(value["rcsb_entry_container_identifiers"]["rcsb_id"])
    try:
        if any(identity(locator) != expected for locator in locators):
            invalid_shape()
    except ResearchError:
        invalid_shape()
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, float) and not math.isfinite(item):
            invalid_shape()
    info = value["rcsb_entry_info"]
    for key, number in info.items():
        if key.endswith("_count") and (type(number) is not int or number < 0):
            invalid_shape()
    if "resolution_combined" in info and (
        not info["resolution_combined"] or any(x <= 0 for x in info["resolution_combined"])
    ):
        invalid_shape()
    accession = value.get("rcsb_accession_info", {})
    for key in ("major_revision", "minor_revision"):
        if key in accession and (type(accession[key]) is not int or accession[key] < 0):
            invalid_shape()
    for key in ("deposit_date", "initial_release_date", "revision_date"):
        if key in accession:
            try:
                datetime.fromisoformat(accession[key])
            except (TypeError, ValueError):
                invalid_shape()
    return value


def observed_release(value):
    accession = value.get("rcsb_accession_info", {})
    if "major_revision" in accession and "minor_revision" in accession:
        return f"{accession['major_revision']}.{accession['minor_revision']}"
    return None


def search(value, *, label, limit, offset):
    no_content = value is NO_CONTENT
    if no_content:
        value = {"result_type": "entry", "result_set": [], "total_count": 0 if offset == 0 else None}
    if (
        not isinstance(value, dict)
        or value.get("result_type") != "entry"
        or value.get("error")
        or value.get("errors")
        or value.get("success") is False
    ):
        invalid_shape()
    rows, total = value.get("result_set"), value.get("total_count")
    if not isinstance(rows, list) or len(rows) > limit:
        invalid_shape()
    if not no_content and (type(total) is not int or total < 0):
        invalid_shape()
    if (
        rows
        and (total is None or total < offset + len(rows))
        or not rows
        and total is not None
        and offset < total
    ):
        invalid_shape()
    ids = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"identifier", "score", "services"}:
            invalid_shape()
        try:
            ids.append(identity(row.get("identifier")))
        except ResearchError:
            invalid_shape()
        score = row.get("score")
        if type(score) not in {float, int} or not math.isfinite(score) or not 0 <= score <= 1:
            invalid_shape()
        if "services" in row:
            if not isinstance(row["services"], list):
                invalid_shape()
            for service in row["services"]:
                if (
                    not isinstance(service, dict)
                    or not isinstance(service.get("service_type"), str)
                    or not service["service_type"]
                    or not isinstance(service.get("nodes"), list)
                ):
                    invalid_shape()
                for node in service["nodes"]:
                    if (
                        not isinstance(node, dict)
                        or type(node.get("node_id")) is not int
                        or node["node_id"] < 0
                    ):
                        invalid_shape()
                    for key in ("original_score", "norm_score"):
                        number = node.get(key)
                        if type(number) not in {float, int} or not math.isfinite(number):
                            invalid_shape()
                    if not 0 <= node["norm_score"] <= 1:
                        invalid_shape()
    if len(set(ids)) != len(ids):
        invalid_shape()
    next_offset = offset + len(rows) if rows and offset + len(rows) < total else None
    window = page_payload(
        rows,
        raw_count=len(rows),
        total=total,
        next_offset=next_offset,
        exhausted=next_offset is None,
    )
    return {
        **label,
        "url": "https://search.rcsb.org/rcsbsearch/v2/query",
        "record_locators": [
            {
                "id": row["identifier"],
                "namespace": "pdb",
                "url": f"https://www.rcsb.org/structure/{row['identifier']}",
            }
            for row in rows
        ],
        "total_count": total,
        "returned_count": len(rows),
        "results": value,
        **window,
        "coverage": {
            "offset": offset,
            "limit": limit,
            "total_count": total,
            "content_scope": "experimental PDB archive entries; computed models excluded",
            "accessible_window_exhausted": next_offset is None,
        },
    }


def coordinates(content, *, requested, format, assembly_id=None):
    if not isinstance(content, str) or not content or len(content.encode()) > FILE_BYTES:
        invalid_shape()
    expected = identity(requested)
    try:
        if format == "mmcif":
            blocks = pdbx.loads(content)
            if len(blocks) != 1 or identity(blocks[0].name) != expected:
                invalid_shape()
            block = blocks[0]
            metadata = block.get_object("entry")
            if (
                metadata is None
                or metadata.row_count != 1
                or not metadata.has_attribute("id")
                or identity(metadata.get_value("id", 0)) != expected
            ):
                invalid_shape()
            atoms = block.get_object("atom_site")
            fields = ("id", "type_symbol", "label_atom_id", "label_comp_id", "label_asym_id")
            axes = tuple("Cartn_" + axis for axis in "xyz")
            if atoms is None or atoms.row_count == 0 or not set(fields + axes).issubset(atoms.attribute_list):
                invalid_shape()
            for row in range(atoms.row_count):
                if any(atoms.get_value(key, row) in {"", ".", "?", None} for key in fields):
                    invalid_shape()
                if not all(math.isfinite(float(atoms.get_value(axis, row))) for axis in axes):
                    invalid_shape()
        elif format == "pdb":
            lines = content.splitlines()
            header = next((line for line in lines if line.startswith("HEADER")), None)
            if header is None or identity(header[62:66].strip()) != expected:
                invalid_shape()
            atoms = [line for line in lines if line.startswith(("ATOM  ", "HETATM"))]
            if not atoms or any(
                len(line) < 78
                or not line[6:11].strip()
                or not line[12:16].strip()
                or not line[17:20].strip()
                or not line[22:26].strip()
                or not line[76:78].strip()
                or not all(math.isfinite(float(line[start : start + 8])) for start in (30, 38, 46))
                for line in atoms
            ):
                invalid_shape()
            if assembly_id is not None and not re.search(
                rf"^REMARK 350 BIOMOLECULE:\s*{re.escape(assembly_id)}\s*$", content, re.MULTILINE
            ):
                invalid_shape()
        elif format == "xml":
            root = ElementTree.fromstring(content)
            if root.tag.rsplit("}", 1)[-1] != "datablock" or identity(root.get("datablockName")) != expected:
                invalid_shape()
            atoms = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "atom_site"]
            if not atoms:
                invalid_shape()
            for atom in atoms:
                values = {node.tag.rsplit("}", 1)[-1]: node.text for node in atom}
                if not atom.get("id") or any(
                    not values.get(key) or values[key] in {".", "?"}
                    for key in ("type_symbol", "label_atom_id", "label_comp_id", "label_asym_id")
                ):
                    invalid_shape()
                if not all(math.isfinite(float(values.get("Cartn_" + axis, "nan"))) for axis in "xyz"):
                    invalid_shape()
        else:
            invalid_shape()
    except (
        ValueError,
        TypeError,
        IndexError,
        KeyError,
        DefusedXmlException,
        ElementTree.ParseError,
        ResearchError,
        pdbx.PdbxError,
        pdbx.PdbxSyntaxError,
    ):
        invalid_shape()
    return {
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "content_utf8_bytes": len(content.encode()),
        "identity_checked": True,
        "coordinate_checks": "Entry container identity, required atom identity fields and finite XYZ values; assembly transforms and geometry are not independently verified.",
    }


def quality(value, requested):
    value = entry(value, requested)
    info, accession = value["rcsb_entry_info"], value.get("rcsb_accession_info", {})
    validation = {key: item for key, item in value.items() if key.startswith("pdbx_vrpt_")}
    released = accession.get("has_released_experimental_data")
    result = {
        "pdb_id": requested,
        "url": f"https://www.rcsb.org/structure/{requested}",
        "source_release": observed_release(value),
        "resolution": info.get("resolution_combined"),
        "resolution_units": "angstroms",
        "experimental_method": info.get("experimental_method"),
        "structure_determination_methodology": info["structure_determination_methodology"],
        "deposit_date": accession.get("deposit_date"),
        "release_date": accession.get("initial_release_date"),
        "released_experimental_data_available": None if released is None else released == "Y",
        "polymer_entity_count": info.get("polymer_entity_count"),
        "assembly_count": info.get("assembly_count"),
        "validation_summary": validation or None,
        "validation_status": "available" if validation else "unavailable",
        "source_revision": {
            key: accession.get(key) for key in ("major_revision", "minor_revision", "revision_date")
        },
        "method": "RCSB entry metadata and embedded wwPDB validation categories; no independent quality ranking.",
        "full_data": value,
    }
    if not validation:
        result.update(
            section_outcomes={"validation_summary": {"outcome": "unavailable"}},
            warnings=[
                "Embedded validation data are unavailable; retained entry metadata does not establish absence of structural issues."
            ],
        )
    return result
