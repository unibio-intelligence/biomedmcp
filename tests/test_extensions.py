import hashlib
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from biomedmcp.charts import study_chart
from biomedmcp.errors import ResearchError
from biomedmcp.extensions import Enrichment, ExtendedSources, NcbiGet
from biomedmcp.studies import load_studies


@pytest.mark.parametrize(
    "values",
    [
        {"database": "genbank", "accession": "../../secret"},
        {"database": "geo", "accession": "SRR123"},
        {"database": "genbank", "accession": "NM_004333.6", "sequence": True},
        {"database": "genbank", "accession": "NM_004333.6", "sequence": True, "start": 10, "stop": 1},
        {"database": "genbank", "accession": "NM_004333.6", "sequence": True, "start": 1, "stop": 10001},
    ],
)
def test_accession_and_sequence_bounds_reject_invalid_requests(values):
    with pytest.raises(ValidationError):
        NcbiGet(**values)


def test_enrichment_requires_identifiers_and_explicit_scientific_defaults():
    with pytest.raises(ValidationError):
        Enrichment(genes=["TP53; rm -rf /"])
    request = Enrichment(genes=["BRAF", "KRAS"], background=["BRAF", "KRAS", "TP53"])
    assert request.organism == "hsapiens"
    assert "KEGG" not in request.sources


@pytest.mark.asyncio
async def test_ncbi_application_errors_are_not_empty(monkeypatch):
    source = ExtendedSources()
    source.eutils = AsyncMock(return_value={"esearchresult": {"idlist": [], "count": "0"}})
    result = await source.ncbi("get", NcbiGet(database="geo", accession="GSE123"))
    assert result["records"] == []
    assert result["database"] == "gds"
    assert source.eutils.call_args.args[1]["term"] == "GSE123[Accession]"


def test_managed_study_digest_and_path_are_verified(tmp_path, monkeypatch):
    root = tmp_path / "studies"
    directory = root / "fixture"
    directory.mkdir(parents=True)
    content = "cancer_study_identifier: fixture\n"
    (directory / "meta_study.txt").write_text(content)
    files = {"meta_study.txt": hashlib.sha256(content.encode()).hexdigest()}
    checksum = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "id": "fixture",
                        "release": "fixture-v1",
                        "enabled": True,
                        "sha256": checksum,
                        "files": files,
                        "source_url": "https://example.org/fixture",
                    }
                ]
            }
        )
    )
    monkeypatch.setenv("UBI_PUBLIC_STUDY_DIR", str(root))
    monkeypatch.setenv("UBI_PUBLIC_STUDY_MANIFEST", str(manifest))
    assert load_studies()["fixture"]["release"] == "fixture-v1"
    extra = directory / "data_mutations.txt"
    extra.write_text("unchecked")
    with pytest.raises(ResearchError, match="undeclared"):
        load_studies()
    extra.unlink()
    link = directory / "linked.txt"
    link.symlink_to(directory / "meta_study.txt")
    with pytest.raises(ResearchError, match="linked"):
        load_studies()
    link.unlink()
    (directory / "meta_study.txt").write_text("changed")
    with pytest.raises(ResearchError, match="differs"):
        load_studies()


def test_mutation_chart_preserves_denominator_and_event_units():
    payload = {
        "study_id": "study",
        "gene": "BRAF",
        "total_samples": 100,
        "unique_samples": 12,
        "mutation_count": 15,
        "frequency": 0.12,
        "top_variant_classes": [["Missense", 15]],
    }
    chart = study_chart(payload)
    assert chart["spec"]["data"]["values"] == [{"category": "Missense", "value": 15}]
    assert chart["spec"]["encoding"]["y"]["title"] == "Mutation events"
    assert chart["metadata"]["unique_samples"] == 12


def test_survival_estimates_are_not_rendered_as_an_invented_km_curve():
    chart = study_chart(
        {
            "study_id": "study",
            "endpoint": "os",
            "groups": [
                {
                    "group_name": "mutant",
                    "survival_1yr": 0.8,
                    "survival_3yr": None,
                    "survival_5yr": 0.2,
                    "n_patients": 10,
                    "n_censored": 3,
                }
            ],
        }
    )
    assert chart["spec"]["mark"]["type"] == "point"
    assert len(chart["spec"]["data"]["values"]) == 2
    assert chart["metadata"]["groups"][0]["n_censored"] == 3
