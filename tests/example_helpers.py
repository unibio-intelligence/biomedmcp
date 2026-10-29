"""Strict synthetic HTTP router for actual public example execution."""

import io
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from gtex_helpers import annotation, association, dataset, expression, gene, page, sample, service, tissue
from native_helpers import JATS, PUBMED

GENES = {
    "BRCA1": ("672", "ENSG00000012048"),
    "PCSK9": ("255738", "ENSG00000169174"),
    "LDLR": ("3949", "ENSG00000130164"),
    "Trp53": ("22059", "ENSMUSG00000059552"),
}
EZETIMIBE = {"_id": "OLNTVTPDXPETLC-XPWALMASSA-N", "chebi": {"name": "ezetimibe"}}
FAMILIAL_HYPERCHOLESTEROLEMIA = {"_id": "MONDO:0007750", "mondo": {"mondo": "MONDO:0007750", "label": "familial hypercholesterolemia"}}
EPMC_ROW = {
    "id": "123",
    "source": "MED",
    "pmcid": "PMC123",
    "title": "Synthetic PCSK9 study",
    "abstractText": "Measured PCSK9 LDL cholesterol in familial hypercholesterolemia",
    "firstPublicationDate": "2024-03-12",
    "isOpenAccess": "Y",
}
TRIAL = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Synthetic trial"},
        "statusModule": {"overallStatus": "RECRUITING"},
        "designModule": {"phases": ["PHASE3"]},
    }
}
CHEMBL_PROPERTIES = {
    "full_mwt": "180.16",
    "alogp": "1.31",
    "hbd": 1,
    "hba": 3,
    "num_ro5_violations": 0,
    "ro3_pass": "N",
}


