from copy import deepcopy

import pytest
from test_research_contracts import Adapters

from biomedmcp.contracts import Entity, GetRequest
from biomedmcp.dispatch import execute, prepare
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.public_catalog import ADAPTERS

HUMAN = {
    "_id": "673",
    "symbol": "BRAF",
    "taxid": 9606,
    "entrezgene": 673,
    "ensembl": {"gene": "ENSG00000157764"},
    "HGNC": "1097",
}
MOUSE = {
    "_id": "22059",
    "symbol": "Trp53",
    "taxid": 10090,
    "entrezgene": 22059,
    "ensembl": {"gene": "ENSMUSG00000059552"},
}


class GeneAdapters(Adapters):
    def __init__(self, rows=None):
        super().__init__()
        self.rows = rows or [HUMAN]

    async def call(self, source, operation, params):
        self.calls.append((source, operation, params))
        if source == "mygene":
            return {"hits": deepcopy(self.rows)}
        return {"records": [{"id": "sentinel", "source": source}]}


class GeneHTTP:
    def __init__(self):
        self.calls = []

    async def post(self, url, body, **kwargs):
        self.calls.append((url, body))
        if "reporter.nih.gov" in url:
            return {"results": []}
        if "civicdb.org" in url:
            from civic_helpers import response

            return response((), ())
        from gnomad_helpers import constraint

        return constraint()

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "thegencc.org" in url:
            from gencc_helpers import assertion, export

            return export([assertion(classification_title="Definitive")])
        if "clinicalgenome.org" in url:
            return [{"label": "BRAF", "hgnc": "HGNC:1097"}, {"label": "BRAF-like", "hgnc": "HGNC:999"}]
        if "esearch.fcgi" in url:
            return {"esearchresult": {"idlist": ["10090"] if kwargs["params"]["db"] == "taxonomy" else []}}
        if "esummary.fcgi" in url:
            return {
                "result": {"uids": ["10090"], "10090": {"uid": "10090", "scientificname": "Mus musculus"}}
            }
        if "string-db.org" in url:
            from string_helpers import edge

            return [edge()]
        return [{"preferredName_A": "BRAF"}]


@pytest.mark.parametrize("identity", ["BRAF", "673", "ENSG00000157764"])
@pytest.mark.asyncio
async def test_equivalent_gene_inputs_map_to_one_qualified_enrichment_plan(identity):
    adapters, http = GeneAdapters(), GeneHTTP()
    result = await ResearchService(adapters=adapters, http=http).get(
        GetRequest(
            entity="gene",
            id=identity,
            sections=["protein", "constraint", "pathways", "interactions", "gencc"],
        ),
        scope="public",
    )
    assert result.outcome == "data"
    protein = next(params for source, _, params in adapters.calls if source == "uniprot")
    assert protein["query"] == "gene_exact:BRAF AND organism_id:9606"
    pathways = next(params for source, _, params in adapters.calls if source == "reactome")
    assert pathways["gene"] == "BRAF"
    assert next(body for url, body in http.calls if "gnomad" in url)["variables"]["id"] == "ENSG00000157764"
    assert next(params for url, params in http.calls if "string-db" in url)["params"]["identifiers"] == "BRAF"
    assert result.sections["gencc"].data["records"][0]["gene_symbol"] == "BRAF"
    assert len([call for call in adapters.calls if call[0] == "mygene"]) == 1
    assert result.query["qualified_identity"]["symbol"] == "BRAF"
    assert result.query["qualified_identity"]["species"] == 9606
    assert all(
        "mygene" in result.query["provider_plan"][section]["identity_dependencies"]
        for section in result.sections
    )


@pytest.mark.asyncio
async def test_explicit_protein_source_plan_cannot_hide_gene_identity_dependency():
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    with pytest.raises(ResearchError) as caught:
        await service.get(
            GetRequest(entity="gene", id="673", sections=["protein"], sources=["uniprot"]), scope="public"
        )
    assert caught.value.code == "source_plan_conflict"
    assert adapters.calls == []


@pytest.mark.asyncio
async def test_ambiguous_gene_stops_all_enrichment_joins():
    adapters, http = GeneAdapters([HUMAN, {**HUMAN, "_id": "other"}]), GeneHTTP()
    result = await ResearchService(adapters=adapters, http=http).get(
        GetRequest(entity="gene", id="BRAF", sections=["protein", "constraint", "pathways"]),
        scope="public",
    )
    assert result.outcome == "ambiguous"
    assert [source for source, _, _ in adapters.calls] == ["mygene"]
    assert http.calls == [] and result.provenance == []


