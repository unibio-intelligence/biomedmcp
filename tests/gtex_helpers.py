"""Synthetic GTEx records with explicit scientific identity and measurements."""

GENCODE = "ENSG00000157764.14"
VARIANT = "chr7_140753336_A_T_b38"


def expression_source_rows(rows):
    """Validate annotations and retain exact original provider field assertions."""
    from biomedmcp.expression_records import EXPRESSION_RECORDS, NORMALIZED_FIELDS

    values = []
    for row in rows:
        EXPRESSION_RECORDS.validate_python(row)
        values.append({key: value for key, value in row.items() if key not in NORMALIZED_FIELDS})
    return values


def qtl_source_rows(rows):
    """Validate scientific annotations, then compare the unchanged provider assertions."""
    from biomedmcp.qtl_records import NORMALIZED_FIELDS, QTL_RECORDS

    values = []
    for row in rows:
        QTL_RECORDS.validate_python(row)
        values.append({key: value for key, value in row.items() if key not in NORMALIZED_FIELDS})
    return values


def page(records, *, total=None, index=0, size=25):
    total = len(records) if total is None else total
    return {
        "data": records,
        "paging_info": {
            "numberOfPages": (total + size - 1) // size,
            "page": index,
            "maxItemsPerPage": size,
            "totalNumberOfItems": total,
        },
    }


def gene(symbol="BRAF", identifier=GENCODE):
    return {
        "chromosome": "chr7",
        "dataSource": "GENCODE",
        "start": 100,
        "end": 200,
        "gencodeId": identifier,
        "gencodeVersion": "v39",
        "geneStatus": "KNOWN",
        "geneSymbol": symbol,
        "geneSymbolUpper": symbol.upper(),
        "geneType": "protein_coding",
        "genomeBuild": "GRCh38/hg38",
        "strand": "+",
        "tss": 100,
    }


def expression(symbol="BRAF", identifier=GENCODE, tissue="Thyroid", *, detailed=False):
    return {
        "gencodeId": identifier,
        "geneSymbol": symbol,
        "datasetId": "gtex_v10",
        "tissueSiteDetailId": tissue,
        "ontologyId": "UBERON:0008367" if tissue == "Breast_Mammary_Tissue" else "UBERON:0002046",
        "unit": "TPM",
        **({"data": [0.0, 1.5]} if detailed else {"median": 1.5}),
    }


def association(symbol="BRAF", identifier=GENCODE, tissue="Thyroid", *, splicing=False):
    return {
        "gencodeId": identifier,
        "geneSymbol": symbol,
        "geneSymbolUpper": symbol.upper(),
        "datasetId": "gtex_v10",
        "tissueSiteDetailId": tissue,
        "ontologyId": "UBERON:0008367" if tissue == "Breast_Mammary_Tissue" else "UBERON:0002046",
        "pValue": 0.01,
        "nes": -0.5,
        "pos": 140753336,
        "variantId": VARIANT,
        "chromosome": "chr7",
        **({"phenotypeId": "chr7:100:200:clu_1"} if splicing else {}),
    }


def tissue():
    summary = {"totalCount": 0, "female": {"count": 0}, "male": {"count": 0}}
    return {
        "tissueSiteDetailId": "Breast_Mammary_Tissue",
        "colorHex": "#000000",
        "colorRgb": "0,0,0",
        "datasetId": "gtex_v10",
        "hasEGenes": True,
        "hasSGenes": True,
        "mappedInHubmap": False,
        "eqtlSampleSummary": summary,
        "rnaSeqSampleSummary": summary,
        "samplingSite": "breast",
        "tissueSite": "Breast",
        "tissueSiteDetail": "Breast - Mammary Tissue",
        "tissueSiteDetailAbbr": "BRST",
        "ontologyId": "UBERON:0008367",
        "ontologyIri": "http://purl.obolibrary.org/obo/UBERON_0008367",
    }


def dynamic(*, splicing=False):
    return {
        "data": [0.0, 1.0, 2.0],
        "error": 0.25,
        "genotypes": [0, 1, 2],
        "hetCount": 1,
        "homoAltCount": 1,
        "homoRefCount": 1,
        "maf": 0.5,
        "nes": -0.5,
        "pValue": 0.01,
        "pValueThreshold": 0.05,
        "tStatistic": -2,
        "tissueSiteDetailId": "Thyroid",
        "variantId": VARIANT,
        **(
            {"phenotypeId": "chr7:100:200:clu_1"}
            if splicing
            else {"gencodeId": GENCODE, "geneSymbol": "BRAF"}
        ),
    }


def dataset():
    return {
        "datasetId": "gtex_v10",
        "dbSnpBuild": 151,
        "description": "Synthetic fixture",
        "displayName": "GTEx V10 fixture",
        "eqtlSubjectCount": 3,
        "eqtlTissuesCount": 1,
        "gencodeVersion": "v39",
        "genomeBuild": "GRCh38/hg38",
        "organization": "GTEx",
        "rnaSeqAndGenotypeSampleCount": 3,
        "rnaSeqSampleCount": 3,
        "subjectCount": 3,
        "tissueCount": 1,
    }


def sample():
    return {
        "aliquotId": "SM-58Q7G",
        "tissueSampleId": "GTEX-1117F-0003",
        "tissueSiteDetail": "Thyroid",
        "pathologyNotesCategories": {},
        "freezeType": "fixture",
        "sampleId": "GTEX-1117F-0003-SM-58Q7G",
        "sampleIdUpper": "GTEX-1117F-0003-SM-58Q7G",
        "ageBracket": "20-29",
        "tissueSiteDetailId": "Thyroid",
        "subjectId": "GTEX-1117F",
        "uberonId": "UBERON:0002046",
        "sex": "female",
        "datasetId": "gtex_v10",
    }


def annotation(*, exon=False):
    return {
        "start": 100,
        "end": 200,
        "featureType": "exon" if exon else "transcript",
        "genomeBuild": "GRCh38/hg38",
        "transcriptId": "ENST00000288602.10",
        "source": "GENCODE",
        "chromosome": "chr7",
        "gencodeId": GENCODE,
        "geneSymbol": "BRAF",
        "gencodeVersion": "v39",
        "strand": "+",
        **({"exonId": "ENSE00001484009.1", "exonNumber": "1"} if exon else {}),
    }


def variant():
    return {
        "snpId": "rs113488022",
        "b37VariantId": "chr7_140453136_A_T_b37",
        "pos": 140753336,
        "maf01": False,
        "variantId": VARIANT,
        "alt": "T",
        "chromosome": "chr7",
        "snpIdUpper": "RS113488022",
        "datasetId": "gtex_v10",
        "ref": "A",
    }


def egene(*, splicing=False):
    return {
        "tissueSiteDetailId": "Thyroid",
        "ontologyId": "UBERON:0002046",
        "datasetId": "gtex_v10",
        "empiricalPValue": 0.01,
        "gencodeId": GENCODE,
        "geneSymbol": "BRAF",
        "pValue": 0.01,
        "pValueThreshold": 0.05,
        "qValue": 0.02,
        **({"nPhenotypes": 1, "phenotypeId": "chr7:100:200:clu_1"} if splicing else {}),
    }


def service():
    return {
        "id": "gtex-fixture",
        "name": "GTEx fixture",
        "version": "2.0.0",
        "organization": {"name": "GTEx", "url": "https://gtexportal.org"},
        "description": None,
        "contactUrl": None,
        "documentationUrl": None,
        "environment": "fixture",
    }
