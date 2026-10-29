"""Tests for mapping tools."""

import pytest
from mydisease_mcp.tools.mapping import MappingApi


class TestMappingTools:
    """Test disease identifier mapping tools."""
    
    @pytest.mark.asyncio
    async def test_map_disease_ids(self, mock_client, sample_mapping_results):
        """Test mapping disease identifiers."""
        mock_client.post.return_value = sample_mapping_results
        
        api = MappingApi()
        result = await api.map_disease_ids(
            mock_client,
            input_ids=["143100"],
            from_type="omim",
            to_types=["mondo", "orphanet"]
        )
        
        assert result["success"] is True
        assert result["mapped"] == 1
        assert result["mappings"][0]["mappings"]["mondo"] == "MONDO:0007739"
        assert result["mappings"][0]["mappings"]["orphanet"] == "ORPHA:399"
    
    @pytest.mark.asyncio
    async def test_validate_disease_ids(self, mock_client):
        """Test validating disease identifiers."""
        mock_client.post.return_value = [
            {"found": True, "query": "143100", "_id": "MONDO:0007739", "name": "Huntington disease", "mondo": {"mondo": "MONDO:0007739"}},
            {"found": False, "query": "999999"}
        ]
        
        api = MappingApi()
        result = await api.validate_disease_ids(
            mock_client,
            identifiers=["143100", "999999"],
            identifier_type="omim"
        )
        
        assert result["success"] is True
        assert result["valid_count"] == 1
        assert result["invalid_count"] == 1
        assert result["valid_identifiers"][0]["identifier"] == "143100"
        assert "999999" in result["invalid_identifiers"]
    
    @pytest.mark.asyncio
    async def test_find_common_diseases(self, mock_client):
        """Test finding common diseases across lists."""
        # Mock the post responses for map_disease_ids calls
        mock_client.post.side_effect = [
            # First call for OMIM IDs
            [
                {
                    "found": True, 
                    "_id": "MONDO:0007739", 
                    "query": "143100", 
                    "name": "Huntington disease",
                    "mondo": {"mondo": "MONDO:0007739"},
                    "orphanet": {"id": "ORPHA:399"}
                },
                {
                    "found": True, 
                    "_id": "MONDO:0011122", 
                    "query": "104300", 
                    "name": "Alzheimer disease",
                    "mondo": {"mondo": "MONDO:0011122"},
                    "orphanet": {"id": "ORPHA:100"}
                }
            ],
            # Second call for Orphanet IDs
            [
                {
                    "found": True, 
                    "_id": "MONDO:0007739", 
                    "query": "ORPHA:399", 
                    "name": "Huntington disease",
                    "mondo": {"mondo": "MONDO:0007739"},
                    "omim": "143100"
                },
                {
                    "found": True, 
                    "_id": "MONDO:0099999", 
                    "query": "ORPHA:100", 
                    "name": "Other disease",
                    "mondo": {"mondo": "MONDO:0099999"}
                }
            ]
        ]
        
        api = MappingApi()
        result = await api.find_common_diseases(
            mock_client,
            identifier_lists={
                "omim_ids": ["143100", "104300"],
                "orphanet_ids": ["ORPHA:399", "ORPHA:100"]
            }
        )
        
        assert result["success"] is True
        assert result["total_unique_diseases"] == 3  # 3 unique diseases total
        assert result["common_diseases_count"] == 1  # Only Huntington disease is common
        assert result["common_diseases"][0]["disease_id"] == "MONDO:0007739"
        assert result["common_diseases"][0]["disease_name"] == "Huntington disease"
        
        # Verify the identifiers are tracked correctly
        common_disease = result["common_diseases"][0]
        identifier_lists = [id_info["list"] for id_info in common_disease["identifiers"]]
        assert "omim_ids" in identifier_lists
        assert "orphanet_ids" in identifier_lists