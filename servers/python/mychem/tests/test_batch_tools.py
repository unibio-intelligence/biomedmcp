# tests/test_batch_tools.py
"""Tests for batch operation tools."""

import pytest
from mychem_mcp.tools.batch import BatchApi
from mychem_mcp.client import MyChemError


class TestBatchTools:
    """Test batch operation tools."""
    
    @pytest.mark.asyncio
    async def test_batch_query_chemicals(self, mock_client, sample_batch_results):
        """Test batch query of chemicals."""
        mock_client.post.return_value = sample_batch_results
        
        api = BatchApi()
        result = await api.batch_query_chemicals(
            mock_client,
            chemical_ids=["aspirin", "ibuprofen", "INVALID_CHEMICAL"]
        )
        
        assert result["success"] is True
        assert result["total"] == 3
        assert result["found"] == 2
        assert result["missing"] == 1
        assert "INVALID_CHEMICAL" in result["missing_ids"]
        
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args[0]
        assert call_args[0] == "query"
        assert "ids" in call_args[1]
    
    @pytest.mark.asyncio
    async def test_batch_query_chemicals_max_size(self, mock_client):
        """Test batch query size limit."""
        api = BatchApi()
        
        # Create list with more than 1000 IDs
        too_many_ids = [f"chem_{i}" for i in range(1001)]
        
        with pytest.raises(MyChemError, match="Batch size exceeds maximum"):
            await api.batch_query_chemicals(mock_client, chemical_ids=too_many_ids)
    
    @pytest.mark.asyncio
    async def test_batch_get_chemicals(self, mock_client):
        """Test batch get chemicals."""
        mock_results = [
            {"_id": "chem1", "name": "Chemical 1"},
            {"_id": "chem2", "name": "Chemical 2"}
        ]
        mock_client.post.return_value = mock_results
        
        api = BatchApi()
        result = await api.batch_get_chemicals(
            mock_client,
            chemical_ids=["chem1", "chem2"],
            fields="name"
        )
        
        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["chemicals"]) == 2
        
        mock_client.post.assert_called_once_with(
            "chem",
            {"ids": ["chem1", "chem2"], "fields": "name"}
        )
    
    @pytest.mark.asyncio
    async def test_batch_get_chemicals_with_email(self, mock_client):
        """Test batch get with email for large requests."""
        mock_client.post.return_value = []
        
        api = BatchApi()
        result = await api.batch_get_chemicals(
            mock_client,
            chemical_ids=["chem1"],
            email="test@example.com"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.post.call_args[0]
        assert call_args[1]["email"] == "test@example.com"