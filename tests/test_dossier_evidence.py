from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from biomedmcp.contracts import Provenance, ResearchResult, Section
from biomedmcp.domain import ResearchService
from biomedmcp.public_catalog import ADAPTERS


def evidence_result(entity, outcome="data", *, truncated=False):
    source = "clinical-trials" if entity == "trial" else "pubmed"
    proof = Provenance(evidence_id=f"ev_{source}", source=source, content_hash="sentinel-hash")
    return ResearchResult(
        entity=entity,
        outcome=outcome,
        records=[{"id": "NCT01234567" if entity == "trial" else "1234", "sentinel": "retained evidence"}]
        if outcome in {"data", "partial"}
        else [],
        sections={
            source: Section(
                outcome=outcome,
                evidence_ids=[proof.evidence_id],
                error={"code": "provider_failed"} if outcome == "unavailable" else None,
            )
        },
        provenance=[proof] if outcome in {"data", "partial"} else [],
        warnings=["Constituent warning"],
        query={
            "entity": entity,
            "query": "sentinel",
            "limit": 5,
            "filters": {},
            "execution": {"requested_filters": {}},
        },
        next_cursor="constituent-cursor" if truncated else None,
        truncated=truncated,
    )


@pytest.mark.parametrize("workflow", ["drug_review", "disease_landscape"])
@pytest.mark.parametrize("outcome", ["data", "empty", "partial", "unavailable", "ambiguous", "error"])
@pytest.mark.asyncio
async def test_dossier_retains_constituent_trials_and_scientific_status(monkeypatch, workflow, outcome):
    service = ResearchService()
    constituent = evidence_result("trial", outcome, truncated=outcome in {"data", "partial"})
    papers = evidence_result("article")

    async def get(*args, **kwargs):
        return ResearchResult(
            outcome="data", sections={"record": Section(outcome="data", data={"id": "focus"})}
        )

    async def search(*args, **kwargs):
        return deepcopy(papers)

    async def relate(*args, **kwargs):
        return deepcopy(constituent)

    monkeypatch.setattr(service, "get", get)
    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service, "relate", relate)
    if workflow == "disease_landscape":
        monkeypatch.setattr(
            service,
            "_disease_discovery",
            AsyncMock(
                return_value=(
                    Section(
                        outcome="data",
                        data={"id": "sentinel", "label": "Disease label", "source": "mydisease"},
                    ),
                    None,
                )
            ),
        )
    result = await service.research(workflow, "sentinel", scope="public")
    section = result.sections["related_trials"]
    assert section.outcome == constituent.outcome
    assert section.data["records"] == constituent.records
    assert section.data["provider_status"] == {
        key: value.model_dump(mode="json") for key, value in constituent.sections.items()
    }
    assert section.data["next_cursor"] == constituent.next_cursor
    assert section.truncated == constituent.truncated
    assert section.warnings == constituent.warnings
    assert section.evidence_ids == [p.evidence_id for p in constituent.provenance]
    assert all(p in result.provenance for p in constituent.provenance)
    assert result.truncated == constituent.truncated
    assert result.outcome == ("data" if outcome in {"data", "empty"} else "partial")
    assert result.sections["literature"].data["records"] == papers.records
    continuation = section.data["continuation"]
    if constituent.next_cursor:
        assert continuation["tool"] == "trial_search"
        next_request = ADAPTERS[continuation["tool"]].validate_python(continuation["arguments"])
        assert next_request.cursor == constituent.next_cursor
        assert next_request.query == constituent.query["query"]
    else:
        assert continuation is None


@pytest.mark.asyncio
async def test_real_trial_search_records_survive_dossier_composition(monkeypatch):
    service = ResearchService()

    async def provider_search(entity, source, query, filters, limit, offset=0):
        return {"records": [{"id": f"NCT0123456{i}", "title": "Sentinel trial"} for i in range(limit)]}

    async def get(*args, **kwargs):
        return ResearchResult(
            outcome="data", sections={"record": Section(outcome="data", data={"id": "drug"})}
        )

    monkeypatch.setattr(service.providers, "search", provider_search)
    monkeypatch.setattr(service, "get", get)
    from biomedmcp.contracts import Entity

    constituent = await service.relate(Entity.drug, "drug", "trials", scope="public", limit=5)
    dossier = await service.research("drug_review", "drug", scope="public")
    retained = dossier.sections["related_trials"]
    assert retained.data["records"] == constituent.records
    assert retained.data["records"][0]["id"] == "NCT01234560"
    from biomedmcp.runtime import digest

    # Nonces distinguish independent snapshots, even in the same second.
    assert retained.data["continuation"]["arguments"]["cursor"] == retained.data["next_cursor"]
    retained_state = await service.runtime.cache.get("page:" + digest(retained.data["next_cursor"]))
    constituent_state = await service.runtime.cache.get("page:" + digest(constituent.next_cursor))
    for name in ("seen", "pending", "providers", "sections"):
        assert retained_state[name] == constituent_state[name]
    assert [p["content_hash"] for p in retained_state["evidence"]] == [
        p["content_hash"] for p in constituent_state["evidence"]
    ]
    assert retained.evidence_ids == [proof.evidence_id for proof in constituent.provenance]
