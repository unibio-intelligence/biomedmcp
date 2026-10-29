"""Selected gnomAD GraphQL fields with explicit denominators and identity."""

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..errors import ResearchError
from ..runtime import digest
from .shapes import invalid_shape

URL = "https://gnomad.broadinstitute.org/api"
COUNTS = (
    "ac an homozygote_count hemizygote_count filters populations{id ac an homozygote_count hemizygote_count}"
)
POPULATION_QUERY = (
    "query($id:String!){variant(variantId:$id,dataset:gnomad_r4){variant_id reference_genome chrom pos ref alt "
    + " ".join(name + "{" + COUNTS + "}" for name in ("exome", "genome", "joint"))
    + "}}"
)
SOURCE_REVISION = "1975cd49436290ac47f7a28fa2747266c8f6f7aa"
CONSTRAINT_QUERY = "query($id:String!){gene(gene_id:$id,reference_genome:GRCh38){gene_id symbol ncbi_id reference_genome canonical_transcript_id mane_select_transcript{ensembl_id ensembl_version refseq_id refseq_version} gnomad_constraint{pli oe_lof_upper mis_z syn_z flags}}}"


def direct_population_identity(identifier, assembly):
    """An explicit GRCh38 SNV can be checked by gnomAD itself without an aggregator."""
    if assembly != "grch38":
        return None
    from .variants import genomic_identity

    identity = genomic_identity(identifier, assembly)
    if identity is None or len(identity["reference"]) != 1 or len(identity["alternate"]) != 1:
        return None
    return identity


class ScientificModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Counts(ScientificModel):
    ac: int | None = Field(ge=0, le=2147483647)
    an: int | None = Field(ge=0, le=2147483647)
    homozygote_count: int | None = Field(ge=0, le=2147483647)
    hemizygote_count: int | None = Field(ge=0, le=2147483647)

    @model_validator(mode="after")
    def consistent(self):
        known = 2 * (self.homozygote_count or 0) + (self.hemizygote_count or 0)
        if self.an is not None and known > self.an:
            raise ValueError("Genotype counts exceed denominator")
        if self.ac is not None:
            if self.an is not None and self.ac > self.an:
                raise ValueError("Allele count exceeds denominator")
            if known > self.ac:
                raise ValueError("Genotype counts exceed allele count")
        return self

    def frequency(self):
        return self.ac / self.an if self.ac is not None and self.an else None


class Population(Counts):
    id: str = Field(max_length=128)
    ac: int = Field(ge=0, le=2147483647)
    an: int = Field(ge=0, le=2147483647)
    homozygote_count: int = Field(ge=0, le=2147483647)


class Sequencing(Counts):
    filters: list[str] | None = Field(max_length=100)
    populations: list[Population] | None = Field(max_length=1000)

    @model_validator(mode="after")
    def groups(self):
        if self.populations is not None and any(
            (self.ac is not None and p.ac > self.ac) or (self.an is not None and p.an > self.an)
            for p in self.populations
        ):
            raise ValueError("Ancestry counts exceed parent")
        return self


class Variant(ScientificModel):
    variant_id: str = Field(min_length=1, max_length=512)
    reference_genome: str
    chrom: str
    pos: int = Field(gt=0, le=2147483647)
    ref: str = Field(pattern=r"^[ACGT]+$", max_length=200)
    alt: str = Field(pattern=r"^[ACGT]+$", max_length=200)
    exome: Sequencing | None
    genome: Sequencing | None
    joint: Sequencing | None


class FrequencyCounts(Counts):
    allele_frequency: float | None = Field(ge=0, le=1)
    frequency_unit: Literal["proportion"]
    denominator_unit: Literal["observed alleles"]
    missingness: Literal[
        "reported", "allele_count_not_supplied", "allele_number_not_supplied", "zero_allele_number"
    ]
    method: Literal["AC / AN when AC is supplied and AN > 0; otherwise unavailable."]
    input_locators: list[str] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def meaning(self):
        expected = (
            "allele_number_not_supplied"
            if self.an is None
            else "zero_allele_number"
            if self.an == 0
            else "allele_count_not_supplied"
            if self.ac is None
            else "reported"
        )
        if self.missingness != expected or self.allele_frequency != self.frequency():
            raise ValueError("Frequency and missingness must agree with their supplied allele counts")
        return self


