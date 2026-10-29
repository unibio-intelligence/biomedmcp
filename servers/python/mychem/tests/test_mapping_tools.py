# tests/test_mapping_tools.py
"""Tests for identifier mapping tools."""

import pytest
from mychem_mcp.tools.mapping import MappingApi


class TestMappingTools:
    """Test chemical identifier mapping tools."""
    
    @pytest.mark.asyncio
    async def test_map_identifiers(self, mock_client, sample_mapping_results):
        """Test mapping identifiers."""
        mock_client.post.return_value = sample_mapping_results
        
        api = MappingApi()
        result = await api.map_identifiers(
            mock_client,
            input_ids=["aspirin"],
            from_type="name",
            to_types=["inchikey", "pubchem", "chembl"]
        )
        
        assert result["success"] is True
        assert result["mapped"] == 1
        assert result["mappings"][0]["input"] == "aspirin"
        assert result["mappings"][0]["mappings"]["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        assert result["mappings"][0]["mappings"]["pubchem"] == 2244
        assert result["mappings"][0]["mappings"]["chembl"] == "CHEMBL25"
    
    @pytest.mark.asyncio
    async def test_map_identifiers_with_missing(self, mock_client):
        """Test mapping with missing identifiers."""
        mock_client.post.return_value = [
            {"found": True, "query": "valid", "_id": "test-id"},
            {"found": False, "query": "invalid"}
        ]
        
        api = MappingApi()
        result = await api.map_identifiers(
            mock_client,
            input_ids=["valid", "invalid"],
            from_type="name",
            to_types=["inchikey"],
            missing_ok=True
        )
        
        assert result["success"] is True
        assert result["mapped"] == 1
        assert result["unmapped"] == 1
        assert "invalid" in result["unmapped_ids"]
    
    @pytest.mark.asyncio
    async def test_validate_identifiers(self, mock_client):
        """Test identifier validation."""
        mock_client.post.return_value = [
            {"found": True, "query": "CHEMBL25", "_id": "test-id"},
            {"found": False, "query": "CHEMBL99999"}
        ]
        
        api = MappingApi()
        result = await api.validate_identifiers(
            mock_client,
            identifiers=["CHEMBL25", "CHEMBL99999"],
            identifier_type="chembl"
        )
        
        assert result["success"] is True
        assert result["valid_count"] == 1
        assert result["invalid_count"] == 1
        assert result["valid_identifiers"][0]["identifier"] == "CHEMBL25"
        assert "CHEMBL99999" in result["invalid_identifiers"]
    
    @pytest.mark.asyncio
    async def test_find_common_identifiers(self, mock_client):
        """Test finding common identifiers across lists."""
        # Mock mapping results
        mock_client.post.side_effect = [
            # First list mapping
            [
                {"found": True, "_id": "common-id", "query": "DB001"},
                {"found": True, "_id": "unique-id1", "query": "DB002"}
            ],
            # Second list mapping
            [
                {"found": True, "_id": "common-id", "query": "CHEMBL1"},
                {"found": True, "_id": "unique-id2", "query": "CHEMBL2"}
            ]
        ]
        
        api = MappingApi()
        result = await api.find_common_identifiers(
            mock_client,
            identifier_lists={
                "drugbank_ids": ["DB001", "DB002"],
                "chembl_ids": ["CHEMBL1", "CHEMBL2"]
            }
        )
        
        assert result["success"] is True
        assert result["total_unique_chemicals"] == 3
        assert result["common_chemicals_count"] == 1
        assert result["common_chemicals"][0]["inchikey"] == "common-id"