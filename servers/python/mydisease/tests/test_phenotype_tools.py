"""Tests for phenotype tools."""

import pytest
from mydisease_mcp.tools.phenotype import PhenotypeApi


class TestPhenotypeTools:
    """Test phenotype and clinical feature tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_phenotypes(self, mock_client, sample_phenotype_data):
        """Test getting disease phenotypes."""
        mock_client.get.return_value = sample_phenotype_data
        
        api = PhenotypeApi()
        result = await api.get_disease_phenotypes(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["phenotypes"]["disease_id"] == "test-id"
        assert len(result["phenotypes"]["clinical_features"]) == 2
        assert result["phenotypes"]["clinical_features"][0]["hpo_id"] == "HP:0001250"
        assert result["phenotypes"]["clinical_features"][0]["frequency"] == "Very frequent (99-80%)"
    
    @pytest.mark.asyncio
    async def test_search_by_hpo_term(self, mock_client):
        """Test searching by HPO term."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "phenotype_related_to_disease": {
                        "hpo_id": "HP:0001250",
                        "hpo_phenotype": "Seizures",
                        "frequency": "Frequent"
                    }
                }
            ]
        }
        
        api = PhenotypeApi()
        result = await api.search_by_hpo_term(
            mock_client,
            hpo_id="HP:0001250"
        )
        
        assert result["success"] is True
        assert result["hpo_term"] == "HP:0001250"
        assert result["total_diseases"] == 1
        assert result["diseases"][0]["phenotype_matches"][0]["hpo_id"] == "HP:0001250"
    
    @pytest.mark.asyncio
    async def test_get_phenotype_similarity(self, mock_client):
        """Test phenotype similarity search."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "hpo": {"hpo_id": "HP:0001250", "phenotype_name": "Seizures"},
                    "phenotype_related_to_disease": [
                        {"hpo_id": "HP:0001250"},
                        {"hpo_id": "HP:0001252"}
                    ]
                }
            ]
        }
        
        api = PhenotypeApi()
        result = await api.get_phenotype_similarity(
            mock_client,
            phenotype_list=["HP:0001250", "HP:0001252", "HP:0001251"],
            algorithm="jaccard",
            min_similarity=0.5
        )
        
        assert result["success"] is True
        assert result["algorithm"] == "jaccard"
        assert len(result["diseases"]) > 0
        assert result["diseases"][0]["similarity_score"] > 0
    
    @pytest.mark.asyncio
    async def test_get_phenotype_frequency(self, mock_client):
        """Test getting phenotype frequency."""
        mock_client.get.return_value = {
            "phenotype_related_to_disease": [
                {
                    "hpo_id": "HP:0001250",
                    "hpo_phenotype": "Seizures",
                    "frequency": "Very frequent (99-80%)",
                    "frequency_hp": "HP:0040281"
                }
            ]
        }
        
        api = PhenotypeApi()
        result = await api.get_phenotype_frequency(
            mock_client,
            disease_id="test-id",
            phenotype_id="HP:0001250"
        )
        
        assert result["success"] is True
        assert result["frequency"]["frequency_info"]["frequency"] == "Very frequent (99-80%)"