class PopulationFrequency(FrequencyCounts):
    id: str = Field(max_length=128)
    id_status: Literal["reported", "missing", "ambiguous"]

    @model_validator(mode="after")
    def source_identity(self):
        if (not self.id and self.id_status != "missing") or (self.id and self.id_status == "missing"):
            raise ValueError("Population identity status must preserve the source identifier")
        return self


class SequencingFrequency(FrequencyCounts):
    filters: list[str] | None = Field(max_length=100)
    populations: list[PopulationFrequency] | None = Field(max_length=1000)


class PopulationVariant(Variant):
    exome: SequencingFrequency | None
    genome: SequencingFrequency | None
    joint: SequencingFrequency | None


class PopulationIdentity(ScientificModel):
    chromosome: str = Field(pattern=r"^(?:[1-9]|1\d|2[0-2]|X|Y)$")
    position: int = Field(gt=0, le=2147483647)
    reference: str = Field(pattern=r"^[ACGT]+$", max_length=200)
    alternate: str = Field(pattern=r"^[ACGT]+$", max_length=200)
    assembly: Literal["grch38"]


class VariantPopulationRecord(ScientificModel):
    record_type: Literal["variant_population"]
    assertion_type: Literal["descriptive_population_measurements"]
    source: Literal["gnomad"]
    species: Literal[9606]
    identity_namespace: Literal["GRCh38 chromosome-position-reference-alternate"]
    identity: PopulationIdentity
    transcript: None
    assembly: Literal["grch38"]
    variant: PopulationVariant | None
    release: None
    dataset_selector: Literal["gnomad_r4"]
    reproducibility: Literal["mutable_provider_alias"]
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_record_locator: Literal["/data/variant"]
    coverage_basis: Literal["Provider-reported allele numbers per modality and ancestry; not participants."]
    section_outcomes: dict[str, Literal["data", "partial", "unavailable"]]
    warnings: list[str]

    @model_validator(mode="after")
    def coherent(self):
        identity = self.identity
        if identity.reference == identity.alternate:
            raise ValueError("Reference and alternate alleles must differ")
        if self.variant is None:
            if self.section_outcomes != {"variant": "unavailable"}:
                raise ValueError("An unindexed allele must remain unavailable")
            selected = None
        else:
            node = self.variant
            variant_id = (
                f"{identity.chromosome}-{identity.position}-{identity.reference}-{identity.alternate}"
            )
            if (node.variant_id, node.reference_genome, node.chrom, node.pos, node.ref, node.alt) != (
                variant_id,
                "GRCh38",
                identity.chromosome,
                identity.position,
                identity.reference,
                identity.alternate,
            ):
                raise ValueError("Measurements must refer to the qualified allele")
            selected = node.model_dump(mode="json")
            outcomes = {}
            for name in ("exome", "genome", "joint"):
                branch = selected[name]
                if branch is None:
                    outcomes[name] = "unavailable"
                    continue
                outcomes[name] = (
                    "unavailable"
                    if branch["allele_frequency"] is None
                    else "partial"
                    if branch["filters"] is None
                    or branch["populations"] is None
                    or any(p["an"] == 0 or p["id_status"] != "reported" for p in branch["populations"])
                    else "data"
                )
                self._strip_measure(branch, f"/data/variant/{name}")
                groups = branch["populations"]
                if groups is not None:
                    identifiers = Counter(group["id"] for group in groups)
                    for index, group in enumerate(groups):
                        expected = "missing" if not group["id"] else "ambiguous" if identifiers[group["id"]] > 1 else "reported"
                        if group["id_status"] != expected:
                            raise ValueError("Population identity status must preserve missing or repeated source IDs")
                        self._strip_measure(group, f"/data/variant/{name}/populations/{index}")
                        group.pop("id_status")
            # Revalidate source arithmetic and ancestry subsets after removing
            # derived fields, rather than trusting a second descriptive copy.
            Variant.model_validate(selected)
            if self.section_outcomes != outcomes:
                raise ValueError("Outcomes must agree with available measurements")
        if self.source_record_sha256 != digest(selected):
            raise ValueError("Input hash must bind the selected source record before derivation")
        return self

    @staticmethod
    def _strip_measure(row, pointer):
        if row["input_locators"] != [f"{pointer}/ac", f"{pointer}/an"]:
            raise ValueError("Frequency inputs must locate their own AC and AN")
        for key in (
            "allele_frequency",
            "frequency_unit",
            "denominator_unit",
            "missingness",
            "method",
            "input_locators",
        ):
            row.pop(key)