class ExampleHTTP:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        host, path, params = request.url.host, request.url.path, request.url.params
        variant = {
            "_id": "chr1:g.55505647G>T",
            "dbnsfp": {"genename": "PCSK9", "hgvsp": "p.Arg46Leu"},
            "snpeff": {"ann": [{"genename": "PCSK9", "hgvs_p": "p.Arg46Leu",
                                  "feature_id": "NM_174936.4", "hgvs_c": "c.137G>T"}]},
            "hg38": {"start": 55039974}, "dbsnp": {"rsid": "rs11591147"},
            "clinvar": {"rcv": [{"clinical_significance": "Benign"}]},
        }
        if host == "mygene.info" and path == "/v3/query" and request.method == "POST":
            body = parse_qs(request.content.decode())
            assert body["q"] == ["PCSK9,LDLR"]
            assert body["scopes"] == ["symbol"] and body["species"] == ["9606"]
            data = [
                {
                    "query": symbol,
                    "_id": GENES[symbol][0],
                    "symbol": symbol,
                    "taxid": 9606,
                    "entrezgene": int(GENES[symbol][0]),
                    "ensembl": {"gene": GENES[symbol][1]},
                }
                for symbol in ("PCSK9", "LDLR")
            ]
        elif host == "mygene.info" and path == "/v3/query":
            query = params.get("q", "")
            symbol = "LDLR" if query == "LDL receptor" else query
            assert symbol in GENES, query
            identifier, ensembl = GENES[symbol]
            species = int(params.get("species", "9606"))
            assert species == (10090 if symbol == "Trp53" else 9606)
            data = {
                "hits": [
                    {
                        "_id": identifier,
                        "symbol": symbol,
                        "taxid": species,
                        "entrezgene": int(identifier),
                        "ensembl": {"gene": ensembl},
                    }
                ],
                "total": 1,
            }
        elif host == "gtexportal.org":
            if path.endswith("/metadata/dataset"):
                return httpx.Response(200, json=[dataset()])
            if path == "/api/v2/":
                return httpx.Response(200, json=service())
            if path.endswith("/reference/gene"):
                data = page([gene("LDLR", "ENSG00000130164.13")])
            elif path.endswith(("/reference/transcript", "/reference/exon")):
                assert params["gencodeId"] == "ENSG00000130164.13"
                data = page(
                    [
                        {
                            **annotation(exon=path.endswith("exon")),
                            "gencodeId": "ENSG00000130164.13",
                            "geneSymbol": "LDLR",
                        }
                    ]
                )
            elif path.endswith("/dataset/tissueSiteDetail"):
                data = page([tissue()])
            elif path.endswith("/dataset/sample"):
                data = page(
                    [
                        {
                            **sample(),
                            "sampleId": params["sampleId"],
                            "sampleIdUpper": params["sampleId"].upper(),
                        }
                    ]
                )
            else:
                assert path.endswith(
                    (
                        "/expression/medianGeneExpression",
                        "/expression/geneExpression",
                        "/association/singleTissueEqtl",
                        "/association/singleTissueSqtl",
                    )
                ), path
                assert params.get("gencodeId") == "ENSG00000130164.13"
                if path.endswith(
                    (
                        "/expression/geneExpression",
                        "/association/singleTissueEqtl",
                        "/association/singleTissueSqtl",
                    )
                ):
                    assert params.get("tissueSiteDetailId") == "Liver"
                row = (
                    association(
                        "LDLR",
                        "ENSG00000130164.13",
                        "Liver",
                        splicing=path.endswith("singleTissueSqtl"),
                    )
                    if path.endswith(("singleTissueEqtl", "singleTissueSqtl"))
                    else expression(
                        "LDLR",
                        "ENSG00000130164.13",
                        "Liver",
                        detailed=path.endswith("geneExpression"),
                    )
                )
                data = page([row])
            data = page(
                data["data"], size=int(params.get("itemsPerPage", 25)), index=int(params.get("page", 0))
            )
        elif host == "mychem.info":
            if path.endswith("/query"):
                assert params["q"] == "ezetimibe"
                data = {"hits": [EZETIMIBE], "total": 1}
            else:
                assert path.endswith("/chem/" + EZETIMIBE["_id"]), path
                data = EZETIMIBE
        elif host == "mydisease.info":
            if path.endswith("/query"):
                assert params["q"] == "familial hypercholesterolemia"
                data = {"hits": [FAMILIAL_HYPERCHOLESTEROLEMIA], "total": 1}
            else:
                assert path.endswith("/disease/MONDO:0007750"), path
                data = FAMILIAL_HYPERCHOLESTEROLEMIA
        elif host == "rest.uniprot.org" and path == "/uniprotkb/Q8NBP7":
            assert params["format"] == "json" and "sequence" in params["fields"].split(",")
            data = {
                "primaryAccession": "Q8NBP7",
                "sequence": {"value": "A" * 45 + "R" + "A" * 646, "length": 692},
                "genes": [{"geneName": {"value": "PCSK9"}}],
                "organism": {"taxonId": 9606, "scientificName": "Homo sapiens"},
            }
        elif host == "rest.uniprot.org" and path.endswith("/search"):
            assert "organism_id:9606" in params["query"]
            insulin = "insulin" in params["query"]
            sequence = "A" * 45 + "R" + "A" * 646
            data = {
                "results": [
                    {
                        "primaryAccession": "P01308" if insulin else "Q8NBP7",
                        "sequence": {"value": sequence, "length": len(sequence)},
                        "genes": [{"geneName": {"value": "INS" if insulin else "PCSK9"}}],
                        "organism": {"taxonId": 9606, "scientificName": "Homo sapiens"},
                        "uniProtKBCrossReferences": [],
                    }
                ]
            }
        elif host == "api.platform.opentargets.org":
            from opentargets_helpers import association as target_association
            from opentargets_helpers import profile, project

            body = json.loads(request.content)
            assert body["variables"]["ensemblId"] == "ENSG00000130164"
            fixture = profile("ENSG00000130164", "LDLR", rows=[target_association()])
            data = project(
                {
                    "data": {
                        "target": {**fixture["target"], "associatedDiseases": fixture["associated_diseases"]}
                    }
                },
                body["query"],
            )
        elif host == "api.fda.gov":
            assert "ezetimibe" in params["search"]
            data = {
                "results": [{"id": "synthetic-regulatory-record", "openfda": {"generic_name": ["ezetimibe"]}}]
            }
            if path == "/drug/label.json":
                data["results"][0].update(id="12345678-1234-1234-1234-123456789abc",
                    set_id="12345678-1234-1234-1234-123456789abd", version="1", effective_time="20260101")
        elif host == "www.fda.gov":
            assert path == "/media/76860/download"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    "products.txt",
                    "Ingredient~Trade_Name~Appl_No~Product_No~DF;Route~Applicant~Strength~TE_Code~Approval_Date~RLD~RS\n"
                    "EZETIMIBE~SYNTHETIC~000001~001~TABLET;ORAL~SYNTHETIC~100MG~AB~Jan 1, 2025~Yes~No\n",
                )
            return httpx.Response(200, content=buffer.getvalue())
        elif host == "api.monarchinitiative.org":
            assert params.get("subject") == "MONDO:0007750" or params.get("object") == "MONDO:0007750"
            phenotype = params.get("subject") == "MONDO:0007750"
            model = params.get("predicate") == "biolink:model_of"
            data = {
                "items": [
                    {
                        "id": "synthetic-association",
                        "subject": "MONDO:0007750" if phenotype else "MGI:1" if model else "HGNC:1097",
                        "object": "HP:0001250" if phenotype else "MONDO:0007750",
                        "subject_category": "biolink:Disease"
                        if phenotype
                        else "biolink:Genotype"
                        if model
                        else "biolink:Gene",
                        "object_category": "biolink:PhenotypicFeature" if phenotype else "biolink:Disease",
                        "category": params["category"],
                        "predicate": "biolink:has_phenotype"
                        if phenotype
                        else "biolink:model_of"
                        if model
                        else "biolink:gene_associated_with_condition",
                    }
                ],
                "total": 1,
                "limit": 25,
                "offset": 0,
            }
        elif host == "www.ebi.ac.uk" and path == "/ebisearch/ws/rest/reactome":
            if "query" not in params:
                data = {
                    "domains": [
                        {
                            "id": "reactome",
                            "indexInfos": [
                                {"name": "Release version", "value": "97"},
                                {"name": "Last modification date", "value": "2026-10-16"},
                            ],
                        }
                    ]
                }
            else:
                assert params["query"] in {
                    '("familial hypercholesterolemia") AND type:Pathway AND species:"Homo sapiens"',
                    '("apoptosis") AND type:Pathway AND species:"Homo sapiens"',
                }
                data = {
                    "hitCount": 1,
                    "entries": [
                        {
                            "id": "109581",
                            "source": "reactome",
                            "fields": {
                                "stid": ["R-HSA-109581"],
                                "name": ["Synthetic pathway"],
                                "type": ["Pathway"],
                                "species": ["Homo sapiens"],
                            },
                        }
                    ],
                }
        elif host == "reactome.org":
            if path == "/ContentService/data/query/R-HSA-109581":
                data = {
                    "stId": "R-HSA-109581",
                    "displayName": "Apoptosis",
                    "schemaClass": "Pathway",
                    "speciesName": "Homo sapiens",
                }
            else:
                assert path == "/ContentService/data/mapping/UniProt/PCSK9/pathways", path
                assert params["species"] == "9606"
                data = [
                    {
                        "stId": "R-HSA-109581",
                        "displayName": "Synthetic PCSK9 pathway",
                        "schemaClass": "Pathway",
                    }
                ]
        elif host == "www.proteinatlas.org":
            assert path == "/ENSG00000130164.xml" and params["format"] == "xml"
            return httpx.Response(
                200,
                text='<proteinAtlas schemaVersion="3.0"><entry version="25" '
                'url="https://v25.proteinatlas.org/ENSG00000130164"><name>LDLR</name>'
                '<identifier id="ENSG00000130164" db="Ensembl" version="109" '
                'assembly="GRCh38.p13" gencodeVersion="43"/></entry></proteinAtlas>',
            )
        elif host == "rest.ensembl.org":
            assert path == "/info/assembly/homo_sapiens"
            data = {
                "assembly_name": "GRCh38.p14",
                "assembly_accession": "GCA_000001405.29",
                "default_coord_system_version": "GRCh38",
                "karyotype": ["1"],
                "top_level_region": [{"name": "1", "coord_system": "chromosome", "length": 248956422}],
            }
        elif host == "data.rcsb.org":
            assert path == "/rest/v1/core/entry/4hhb"
            data = json.loads((Path(__file__).parent / "fixtures/pdb-entry-4hhb-2026-10-11.json").read_text())
        elif host == "www.surechembl.org":
            assert path == "/api/search/content" and request.method == "POST"
            assert params["query"] == "ezetimibe"
            data = {
                "status": "OK",
                "data": {
                    "type": "CONTENT",
                    "results": {
                        "query": "ezetimibe",
                        "total_hits": 1,
                        "documents": [
                            {
                                "docId": "US-9095515-B2",
                                "metadata": {"pn": "US-9095515-B2", "pd": "20150804"},
                                "pa": "Synthetic assignee",
                            }
                        ],
                    },
                },
            }
        elif host == "data.bioontology.org":
            assert path == "/ontologies/GO/classes/http://purl.obolibrary.org/obo/GO_0006915"
            assert "http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0006915" in request.url.raw_path.decode()
            assert request.headers["authorization"] == "apikey token=synthetic-example-fixture"
            assert "apikey" not in params
            data = {"@id": "http://purl.obolibrary.org/obo/GO_0006915", "prefLabel": "apoptotic process"}
        elif host == "www.antibodyregistry.org":
            assert path == "/api/antibodies/3753073"
            data = [{"abId": 3753073, "abName": "Synthetic BRCA1 antibody", "epitope": None}]
        elif host == "myvariant.info":
            data = (
                {"hits": [variant], "total": 1}
                if path.endswith("/query")
                else {**variant, "_id": path.rsplit("/", 1)[-1]}
            )
        elif host == "gnomad.broadinstitute.org":
            from gnomad_helpers import population

            body = json.loads(request.content)
            data = population()
            data["data"]["variant"].update(variant_id="1-55039974-G-T", chrom="1", pos=55039974, ref="G")
            assert data["data"]["variant"]["variant_id"] == body["variables"]["id"]
        elif host == "civicdb.org":
            from civic_helpers import response

            data = response(assertions=())
        elif host == "www.cbioportal.org":
            assert "/molecular-profiles/study_mutations/mutations/fetch" in path
            assert json.loads(request.content)["sampleListId"] == "study_all"
            data = [{"proteinChange": "R46L", "sampleId": "synthetic"}]
        elif host == "eutils.ncbi.nlm.nih.gov":
            if params.get("db") == "clinvar":
                from clinvar_helpers import variant as clinvar_variant

                assert params["retmode"] == "json"
                if path.endswith("/esearch.fcgi"):
                    data = {"esearchresult": {"idlist": ["2878"], "count": "1"}}
                else:
                    assert path.endswith("/esummary.fcgi") and params["id"] == "2878"
                    record = clinvar_variant()
                    record.update(uid="2878", accession_version="VCV000002878.1")
                    record["variation_set"] = [{
                        "variation_name": "NM_174936.4(PCSK9):c.137G>T (p.Arg46Leu)",
                        "variation_xrefs": [{"db_source": "dbSNP", "db_id": "11591147"}],
                        "canonical_spdi": "NC_000001.11:55039973:G:T",
                        "variation_loc": [
                            {"assembly_name": "GRCh38", "chr": "1", "start": "55039974", "stop": "55039974"},
                            {"assembly_name": "GRCh37", "chr": "1", "start": "55505647", "stop": "55505647"},
                        ],
                    }]
                    record["germline_classification"] = {"description": "Benign", "review_status": "synthetic fixture"}
                    record.pop("oncogenicity_classification", None)
                    record.pop("clinical_impact_classification", None)
                    data = {"result": {"uids": ["2878"], "2878": record}}
            elif path.endswith("/esearch.fcgi"):
                data = {"esearchresult": {"idlist": ["123"], "count": "1"}}
            elif params.get("rettype") == "fasta":
                assert (
                    params["id"] == "NM_174936.4"
                    and params["seq_start"] == "1"
                    and params["seq_stop"] == "100"
                )
                return httpx.Response(200, text=">NM_174936.4 synthetic fixture\n" + "A" * 100 + "\n")
            elif path.endswith("/esummary.fcgi"):
                data = {"result": {"uids": ["123"], "123": {"uid": "123", "accessionversion": "NM_174936.4"}}}
            else:
                assert params["db"] == "pubmed" and params["id"] == "123"
                return httpx.Response(200, text=PUBMED.replace("Retracted Publication", "Journal Article"))
        elif host == "api.ncbi.nlm.nih.gov":
            from ncbi_helpers import (
                ANNOTATION,
                ASSEMBLY,
                BACTERIAL_ASSEMBLY,
                NAMES,
                SEQUENCE_REPORT,
                TAXONOMY,
                documented_request,
            )

            documented_request(request)
            if path == "/datasets/v2/genome/taxon/Homo sapiens/dataset_report":
                assert (
                    params["filters.assembly_source"] == "refseq"
                    and params["filters.assembly_level"] == "chromosome"
                )
                data = {"reports": [deepcopy(ASSEMBLY)], "total_count": 1}
            elif path == "/datasets/v2/genome/accession/GCF_000001405.40/dataset_report":
                assert params["page_size"] == "1"
                data = {"reports": [deepcopy(ASSEMBLY)], "total_count": 1}
            elif path == "/datasets/v2/genome/accession/GCF_000001405.40/annotation_report":
                assert params["symbols"] == "BRCA1" and params["gene_types"] == "protein-coding"
                data = {"reports": [deepcopy(ANNOTATION)], "total_count": 1}
            elif path in {
                "/datasets/v2/taxonomy/taxon/Homo sapiens/dataset_report",
                "/datasets/v2/taxonomy/taxon/9606/dataset_report",
            }:
                if "ranks" in params:
                    assert params["ranks"] == "SPECIES"
                data = {"reports": [deepcopy(TAXONOMY)], "total_count": 1}
            elif path == "/datasets/v2/taxonomy/taxon/9606/name_report":
                data = {"reports": [deepcopy(NAMES)], "total_count": 1}
            elif path == "/datasets/v2/genome/taxon/9606/dataset_report":
                data = {"reports": [deepcopy(ASSEMBLY)], "total_count": 1}
            elif path == "/datasets/v2/genome/accession/GCF_000001405.40/sequence_reports":
                data = {"reports": [deepcopy(SEQUENCE_REPORT)], "total_count": 1}
            elif path in {
                "/datasets/v2/genome/accession/GCF_000005845.2/dataset_report",
                "/datasets/v2/genome/biosample/SAMN02604091/dataset_report",
            }:
                data = {"reports": [deepcopy(BACTERIAL_ASSEMBLY)], "total_count": 1}
            elif path == "/datasets/v2/genome/bioproject/PRJNA31257/dataset_report":
                row = deepcopy(ASSEMBLY)
                row["assembly_info"]["bioproject_accession"] = "PRJNA31257"
                data = {"reports": [row], "total_count": 1}
            else:
                pytest.fail("Unqualified NCBI example route: " + path)
        elif host == "www.ebi.ac.uk" and "/chembl/api/data/" in path:
            assert request.method == "GET"
            if path.endswith("/molecule/search.json"):
                assert params["q"] == "aspirin" and params["limit"] == "10"
                data = {
                    "molecules": [{"molecule_chembl_id": "CHEMBL25", "pref_name": "ASPIRIN"}],
                    "page_meta": {"total_count": 1},
                }
            elif path.endswith("/target/search.json"):
                assert params["q"] == "kinase" and params["organism"] == "Homo sapiens"
                data = {"targets": [{"target_chembl_id": "CHEMBL2095173", "organism": "Homo sapiens"}]}
            elif path.endswith("/activity.json"):
                assert (
                    params["target_chembl_id"] == "CHEMBL2095173"
                    and params["standard_type"] == "IC50"
                    and params["standard_units"] == "nM"
                )
                data = {
                    "activities": [
                        {
                            "activity_id": 1,
                            "assay_chembl_id": "CHEMBL000001",
                            "target_chembl_id": "CHEMBL2095173",
                            "standard_type": "IC50",
                            "standard_relation": "=",
                            "standard_value": "12.5",
                            "standard_units": "nM",
                        }
                    ]
                }
            else:
                identifier = path.rsplit("/", 1)[-1].removesuffix(".json")
                assert path.endswith("/molecule/" + identifier + ".json") and identifier in {
                    "CHEMBL25",
                    "CHEMBL521",
                    "CHEMBL192",
                }
                data = {"molecule_chembl_id": identifier, "molecule_properties": deepcopy(CHEMBL_PROPERTIES)}
        elif host == "www.ebi.ac.uk" and "europepmc" in path:
            if path.endswith("/fullTextXML"):
                return httpx.Response(200, text=JATS)
            if path.endswith(("/references", "/citations")):
                field = "reference" if path.endswith("/references") else "citation"
                data = {"hitCount": 1, field + "List": {field: [EPMC_ROW]}}
            else:
                data = {"resultList": {"result": [EPMC_ROW]}, "hitCount": 1}
        elif host == "www.ebi.ac.uk" and "interpro" in path:
            data = {"count": 0, "results": [], "next": None, "previous": None}
        elif host == "www.ncbi.nlm.nih.gov" and "pubtator" in path:
            data = {"results": [{"pmid": "123", "title": "Synthetic PCSK9 study", "date": "2024-03-12"}]}
        elif host == "clinicaltrials.gov":
            from clinical_trials_helpers import documented_request, study

            documented_request(request)
            if path == "/api/v2/studies":
                row = study()
                row["protocolSection"]["statusModule"]["overallStatus"] = params.get(
                    "filter.overallStatus", "RECRUITING"
                )
                data = {"studies": [row], "totalCount": 1}
            else:
                identifier = path.rsplit("/", 1)[-1]
                assert identifier in {"NCT04368728", "NCT04280705"}
                data = study(identifier)
        elif host == "biit.cs.ut.ee":
            body = json.loads(request.content)
            assert body["organism"] == "hsapiens" and body["query"] == ["PCSK9", "KRAS", "TP53"]
            data = {"result": [{"native": "GO:0000001", "p_value": 0.01}], "meta": {}}
        else:
            pytest.fail("Example attempted unqualified HTTP: " + request.method + " " + str(request.url))
        return httpx.Response(200, json=data)
