"""Tests for drug tools."""

import pytest
from mydisease_mcp.tools.drug import DrugApi


class TestDrugTools:
    """Test drug and treatment tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_drugs(self, mock_client, sample_drug_data):
        """Test getting drugs for a disease."""
        mock_client.get.return_value = sample_drug_data
        
        api = DrugApi()
        result = await api.get_disease_drugs(
            mock_client,
            disease_id="test-id",
            approved_only=True
        )
        
        assert result["success"] is True
        assert len(result["drugs"]["approved_drugs"]) == 1
        assert result["drugs"]["approved_drugs"][0]["name"] == "Riluzole"
    
    @pytest.mark.asyncio
    async def test_search_drugs_by_indication(self, mock_client):
        """Test searching drugs by indication."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "drug": {
                        "name": "Drug A",
                        "status": "approved",
                        "indication": "Treatment of pain"
                    }
                }
            ]
        }
        
        api = DrugApi()
        result = await api.search_drugs_by_indication(
            mock_client,
            indication="pain",
            drug_status="approved"
        )
        
        assert result["success"] is True
        assert result["total_diseases"] == 1
        assert result["results"][0]["drugs"][0]["name"] == "Drug A"
    
    @pytest.mark.asyncio
    async def test_get_drug_targets(self, mock_client):
        """Test getting drug targets."""
        mock_client.get.return_value = {
            "drug": {
                "name": "Drug A",
                "targets": [
                    {
                        "name": "Target Protein 1",
                        "gene_symbol": "GENE1",
                        "action": "inhibitor"
                    }
                ]
            },
            "gene": [{"symbol": "GENE1"}]
        }
        
        api = DrugApi()
        result = await api.get_drug_targets(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["targets"]["drug_targets"]) == 1
        assert result["targets"]["drug_targets"][0]["target_gene"] == "GENE1"
        assert "GENE1" in result["targets"]["disease_genes"]
    
    @pytest.mark.asyncio
    async def test_get_pharmacogenomics(self, mock_client):
        """Test getting pharmacogenomics data."""
        mock_client.get.return_value = {
            "pharmgkb": {
                "variants": [{"rsid": "rs12345", "gene": "CYP2D6"}],
                "drug_labels": [{"drug": "Drug A", "recommendation": "Dose adjustment"}]
            }
        }
        
        api = DrugApi()
        result = await api.get_pharmacogenomics(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["pharmacogenomics"]["pgx_variants"]) == 1
        assert len(result["pharmacogenomics"]["dosing_guidelines"]) == 1