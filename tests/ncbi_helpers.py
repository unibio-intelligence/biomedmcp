"""Synthetic NCBI records and requests qualified by the official contract snapshot."""

import json
import re
from importlib.resources import files

import jsonschema
import pytest

CONTRACT = json.loads(files("ncbi_mcp").joinpath("contracts.json").read_text())
ASSEMBLY = {
    "accession": "GCF_000001405.40",
    "current_accession": "GCF_000001405.40",
    "organism": {"tax_id": 9606, "organism_name": "Homo sapiens"},
    "assembly_info": {"assembly_name": "GRCh38.p14", "assembly_level": "Chromosome"},
    "assembly_stats": {"total_sequence_length": "3000000000", "number_of_contigs": 1000},
    "annotation_info": {"name": "Synthetic annotation", "release_date": "2026-01-01", "provider": "NCBI"},
}
ANNOTATION = {
    "row_id": "1",
    "annotation": {
        "gene_id": "672",
        "symbol": "BRCA1",
        "gene_type": "protein-coding",
        "annotations": [{"assembly_accession": "GCF_000001405.40"}],
    },
}
TAXONOMY = {
    "taxonomy": {
        "tax_id": 9606,
        "rank": "SPECIES",
        "current_scientific_name": {"name": "Homo sapiens"},
        "parents": [1, 9605],
        "classification": {
            "genus": {"id": 9605, "name": "Homo"},
            "species": {"id": 9606, "name": "Homo sapiens"},
        },
    },
    "query": ["9606"],
}
NAMES = {
    "taxonomy": {
        "tax_id": "9606",
        "rank": "SPECIES",
        "current_scientific_name": {"name": "Homo sapiens"},
        "curator_common_name": "human",
    },
    "query": ["9606"],
}
SEQUENCE_REPORT = {
    "assembly_accession": ASSEMBLY["accession"],
    "refseq_accession": "NC_000001.11",
    "chr_name": "1",
    "length": 248956422,
    "gc_percent": 41.5,
}
BACTERIAL_ASSEMBLY = {
    "accession": "GCF_000005845.2",
    "organism": {"tax_id": 511145, "organism_name": "Escherichia coli str. K-12 substr. MG1655"},
    "assembly_info": {
        "assembly_name": "ASM584v2",
        "bioproject_accession": "PRJNA225",
        "biosample": {"accession": "SAMN02604091"},
    },
    "assembly_stats": {"total_sequence_length": "4641652"},
    "checkm_info": {
        "completeness": 99.48,
        "contamination": 0.15,
        "checkm_species_tax_id": 562,
        "checkm_version": "v1.2.4",
        "checkm_marker_set": "Escherichia coli",
    },
}


def documented_request(request):
    relative = request.url.path.removeprefix("/datasets/v2")
    for template, operations in CONTRACT["paths"].items():
        pattern = re.sub(r"\{[^}]+\}", "([^/]+)", template)
        if re.fullmatch(pattern, relative):
            operation = operations[request.method.lower()]
            allowed = {
                parameter["name"]: parameter["schema"]
                for parameter in operation["parameters"]
                if parameter["in"] == "query"
            }
            assert set(request.url.params) <= set(allowed)
            for name, value in request.url.params.multi_items():
                schema = allowed[name]
                resolved = (
                    CONTRACT["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
                    if "$ref" in schema
                    else schema
                )
                if resolved.get("type") == "integer":
                    value = int(value)
                elif resolved.get("type") == "boolean":
                    value = {"true": True, "false": False}[value]
                elif resolved.get("type") == "array":
                    value = value.split(",")
                jsonschema.validate(value, {**schema, "components": CONTRACT["components"]})
            return
    pytest.fail("NCBI route is absent from the official contract: " + relative)
