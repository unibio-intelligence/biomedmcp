"""Tests for GWAS tools."""

import pytest
from mydisease_mcp.tools.gwas import GWASApi


class TestGWASTools:
    """Test GWAS data tools."""
    
    @pytest.mark.asyncio
    async def test_get_gwas_associations(self, mock_client, sample_gwas_data):
        """Test getting GWAS associations."""
        mock_client.get.return_value = sample_gwas_data
        
        api = GWASApi()
        result = await api.get_gwas_associations(
            mock_client,
            disease_id="test-id",
            p_value_threshold=5e-8
        )
        
        assert result["success"] is True
        assert len(result["gwas_data"]["associations"]) == 1
        assert result["gwas_data"]["associations"][0]["rsid"] == "rs12345678"
        assert float(result["gwas_data"]["associations"][0]["p_value"]) < 5e-8
    
    @pytest.mark.asyncio
    async def test_search_gwas_by_trait(self, mock_client):
        """Test searching GWAS by trait."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "gwas_catalog": {
                        "trait": "Type 2 diabetes",
                        "rsid": "rs12345678",
                        "p_value": "1.2e-10",
                        "sample_size": "50000",
                        "ancestry": "European"
                    }
                }
            ]
        }
        
        api = GWASApi()
        result = await api.search_gwas_by_trait(
            mock_client,
            trait="Type 2 diabetes",
            min_sample_size=10000,
            ancestry="European"
        )
        
        assert result["success"] is True
        assert result["trait_query"] == "Type 2 diabetes"
        assert len(result["studies"]) == 1
        assert result["studies"][0]["sample_size"] == "50000"
    
    @pytest.mark.asyncio
    async def test_get_gwas_variants(self, mock_client):
        """Test getting GWAS variants."""
        mock_client.get.return_value = {
            "gwas_catalog": [
                {
                    "rsid": "rs12345678",
                    "position": "12345",
                    "chromosome": "1",
                    "p_value": "1.2e-10",
                    "mapped_gene": "GENE1"
                }
            ]
        }
        
        api = GWASApi()
        result = await api.get_gwas_variants(
            mock_client,
            disease_id="test-id",
            gene_symbol="GENE1"
        )
        
        assert result["success"] is True
        assert len(result["variants"]["all_variants"]) == 1
        assert "GENE1" in result["variants"]["variants_by_gene"]
    
    @pytest.mark.asyncio
    async def test_get_gwas_statistics(self, mock_client):
        """Test getting GWAS statistics."""
        mock_client.get.return_value = {
            "gwas_catalog": [
                {
                    "rsid": "rs1",
                    "p_value": "1e-10",
                    "odds_ratio": "1.25",
                    "ancestry": "European",
                    "mapped_gene": "GENE1"
                },
                {
                    "rsid": "rs2",
                    "p_value": "5e-9",
                    "odds_ratio": "1.15",
                    "ancestry": "European",
                    "mapped_gene": "GENE1"
                }
            ]
        }
        
        api = GWASApi()
        result = await api.get_gwas_statistics(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        stats = result["statistics"]
        assert stats["total_associations"] == 2
        assert stats["significant_associations"] == 2
        assert stats["unique_variants"] == 2
        assert "European" in stats["ancestry_distribution"]