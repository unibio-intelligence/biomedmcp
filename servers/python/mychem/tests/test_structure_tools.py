# tests/test_structure_tools.py
"""Tests for structure tools."""

import pytest
from mychem_mcp.tools.structure import StructureApi


class TestStructureTools:
    """Test structure-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_chemical_structure(self, mock_client, sample_structure_data):
        """Test getting chemical structure."""
        mock_client.get.return_value = sample_structure_data
        
        api = StructureApi()
        result = await api.get_chemical_structure(
            mock_client,
            chemical_id="RYYVLZVUVIJVGH-UHFFFAOYSA-N"
        )
        
        assert result["success"] is True
        assert result["chemical_id"] == "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
        assert "pubchem" in result["structures"]
        assert "chembl" in result["structures"]
    
    @pytest.mark.asyncio
    async def test_search_by_structure(self, mock_client):
        """Test structure search."""
        mock_client.get.return_value = {
            "total": 1,
            "hits": [{"_id": "test-chemical"}]
        }
        
        api = StructureApi()
        result = await api.search_by_structure(
            mock_client,
            structure="CC(=O)OC1=CC=CC=C1C(=O)O",
            structure_type="smiles"
        )
        
        assert result["success"] is True
        assert result["total"] == 1
        assert result["structure_type"] == "smiles"
    
    @pytest.mark.asyncio
    async def test_convert_structure(self, mock_client):
        """Test structure conversion."""
        # Mock search result
        mock_client.get.side_effect = [
            {"total": 1, "hits": [{"_id": "test-id"}]},  # search result
            {"pubchem": {"inchi": "InChI=1S/test"}}      # structure result
        ]
        
        api = StructureApi()
        result = await api.convert_structure(
            mock_client,
            structure="CC(=O)OC1=CC=CC=C1C(=O)O",
            from_format="smiles",
            to_format="inchi"
        )
        
        assert result["success"] is True
        assert result["from_format"] == "smiles"
        assert result["to_format"] == "inchi"
        assert "pubchem" in result["converted_structure"]
    
    @pytest.mark.asyncio
    async def test_convert_structure_not_found(self, mock_client):
        """Test structure conversion when chemical not found."""
        mock_client.get.return_value = {"total": 0, "hits": []}
        
        api = StructureApi()
        result = await api.convert_structure(
            mock_client,
            structure="invalid",
            from_format="smiles",
            to_format="inchi"
        )
        
        assert result["success"] is False
        assert "not found" in result["error"]
    
    @pytest.mark.asyncio
    async def test_get_structure_properties(self, mock_client, sample_structure_properties):
        """Test getting structure properties."""
        mock_client.get.return_value = sample_structure_properties
        
        api = StructureApi()
        result = await api.get_structure_properties(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        assert "basic_properties" in result["structure_properties"]
        assert "physicochemical_properties" in result["structure_properties"]
        assert "structural_features" in result["structure_properties"]
        assert "drug_like_properties" in result["structure_properties"]
    
    @pytest.mark.asyncio
    async def test_search_by_substructure(self, mock_client):
        """Test substructure search."""
        mock_client.get.return_value = {"total": 5, "hits": []}
        
        api = StructureApi()
        result = await api.search_by_substructure(
            mock_client,
            substructure_smiles="C1=CC=CC=C1"
        )
        
        assert result["success"] is True
        assert "note" in result  # Should include note about limitations
        assert result["total"] == 5
    
    @pytest.mark.asyncio
    async def test_calculate_similarity_matrix(self, mock_client):
        """Test similarity matrix calculation."""
        # Set up responses for each chemical separately
        responses = [
            {"pubchem": {"smiles": {"canonical": "CC"}}, "drugbank": {"name": "Chemical 1"}},
            {"chembl": {"smiles": "CCC", "pref_name": "Chemical 2"}}
        ]
        
        # Mock get to return responses in order
        mock_client.get.side_effect = responses
        
        api = StructureApi()
        result = await api.calculate_similarity_matrix(
            mock_client,
            chemical_ids=["chem1", "chem2"]
        )
        
        assert result["success"] is True
        assert "chemicals" in result
        assert len(result["chemicals"]) == 2
        assert result["matrix_size"] == "2x2"
    
    @pytest.mark.asyncio
    async def test_get_stereoisomers(self, mock_client):
        """Test getting stereoisomer information."""
        mock_client.get.side_effect = [
            {
                "pubchem": {
                    "canonical_smiles": "CC",
                    "isomeric_smiles": "C[C@H]",
                    "atom_stereo_count": 1
                }
            },
            {"total": 2, "hits": [{"_id": "isomer1"}, {"_id": "isomer2"}]}
        ]
        
        api = StructureApi()
        result = await api.get_stereoisomers(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        assert "stereochemistry" in result["stereoisomer_data"]
        assert "related_isomers" in result["stereoisomer_data"]