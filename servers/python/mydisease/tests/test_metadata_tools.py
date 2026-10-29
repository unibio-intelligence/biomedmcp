"""Tests for metadata tools."""

import pytest
from mydisease_mcp.tools.metadata import MetadataApi


class TestMetadataTools:
    """Test metadata and utility tools."""
    
    @pytest.mark.asyncio
    async def test_get_mydisease_metadata(self, mock_client, sample_metadata):
        """Test getting MyDisease.info metadata."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_mydisease_metadata(mock_client)
        
        assert result["success"] is True
        assert result["metadata"]["build_version"] == "20240101"
        assert result["metadata"]["stats"]["total"] == 30000
        
        mock_client.get.assert_called_once_with("metadata")
    
    @pytest.mark.asyncio
    async def test_get_available_fields(self, mock_client, sample_fields_metadata):
        """Test getting available fields."""
        mock_client.get.return_value = sample_fields_metadata
        
        api = MetadataApi()
        result = await api.get_available_fields(mock_client)
        
        assert result["success"] is True
        assert result["total_fields"] == len(sample_fields_metadata)
        assert "field_categories" in result
        assert "identifiers" in result["field_categories"]
        assert "genetic" in result["field_categories"]
        
        mock_client.get.assert_called_once_with("metadata/fields")
    
    @pytest.mark.asyncio
    async def test_get_database_statistics(self, mock_client, sample_metadata):
        """Test getting database statistics."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_database_statistics(mock_client)
        
        assert result["success"] is True
        stats = result["statistics"]
        assert stats["total_diseases"] == 30000
        assert stats["last_updated"] == "2024-01-01"
        assert stats["version"] == "20240101"
        assert len(stats["sources"]) == 3
        assert stats["sources"]["omim"]["total"] == 10000
        
        # Check coverage summary
        assert "coverage_summary" in stats
        assert stats["coverage_summary"]["genetic_diseases"] == 10000
        assert stats["coverage_summary"]["rare_diseases"] == 7000