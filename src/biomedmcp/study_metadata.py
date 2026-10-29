"""Managed release metadata: installed files do not establish assay populations."""

import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ResearchError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
Text = Annotated[str, Field(min_length=1, max_length=512, pattern=r"\S")]


def public_locator(value):
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Study attribution requires a public HTTP(S) locator")


class ReleaseMetadata(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: Identifier
    enabled: bool = Field(json_schema_extra={"const": True})
    release: Text
    source_url: Text
    sha256: Digest
    files: dict[Text, Digest] = Field(min_length=1, max_length=10000)
    assays: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def input_meaning(self):
        if self.enabled is not True:
            raise ValueError("Verified release metadata requires explicit enablement")
        public_locator(self.source_url)
        for declaration in self.assays.values():
            if "units" in declaration and (
                not isinstance(declaration["units"], str)
                or not declaration["units"].strip()
                or len(declaration["units"]) > 512
            ):
                raise ValueError("Declared units must be nonempty source strings")
        return self


def manifest_entries(raw):
    """Validate metadata before truth testing flags or touching enabled members."""
    try:
        if len(raw) > 1_000_000:
            raise ValueError("Study metadata budget exceeded")
        document = json.loads(raw)
        entries = document["studies"]
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValueError("Invalid study inventory")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or type(entry.get("enabled", False)) is not bool:
                raise ValueError("Invalid study enable flag")
            if not entry.get("enabled", False):
                continue
            ReleaseMetadata.model_validate(entry)
            if entry["id"] in seen:
                raise ValueError("Duplicate enabled study identity")
            seen.add(entry["id"])
        return entries
    except (ValueError, KeyError, TypeError, ValidationError):
        raise ResearchError("invalid_study_manifest", "Study release metadata violates its contract.") from None


class InstalledAssay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    available: bool
    file: Text
    sha256: Digest | None
    units: Text
    units_basis: Literal["manifest declaration", "managed cBioPortal file format"]
    sample_coverage: Literal["finite values per gene", "release-declared assay coverage"]
    gene_coverage: Literal["verified matrix rows", "release-declared assay coverage"]

    @model_validator(mode="after")
    def file_availability(self):
        if self.available != (self.sha256 is not None):
            raise ValueError("Availability must describe a checksummed installed file")
        return self


class StudyMetadataRecord(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    record_type: Literal["study_metadata"]
    assertion_type: Literal["verified_installed_release_metadata"]
    id: Identifier
    enabled: bool = Field(json_schema_extra={"const": True})
    release: Text
    source_url: Text
    sha256: Digest
    metadata_sha256: Digest
    identity_namespace: Literal["managed_public_study_release"]
    identity_scope: Literal["Study ID and release within the installed checksummed registry."]
    sample_count: None
    patient_count: None
    count_missingness: Literal["not_calculated_by_metadata_discovery"]
    interpretation: Literal[
        "Installed files do not establish measured-negative results, sample counts or complete assay coverage."
    ]
    assays: dict[Literal["mutations", "cna", "expression", "sv"], InstalledAssay]

    @model_validator(mode="after")
    def assay_inventory(self):
        from .studies import ASSAY_FILES

        if self.enabled is not True:
            raise ValueError("An installed release must be enabled")
        public_locator(self.source_url)
        if set(self.assays) != set(ASSAY_FILES):
            raise ValueError("All supported assay availability states must remain explicit")
        for kind, assay in self.assays.items():
            matrix = kind in {"cna", "expression"}
            if (
                assay.file != ASSAY_FILES[kind][0]
                or assay.sample_coverage != ("finite values per gene" if matrix else "release-declared assay coverage")
                or assay.gene_coverage != ("verified matrix rows" if matrix else "release-declared assay coverage")
            ):
                raise ValueError("Assay semantics must preserve their selected file and coverage basis")
        return self


def study_metadata_record(release):
    try:
        return StudyMetadataRecord.model_validate(
            {
                **release,
                "record_type": "study_metadata",
                "assertion_type": "verified_installed_release_metadata",
                "identity_namespace": "managed_public_study_release",
                "identity_scope": "Study ID and release within the installed checksummed registry.",
                "sample_count": None,
                "patient_count": None,
                "count_missingness": "not_calculated_by_metadata_discovery",
                "interpretation": "Installed files do not establish measured-negative results, sample counts or complete assay coverage.",
            }
        ).model_dump(mode="json")
    except ValidationError:
        raise ResearchError("invalid_study_manifest", "Verified study metadata violates its record contract.") from None
