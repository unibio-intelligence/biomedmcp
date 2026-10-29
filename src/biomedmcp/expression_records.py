"""GTEx gene expression assertions without invented cohort denominators."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .errors import ResearchError
from .runtime import digest

Value = (
    Annotated[int, Field(strict=True, ge=0)] | Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
)
Count = Annotated[int, Field(strict=True, ge=0)]


class ExpressionGeneIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    gencode_id: str = Field(pattern=r"^ENSG\d{11}\.\d+(?:_PAR_Y)?$")
    dataset_id: Literal["gtex_v8", "gtex_v10"]
    gencode_version: Literal["v26", "v39"]
    genome_build: Literal["GRCh38/hg38"]

    @model_validator(mode="after")
    def release(self):
        from gtex_mcp.identity import release_parameters

        if release_parameters(self.dataset_id)["gencodeVersion"] != self.gencode_version:
            raise ValueError("Gene reference annotation must match the requested dataset release")
        return self


class ExpressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint: Literal["/expression/medianGeneExpression", "/expression/geneExpression"]
    page: Count
    row_index: Count
    record_pointer: str
    measurement_pointer: str
    units_pointer: str


class ExpressionRecord(BaseModel):
    # Original provider fields and independent coding remain available.
    model_config = ConfigDict(extra="allow", strict=True, allow_inf_nan=False)
    record_type: Literal["expression"]
    source: Literal["gtex"]
    species: Literal[9606]
    identity_namespace: Literal["gencode_gene"]
    gene_identity: ExpressionGeneIdentity
    transcript: None
    tissue_namespace: Literal["gtex_tissue_site_detail"]
    source_release: Literal["gtex_v8", "gtex_v10"]
    participant_count: None
    missing_measurement_count: None
    measurement_missingness: Literal["reported"]
    coverage_basis: Literal[
        "Participant/assay population and missing measurements are not supplied by this endpoint."
    ]
    ontology_interpretation: Literal[
        "Retain the independent provider ontology code; no tissue-to-ontology equivalence is inferred."
    ]
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_locator: ExpressionInput
    gencodeId: str = Field(pattern=r"^ENSG\d{11}\.\d+(?:_PAR_Y)?$")
    geneSymbol: str = Field(min_length=1, max_length=128)
    tissueSiteDetailId: str = Field(min_length=1, max_length=128)
    ontologyId: str = Field(min_length=1, max_length=128)
    datasetId: Literal["gtex_v8", "gtex_v10"]
    unit: Literal["TPM", "read count", "log(CP10K)"]

    @model_validator(mode="after")
    def meaning(self):
        if self.gencodeId != self.gene_identity.gencode_id or self.datasetId != self.gene_identity.dataset_id:
            raise ValueError("Expression must refer to the resolved gene and dataset")
        if self.source_release != self.datasetId:
            raise ValueError("The release label must preserve the supplied dataset identity")
        median = self.assertion_type == "provider_median_expression"
        endpoint = "/expression/medianGeneExpression" if median else "/expression/geneExpression"
        field = "median" if median else "data"
        locator = self.input_locator
        pointer = f"/data/{locator.row_index}"
        if (locator.endpoint, locator.record_pointer, locator.measurement_pointer, locator.units_pointer) != (
            endpoint,
            pointer,
            f"{pointer}/{field}",
            f"{pointer}/unit",
        ):
            raise ValueError("Expression input pointers must locate their own provider row and measure")
        if not median and self.provided_value_count != len(self.data):
            raise ValueError("Supplied value count must agree with the source series")
        raw = self.model_dump(mode="json")
        for key in NORMALIZED_FIELDS:
            raw.pop(key, None)
        if self.source_record_sha256 != digest(raw):
            raise ValueError("The input hash must bind the source record before annotation")
        return self


class MedianExpressionRecord(ExpressionRecord):
    assertion_type: Literal["provider_median_expression"]
    median: Value
    provided_value_count: None
    method: Literal["Provider-reported tissue median; no local summary calculation."]
    count_method: None

    @model_validator(mode="after")
    def no_series(self):
        if "data" in (self.model_extra or {}):
            raise ValueError("A tissue median cannot silently become an individual-value series")
        return self


class ValuesExpressionRecord(ExpressionRecord):
    assertion_type: Literal["provider_expression_values"]
    data: list[Value] = Field(min_length=1)
    provided_value_count: Count
    method: Literal["Retain provider-reported expression values without transformation or imputation."]
    count_method: Literal["len(data); counts supplied values, not participants."]

    @model_validator(mode="after")
    def no_median(self):
        if "median" in (self.model_extra or {}):
            raise ValueError("A value series cannot silently become a provider tissue median")
        return self


EXPRESSION_RECORDS = TypeAdapter(
    Annotated[MedianExpressionRecord | ValuesExpressionRecord, Field(discriminator="assertion_type")]
)
NORMALIZED_FIELDS = {
    "record_type",
    "source",
    "species",
    "identity_namespace",
    "gene_identity",
    "transcript",
    "tissue_namespace",
    "source_release",
    "participant_count",
    "missing_measurement_count",
    "measurement_missingness",
    "coverage_basis",
    "ontology_interpretation",
    "source_record_sha256",
    "input_locator",
    "assertion_type",
    "provided_value_count",
    "method",
    "count_method",
}


def expression_window(window, query_type):
    """Annotate qualified acquired rows; provider continuation remains intact."""
    try:
        median = query_type == "gene_median"
        if query_type not in {"gene_median", "gene_tissue"}:
            raise ValueError("Unsupported gene expression family")
        gene = ExpressionGeneIdentity.model_validate(window["gene_identity"])
        page = window["paging_info"]["page"]
        rows = []
        for index, row in enumerate(window["data"]):
            if not isinstance(row, dict) or NORMALIZED_FIELDS & set(row):
                raise ValueError("Provider metadata cannot supply service scientific annotations")
            pointer = f"/data/{index}"
            rows.append(
                EXPRESSION_RECORDS.validate_python(
                    {
                        **row,
                        "record_type": "expression",
                        "source": "gtex",
                        "species": 9606,
                        "identity_namespace": "gencode_gene",
                        "gene_identity": gene.model_dump(mode="json"),
                        "transcript": None,
                        "tissue_namespace": "gtex_tissue_site_detail",
                        "source_release": row["datasetId"],
                        "participant_count": None,
                        "missing_measurement_count": None,
                        "measurement_missingness": "reported",
                        "coverage_basis": "Participant/assay population and missing measurements are not supplied by this endpoint.",
                        "ontology_interpretation": "Retain the independent provider ontology code; no tissue-to-ontology equivalence is inferred.",
                        "source_record_sha256": digest(row),
                        "input_locator": {
                            "endpoint": "/expression/medianGeneExpression"
                            if median
                            else "/expression/geneExpression",
                            "page": page,
                            "row_index": index,
                            "record_pointer": pointer,
                            "measurement_pointer": f"{pointer}/{'median' if median else 'data'}",
                            "units_pointer": f"{pointer}/unit",
                        },
                        "assertion_type": "provider_median_expression"
                        if median
                        else "provider_expression_values",
                        "provided_value_count": None if median else len(row["data"]),
                        "method": "Provider-reported tissue median; no local summary calculation."
                        if median
                        else "Retain provider-reported expression values without transformation or imputation.",
                        "count_method": None
                        if median
                        else "len(data); counts supplied values, not participants.",
                    }
                ).model_dump(mode="json")
            )
        return {**window, "data": rows}
    except (ValidationError, ValueError, TypeError, KeyError):
        raise ResearchError(
            "invalid_source_response", "GTEx expression violates its scientific record contract."
        ) from None
