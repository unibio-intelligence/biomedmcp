# tests/test_patent_tools.py
"""Tests for patent tools."""

import pytest
from mychem_mcp.tools.patent import PatentApi


class TestPatentTools:
    """Test patent-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_patent_data(self, mock_client, sample_patent_data):
        """Test getting patent data."""
        mock_client.get.return_value = sample_patent_data
        
        api = PatentApi()
        result = await api.get_patent_data(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        assert result["total_patents"] == 3
        patents = result["patent_data"]["patents"]
        
        # Check PharmGKB patents
        pharmgkb_patents = [p for p in patents if p["source"] == "pharmgkb"]
        assert len(pharmgkb_patents) == 2
        
        # Check DrugBank patents
        drugbank_patents = [p for p in patents if p["source"] == "drugbank"]
        assert len(drugbank_patents) == 1
        assert drugbank_patents[0]["country"] == "United States"
    
    @pytest.mark.asyncio
    async def test_search_patents_by_chemical(self, mock_client):
        """Test searching patents by chemical name."""
        mock_client.get.return_value = {
            "total": 5,
            "hits": [
                {
                    "_id": "chem1",
                    "name": "Test Chemical",
                    "pharmgkb": {"patent": ["US123"]}
                }
            ]
        }
        
        api = PatentApi()
        result = await api.search_patents_by_chemical(
            mock_client,
            chemical_name="test chemical"
        )
        
        assert result["success"] is True
        assert result["total"] == 5
        assert len(result["hits"]) == 1
        
        # Check query construction
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "patent" in call_args
        assert "test chemical" in call_args