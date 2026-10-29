"""GTEx QTL assertions with source inputs, separate probabilities and qualified joins."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .errors import ResearchError
from .expression_records import ExpressionGeneIdentity
from .runtime import digest

Number = Annotated[int, Field(strict=True)] | Annotated[float, Field(strict=True, allow_inf_nan=False)]
Probability = (
    Annotated[int, Field(strict=True, ge=0, le=1)]
    | Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
)
Nonnegative = (
    Annotated[int, Field(strict=True, ge=0)] | Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
)
Count = Annotated[int, Field(strict=True, ge=0)]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
AlleleIdentity = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Release = Literal["gtex_v8", "gtex_v10"]
ASSERTIONS = {
    "provider_single_tissue_eqtl": ("/association/singleTissueEqtl", "eqtl"),
    "provider_single_tissue_sqtl": ("/association/singleTissueSqtl", "sqtl"),
    "provider_eqtl_gene_summary": ("/association/egene", "eqtl"),
    "provider_sqtl_gene_summary": ("/association/sgene", "sqtl"),
    "provider_metasoft_eqtl": ("/association/metasoft", "eqtl"),
    "provider_dynamic_eqtl": ("/association/dyneqtl", "eqtl"),
    "provider_dynamic_sqtl": ("/association/dynsqtl", "sqtl"),
}
METHODS = {
    "provider_single_tissue_eqtl": "Retain provider precomputed single-tissue eQTL probability and normalized effect; no local inference.",
    "provider_single_tissue_sqtl": "Retain provider precomputed single-tissue sQTL phenotype, probability and normalized effect; no local inference.",
    "provider_eqtl_gene_summary": "Retain provider eGene nominal/empirical probabilities, threshold and q-value as distinct quantities.",
    "provider_sqtl_gene_summary": "Retain provider sGene phenotype/count and nominal/empirical probabilities, threshold and q-value as distinct quantities.",
    "provider_metasoft_eqtl": "Retain provider cross-tissue MetaSoft probability and independent tissue posterior probabilities, probabilities, slopes and standard errors.",
    "provider_dynamic_eqtl": "Retain provider-calculated gene/variant/tissue association and paired measurements without local recomputation or imputation.",
    "provider_dynamic_sqtl": "Retain provider-calculated intron/variant/tissue association and paired measurements after a source-qualified gene/intron join.",
}
MEASURES = {
    "provider_single_tissue_eqtl": {"pValue", "nes"},
    "provider_single_tissue_sqtl": {"pValue", "nes"},
    "provider_eqtl_gene_summary": {
        "pValue",
        "empiricalPValue",
        "pValueThreshold",
        "qValue",
        "log2AllelicFoldChange",
    },
    "provider_sqtl_gene_summary": {"pValue", "empiricalPValue", "pValueThreshold", "qValue", "nPhenotypes"},
    "provider_metasoft_eqtl": {"metaP", "tissues"},
    "provider_dynamic_eqtl": {
        "data",
        "genotypes",
        "hetCount",
        "homoAltCount",
        "homoRefCount",
        "maf",
        "nes",
        "error",
        "pValue",
        "tStatistic",
        "pValueThreshold",
    },
    "provider_dynamic_sqtl": {
        "data",
        "genotypes",
        "hetCount",
        "homoAltCount",
        "homoRefCount",
        "maf",
        "nes",
        "error",
        "pValue",
        "tStatistic",
        "pValueThreshold",
    },
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QTLVariantIdentity(StrictModel):
    variant_id: AlleleIdentity
    snp_id: Annotated[str, Field(pattern=r"^rs[1-9][0-9]*$")] | None
    dataset_id: Release
    genome_build: Literal["GRCh38/hg38"]
    chromosome: Identity
    position: Annotated[int, Field(strict=True, ge=1)]
    reference: AlleleIdentity
    alternate: AlleleIdentity

    @model_validator(mode="after")
    def allele(self):
        from gtex_mcp.identity import VARIANT_ID

        match = VARIANT_ID.fullmatch(self.variant_id)
        if (
            not match
            or (match[1], int(match[2]), match[3], match[4])
            != (self.chromosome, self.position, self.reference, self.alternate)
            or self.reference == self.alternate
        ):
            raise ValueError("QTL allele must retain its explicit GTEx GRCh38 identity")
        return self


class QTLInput(StrictModel):
    endpoint: Literal[
        "/association/singleTissueEqtl",
        "/association/singleTissueSqtl",
        "/association/egene",
        "/association/sgene",
        "/association/metasoft",
        "/association/dyneqtl",
        "/association/dynsqtl",
    ]
    page: Count | None
    row_index: Count | None
    record_pointer: str
    response_sha256: Digest
    measurements: dict[str, str]


class QTLRecord(BaseModel):
    # Source fields remain independent assertions, including optional/null metadata.
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    source: Literal["gtex"]
    species: Literal[9606]
    qtl_type: Literal["eqtl", "sqtl"]
    identity_namespace: Literal["gencode_gene"]
    gene_identity: ExpressionGeneIdentity
    identity_basis: Literal["resolved_release_reference", "provider_reported_gene"]
    variant_identity: QTLVariantIdentity | None
    allele_validation: Literal[
        "GTEx identifier/reference-row consistency only; no independent FASTA or allele-normalization check."
    ]
    transcript: None
    phenotype_namespace: Literal["gtex_splicing_phenotype"] | None
    tissue_namespace: Literal["gtex_tissue_site_detail"]
    tissue_scope: Literal["single_reported_tissue", "provider_cross_tissue"]
    source_release: Release
    source_release_basis: Literal["provider_row", "acquisition_parameter"]
    participant_count: None
    missing_measurement_count: None
    coverage_basis: Literal[
        "Record and paired-value counts do not identify unique participants, assay population or missing measurements."
    ]
    effect_allele: None
    measurement_units: None
    interpretation: Literal[
        "Provider associations and normalized effects are not causal evidence, clinical effects, fold changes or participant denominators."
    ]
    source_record_sha256: Digest
    input_locator: QTLInput
    method: str = Field(min_length=1)

    @model_validator(mode="after")
    def meaning(self):
        endpoint, qtl = ASSERTIONS[self.assertion_type]
        dynamic = self.assertion_type.startswith("provider_dynamic_")
        summary = self.assertion_type.endswith("gene_summary")
        if (
            self.qtl_type != qtl
            or self.method != METHODS[self.assertion_type]
            or self.gene_identity.dataset_id != self.source_release
            or self.identity_basis != ("provider_reported_gene" if summary else "resolved_release_reference")
            or self.phenotype_namespace != ("gtex_splicing_phenotype" if qtl == "sqtl" else None)
            or self.tissue_scope
            != (
                "provider_cross_tissue"
                if self.assertion_type == "provider_metasoft_eqtl"
                else "single_reported_tissue"
            )
        ):
            raise ValueError("QTL method, identity qualification, phenotype and tissue scope must agree")
        raw = self.model_dump(mode="json", exclude_unset=True)
        for key in NORMALIZED_FIELDS:
            raw.pop(key, None)
        if self.source_record_sha256 != digest(raw):
            raise ValueError("QTL input hash must bind unchanged provider fields")
        if self.source_release_basis != ("provider_row" if "datasetId" in raw else "acquisition_parameter"):
            raise ValueError("QTL release must distinguish provider assertion from acquisition scope")
        if raw.get("gencodeId", self.gene_identity.gencode_id) != self.gene_identity.gencode_id:
            raise ValueError("QTL must preserve its resolved versioned gene")
        if raw.get("datasetId", self.source_release) != self.source_release:
            raise ValueError("QTL must preserve its requested dataset release")
        if summary != (self.variant_identity is None):
            raise ValueError("A gene summary cannot invent a variant; variant associations require identity")
        if self.variant_identity is not None:
            variant = self.variant_identity
            if (
                variant.dataset_id != self.source_release
                or raw["variantId"] != variant.variant_id
                or raw.get("pos", variant.position) != variant.position
                or raw.get("chromosome", variant.chromosome) != variant.chromosome
            ):
                raise ValueError("QTL source coordinates and qualified allele must agree")
        locator = self.input_locator
        if dynamic:
            if locator.page is not None or locator.row_index is not None:
                raise ValueError("Dynamic QTL is one provider calculation, not a provider page")
            pointer = ""
            if locator.response_sha256 != self.source_record_sha256:
                raise ValueError("Dynamic response and source record must identify the same calculation")
        else:
            if locator.page is None or locator.row_index is None:
                raise ValueError("Paginated QTL inputs must locate the original provider row")
            pointer = f"/data/{locator.row_index}"
        measures = {f: f"{pointer}/{f}" for f in MEASURES[self.assertion_type] if f in raw}
        if (locator.endpoint, locator.record_pointer, locator.measurements) != (endpoint, pointer, measures):
            raise ValueError("QTL input pointers must identify their own unchanged source quantities")
        return self


class SingleTissueRecord(QTLRecord):
    record_type: Literal["qtl_association"]
    gencodeId: Identity
    geneSymbol: Identity
    geneSymbolUpper: Identity
    datasetId: Release
    tissueSiteDetailId: Identity
    ontologyId: Identity
    pValue: Probability
    nes: Number
    pos: Annotated[int, Field(strict=True, ge=1)]
    variantId: AlleleIdentity
    chromosome: Identity


class SingleTissueEqtlRecord(SingleTissueRecord):
    assertion_type: Literal["provider_single_tissue_eqtl"]


class SingleTissueSqtlRecord(SingleTissueRecord):
    assertion_type: Literal["provider_single_tissue_sqtl"]
    phenotypeId: Identity


class GeneSummary(QTLRecord):
    record_type: Literal["qtl_gene_summary"]
    gencodeId: Identity
    geneSymbol: Identity
    datasetId: Release
    tissueSiteDetailId: Identity
    ontologyId: Identity
    pValue: Probability
    empiricalPValue: Probability
    pValueThreshold: Probability
    qValue: Probability


class EqtlGeneSummary(GeneSummary):
    assertion_type: Literal["provider_eqtl_gene_summary"]
    log2AllelicFoldChange: Number | None = None


class SqtlGeneSummary(GeneSummary):
    assertion_type: Literal["provider_sqtl_gene_summary"]
    phenotypeId: Identity
    nPhenotypes: Count


class TissueMetasoft(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    mValue: Probability | None = None
    pValue: Probability | None = None
    se: Nonnegative | None = None
    nes: Number | None = None


class MetasoftRecord(QTLRecord):
    record_type: Literal["qtl_metasoft"]
    assertion_type: Literal["provider_metasoft_eqtl"]
    gencodeId: Identity
    datasetId: Release
    variantId: AlleleIdentity
    metaP: Probability
    tissues: dict[Identity, TissueMetasoft]
    probability_interpretation: Literal[
        "Tissue mValue is a provider posterior probability; tissue pValue and metaP are distinct quantities. Missing tissue fields are not zero or absence of effect."
    ]


class DynamicRecord(QTLRecord):
    record_type: Literal["qtl_dynamic"]
    data: list[Number] = Field(min_length=1)
    genotypes: list[Annotated[int, Field(strict=True, ge=0, le=2)]] = Field(min_length=1)
    paired_measurement_count: Count
    paired_measurement_method: Literal[
        "len(data) == len(genotypes); retain aligned provider array positions."
    ]
    genotype_coding: Literal[
        "Provider categories 0/1/2 and homoRef/het/homoAlt counts; no retained participant IDs or cross-record array joins."
    ]
    error: Nonnegative
    uncertainty_measure: Literal["provider_standard_error"]
    hetCount: Count
    homoAltCount: Count
    homoRefCount: Count
    maf: Probability
    frequency_interpretation: Literal[
        "Retain provider-reported maf; eligible-sample scope and rounding are not supplied; not recomputed from genotypes."
    ]
    nes: Number
    pValue: Probability
    pValueThreshold: Probability | None = None
    tStatistic: Number
    tissueSiteDetailId: Identity
    variantId: AlleleIdentity

    @model_validator(mode="after")
    def paired(self):
        if (
            self.paired_measurement_count != len(self.data)
            or len(self.data) != len(self.genotypes)
            or any(
                count != self.genotypes.count(category)
                for category, count in ((0, self.homoRefCount), (1, self.hetCount), (2, self.homoAltCount))
            )
        ):
            raise ValueError("Dynamic QTL genotype counts must partition paired measurements")
        return self


class DynamicEqtlRecord(DynamicRecord):
    assertion_type: Literal["provider_dynamic_eqtl"]
    gencodeId: Identity
    geneSymbol: Identity
    data: list[Nonnegative] = Field(min_length=1)
    phenotype_qualification: None


class DynamicSqtlRecord(DynamicRecord):
    assertion_type: Literal["provider_dynamic_sqtl"]
    phenotypeId: Identity
    pValueThreshold: Probability
    phenotype_qualification: SingleTissueSqtlRecord

    @model_validator(mode="after")
    def joined_phenotype(self):
        join = self.phenotype_qualification
        if (
            join.gene_identity != self.gene_identity
            or join.variant_identity.variant_id != self.variant_identity.variant_id
            or join.source_release != self.source_release
            or join.phenotypeId != self.phenotypeId
            or join.tissueSiteDetailId != self.tissueSiteDetailId
        ):
            raise ValueError("Dynamic sQTL must retain its own qualified gene/intron/variant/tissue join")
        return self


QTL_RECORDS = TypeAdapter(
    Annotated[
        SingleTissueEqtlRecord
        | SingleTissueSqtlRecord
        | EqtlGeneSummary
        | SqtlGeneSummary
        | MetasoftRecord
        | DynamicEqtlRecord
        | DynamicSqtlRecord,
        Field(discriminator="assertion_type"),
    ]
)
PUBLIC_QTL_RECORDS = TypeAdapter(
    Annotated[
        SingleTissueEqtlRecord
        | SingleTissueSqtlRecord
        | MetasoftRecord
        | DynamicEqtlRecord
        | DynamicSqtlRecord,
        Field(discriminator="assertion_type"),
    ]
)
NORMALIZED_FIELDS = set(QTLRecord.model_fields) | {
    "record_type",
    "assertion_type",
    "paired_measurement_count",
    "paired_measurement_method",
    "genotype_coding",
    "uncertainty_measure",
    "frequency_interpretation",
    "phenotype_qualification",
    "probability_interpretation",
}


def gene_identity(identifier, dataset):
    from gtex_mcp.identity import GENOME_BUILD, release_parameters

    return {
        "gencode_id": identifier,
        "dataset_id": dataset,
        "gencode_version": release_parameters(dataset)["gencodeVersion"],
        "genome_build": GENOME_BUILD,
    }


def row_variant(identifier, dataset):
    from gtex_mcp.identity import GENOME_BUILD, VARIANT_ID

    match = VARIANT_ID.fullmatch(identifier)
    if not match:
        raise ValueError("No qualified GTEx allele")
    return {
        "variant_id": identifier,
        "snp_id": None,
        "dataset_id": dataset,
        "genome_build": GENOME_BUILD,
        "chromosome": match[1],
        "position": int(match[2]),
        "reference": match[3],
        "alternate": match[4],
    }


def qtl_record(
    raw,
    *,
    qtl_type,
    mode,
    dataset,
    gene=None,
    variant=None,
    tissue=None,
    page=None,
    row_index=None,
    response_sha256=None,
    phenotype_qualification=None,
):
    """Bind a row before filtering; retain the actual source page/index and joined input."""
    try:
        if not isinstance(raw, dict) or NORMALIZED_FIELDS & set(raw):
            raise ValueError("Provider cannot supply service QTL annotations")
        if mode == "gene_associations":
            assertion, kind = f"provider_single_tissue_{qtl_type}", "qtl_association"
        elif mode == "genes_list":
            assertion, kind = f"provider_{qtl_type}_gene_summary", "qtl_gene_summary"
        elif mode == "metasoft" and qtl_type == "eqtl":
            assertion, kind = "provider_metasoft_eqtl", "qtl_metasoft"
        elif mode == "dynamic":
            assertion, kind = f"provider_dynamic_{qtl_type}", "qtl_dynamic"
        else:
            raise ValueError("Unsupported QTL assertion")
        if tissue is not None and raw.get("tissueSiteDetailId", tissue) != tissue:
            raise ValueError("QTL must retain its requested tissue")
        summary, dynamic = mode == "genes_list", mode == "dynamic"
        identity = gene_identity(raw["gencodeId"], dataset) if summary else gene
        allele = None if summary else variant or row_variant(raw["variantId"], dataset)
        pointer = "" if dynamic else f"/data/{row_index}"
        extra = {}
        if dynamic:
            extra = {
                "paired_measurement_count": len(raw["data"]),
                "paired_measurement_method": "len(data) == len(genotypes); retain aligned provider array positions.",
                "genotype_coding": "Provider categories 0/1/2 and homoRef/het/homoAlt counts; no retained participant IDs or cross-record array joins.",
                "uncertainty_measure": "provider_standard_error",
                "frequency_interpretation": "Retain provider-reported maf; eligible-sample scope and rounding are not supplied; not recomputed from genotypes.",
                "phenotype_qualification": phenotype_qualification,
            }
        if mode == "metasoft":
            extra["probability_interpretation"] = (
                "Tissue mValue is a provider posterior probability; tissue pValue and metaP are distinct quantities. Missing tissue fields are not zero or absence of effect."
            )
        value = {
            **raw,
            **extra,
            "record_type": kind,
            "assertion_type": assertion,
            "source": "gtex",
            "species": 9606,
            "qtl_type": qtl_type,
            "identity_namespace": "gencode_gene",
            "gene_identity": identity,
            "identity_basis": "provider_reported_gene" if summary else "resolved_release_reference",
            "variant_identity": allele,
            "allele_validation": "GTEx identifier/reference-row consistency only; no independent FASTA or allele-normalization check.",
            "transcript": None,
            "phenotype_namespace": "gtex_splicing_phenotype" if qtl_type == "sqtl" else None,
            "tissue_namespace": "gtex_tissue_site_detail",
            "tissue_scope": "provider_cross_tissue" if mode == "metasoft" else "single_reported_tissue",
            "source_release": dataset,
            "source_release_basis": "provider_row" if "datasetId" in raw else "acquisition_parameter",
            "participant_count": None,
            "missing_measurement_count": None,
            "coverage_basis": "Record and paired-value counts do not identify unique participants, assay population or missing measurements.",
            "effect_allele": None,
            "measurement_units": None,
            "interpretation": "Provider associations and normalized effects are not causal evidence, clinical effects, fold changes or participant denominators.",
            "source_record_sha256": digest(raw),
            "input_locator": {
                "endpoint": ASSERTIONS[assertion][0],
                "page": page,
                "row_index": row_index,
                "record_pointer": pointer,
                "response_sha256": response_sha256 or digest(raw),
                "measurements": {f: f"{pointer}/{f}" for f in MEASURES[assertion] if f in raw},
            },
            "method": METHODS[assertion],
        }
        return QTL_RECORDS.validate_python(value).model_dump(mode="json", exclude_unset=True)
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
        raise ResearchError(
            "invalid_source_response", "GTEx QTL violates its scientific record contract."
        ) from None