def frequency_record(counts, pointer):
    return {
        "allele_frequency": counts.frequency(),
        "frequency_unit": "proportion",
        "denominator_unit": "observed alleles",
        "missingness": "allele_number_not_supplied"
        if counts.an is None
        else "zero_allele_number"
        if counts.an == 0
        else "allele_count_not_supplied"
        if counts.ac is None
        else "reported",
        "method": "AC / AN when AC is supplied and AN > 0; otherwise unavailable.",
        "input_locators": [f"{pointer}/ac", f"{pointer}/an"],
    }


def population_record(value):
    try:
        return VariantPopulationRecord.model_validate(value).model_dump(mode="json")
    except ValidationError:
        invalid_shape()


class ConstraintMetrics(ScientificModel):
    pli: float | None = Field(ge=0, le=1)
    oe_lof_upper: float | None = Field(ge=0)
    mis_z: float | None
    syn_z: float | None
    flags: list[str] | None = Field(max_length=100)


class ManeSelect(ScientificModel):
    ensembl_id: str = Field(pattern=r"^ENST\d{11}$")
    ensembl_version: str = Field(pattern=r"^\d+$")
    refseq_id: str = Field(pattern=r"^N[MR]_\d+$")
    refseq_version: str = Field(pattern=r"^\d+$")


class Gene(ScientificModel):
    gene_id: str = Field(pattern=r"^ENSG\d{11}$")
    symbol: str = Field(min_length=1, max_length=128)
    ncbi_id: str | None = Field(pattern=r"^\d+$")
    reference_genome: str
    canonical_transcript_id: str | None = Field(pattern=r"^ENST\d{11}(?:\.\d+)?$")
    mane_select_transcript: ManeSelect | None
    gnomad_constraint: ConstraintMetrics | None


def response(value, field, model):
    if (
        not isinstance(value, dict)
        or value.get("error")
        or value.get("errors")
        or not isinstance(value.get("data"), dict)
        or field not in value["data"]
    ):
        invalid_shape()
    node = value["data"][field]
    if node is None:
        return None
    try:
        return model.model_validate(node)
    except ValidationError:
        invalid_shape()


