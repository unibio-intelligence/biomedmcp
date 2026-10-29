"""Every canonical public example executes against actual adapters with HTTP mocked."""

from pathlib import Path

import httpx
import jsonschema
import pytest
from example_helpers import ExampleHTTP
from fastmcp import Client

from biomedmcp import transport
from biomedmcp.dispatch import prepare
from biomedmcp.domain import ResearchService
from biomedmcp.examples import (
    ADAPTER_READMES,
    EXAMPLES,
    adapter_readme,
    for_operation,
    guide_examples,
    readme_examples,
)
from biomedmcp.mcp.server import create_server
from biomedmcp.public_catalog import ADAPTERS, DESCRIPTIONS, schema

EXPECTED_HOSTS = {
    "gene-map": {"mygene.info"},
    "disease-search": {"mydisease.info"},
    "protein-record": {"rest.uniprot.org"},
    "pathway-search": {"www.ebi.ac.uk"},
    "pathway-record": {"reactome.org"},
    "gene-pathways": {"mygene.info", "reactome.org"},
    "gene-target-evidence": {"mygene.info", "api.platform.opentargets.org"},
    "gene-hpa": {"mygene.info", "www.proteinatlas.org"},
    "drug-label": {"api.fda.gov"},
    "drug-safety": {"api.fda.gov"},
    "adverse-event-search": {"api.fda.gov"},
    "patent-search": {"www.surechembl.org"},
    "ensembl-assembly": {"rest.ensembl.org"},
    "pdb-record": {"data.rcsb.org"},
    "bio-ontology-class": {"data.bioontology.org"},
    "antibody-record": {"www.antibodyregistry.org"},
    **{
        identifier: {"clinicaltrials.gov"}
        for identifier in (
            "trial-record",
            "trial-contacts",
            "trial-location",
            "trial-completed",
            "trial-pediatric",
            "trial-statistics",
            "trial-comparison",
        )
    },
    "drug-record": {"mychem.info"},
    "disease-record": {"mydisease.info"},
    "gene-search": {"mygene.info"},
    "protein-search": {"rest.uniprot.org"},
    "drug-search": {"mychem.info"},
    "gene-record": {"mygene.info"},
    "gene-expression": {"gtexportal.org"},
    "gene-tissue": {"gtexportal.org"},
    "gene-eqtl": {"gtexportal.org"},
    "gene-sqtl": {"gtexportal.org"},
    "gene-transcripts": {"gtexportal.org"},
    "gene-exons": {"gtexportal.org"},
    "article-fulltext": {"www.ebi.ac.uk"},
    "literature-kras": {
        "eutils.ncbi.nlm.nih.gov",
        "www.ebi.ac.uk",
        "www.ncbi.nlm.nih.gov",
    },
    "literature-date": {"eutils.ncbi.nlm.nih.gov"},
    "literature-open": {"www.ebi.ac.uk"},
    "trial-recruiting": {"clinicaltrials.gov"},
    "trial-phase": {"clinicaltrials.gov"},
    "trial-imatinib": {"clinicaltrials.gov"},
    "variant-protein": {"eutils.ncbi.nlm.nih.gov", "myvariant.info", "gnomad.broadinstitute.org", "civicdb.org"},
    "variant-coordinate": {"eutils.ncbi.nlm.nih.gov", "gnomad.broadinstitute.org"},
    "variant-rsid": {"eutils.ncbi.nlm.nih.gov", "myvariant.info", "gnomad.broadinstitute.org"},
    "variant-cohort": {"myvariant.info", "mygene.info", "www.cbioportal.org"},
    "resolve-her2": {"mygene.info"},
    "resolve-variant": {"myvariant.info"},
    "resolve-mouse": {"mygene.info"},
    "article-references": {"www.ebi.ac.uk"},
    "variant-structure": {"myvariant.info", "rest.uniprot.org", "www.ebi.ac.uk"},
    "gene-articles": {"mygene.info", "eutils.ncbi.nlm.nih.gov"},
    "target-dossier": {
        "mygene.info",
        "gtexportal.org",
        "api.platform.opentargets.org",
        "eutils.ncbi.nlm.nih.gov",
    },
    "drug-dossier": {"api.fda.gov", "www.fda.gov", "clinicaltrials.gov"},
    "disease-dossier": {"mydisease.info", "api.monarchinitiative.org", "www.ebi.ac.uk", "clinicaltrials.gov"},
    "gtex-tissues": {"gtexportal.org"},
    "gtex-dataset": {"gtexportal.org"},
    "gtex-service": {"gtexportal.org"},
    "gtex-sample": {"gtexportal.org"},
    "enrichment": {"biit.cs.ut.ee"},
    "genbank-region": {"eutils.ncbi.nlm.nih.gov"},
    "ncbi-genomes": {"api.ncbi.nlm.nih.gov"},
    "ncbi-assembly": {"api.ncbi.nlm.nih.gov"},
    "ncbi-annotation": {"api.ncbi.nlm.nih.gov"},
    **{
        identifier: {"api.ncbi.nlm.nih.gov"}
        for identifier in (
            "ncbi-taxonomy-search",
            "ncbi-lineage",
            "ncbi-organism",
            "ncbi-quality",
            "ncbi-sequence-report",
            "ncbi-stats",
            "ncbi-project",
            "ncbi-sample",
        )
    },
    "batch-gene": {"mygene.info"},
    "batch-trial": {"clinicaltrials.gov"},
    "batch-resolve": {"mygene.info"},
    **{
        identifier: {"www.ebi.ac.uk"}
        for identifier in (
            "chembl-compounds",
            "chembl-compound",
            "chembl-targets",
            "chembl-bioactivities",
            "chembl-properties",
            "chembl-batch",
        )
    },
}