@pytest.mark.parametrize("identity", ["BRAF", "673", "ENSG00000157764"])
@pytest.mark.asyncio
async def test_resolve_recognizes_each_exact_gene_namespace(identity):
    result = await execute(
        ResearchService(adapters=GeneAdapters()),
        "resolve",
        {"entity": "gene", "query": identity},
        scope="public",
    )
    assert result.outcome == "data"
    assert result.next_actions[0]["arguments"]["id"] == "673"


@pytest.mark.asyncio
async def test_mouse_followup_validates_and_keeps_species_through_enrichment():
    adapters = GeneAdapters([MOUSE])
    service = ResearchService(adapters=adapters)
    resolved = await execute(
        service, "resolve", {"entity": "gene", "query": "Trp53", "species": 10090}, scope="public"
    )
    action = resolved.next_actions[0]
    assert action["arguments"]["species"] == 10090
    ADAPTERS[action["tool"]].validate_python(action["arguments"])
    await prepare(service, action["tool"], action["arguments"], scope="public")
    args = {**action["arguments"], "sections": ["protein"]}
    result = await execute(service, "get", args, scope="public")
    assert result.outcome == "data"
    assert adapters.calls[-1][2]["query"] == "gene_exact:Trp53 AND organism_id:10090"


@pytest.mark.asyncio
async def test_gene_relation_uses_symbol_and_labels_discovery(monkeypatch):
    service = ResearchService(adapters=GeneAdapters())
    observed = []

    async def search(entity, source, query, *args):
        observed.append(query)
        return {"records": [{"id": "123", "title": "BRAF evidence"}]}

    monkeypatch.setattr(service.providers, "search", search)
    result = await service.relate(Entity.gene, "673", "articles", scope="public")
    assert observed and all(query == "BRAF" for query in observed)
    assert result.query["qualified_identity"]["symbol"] == "BRAF"
    assert result.query["relationship_evidence"] == "discovery"
    assert any("co-mention" in warning.lower() for warning in result.warnings)


@pytest.mark.asyncio
async def test_clingen_autocomplete_is_filtered_to_the_exact_hgnc_gene():
    service = ResearchService(adapters=GeneAdapters(), http=GeneHTTP())
    result = await service.get(GetRequest(entity="gene", id="673", sections=["clingen"]), scope="public")
    assert result.sections["clingen"].data["records"] == [{"label": "BRAF", "hgnc": "HGNC:1097"}]


@pytest.mark.asyncio
async def test_cached_enrichment_cannot_bypass_a_changed_or_ambiguous_mapping():
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    request = GetRequest(entity="gene", id="BRAF", sections=["protein"])
    first = await service.get(request, scope="public")
    assert first.outcome == "data"
    second = await service.get(request, scope="public")
    assert second.outcome == "data" and len(adapters.calls) == 2
    for key, (_, record) in list(service.runtime.cache.values.items()):
        if record.get("payload", {}).get("qualified_identity"):
            del service.runtime.cache.values[key]
    adapters.rows = [HUMAN, {**HUMAN, "_id": "999", "entrezgene": 999}]
    rejected = await service.get(request, scope="public")
    assert rejected.outcome == "ambiguous" and rejected.provenance == []
    assert len([c for c in adapters.calls if c[0] == "uniprot"]) == 1


@pytest.mark.asyncio
async def test_new_qualified_identity_does_not_reuse_old_enrichment_cache():
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    request = GetRequest(entity="gene", id="673", sections=["protein"])
    await service.get(request, scope="public")
    for key, (_, record) in list(service.runtime.cache.values.items()):
        if record.get("payload", {}).get("qualified_identity"):
            del service.runtime.cache.values[key]
    adapters.rows = [{**HUMAN, "symbol": "BRAF_RENAMED"}]
    changed = await service.get(request, scope="public")
    assert changed.query["qualified_identity"]["symbol"] == "BRAF_RENAMED"
    protein_calls = [params["query"] for source, _, params in adapters.calls if source == "uniprot"]
    assert protein_calls == [
        "gene_exact:BRAF AND organism_id:9606",
        "gene_exact:BRAF_RENAMED AND organism_id:9606",
    ]


