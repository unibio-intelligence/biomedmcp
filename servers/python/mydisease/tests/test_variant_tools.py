"""Tests for variant tools."""

import pytest
from mydisease_mcp.tools.variant import VariantApi


class TestVariantTools:
    """Test variant-disease association tools."""
    
    @pytest.mark.asyncio
    async def test_get_diseases_by_variant(self, mock_client, sample_variant_data):
        """Test getting diseases by variant."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "MONDO:0007739",
                    "name": "Test Disease",
                    "clinvar": sample_variant_data["clinvar"]
                }
            ]
        }
        
        api = VariantApi()
        result = await api.get_diseases_by_variant(
            mock_client,
            variant_id="rs104894090"
        )
        
        assert result["success"] is True
        assert result["variant_id"] == "rs104894090"
        assert result["total_diseases"] == 1
        assert result["diseases"][0]["variant_associations"][0]["source"] == "clinvar"
    
    @pytest.mark.asyncio
    async def test_get_disease_variants(self, mock_client, sample_variant_data):
        """Test getting variants for a disease."""
        mock_client.get.return_value = sample_variant_data
        
        api = VariantApi()
        result = await api.get_disease_variants(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["variants"]["clinvar_variants"]) == 1
        assert result["variants"]["clinvar_variants"][0]["rsid"] == "rs104894090"
        assert result["variants"]["clinvar_variants"][0]["clinical_significance"] == "Pathogenic"
    
    @pytest.mark.asyncio
    async def test_get_variant_pathogenicity(self, mock_client):
        """Test getting variant pathogenicity."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "clinvar": {
                        "variant": {
                            "rsid": "rs104894090",
                            "clinical_significance": "Pathogenic"
                        }
                    }
                }
            ]
        }
        
        api = VariantApi()
        result = await api.get_variant_pathogenicity(
            mock_client,
            variant_id="rs104894090"
        )
        
        assert result["success"] is True
        assert result["pathogenicity"]["variant_id"] == "rs104894090"
        assert "Pathogenic" in result["pathogenicity"]["pathogenicity_summary"]
        assert len(result["pathogenicity"]["disease_associations"]) == 1
    
    @pytest.mark.asyncio
    async def test_search_by_variant_type(self, mock_client):
        """Test searching by variant type."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "clinvar": {
                        "variant": [
                            {
                                "variant_type": "missense",
                                "gene": "GENE1",
                                "rsid": "rs12345"
                            }
                        ]
                    }
                }
            ]
        }
        
        api = VariantApi()
        result = await api.search_by_variant_type(
            mock_client,
            variant_type="missense",
            gene_symbol="GENE1"
        )
        
        assert result["success"] is True
        assert result["variant_type"] == "missense"
        assert result["total_diseases"] == 1
        assert result["diseases"][0]["variant_count"] == 1