def lookup_identity(record):
    if not isinstance(record, dict):
        raise ResearchError("unresolved_identity", "Population evidence requires one qualified allele.")
    identity = record.get("identity")
    if not isinstance(identity, dict) or not identity.get("chromosome"):
        annotation = record.get("annotation")
        hg38 = annotation.get("hg38") if isinstance(annotation, dict) else None
        if isinstance(hg38, list):
            if len(hg38) != 1:
                raise ResearchError("ambiguous_identifier", "Population lookup requires one GRCh38 mapping.")
            hg38 = hg38[0]
        identifier = record.get("id")
        match = (
            re.fullmatch(r"chr([\dXY]+):g\.\d+([ACGT])>([ACGT])", identifier)
            if isinstance(identifier, str)
            else None
        )
        if not match or not isinstance(hg38, dict):
            raise ResearchError(
                "unresolved_identity", "Population evidence requires exact allele and GRCh38 coordinates."
            )
        identity = {
            "chromosome": match[1],
            "position": hg38.get("start"),
            "reference": match[2],
            "alternate": match[3],
            "assembly": "grch38",
        }
    if identity.get("assembly") != "grch38":
        raise ResearchError(
            "unsupported_assembly",
            "Direct gnomAD v4 retrieval requires GRCh38; no implicit lift-over is performed.",
        )
    if (
        not isinstance(identity.get("chromosome"), str)
        or identity["chromosome"] not in {str(i) for i in range(1, 23)} | {"X", "Y"}
        or type(identity.get("position")) is not int
        or not 1 <= identity["position"] <= 2147483647
        or not isinstance(identity.get("reference"), str)
        or not re.fullmatch(r"[ACGT]{1,200}", identity["reference"])
        or not isinstance(identity.get("alternate"), str)
        or not re.fullmatch(r"[ACGT]{1,200}", identity["alternate"])
        or identity["reference"] == identity["alternate"]
    ):
        raise ResearchError(
            "unresolved_identity", "Population evidence requires one valid GRCh38 allele identity."
        )
    return {key: identity[key] for key in ("chromosome", "position", "reference", "alternate", "assembly")}


async def population(http, record):
    identity = lookup_identity(record)
    variant_id = "-".join(str(identity[k]) for k in ("chromosome", "position", "reference", "alternate"))
    raw = await http.post(URL, {"query": POPULATION_QUERY, "variables": {"id": variant_id}})
    node = response(raw, "variant", Variant)
    result = {
        "record_type": "variant_population",
        "assertion_type": "descriptive_population_measurements",
        "source": "gnomad",
        "species": 9606,
        "identity_namespace": "GRCh38 chromosome-position-reference-alternate",
        "transcript": None,
        "source_record_sha256": digest(node.model_dump(mode="json") if node is not None else None),
        "source_record_locator": "/data/variant",
        "coverage_basis": "Provider-reported allele numbers per modality and ancestry; not participants.",
        "variant": None,
        "assembly": "grch38",
        "release": None,
        "dataset_selector": "gnomad_r4",
        "reproducibility": "mutable_provider_alias",
        "identity": identity,
        "section_outcomes": {},
        "warnings": [
            "Population evidence is descriptive; no clinical classification is inferred. Exome/genome counts must not be summed; joint values are provider supplied.",
            "gnomad_r4 is a mutable dataset selector, not an exact data-release pin.",
        ],
    }
    if node is None:
        result["section_outcomes"]["variant"] = "unavailable"
        result["warnings"].append(
            "No indexed variant record was supplied; population absence or a zero allele frequency cannot be inferred."
        )
        return population_record(result)
    if (node.variant_id, node.reference_genome, node.chrom, node.pos, node.ref, node.alt) != (
        variant_id,
        "GRCh38",
        identity["chromosome"],
        identity["position"],
        identity["reference"],
        identity["alternate"],
    ):
        raise ResearchError("identity_mismatch", "gnomAD returned a different allele or reference genome.")
    result["variant"] = node.model_dump(mode="json")
    for name in ("exome", "genome", "joint"):
        branch = getattr(node, name)
        if branch is None:
            result["section_outcomes"][name] = "unavailable"
            continue
        visible = result["variant"][name]
        visible.update(frequency_record(branch, f"/data/variant/{name}"))
        identifiers = Counter(group.id for group in branch.populations or [])
        for index, group in enumerate(branch.populations or []):
            visible["populations"][index]["id_status"] = (
                "missing" if not group.id else "ambiguous" if identifiers[group.id] > 1 else "reported"
            )
            visible["populations"][index].update(
                frequency_record(group, f"/data/variant/{name}/populations/{index}")
            )
        result["section_outcomes"][name] = (
            "unavailable"
            if branch.frequency() is None
            else "partial"
            if branch.filters is None
            or branch.populations is None
            or any(p.an == 0 or not p.id or identifiers[p.id] > 1 for p in branch.populations)
            else "data"
        )
    if any(value != "data" for value in result["section_outcomes"].values()):
        result["warnings"].append(
            "Missing modalities, denominators or ancestry measurements remain unknown; only AC=0 with AN>0 is measured zero."
        )
    return population_record(result)


