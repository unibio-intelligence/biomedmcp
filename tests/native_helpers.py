"""Synthetic provider fixtures: no network or external executable."""

from copy import deepcopy

from defusedxml import ElementTree


class HTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    async def post(self, url, body, **kwargs):
        self.calls.append(("POST", url, {"body": body, **kwargs}))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    async def xml(self, url, **kwargs):
        return ElementTree.fromstring(await self.get(url, **kwargs))


PUBMED = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>BRAF <i>V600E</i> in cancer</ArticleTitle><Journal><Title>Synthetic Journal</Title><JournalIssue><PubDate><Year>2024</Year><Month>03</Month><Day>12</Day></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="RESULTS">BRAF V600E showed a response.</AbstractText></Abstract>
<AuthorList><Author><LastName>Smith</LastName><ForeName>Alice</ForeName><AffiliationInfo><Affiliation>Example University</Affiliation></AffiliationInfo></Author><Author><CollectiveName>Study Group</CollectiveName></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType><PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
</Article><MeshHeadingList><MeshHeading><DescriptorName>Neoplasms</DescriptorName></MeshHeading></MeshHeadingList></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/synthetic</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""
JATS = """<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><permissions><license><license-p>CC BY 4.0</license-p></license></permissions></article-meta></front><body><sec><title>Results</title><p>Measured BRAF V600E activity.</p><p>Study limitations.</p></sec></body><back><supplementary-material id="s1"><label>Table S1</label><media xlink:href="table.csv"/></supplementary-material></back></article>"""
BRAF = {
    "_id": "chr7:g.140453136A>T",
    "dbnsfp": {"genename": "BRAF", "hgvsp": "p.Val600Glu"},
    "snpeff": {
        "ann": [
            {"genename": "BRAF", "hgvs_p": "p.Val600Glu", "feature_id": "NM_004333.6", "hgvs_c": "c.1799T>A"}
        ]
    },
    "hg38": {"start": 140753336},
    "clinvar": {"rcv": [{"clinical_significance": "Pathogenic"}]},
}
