# tests/test_biological_context_tools.py
"""Tests for biological context tools."""

import pytest
from mychem_mcp.tools.biological_context import BiologicalContextApi


class TestBiologicalContextTools:
    """Test biological context, pathway, and disease tools."""
    
    @pytest.mark.asyncio
    async def test_get_pathway_associations(self, mock_client, sample_pathway_data):
        """Test getting pathway associations."""
        mock_client.get.return_value = sample_pathway_data
        
        api = BiologicalContextApi()
        result = await api.get_pathway_associations(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        pathways = result["pathway_associations"]
        assert pathways["chemical_id"] == "test-id"
        assert len(pathways["pathways"]) == 2
        assert pathways["pathways"][0]["source"] == "pharmgkb"
        assert len(pathways["enzymes"]) == 1
        assert pathways["enzymes"][0]["gene_name"] == "PTGS1"
    
    @pytest.mark.asyncio
    async def test_get_disease_associations(self, mock_client, sample_disease_data):
        """Test getting disease associations."""
        mock_client.get.return_value = sample_disease_data
        
        api = BiologicalContextApi()
        result = await api.get_disease_associations(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        diseases = result["disease_associations"]
        assert len(diseases["approved_indications"]) == 1
        assert diseases["pharmacodynamics"] is None  # Not in sample
        assert len(diseases["therapeutic_categories"]) == 2
        assert "Analgesics" in diseases["therapeutic_categories"]
    
    @pytest.mark.asyncio
    async def test_search_by_indication(self, mock_client):
        """Test searching drugs by indication."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "chem1",
                    "drugbank": {
                        "name": "Test Drug",
                        "indication": "For pain relief",
                        "groups": ["approved"]
                    },
                    "chembl": {"max_phase": 4}
                }
            ]
        }
        
        api = BiologicalContextApi()
        result = await api.search_by_indication(
            mock_client,
            indication="pain"
        )
        
        assert result["success"] is True
        assert result["total_found"] == 1
        assert result["drugs"][0]["name"] == "Test Drug"
        assert "approved" in result["drugs"][0]["status"]
    
    @pytest.mark.asyncio
    async def test_get_mechanism_of_action(self, mock_client):
        """Test getting mechanism of action."""
        mock_client.get.return_value = {
            "drugbank": {
                "mechanism_of_action": "Inhibits COX enzymes",
                "targets": [
                    {
                        "name": "Prostaglandin G/H synthase 1",
                        "gene_name": "PTGS1",
                        "actions": ["inhibitor"],
                        "organism": "Human"
                    }
                ]
            },
            "chembl": {
                "drug_mechanisms": [
                    {
                        "action_type": "INHIBITOR",
                        "mechanism_of_action": "Cyclooxygenase inhibitor",
                        "target_name": "Cyclooxygenase-1"
                    }
                ]
            }
        }
        
        api = BiologicalContextApi()
        result = await api.get_mechanism_of_action(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        moa = result["mechanism_of_action"]
        assert len(moa["mechanisms"]) == 2
        assert moa["mechanisms"][0]["source"] == "drugbank"
        assert len(moa["primary_targets"]) == 1
        assert moa["primary_targets"][0]["gene_name"] == "PTGS1"
    
    @pytest.mark.asyncio
    async def test_find_drugs_by_target_class(self, mock_client):
        """Test finding drugs by target class."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "chem1",
                    "chembl": {
                        "pref_name": "Kinase Inhibitor 1",
                        "target_class": ["Kinase"],
                        "max_phase": 4,
                        "drug_mechanisms": [
                            {
                                "action_type": "INHIBITOR",
                                "target_name": "Protein kinase A"
                            }
                        ]
                    }
                }
            ]
        }
        
        api = BiologicalContextApi()
        result = await api.find_drugs_by_target_class(
            mock_client,
            target_class="Kinase"
        )
        
        assert result["success"] is True
        assert result["total_found"] == 1
        drug = result["drugs"][0]
        assert drug["name"] == "Kinase Inhibitor 1"
        assert "Kinase" in drug["target_classes"]
        assert len(drug["mechanisms"]) == 1