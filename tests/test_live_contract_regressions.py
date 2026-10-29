"""Production shapes with real permission gates and deterministic provider fixtures."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from defusedxml import ElementTree
from native_helpers import HTTP, PUBMED
from test_qualified_gene_identity import GeneAdapters

from biomedmcp import source_licensing
from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.literature import Literature

pytestmark = pytest.mark.source_permissions

BOOK = """<PubmedBookArticle><BookDocument><PMID>456</PMID>
<ArticleIdList><ArticleId IdType="doi">10.1234/chapter</ArticleId></ArticleIdList>
<Book><BookTitle>Synthetic reference</BookTitle><PubDate><Year>2025</Year></PubDate>
<AuthorList Type="editors"><Author><LastName>Editor</LastName></Author></AuthorList></Book>
<ArticleTitle>Synthetic BRAF chapter</ArticleTitle>
<AuthorList Type="authors" CompleteYN="Y"><Author><ForeName>Alice</ForeName><LastName>Writer</LastName></Author></AuthorList>
<PublicationType>Study Guide</PublicationType><Abstract><AbstractText>Source abstract.</AbstractText></Abstract>
<ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1234/cited</ArticleId>
<ArticleId IdType="pmc">PMC999</ArticleId></ArticleIdList></Reference></ReferenceList>
</BookDocument><PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">456</ArticleId>
</ArticleIdList></PubmedBookData></PubmedBookArticle>"""


async def test_mixed_pubmed_chapters_preserve_records_identities_and_provenance():
    xml = PUBMED.replace("Retracted Publication", "Review").replace(
        "</PubmedArticleSet>", BOOK + "</PubmedArticleSet>"
    )
    service = ResearchService(http=HTTP({"esearchresult": {"idlist": ["123", "456"], "count": "2"}}, xml))
    result = await execute(
        service,
        "literature_search",
        {
            "query": "BRAF",
            "filters": {"source": "pubmed", "date_from": "2024-01-01"},
        },
        scope="public",
    )
    assert result.outcome == "data"
    chapter = next(row for row in result.records if row["pmid"] == "456")
    assert chapter["doi"] == "10.1234/chapter" and chapter["pmcid"] is None
    assert chapter["book_title"] == "Synthetic reference" and chapter["publication_form"] == "book_chapter"
    assert chapter["authors"] == ["Alice Writer"] and chapter["is_retracted"] is None
    assert chapter["author_completeness"] == "complete"
    assert result.provenance[0].source == "pubmed" and result.sections["pubmed"].evidence_ids
    # Article publication types supply a negative assertion; absent chapter metadata does not.
    assert next(row for row in result.records if row["pmid"] == "123")["is_retracted"] is False


@pytest.mark.parametrize("chapter", [BOOK.replace("<PMID>456</PMID>", ""), "<UnknownRecord/>"])
def test_invalid_pubmed_siblings_still_fail_closed(chapter):
    with pytest.raises(ResearchError):
        Literature.parse_pubmed(
            ElementTree.fromstring("<PubmedArticleSet>" + chapter + "</PubmedArticleSet>")
        )


@pytest.mark.parametrize("workflow", ["target_dossier", "model_input_bundle"])
async def test_gene_workflow_uses_fixed_identity_projection_with_shipped_permission_gate(workflow):
    adapters = GeneAdapters()
    service = ResearchService(adapters=adapters)
    service.providers.literature.search_source = AsyncMock(return_value=[])
    service._gene_discovery_text = AsyncMock(return_value=("BRAF Homo sapiens", None))
    result = await execute(
        service,
        "research",
        {
            "workflow": workflow,
            "focus": "BRAF",
            "species": 9606,
            "sections": ["record"],
        },
        scope="public",
    )
    assert "identity" not in result.sections and result.sections["record"].outcome == "data"
    assert result.query["qualified_identity"]["species"] == 9606
    assert any(p.source == "mygene" for p in result.provenance)
    assert all(call[1] == "query_genes" for call in adapters.calls if call[0] == "mygene")
    assert source_licensing.operation_allowed("mygene", "gene_identity")
    assert not source_licensing.operation_allowed("mygene", "map_gene_ids")


async def test_gene_relation_passes_real_identity_gate_before_species_qualified_search():
    service = ResearchService(adapters=GeneAdapters())
    service._gene_discovery_text = AsyncMock(return_value=("BRAF Homo sapiens", None))
    service.providers.literature.search_source = AsyncMock(return_value=[])
    result = await execute(
        service,
        "relate",
        {
            "entity": "gene",
            "id": "BRAF",
            "relation": "articles",
            "species": 9606,
        },
        scope="public",
    )
    assert "identity" not in result.sections
    assert result.query["qualified_identity"]["species"] == 9606
    service._gene_discovery_text.assert_awaited_once()


class DiseaseAdapters(GeneAdapters):
    def __init__(self, record=None):
        super().__init__()
        self.record = record or {
            "_id": "MONDO:0005105",
            "mondo": {"mondo": "MONDO:0005105", "label": "melanoma"},
        }

    async def call(self, source, operation, params):
        self.calls.append((source, operation, params))
        if source == "mydisease":
            return {"success": True, "disease": deepcopy(self.record)}
        assert source == "reactome" and params["disease"] == "melanoma"
        return {
            "records": [{"id": "R-HSA-123", "name": "Melanoma discovery"}],
            "relation_basis": "provider_pathway_text_search",
        }


async def test_disease_pathways_resolve_label_and_declare_identity_dependency():
    adapters = DiseaseAdapters()
    result = await execute(
        ResearchService(adapters=adapters),
        "get",
        {
            "entity": "disease",
            "id": "MONDO:0005105",
            "sections": ["pathways"],
        },
        scope="public",
    )
    assert result.outcome == "data"
    data = result.sections["pathways"].data
    assert data["disease_identity"] == {"id": "MONDO:0005105", "label": "melanoma", "source": "mydisease"}
    assert data["relation_basis"] == "provider_pathway_text_search"
    assert result.provenance[0].sources == ["mydisease", "reactome"]
    assert result.query["provider_plan"]["pathways"]["identity_dependencies"] == ["mydisease"]


@pytest.mark.parametrize(
    "record",
    [
        {"_id": "MONDO:other", "name": "melanoma"},
        {"_id": "MONDO:0005105", "mondo": {"mondo": "MONDO:other", "label": "melanoma"}},
        {"_id": "MONDO:0005105", "mondo": {"mondo": "MONDO:0005105", "label": ""}},
    ],
)
async def test_disease_identity_failure_cannot_start_pathway_discovery(record):
    adapters = DiseaseAdapters(record)
    result = await execute(
        ResearchService(adapters=adapters),
        "get",
        {
            "entity": "disease",
            "id": "MONDO:0005105",
            "sections": ["pathways"],
        },
        scope="public",
    )
    assert result.sections["pathways"].error["code"] == "unresolved_identity"
    assert all(source != "reactome" for source, _, _ in adapters.calls)


async def test_disease_source_restriction_cannot_hide_label_acquisition():
    adapters = DiseaseAdapters()
    with pytest.raises(ResearchError, match="mydisease"):
        await execute(
            ResearchService(adapters=adapters),
            "get",
            {
                "entity": "disease",
                "id": "MONDO:0005105",
                "sections": ["pathways"],
                "sources": ["reactome"],
            },
            scope="public",
        )
    assert adapters.calls == []
