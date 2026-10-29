# tests/test_go_tools.py
"""Tests for Gene Ontology tools."""

import pytest
from mygene_mcp.tools.go import GOApi


class TestGOTools:
    """Test GO-related tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_id_with_aspect(self, mock_client):
        """Test querying genes by GO ID with specific aspect."""
        mock_client.get.return_value = {
            "total": 150,
            "took": 12,
            "hits": [
                {
                    "symbol": "CDK2",
                    "go": {
                        "MF": [
                            {"id": "GO:0004672", "term": "protein kinase activity"}
                        ]
                    }
                }
            ]
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_id="GO:0004672",
            aspect="MF"
        )
        
        assert result["success"] is True
        assert result["total"] == 150
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'go.MF:"GO:0004672"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_id_all_aspects(self, mock_client):
        """Test querying genes by GO ID across all aspects."""
        mock_client.get.return_value = {
            "total": 200,
            "took": 15,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_id="GO:0008283"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should search across BP, MF, and CC
        assert "go.BP" in call_args or "go.MF" in call_args or "go.CC" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_name(self, mock_client):
        """Test querying genes by GO term name."""
        mock_client.get.return_value = {
            "total": 75,
            "took": 8,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_name="protein kinase activity",
            aspect="MF"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'go.MF.term:"protein kinase activity"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_evidence_codes(self, mock_client):
        """Test querying genes by GO evidence codes."""
        mock_client.get.return_value = {
            "total": 50,
            "took": 6,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_id="GO:0006468",
            evidence_codes=["EXP", "IDA", "IMP"]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should include evidence code filters
        assert "go.evidence" in call_args
        assert "EXP" in call_args or "IDA" in call_args or "IMP" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_qualifier(self, mock_client):
        """Test querying genes by GO qualifier."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 3,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_id="GO:0005634",
            qualifier="NOT"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'go.qualifier:"NOT"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_combined(self, mock_client):
        """Test combined GO query."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 2,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(
            mock_client,
            go_name="kinase activity",
            aspect="MF",
            evidence_codes=["IDA"],
            species="human"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]
        query = call_args["q"]
        assert "kinase activity" in query
        assert "MF" in query
        assert "IDA" in query
        assert call_args["species"] == "human"
    
    @pytest.mark.asyncio
    async def test_query_genes_by_go_default(self, mock_client):
        """Test default GO query."""
        mock_client.get.return_value = {
            "total": 30000,
            "took": 100,
            "hits": []
        }
        
        api = GOApi()
        result = await api.query_genes_by_go_term(mock_client)
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:go" in call_args
    
    @pytest.mark.asyncio
    async def test_get_gene_go_annotations_basic(self, mock_client):
        """Test getting GO annotations for a gene."""
        mock_client.get.return_value = {
            "symbol": "CDK2",
            "name": "cyclin dependent kinase 2",
            "go": {
                "BP": [
                    {
                        "id": "GO:0006468",
                        "term": "protein phosphorylation",
                        "evidence": "IDA",
                        "pubmed": [12345]
                    },
                    {
                        "id": "GO:0007049",
                        "term": "cell cycle",
                        "evidence": "TAS"
                    }
                ],
                "MF": {
                    "id": "GO:0004672",
                    "term": "protein kinase activity",
                    "evidence": "IDA",
                    "qualifier": ["enables"]
                },
                "CC": [
                    {
                        "id": "GO:0005634",
                        "term": "nucleus",
                        "evidence": "IDA"
                    }
                ]
            }
        }
        
        api = GOApi()
        result = await api.get_gene_go_annotations(
            mock_client,
            gene_id="1017"
        )
        
        assert result["success"] is True
        assert result["total_annotations"] == 4
        
        annotations = result["go_annotations"]["annotations"]
        assert len(annotations["BP"]) == 2
        assert len(annotations["MF"]) == 1
        assert len(annotations["CC"]) == 1
        
        # Check BP annotation details
        bp_anno = annotations["BP"][0]
        assert bp_anno["id"] == "GO:0006468"
        assert bp_anno["term"] == "protein phosphorylation"
        assert bp_anno["evidence"] == "IDA"
        assert bp_anno["pubmed"] == [12345]
        
        # Check MF annotation (single item converted to list)
        mf_anno = annotations["MF"][0]
        assert mf_anno["qualifier"] == ["enables"]
        
        mock_client.get.assert_called_once_with(
            "gene/1017",
            params={"fields": "symbol,name,entrezgene,go"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_go_annotations_with_aspect(self, mock_client):
        """Test getting GO annotations for specific aspect."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "go": {
                "BP": [
                    {"id": "GO:0006915", "term": "apoptotic process", "evidence": "IMP"},
                    {"id": "GO:0006977", "term": "DNA damage response", "evidence": "IDA"}
                ],
                "MF": [
                    {"id": "GO:0003677", "term": "DNA binding", "evidence": "IDA"}
                ],
                "CC": [
                    {"id": "GO:0005634", "term": "nucleus", "evidence": "IDA"}
                ]
            }
        }
        
        api = GOApi()
        result = await api.get_gene_go_annotations(
            mock_client,
            gene_id="7157",
            aspect="BP"
        )
        
        assert result["success"] is True
        assert result["total_annotations"] == 2
        
        annotations = result["go_annotations"]["annotations"]
        assert len(annotations["BP"]) == 2
        assert len(annotations["MF"]) == 0  # Filtered out
        assert len(annotations["CC"]) == 0  # Filtered out
    
    @pytest.mark.asyncio
    async def test_get_gene_go_annotations_with_evidence_filter(self, mock_client):
        """Test getting GO annotations with evidence code filter."""
        mock_client.get.return_value = {
            "symbol": "BRCA1",
            "go": {
                "BP": [
                    {"id": "GO:0006281", "term": "DNA repair", "evidence": "IDA"},
                    {"id": "GO:0006974", "term": "cellular response to DNA damage", "evidence": "IEP"},
                    {"id": "GO:0000724", "term": "double-strand break repair", "evidence": "IMP"}
                ]
            }
        }
        
        api = GOApi()
        result = await api.get_gene_go_annotations(
            mock_client,
            gene_id="672",
            evidence_codes=["IDA", "IMP"]
        )
        
        assert result["success"] is True
        assert result["total_annotations"] == 2
        
        # Only IDA and IMP evidence should be included
        annotations = result["go_annotations"]["annotations"]["BP"]
        assert len(annotations) == 2
        assert all(anno["evidence"] in ["IDA", "IMP"] for anno in annotations)
    
    @pytest.mark.asyncio
    async def test_get_gene_go_annotations_no_go(self, mock_client):
        """Test gene with no GO annotations."""
        mock_client.get.return_value = {
            "symbol": "UNKNOWN",
            "name": "unknown gene"
        }
        
        api = GOApi()
        result = await api.get_gene_go_annotations(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["total_annotations"] == 0
        assert all(len(annotations) == 0 
                  for annotations in result["go_annotations"]["annotations"].values())
    
    @pytest.mark.asyncio
    async def test_get_gene_go_annotations_qualifier_handling(self, mock_client):
        """Test proper handling of GO qualifiers."""
        mock_client.get.return_value = {
            "symbol": "GENE1",
            "go": {
                "MF": [
                    {
                        "id": "GO:0003674",
                        "term": "molecular_function",
                        "evidence": "ND",
                        "qualifier": ["NOT", "enables"]
                    },
                    {
                        "id": "GO:0005515",
                        "term": "protein binding",
                        "evidence": "IPI",
                        "qualifier": []  # Empty qualifier list
                    }
                ]
            }
        }
        
        api = GOApi()
        result = await api.get_gene_go_annotations(
            mock_client,
            gene_id="12345"
        )
        
        assert result["success"] is True
        
        mf_annotations = result["go_annotations"]["annotations"]["MF"]
        assert mf_annotations[0]["qualifier"] == ["NOT", "enables"]
        assert mf_annotations[1]["qualifier"] == []