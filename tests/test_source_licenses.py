"""Real permission boundary: credentials, cache hits and access attestations cannot override holds."""

import json
from pathlib import Path

import pytest
from fastmcp import Client

from biomedmcp import source_licensing
from biomedmcp.adapters import SourceAdapters
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.mcp.server import create_server
from biomedmcp.source_policy import recovery, source_names

pytestmark = pytest.mark.source_permissions


def test_inventory_is_exhaustive_and_not_a_blanket_aggregator_license():
    inventory = source_licensing.check_inventory(source_names())
    assert len(inventory["sources"]) == 57
    assert source_licensing.review("pmc")["license"] == "article_specific"
    for source in ("mychem", "mydisease", "bio-ontology"):
        row = source_licensing.review(source)
        assert row["review_status"] == "content_review_required"
        assert row["release_status"] == "eligible"
        assert row["activation_basis"] == "owner_default_allow"
    assert source_licensing.review("myvariant")["release_status"] == "unreleased"


@pytest.mark.parametrize("source", ["disgenet", "oncokb", "patents", "myvariant"])
def test_restricted_sources_stay_unreleased_even_with_keys_and_access_attestations(monkeypatch, source):
    monkeypatch.setenv("UBI_LICENSED_SOURCES", ",".join(source_names()))
    for name in (
        "DISGENET_API_KEY",
        "ONCOKB_TOKEN",
        "BIOONTOLOGY_API_KEY",
        "EPO_OPS_CONSUMER_KEY",
        "EPO_OPS_CONSUMER_SECRET",
    ):
        monkeypatch.setenv(name, "synthetic-credential-sentinel")
    assert source_licensing.availability(source)[0] is False
    assert SourceAdapters().availability(source)[0] is False
    service = ResearchService()
    assert service.source_availability(source)[0] is False
    with pytest.raises(ResearchError) as error:
        source_licensing.require(source)
    assert error.value.code == "source_license_unreleased"
    assert "sentinel" not in json.dumps(source_licensing.review(source))


@pytest.mark.parametrize(
    "source",
    [
        "civic",
        "clingen",
        "complexportal",
        "pdb",
        "opentargets",
        "uniprot",
        "protein-atlas",
        "string",
        "reactome",
        "surechembl",
        "gtex",
        "gencc",
    ],
)
def test_reviewed_permissive_sources_have_evidence_and_keep_attribution(source):
    assert source_licensing.availability(source) == (True, None)
    row = source_licensing.review(source)
    assert row["evidence"] and row["reason"]


def test_unknown_sources_are_fail_closed_and_review_objects_cannot_mutate_policy():
    assert source_licensing.availability("new-unreviewed-provider")[0] is False
    copy = source_licensing.review("myvariant")
    copy["release_status"] = "eligible"
    copy["evidence"].clear()
    assert source_licensing.review("myvariant")["release_status"] == "unreleased"
    assert source_licensing.review("myvariant")["evidence"]


def test_diagnostic_recovery_does_not_suggest_unlocking_license_holds_with_keys():
    message = recovery("myvariant", configured=False, importable=True)
    assert "unreleased" in message and "cannot override" in message


async def test_unreleased_source_is_denied_before_old_cached_evidence_or_http_reads(monkeypatch):
    service = ResearchService()
    touched = []

    async def should_not_run():
        touched.append("provider-or-cache")
        return {"records": [{"title": "previously cached restricted evidence"}]}

    async def old_cache(*args, **kwargs):
        touched.append("cache")
        return {"payload": {"records": [{"title": "old restricted evidence"}]}}, True

    monkeypatch.setattr(service.runtime, "invoke", old_cache)

    with pytest.raises(ResearchError) as error:
        await service._invoke("myvariant", "get:record", {}, should_not_run, scope="public")
    assert error.value.code == "source_license_unreleased"
    assert touched == []


async def test_permissive_source_cannot_reuse_unreleased_identity_dependency():
    service = ResearchService()

    async def should_not_run():
        pytest.fail("Acquisition must not run with an unreviewed identity dependency")

    with pytest.raises(ResearchError) as error:
        await service._invoke(
            "uniprot", "get:protein", {}, should_not_run, scope="public", attribution=("myvariant",)
        )
    assert error.value.code == "source_license_unreleased"




def test_license_document_is_generated_from_the_installed_policy():
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs/source-licenses.md").read_text() == source_licensing.matrix_markdown()