@pytest.mark.parametrize(
    "row",
    [
        {**HUMAN, "symbol": "BRAF OR *"},
        {**HUMAN, "_id": None},
        {**HUMAN, "entrezgene": 999},
        {**HUMAN, "ensembl": "not an annotation"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_provider_identity_never_reaches_enrichment(row):
    adapters = GeneAdapters([row])
    result = await ResearchService(adapters=adapters).get(
        GetRequest(entity="gene", id="673", sections=["protein"]), scope="public"
    )
    assert result.outcome == "error"
    assert [source for source, _, _ in adapters.calls] == ["mygene"]


@pytest.mark.asyncio
async def test_mouse_discovery_qualifies_taxonomy_and_keeps_continuation_query(monkeypatch):
    service = ResearchService(adapters=GeneAdapters([MOUSE]), http=GeneHTTP())
    observed = []

    async def search(entity, source, query, filters, limit, offset):
        observed.append(query)
        return {"records": [{"id": str(i), "title": "Mouse Trp53"} for i in range(limit)]}

    monkeypatch.setattr(service.providers, "search", search)
    result = await execute(
        service,
        "relate",
        {"entity": "gene", "id": "22059", "relation": "articles", "species": 10090},
        scope="public",
    )
    assert observed and all(query == 'Trp53 AND "Mus musculus"' for query in observed)
    assert result.query["qualified_identity"]["species"] == 10090
    assert result.query["relation_from"]["species"] == 10090
    assert "species" not in result.query["filters"]
    assert {proof.source for proof in result.provenance} >= {"mygene", "ncbi"}
    assert result.next_cursor


@pytest.mark.asyncio
async def test_mouse_relation_metadata_and_mcp_continuation_do_not_claim_a_human_filter(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    service = ResearchService(adapters=GeneAdapters([MOUSE]), http=GeneHTTP())
    observed = []

    async def search(entity, source, query, filters, limit, offset):
        observed.append((query, filters))
        return {
            "records": [
                {"pmid": str(90001000 + offset + i), "title": "Synthetic mouse Trp53 paper"}
                for i in range(limit)
            ],
            "total": 30,
        }

    monkeypatch.setattr(service.providers, "search", search)
    async with Client(create_server(service=service)) as client:
        first = (
            await client.call_tool(
                "relate",
                {"entity": "gene", "id": "22059", "relation": "articles", "species": 10090, "limit": 2},
            )
        ).data
        assert first["query"]["qualified_identity"]["species"] == 10090
        assert first["query"]["relation_from"]["species"] == 10090
        assert "species" not in first["query"]["filters"]
        assert first["next_cursor"]
        later = (
            await client.call_tool(
                "literature_search",
                {
                    "query": first["query"]["query"],
                    "limit": first["query"]["limit"],
                    "cursor": first["next_cursor"],
                },
            )
        ).data
        assert later["records"]
        assert "species" not in later["query"]["filters"]
    assert all(query == 'Trp53 AND "Mus musculus"' for query, _ in observed)
    assert all("species" not in filters for _, filters in observed)


@pytest.mark.parametrize("entity", ["gene", "protein"])
@pytest.mark.parametrize("species", [None, 10090])
@pytest.mark.asyncio
async def test_search_keeps_supported_species_metadata(monkeypatch, entity, species):
    service = ResearchService(adapters=GeneAdapters())

    async def search(entity, source, query, filters, limit, offset):
        return {"records": [{"id": "synthetic-result"}]}

    monkeypatch.setattr(service.providers, "search", search)
    arguments = {"entity": entity, "query": "Trp53"}
    if species is not None:
        arguments["filters"] = {"species": species}
    result = await execute(service, "search", arguments, scope="public")
    assert result.query["filters"]["species"] == (species or 9606)


@pytest.mark.asyncio
async def test_nonhuman_trials_fail_preflight_without_any_provider():
    adapters = GeneAdapters([MOUSE])
    service = ResearchService(adapters=adapters)
    with pytest.raises(ResearchError) as caught:
        await execute(
            service,
            "relate",
            {"entity": "gene", "id": "22059", "relation": "trials", "species": 10090},
            scope="public",
        )
    assert caught.value.code == "unsupported_species" and adapters.calls == []


@pytest.mark.asyncio
async def test_untyped_mouse_followups_keep_scope_and_pass_preflight():
    service = ResearchService(adapters=GeneAdapters([MOUSE]))
    result = await execute(service, "resolve", {"query": "Trp53", "species": 10090}, scope="public")
    assert {a["arguments"]["entity"] for a in result.next_actions} == {"gene", "protein"}
    for action in result.next_actions:
        assert action["arguments"]["species"] == 10090
        await prepare(service, action["tool"], action["arguments"], scope="public")


@pytest.mark.asyncio
async def test_gene_dossier_reuses_one_identity_for_enrichment_and_literature(monkeypatch):
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    observed = []

    async def search(entity, source, query, *args):
        observed.append(query)
        return {"records": [{"id": "123", "title": "BRAF paper"}]}

    monkeypatch.setattr(service.providers, "search", search)
    result = await execute(
        service,
        "research",
        {"workflow": "target_dossier", "focus": "673", "sections": ["protein"]},
        scope="public",
    )
    assert result.outcome == "data"
    assert all(query == "BRAF" for query in observed)
    assert len([call for call in adapters.calls if call[0] == "mygene"]) == 1
    assert (
        result.sections["literature"].data["query"]["qualified_identity"]
        == result.query["qualified_identity"]
    )


@pytest.mark.asyncio
async def test_variant_resolution_and_relations_preserve_explicit_build(monkeypatch):
    service = ResearchService(adapters=GeneAdapters())
    seen = []

    async def variant(value, assembly=None):
        seen.append((value, assembly))
        return {
            "resolution": "exact",
            "identity": {
                "gene": "BRAF",
                "change": "V600E",
                "assembly": assembly,
                "transcript": "NM_004333.6",
            },
        }

    async def papers(*args):
        return [{"id": "123", "title": "BRAF V600E", "abstract": "BRAF V600E"}]

    monkeypatch.setattr(service.providers.variants, "resolve", variant)
    monkeypatch.setattr(service.providers.literature, "search_source", papers)
    args = {"entity": "variant", "query": "chr7:140453136:A:T", "assembly": "grch37"}
    resolved = await execute(service, "resolve", args, scope="public")
    assert resolved.query["assembly"] == "grch37"
    related = await execute(
        service,
        "relate",
        {"entity": "variant", "id": args["query"], "relation": "articles", "assembly": "grch37"},
        scope="public",
    )
    assert related.query["assembly"] == "grch37"
    assert related.sections["articles"].data["identity"]["transcript"] == "NM_004333.6"
    assert seen and all(assembly == "grch37" for _, assembly in seen)


@pytest.mark.parametrize("identity", ["BRAF", "673", "ENSG00000157764"])
@pytest.mark.asyncio
async def test_gtex_reuses_the_existing_qualified_gene_in_composed_enrichment(identity):
    adapters = GeneAdapters()
    result = await ResearchService(adapters=adapters).get(
        GetRequest(entity="gene", id=identity, sections=["record", "expression"]),
        scope="public",
    )
    assert result.outcome == "data"
    assert next(p for s, _, p in adapters.calls if s == "gtex")["gene_id"] == "ENSG00000157764"
    assert len([call for call in adapters.calls if call[0] == "mygene"]) == 1


@pytest.mark.asyncio
async def test_entrez_gtex_plan_declares_its_identity_dependency():
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    with pytest.raises(ResearchError) as caught:
        await service.get(
            GetRequest(entity="gene", id="673", sections=["expression"], sources=["gtex"]), scope="public"
        )
    assert caught.value.code == "source_plan_conflict" and adapters.calls == []
    result = await service.get(
        GetRequest(entity="gene", id="673", sections=["expression"], sources=["gtex", "mygene"]),
        scope="public",
    )
    assert result.outcome == "data"
    assert adapters.calls[-1][2]["gene_id"] == "ENSG00000157764"


@pytest.mark.asyncio
async def test_mouse_generated_action_executes_through_mcp_without_changing_species(monkeypatch):
    from fastmcp import Client

    from biomedmcp.mcp.server import create_server

    monkeypatch.setenv("UBI_PROFILE", "local")
    service = ResearchService(adapters=GeneAdapters([MOUSE]))
    async with Client(create_server(service=service)) as client:
        resolved = (
            await client.call_tool("resolve", {"entity": "gene", "query": "Trp53", "species": 10090})
        ).data
        action = resolved["next_actions"][0]
        record = (await client.call_tool(action["tool"], action["arguments"])).data
        assert record["sections"]["record"]["data"]["qualified_identity"]["species"] == 10090
        enriched = (await client.call_tool("get", {**action["arguments"], "sections": ["protein"]})).data
        assert enriched["query"]["qualified_identity"]["species"] == 10090
    assert service.adapters.calls[-1][2]["query"] == "gene_exact:Trp53 AND organism_id:10090"


@pytest.mark.parametrize("section", ["funding", "diagnostics", "civic", "disgenet", "hpa", "genetics"])
@pytest.mark.asyncio
async def test_remaining_gene_enrichments_use_the_qualified_provider_field(section, monkeypatch):
    adapters, http = GeneAdapters(), GeneHTTP()
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "disgenet")
    monkeypatch.setenv("DISGENET_API_KEY", "synthetic-contract-key")
    await ResearchService(adapters=adapters, http=http).get(
        GetRequest(entity="gene", id="673", sections=[section]),
        scope="public",
    )
    assert len([c for c in adapters.calls if c[0] == "mygene"]) == 1
    if section == "hpa":
        assert adapters.calls[-1][2]["ensembl_id"] == "ENSG00000157764"
    elif section == "genetics":
        assert adapters.calls[-1][2]["gene_id"] == "ENSG00000157764"
    elif section == "funding":
        assert http.calls[-1][1]["criteria"]["advanced_text_search"]["search_text"] == "BRAF"
    elif section == "diagnostics":
        assert http.calls[-1][1]["params"]["term"] == "BRAF"
    elif section == "civic":
        assert http.calls[-1][1]["variables"]["name"] == "BRAF"
    else:
        assert http.calls[-1][1]["params"]["gene_symbol"] == "BRAF"
