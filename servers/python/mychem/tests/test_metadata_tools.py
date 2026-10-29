# tests/test_metadata_tools.py
"""Tests for metadata tools."""

import pytest
from mychem_mcp.tools.metadata import MetadataApi


class TestMetadataTools:
    """Test metadata and utility tools."""
    
    @pytest.mark.asyncio
    async def test_get_mychem_metadata(self, mock_client, sample_metadata):
        """Test getting MyChemInfo metadata."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_mychem_metadata(mock_client)
        
        assert result["success"] is True
        assert result["metadata"]["build_version"] == "20240101"
        assert result["metadata"]["stats"]["total"] == 150000000
        
        mock_client.get.assert_called_once_with("metadata")
    
    @pytest.mark.asyncio
    async def test_get_available_fields(self, mock_client, sample_fields_metadata):
        """Test getting available fields."""
        mock_client.get.return_value = sample_fields_metadata
        
        api = MetadataApi()
        result = await api.get_available_fields(mock_client)
        
        assert result["success"] is True
        assert "pubchem.cid" in result["fields"]
        assert result["fields"]["pubchem.cid"]["type"] == "integer"
        
        mock_client.get.assert_called_once_with("metadata/fields")
    
    @pytest.mark.asyncio
    async def test_get_database_statistics(self, mock_client, sample_metadata):
        """Test getting database statistics."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_database_statistics(mock_client)
        
        assert result["success"] is True
        stats = result["statistics"]
        assert stats["total_chemicals"] == 150000000
        assert stats["last_updated"] == "2024-01-01"
        assert stats["version"] == "20240101"
        assert len(stats["sources"]) == 3
        assert stats["sources"]["chembl"]["total"] == 2300000