def test_catalog_drift_is_not_an_unreviewed_license_grant():
    with pytest.raises(ResearchError) as error:
        source_licensing.check_inventory([*source_names(), "new-provider"])
    assert error.value.code == "source_license_unavailable"


def test_cpic_owner_activation_preserves_separate_api_terms():
    row = source_licensing.review("cpic")
    assert row["release_status"] == "eligible"
    assert row["review_status"] == "content_review_required"
    assert "CC0" in row["license"] and "API" in row["license"]
    assert any("82aa2518" in url for url in row["evidence"])
    assert "owner policy" in source_licensing.notice("cpic")


async def test_attribution_survives_cache_and_recovery_with_original_retrieval_time():
    service = ResearchService()
    acquired = []

    async def provider():
        acquired.append(True)
        return {"records": [{"id": str(i)} for i in range(40)]}

    first, proof = await service._invoke(
        "gtex", "get:expression", {}, provider, scope="local", version="gtex_v10"
    )
    cached, cached_proof = await service._invoke(
        "gtex", "get:expression", {}, provider, scope="local", version="gtex_v10"
    )
    assert acquired == [True] and cached_proof.cached
    expected = source_licensing.notice("gtex", version="gtex_v10", retrieved_at=proof.retrieved_at)
    assert expected in first.warnings and expected in cached.warnings
    assert proof.retrieved_at == cached_proof.retrieved_at
    assert "currency is not verified" in expected
    assert "endorsement" in expected and "gtex_v10" in expected
    omission = first.recovery["omissions"][0]
    recovered = await service.read_evidence(omission["uri"], scope="local")
    assert recovered["source_permissions"] == [expected]
    assert recovered["value"] == [{"id": str(i)} for i in range(25, 40)]


async def test_recovery_rechecks_held_dependencies_before_returning_data(monkeypatch):
    from biomedmcp.contracts import Provenance
    from biomedmcp.runtime import digest

    service = ResearchService()
    proof = Provenance(
        evidence_id="ev_previously_cached_dependency",
        source="uniprot",
        sources=["myvariant"],
        content_hash=digest("synthetic historic identity"),
    )
    recovery = await service.evidence.publish(
        {"identity": "synthetic historic identity"}, proof, {}, scope="local"
    )
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "myvariant")
    with pytest.raises(ResearchError) as error:
        await service.read_evidence(recovery["uri"], scope="local")
    assert error.value.code == "source_access_denied"


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", ""),
        ("source", ["uniprot"]),
        ("evidence", []),
        ("evidence", ["https://user:synthetic@provider.example/license"]),
        ("evidence", ["https://[broken"]),
        ("review_status", "restricted"),
        ("release_status", ["eligible"]),
        ("license", "CC-BY-NC-4.0"),
        ("byok", "keys_override_permissions"),
    ],
)
def test_invalid_installed_permission_entries_fail_closed(monkeypatch, field, value):
    from copy import deepcopy

    original = deepcopy(source_licensing.inventory())
    row = next(row for row in original["sources"] if row["source"] == "uniprot")
    row[field] = value

    class InvalidPolicy:
        def joinpath(self, _):
            return self

        def read_text(self):
            return json.dumps(original)

    monkeypatch.setattr(source_licensing, "files", lambda _: InvalidPolicy())
    source_licensing.inventory.cache_clear()
    try:
        with pytest.raises(ResearchError) as error:
            source_licensing.availability("uniprot")
        assert error.value.code == "source_license_unavailable"
    finally:
        source_licensing.inventory.cache_clear()


@pytest.mark.parametrize("source", ["chembl", "cbioportal"])
def test_share_alike_activation_keeps_upstream_obligations(source):
    assert source_licensing.availability(source) == (True, None)
    assert "share-alike obligations" in source_licensing.notice(source)
    assert "Apache-2.0 code" in source_licensing.notice(source)


@pytest.mark.parametrize("source", ["clinical-trials", "pubmed", "cpic", "ols", "orcid"])
def test_default_enable_is_not_a_false_permissive_license(source):
    row = source_licensing.review(source)
    assert row["review_status"] != "permissive"
    assert row["activation_basis"] == "owner_default_allow"
    assert source_licensing.availability(source) == (True, None)
    assert "conditional" in source_licensing.notice(source)
