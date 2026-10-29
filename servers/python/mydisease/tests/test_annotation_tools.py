"""Tests for annotation tools."""

import pytest
from mydisease_mcp.tools.annotation import AnnotationApi


class TestAnnotationTools:
    """Test annotation tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_by_id(self, mock_client, sample_disease_annotation):
        """Test getting disease by ID."""
        mock_client.get.return_value = sample_disease_annotation
        
        api = AnnotationApi()
        result = await api.get_disease_by_id(
            mock_client,
            disease_id="MONDO:0007739"
        )
        
        assert result["success"] is True
        assert result["disease"]["_id"] == "MONDO:0007739"
        assert result["disease"]["name"] == "Huntington disease"
        
        mock_client.get.assert_called_once_with(
            "disease/MONDO:0007739",
            params={}
        )
    
    @pytest.mark.asyncio
    async def test_get_disease_by_id_with_fields(self, mock_client):
        """Test getting disease with specific fields."""
        mock_client.get.return_value = {
            "_id": "MONDO:0007739",
            "name": "Huntington disease"
        }
        
        api = AnnotationApi()
        result = await api.get_disease_by_id(
            mock_client,
            disease_id="MONDO:0007739",
            fields="name"
        )
        
        assert result["success"] is True
        assert "name" in result["disease"]
        
        mock_client.get.assert_called_once_with(
            "disease/MONDO:0007739",
            params={"fields": "name"}
        )