@pytest.fixture
async def example_service(monkeypatch, study):
    _, install = study
    install()
    monkeypatch.setenv("UBI_PROFILE", "local")
    monkeypatch.delenv("NCI_API_KEY", raising=False)
    monkeypatch.setenv("BIOONTOLOGY_API_KEY", "synthetic-example-fixture")
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "antibody-registry")
    router = ExampleHTTP()
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(router))
    )
    from gtex_mcp import server as gtex

    await gtex.client.close()
    monkeypatch.setattr(gtex.client, "_rate_limit_delay", 0)
    service = ResearchService()
    yield service, router
    await gtex.client.close()


@pytest.mark.parametrize("item", EXAMPLES, ids=lambda item: item.id)
async def test_each_public_example_passes_schema_preflight_and_actual_mcp_execution(example_service, item):
    service, router = example_service
    if item.operation in ADAPTERS:
        jsonschema.validate(item.arguments, schema(item.operation))
        ADAPTERS[item.operation].validate_python(item.arguments)
        await prepare(service, item.operation, item.arguments, scope="example-test")
        assert router.requests == []
    elif item.operation == "batch":
        for call in item.arguments["calls"]:
            await prepare(service, call["operation"], call["arguments"], scope="example-test")
        assert router.requests == []
    async with Client(create_server(service=service)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        jsonschema.validate(item.arguments, tools[item.operation].input_schema)
        result = (await client.call_tool(item.operation, item.arguments)).data
    if item.operation in {"capabilities", "quota"}:
        assert router.requests == [] and isinstance(result, dict)
    elif item.operation == "batch":
        assert all(item["outcome"] in {"data", "ambiguous"} for item in result["results"]), result
        assert EXPECTED_HOSTS[item.id] <= {request.url.host for request in router.requests}
    else:
        assert result["outcome"] in ({"partial"} if item.id == "ncbi-quality" else {"data", "ambiguous"}), (
            result
        )
        assert not any(section.get("error") for section in result["sections"].values()), result
        if item.operation == "study_analysis":
            assert router.requests == []
            assert result["provenance"][0]["source"] == "study"
        else:
            assert router.requests, "The example must reach an actual mocked provider"
        if item.id in EXPECTED_HOSTS:
            assert EXPECTED_HOSTS[item.id] <= {request.url.host for request in router.requests}
        if item.id == "gene-map":
            mappings = result["sections"]["mygene"]["data"]["mappings"]
            assert [row["query"] for row in mappings] == ["BRAF", "ERBB2"]
            assert all(
                row["status"] == "resolved" and row["candidates"][0]["species"] == 9606 for row in mappings
            )
        if item.id == "gene-hpa":
            assert result["query"]["qualified_identity"]["ensembl_ids"] == ["ENSG00000141736"]
            assert "ENSG00000141736" in result["sections"]["hpa"]["data"]["data"]
        if item.id == "antibody-record":
            data = result["sections"]["antibody-registry"]["data"]
            assert data["identity_status"] == "exact" and data["items"][0]["abId"] == 3753073
            assert data["items"][0]["epitope"] is None
        if item.id == "literature-open":
            assert {request.url.host for request in router.requests} == {"www.ebi.ac.uk"}
            assert "OPEN_ACCESS:Y" in router.requests[0].url.params["query"]
        if item.id == "article-fulltext":
            assert len(router.requests) == 2
            assert router.requests[0].url.params["query"] == 'EXT_ID:"123"'
        if item.id == "resolve-mouse":
            assert all(record["taxid"] == 10090 for record in result["records"])
        if item.id in {"ncbi-assembly", "ncbi-annotation"}:
            data = result["sections"]["ncbi"]["data"]
            assert data["assembly_accession"] == "GCF_000001405.40"
            if item.id == "ncbi-annotation":
                assert data["records"][0]["annotation"]["symbol"] == "BRCA1"
            else:
                assert data["records"][0]["organism"]["tax_id"] == 9606
        if item.id == "ncbi-quality":
            metrics = result["sections"]["ncbi"]["data"]["quality_metrics"]
            assert (
                metrics["checkm"]["value"]["completeness"] == 99.48
                and metrics["busco"]["outcome"] == "unavailable"
            )
        if item.id in {"ncbi-lineage", "ncbi-organism"}:
            assert result["sections"]["ncbi"]["data"]["tax_id"] == 9606
        if item.id == "ncbi-sample":
            assert result["sections"]["ncbi"]["data"]["records"][0]["organism"]["tax_id"] == 511145
        if item.id == "trial-phase":
            assert router.requests[0].url.params["filter.advanced"] == "AREA[Phase]PHASE3"
        if item.id == "trial-record":
            assert result["provenance"][0]["url"] == "https://clinicaltrials.gov/study/NCT04368728"
        if item.id == "trial-statistics":
            data = result["sections"]["clinical-trials"]["data"]
            assert data["counts"] == {"PHASE2": 1, "PHASE3": 1}
            assert data["coverage"]["acquired_studies"] == 1
        if item.id == "trial-comparison":
            rows = result["sections"]["clinical-trials"]["data"]["results"]
            assert len(rows) == 2 and all(
                row["fields"]["enrollment"]["value"]["count"] == 100 for row in rows
            )
        if item.id == "chembl-properties":
            assessment = result["sections"]["chembl"]["data"]["drug_likeness"]["lipinski_rule_of_five"]
            assert assessment["molecular_weight"]["value"] == 180.16
            assert assessment["logp"]["value"] == 1.31
            assert assessment["drug_like"] is True
        if item.id == "chembl-bioactivities":
            activity = result["sections"]["chembl"]["data"]["activities"][0]
            assert (
                activity["standard_relation"] == "="
                and activity["standard_units"] == "nM"
                and activity["assay_chembl_id"]
            )
        dossier_sections = {
            "target-dossier": {"expression", "target_evidence", "diseases", "druggability"},
            "drug-dossier": {"label", "regulatory", "safety", "shortage", "approvals"},
            "disease-dossier": {"genes", "phenotypes", "pathways"},
        }
        if item.id in dossier_sections:
            assert dossier_sections[item.id] <= set(result["sections"])


def test_descriptions_and_generated_docs_share_the_complete_registry():
    assert len({item.id for item in EXAMPLES}) == len(EXAMPLES)
    assert {item.operation for item in EXAMPLES} == {*ADAPTERS, "batch", "capabilities", "quota"}
    for operation, description in DESCRIPTIONS.items():
        assert for_operation(operation)[0].arguments_json in description
    root = Path(__file__).resolve().parents[1]
    assert set(ADAPTER_READMES) == {
        path.parent.name for path in (root / "servers/python").glob("*/README.md")
    }
    assert (root / "docs/examples.md").read_text().endswith(guide_examples())
    readme = (root / "README.md").read_text()
    assert readme_examples() in readme
    import json
    import re

    registered = [(item.operation, item.arguments) for item in EXAMPLES]
    calls = re.findall(r"UBI_PROFILE=local uv run biomedmcp ([a-z_]+) '([^']+)'", readme)
    assert len(calls) == 3 and all((name, json.loads(arguments)) in registered for name, arguments in calls)
    documented = [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)\n```", (root / "docs/examples.md").read_text(), re.DOTALL)
    ]
    assert [(item["tool"], item["arguments"]) for item in documented] == registered
    for package in ADAPTER_READMES:
        text = (root / "servers/python" / package / "README.md").read_text()
        assert text == adapter_readme(package)
        for block in re.findall(r"```json\n(.*?)\n```", text, re.DOTALL):
            item = json.loads(block)
            assert (item["tool"], item["arguments"]) in registered
    assert "open-access melanoma papers from PubMed" not in str(DESCRIPTIONS)
    for item in EXAMPLES:
        arguments = item.arguments
        arguments["tampered"] = True
        assert "tampered" not in item.arguments


async def test_guide_resource_contains_the_same_executable_calls(example_service):
    service, _ = example_service
    async with Client(create_server(service=service)) as client:
        contents = await client.read_resource("biomedmcp://guide")
    assert guide_examples() in contents[0].text


async def test_target_prompt_uses_shared_arguments_and_executes_them(example_service):
    import json

    from biomedmcp.examples import by_id

    service, _ = example_service
    async with Client(create_server(service=service)) as client:
        prompt = await client.get_prompt("target_research", {"gene": "ERBB2"})
        text = prompt.messages[0].content.text
        arguments, _ = json.JSONDecoder().raw_decode(text.split("arguments ", 1)[1])
        assert arguments == by_id("target-dossier").arguments
        result = (await client.call_tool("research", arguments)).data
    assert result["outcome"] == "data"
