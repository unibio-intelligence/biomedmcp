# tests/test_drug_tools.py
"""Tests for drug-specific tools."""

import pytest
from mychem_mcp.tools.drug import DrugApi


class TestDrugTools:
    """Test drug-specific tools."""
    
    @pytest.mark.asyncio
    async def test_search_drug(self, mock_client):
        """Test drug search."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "test-id",
                    "drugbank": {"name": "Aspirin", "groups": ["approved"]}
                }
            ]
        }
        
        api = DrugApi()
        result = await api.search_drug(
            mock_client,
            query="aspirin"
        )
        
        assert result["success"] is True
        assert result["total"] == 1
        assert result["hits"][0]["drugbank"]["name"] == "Aspirin"
    
    @pytest.mark.asyncio
    async def test_search_drug_exclude_withdrawn(self, mock_client):
        """Test drug search excluding withdrawn drugs."""
        mock_client.get.return_value = {
            "hits": [
                {"drugbank": {"groups": ["approved"]}},
                {"drugbank": {"groups": ["withdrawn"]}},
                {"drugbank": {"groups": ["approved", "withdrawn"]}}
            ]
        }
        
        api = DrugApi()
        result = await api.search_drug(
            mock_client,
            query="test",
            include_withdrawn=False
        )
        
        assert result["success"] is True
        assert result["total"] == 1  # Only approved drug
    
    @pytest.mark.asyncio
    async def test_get_drug_interactions(self, mock_client, sample_drug_interactions):
        """Test getting drug interactions."""
        mock_client.get.return_value = sample_drug_interactions
        
        api = DrugApi()
        result = await api.get_drug_interactions(
            mock_client,
            drug_id="test-id"
        )
        
        assert result["success"] is True
        assert result["total_interactions"] == 2
        assert result["interactions"][0]["drug"] == "Warfarin"
        assert result["interactions"][0]["source"] == "drugbank"
    
    @pytest.mark.asyncio
    async def test_get_drug_targets(self, mock_client):
        """Test getting drug targets."""
        mock_client.get.return_value = {
            "drugbank": {
                "targets": [
                    {"name": "COX-1", "gene_name": "PTGS1"}
                ]
            },
            "chembl": {
                "target_component": [
                    {"component_type": "PROTEIN"}
                ]
            }
        }
        
        api = DrugApi()
        result = await api.get_drug_targets(
            mock_client,
            drug_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["targets"]["drugbank_targets"]) == 1
        assert len(result["targets"]["chembl_targets"]) == 1