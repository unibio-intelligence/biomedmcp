# tests/test_annotation_tools.py
"""Tests for annotation tools."""

import pytest
from mychem_mcp.tools.annotation import AnnotationApi


class TestAnnotationTools:
    """Test annotation tools."""
    
    @pytest.mark.asyncio
    async def test_get_chemical_by_id(self, mock_client, sample_chemical_annotation):
        """Test getting chemical by ID."""
        mock_client.get.return_value = sample_chemical_annotation
        
        api = AnnotationApi()
        result = await api.get_chemical_by_id(
            mock_client,
            chemical_id="BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        )
        
        assert result["success"] is True
        assert result["chemical"]["_id"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        assert result["chemical"]["drugbank"]["name"] == "Aspirin"
        
        mock_client.get.assert_called_once_with(
            "chem/BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            params={}
        )
    
    @pytest.mark.asyncio
    async def test_get_chemical_by_id_with_fields(self, mock_client):
        """Test getting chemical with specific fields."""
        mock_client.get.return_value = {
            "_id": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "pubchem": {"cid": 2244}
        }
        
        api = AnnotationApi()
        result = await api.get_chemical_by_id(
            mock_client,
            chemical_id="BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            fields="pubchem.cid"
        )
        
        assert result["success"] is True
        assert "pubchem" in result["chemical"]
        
        mock_client.get.assert_called_once_with(
            "chem/BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            params={"fields": "pubchem.cid"}
        )
    
    @pytest.mark.asyncio
    async def test_get_chemical_by_id_no_dotfield(self, mock_client):
        """Test getting chemical without dotfield notation."""
        mock_client.get.return_value = {}
        
        api = AnnotationApi()
        result = await api.get_chemical_by_id(
            mock_client,
            chemical_id="test-id",
            dotfield=False
        )
        
        assert result["success"] is True
        
        mock_client.get.assert_called_once_with(
            "chem/test-id",
            params={"dotfield": "false"}
        )