import pytest

from biomedmcp.adapters import SourceAdapters
from biomedmcp.contracts import GetRequest, SearchRequest, VariantIdentity
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.evidence import deduplicate_articles
from biomedmcp.runtime import CursorCodec, ProviderRuntime


class Adapters:
    _bounds = staticmethod(SourceAdapters._bounds)

    @staticmethod
    def availability(source):
        from biomedmcp.source_policy import source_names

        return (source in set(source_names()), "Synthetic adapter fixture")

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def validate(self, *args):
        pass

    async def call(self, source, operation, params):
        self.calls.append((source, operation, params))
        if source == "mygene":
            return {
                "hits": [
                    {
                        "_id": "673",
                        "symbol": "BRAF",
                        "taxid": 9606,
                        "entrezgene": 673,
                        "ensembl": {"gene": "ENSG00000157764"},
                    }
                ]
            }
        if self.fail:
            raise ResearchError("upstream_error", "Provider failed")
        if source == "opentargets":
            from opentargets_helpers import profile

            return profile()
        return {
            "dataset_id": params.get("dataset_id"),
            "data": [{"tissue": "Liver", "expression": 1.5, "unit": "TPM"}],
        }


@pytest.mark.asyncio
async def test_gtex_has_one_owner_no_hidden_identity_lookup_and_retains_release():
    adapters = Adapters()
    service = ResearchService(adapters=adapters)
    result = await service.get(
        GetRequest(
            entity="gene",
            id="BRAF",
            sections=["expression"],
            sources=["gtex"],
            source_versions={"gtex": "gtex_v10"},
        ),
        scope="alice",
    )
    assert [(s, o) for s, o, _ in adapters.calls] == [("gtex", "query_expression")]
    assert set(result.sections) == {"expression"}
    assert result.sections["expression"].data["data"][0]["unit"] == "TPM"
    assert result.provenance[0].source_version == "gtex_v10"
    for operation in ["query_expression", "query_qtl", "get_annotation"]:
        with pytest.raises(ResearchError, match="not a public advanced"):
            await service.source("gtex", operation, {}, scope="alice")


@pytest.mark.asyncio
async def test_failed_section_preserves_record_and_never_becomes_empty():
    result = await ResearchService(adapters=Adapters(fail=True)).get(
        GetRequest(entity="gene", id="BRAF", sections=["record", "expression"]), scope="alice"
    )
    assert result.outcome == "partial"
    assert result.sections["record"].outcome == "data"
    assert result.sections["expression"].outcome == "error"
    assert all(p.source != "gtex" for p in result.provenance)


@pytest.mark.asyncio
async def test_invalid_qtl_request_makes_no_outbound_calls():
    adapters = Adapters()
    with pytest.raises(ResearchError, match="tissue"):
        await ResearchService(adapters=adapters).get(
            GetRequest(entity="gene", id="BRAF", sections=["eqtl"]), scope="alice"
        )
    assert adapters.calls == []


@pytest.mark.asyncio
async def test_unsupported_filter_is_rejected_before_network():
    adapters = Adapters()
    with pytest.raises(ResearchError, match="Unsupported"):
        await ResearchService(adapters=adapters).search(
            SearchRequest(entity="drug", query="aspirin", filters={"phase": "3"}), scope="alice"
        )
    assert adapters.calls == []


def test_variant_identity_is_conjunctive_not_a_residue_name_match():
    variant = VariantIdentity(gene="BRAF", protein="NP_004324.2", hgvsp="p.Val600Glu")
    assert variant.equivalent_to(variant)
    assert not variant.equivalent_to(VariantIdentity(gene="BRAF", protein="NP_004324.2", hgvsp="p.Val600Lys"))
    assert not variant.equivalent_to(
        VariantIdentity(gene="OTHER", protein="NP_004324.2", hgvsp="p.Val600Glu")
    )
    assert not variant.equivalent_to(VariantIdentity(gene="BRAF", hgvsp="p.Val600Glu"))


def test_linked_publication_ids_merge_transitively_without_title_guessing():
    records = [
        {"pmid": "1", "title": "A", "sources": ["pubmed"]},
        {"doi": "10.1/x", "title": "A", "sources": ["europepmc"]},
        {"pmid": "1", "doi": "https://doi.org/10.1/X", "sources": ["s2"]},
        {"pmid": "2", "title": "A"},
    ]
    merged = deduplicate_articles(records)
    assert len(merged) == 2
    assert merged[0]["sources"] == ["europepmc", "pubmed", "s2"]
    assert merged[1]["pmid"] == "2"


def test_cursor_is_query_and_account_bound():
    codec = CursorCodec(b"x" * 32)
    cursor = codec.encode(query={"gene": "BRAF"}, scope="alice", offset=10)
    assert codec.decode(cursor, query={"gene": "BRAF"}, scope="alice") == 10
    for query, scope in [({"gene": "TP53"}, "alice"), ({"gene": "BRAF"}, "bob")]:
        with pytest.raises(ResearchError):
            codec.decode(cursor, query=query, scope=scope)
    with pytest.raises(ResearchError):
        codec.decode(cursor[:-4] + "abcd", query={"gene": "BRAF"}, scope="alice")


@pytest.mark.asyncio
async def test_freshness_and_account_cache_isolation():
    runtime = ProviderRuntime()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return {"count": calls}

    first, _ = await runtime.invoke("source", {}, fetch, scope="alice")
    cached, hit = await runtime.invoke("source", {}, fetch, scope="alice")
    assert cached == first and hit
    await runtime.invoke("source", {}, fetch, scope="bob")
    await runtime.invoke("source", {}, fetch, scope="alice", freshness="fresh")
    assert calls == 3