async def constraint(http, identity):
    if (
        not isinstance(identity, dict)
        or identity.get("species") != 9606
        or not isinstance(identity.get("symbol"), str)
        or not identity["symbol"].strip()
    ):
        raise ResearchError(
            "unresolved_identity", "Gene constraint requires a qualified human gene identity."
        )
    ids = identity.get("ensembl_ids", [])
    if not isinstance(ids, list) or any(
        not isinstance(value, str) or not re.fullmatch(r"ENSG\d{11}", value) for value in ids
    ):
        raise ResearchError("unresolved_identity", "Gene constraint requires qualified Ensembl identifiers.")
    if len(ids) != 1:
        raise ResearchError(
            "ambiguous_identifier" if len(ids) > 1 else "unresolved_identity",
            "Gene constraint requires one qualified Ensembl gene identity.",
        )
    raw = await http.post(URL, {"query": CONSTRAINT_QUERY, "variables": {"id": ids[0]}})
    node = response(raw, "gene", Gene)
    result = {
        "gene": None,
        "assembly": "grch38",
        "release": None,
        "reproducibility": "time_dependent_gene_annotation",
        "qualified_identity": identity,
        "constraint_transcript": None,
        "section_outcomes": {},
        "warnings": [
            "The gene API exposes no exact constraint-release selector. Constraint metrics describe variation and do not establish clinical pathogenicity."
        ],
    }
    if node is None:
        result["section_outcomes"]["constraint"] = "unavailable"
        return result
    if (
        node.gene_id != ids[0]
        or node.symbol != identity["symbol"]
        or node.reference_genome != "GRCh38"
        or node.ncbi_id is not None
        and identity.get("entrez_id") is not None
        and node.ncbi_id != identity["entrez_id"]
    ):
        raise ResearchError(
            "identity_mismatch", "gnomAD constraint does not match the qualified gene/reference genome."
        )
    result["gene"] = node.model_dump(mode="json")
    if node.mane_select_transcript is not None:
        preferred = node.mane_select_transcript
        result["constraint_transcript"] = {
            "id": preferred.ensembl_id,
            "version": preferred.ensembl_version,
            "selection": "mane_select",
            "refseq_id": preferred.refseq_id,
            "refseq_version": preferred.refseq_version,
        }
    elif node.canonical_transcript_id is not None:
        parts = node.canonical_transcript_id.split(".")
        result["constraint_transcript"] = {
            "id": parts[0],
            "version": parts[1] if len(parts) == 2 else None,
            "selection": "canonical_fallback",
        }
    if result["constraint_transcript"] is not None:
        result["constraint_transcript"].update(
            attribution="inferred_from_dated_provider_annotation_policy", source_revision=SOURCE_REVISION
        )
        result["warnings"].append(
            "Constraint transcript association is inferred from the provider's dated preferred-transcript policy and returned annotations, not an explicit transcript field on the constraint record."
        )
    metrics = node.gnomad_constraint
    result["section_outcomes"]["constraint"] = (
        "unavailable"
        if metrics is None
        or all(getattr(metrics, field) is None for field in ("pli", "oe_lof_upper", "mis_z", "syn_z"))
        else "partial"
        if any(getattr(metrics, field) is None for field in ("pli", "oe_lof_upper", "mis_z", "syn_z"))
        or result["constraint_transcript"] is None
        or metrics.flags is None
        else "data"
    )
    if result["section_outcomes"]["constraint"] != "data":
        result["warnings"].append(
            "Missing constraint measurements or transcript attribution do not establish lack of constraint."
        )
    return result
