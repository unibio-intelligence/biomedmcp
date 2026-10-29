"""Tests for batch operation tools."""

import pytest
from mydisease_mcp.tools.batch import BatchApi
from mydisease_mcp.client import MyDiseaseError


class TestBatchTools:
    """Test batch operation tools."""
    
    @pytest.mark.asyncio
    async def test_batch_query_diseases(self, mock_client, sample_batch_results):
        """Test batch query of diseases."""
        mock_client.post.return_value = sample_batch_results
        
        api = BatchApi()
        result = await api.batch_query_diseases(
            mock_client,
            disease_ids=["143100", "ORPHA:15", "INVALID_DISEASE"]
        )
        
        assert result["success"] is True
        assert result["total"] == 3
        assert result["found"] == 2
        assert result["missing"] == 1
        assert "INVALID_DISEASE" in result["missing_ids"]
        
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args[0]
        assert call_args[0] == "query"
        assert "ids" in call_args[1]
    
    @pytest.mark.asyncio
    async def test_batch_query_diseases_max_size(self, mock_client):
        """Test batch query size limit."""
        api = BatchApi()
        
        # Create list with more than 1000 IDs
        too_many_ids = [f"disease_{i}" for i in range(1001)]
        
        with pytest.raises(MyDiseaseError, match="Batch size exceeds maximum"):
            await api.batch_query_diseases(mock_client, disease_ids=too_many_ids)
    
    @pytest.mark.asyncio
    async def test_batch_get_diseases(self, mock_client):
        """Test batch get diseases."""
        mock_results = [
            {"_id": "MONDO:0007739", "name": "Huntington disease"},
            {"_id": "MONDO:0011122", "name": "Achondroplasia"}
        ]
        mock_client.post.return_value = mock_results
        
        api = BatchApi()
        result = await api.batch_get_diseases(
            mock_client,
            disease_ids=["MONDO:0007739", "MONDO:0011122"],
            fields="name"
        )
        
        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["diseases"]) == 2
        
        mock_client.post.assert_called_once_with(
            "disease",
            {"ids": ["MONDO:0007739", "MONDO:0011122"], "fields": "name"}
        )