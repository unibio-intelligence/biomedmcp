"""Tests for gene association tools."""

import pytest
from mydisease_mcp.tools.gene_association import GeneAssociationApi


class TestGeneAssociationTools:
    """Test gene-disease association tools."""
    
    @pytest.mark.asyncio
    async def test_get_diseases_by_gene(self, mock_client):
        """Test finding diseases by gene."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "MONDO:0007739",
                    "name": "Huntington disease",
                    "gene": [{"symbol": "HTT", "id": "3064"}]
                }
            ]
        }
        
        api = GeneAssociationApi()
        result = await api.get_diseases_by_gene(
            mock_client,
            gene_symbol="HTT"
        )
        
        assert result["success"] is True
        assert result["gene_symbol"] == "HTT"
        assert result["total_diseases"] == 1
        assert result["diseases"][0]["disease_name"] == "Huntington disease"
    
    @pytest.mark.asyncio
    async def test_get_disease_genes(self, mock_client, sample_gene_association):
        """Test getting genes for a disease."""
        mock_client.get.return_value = sample_gene_association
        
        api = GeneAssociationApi()
        result = await api.get_disease_genes(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["genes"]["primary_genes"]) == 1
        assert result["genes"]["primary_genes"][0]["symbol"] == "BRCA1"
        assert len(result["genes"]["causal_genes"]) == 1
    
    @pytest.mark.asyncio
    async def test_search_by_gene_panel(self, mock_client):
        """Test searching by gene panel."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "gene": [{"symbol": "GENE1"}, {"symbol": "GENE2"}]
                }
            ]
        }
        
        api = GeneAssociationApi()
        result = await api.search_by_gene_panel(
            mock_client,
            gene_symbols=["GENE1", "GENE2", "GENE3"]
        )
        
        assert result["success"] is True
        assert result["total_diseases"] == 1
        assert set(result["diseases"][0]["matching_genes"]) == {"GENE1", "GENE2"}
        assert result["diseases"][0]["match_count"] == 2