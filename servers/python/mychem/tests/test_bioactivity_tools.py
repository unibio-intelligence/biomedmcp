# tests/test_bioactivity_tools.py
"""Tests for bioactivity tools."""

import pytest
from mychem_mcp.tools.bioactivity import BioactivityApi


class TestBioactivityTools:
    """Test bioactivity and assay tools."""
    
    @pytest.mark.asyncio
    async def test_get_bioassay_data(self, mock_client, sample_bioactivity_data):
        """Test getting bioassay data."""
        mock_client.get.return_value = sample_bioactivity_data
        
        api = BioactivityApi()
        result = await api.get_bioassay_data(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        bioassay = result["bioassay_data"]
        assert bioassay["chemical_id"] == "test-id"
        assert len(bioassay["activities"]) == 2
        
        # Check ChEMBL activity
        chembl_activity = bioassay["activities"][0]
        assert chembl_activity["source"] == "chembl"
        assert chembl_activity["target_name"] == "Cyclooxygenase-2"
        assert chembl_activity["activity_type"] == "IC50"
        assert chembl_activity["value"] == "50"
        
        # Check summary
        assert bioassay["assay_summary"]["total_assays"] == 2
        assert bioassay["assay_summary"]["active_assays"] == 2
    
    @pytest.mark.asyncio
    async def test_get_bioassay_data_with_filters(self, mock_client):
        """Test getting bioassay data with filters."""
        mock_client.get.return_value = {
            "chembl": {
                "activities": [
                    {
                        "standard_type": "IC50",
                        "target_type": "SINGLE PROTEIN",
                        "standard_value": "10"
                    },
                    {
                        "standard_type": "EC50",
                        "target_type": "PROTEIN COMPLEX",
                        "standard_value": "100"
                    }
                ]
            }
        }
        
        api = BioactivityApi()
        result = await api.get_bioassay_data(
            mock_client,
            chemical_id="test-id",
            activity_type="IC50",
            target_type="SINGLE PROTEIN",
            min_potency=50
        )
        
        # Should only include IC50 for single protein with value < 50
        assert len(result["bioassay_data"]["activities"]) == 1
    
    @pytest.mark.asyncio
    async def test_search_active_compounds(self, mock_client):
        """Test searching for active compounds."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "chem1",
                    "chembl": {
                        "molecule_chembl_id": "CHEMBL1",
                        "activities": [
                            {
                                "target_pref_name": "COX-2",
                                "standard_type": "IC50",
                                "standard_value": "50",
                                "standard_units": "nM"
                            }
                        ]
                    },
                    "drugbank": {"name": "Test Drug"}
                }
            ]
        }
        
        api = BioactivityApi()
        result = await api.search_active_compounds(
            mock_client,
            target_name="COX-2",
            activity_type="IC50",
            max_value=100,
            units="nM"
        )
        
        assert result["success"] is True
        assert result["total_found"] == 1
        compounds = result["active_compounds"]
        assert compounds[0]["name"] == "Test Drug"
        assert compounds[0]["relevant_activities"][0]["value"] == 50.0
    
    @pytest.mark.asyncio
    async def test_compare_compound_activities(self, mock_client):
        """Test comparing activities across compounds."""
        # Mock responses for two compounds
        mock_client.get.side_effect = [
            {
                "chembl": {
                    "pref_name": "Drug 1",
                    "activities": [
                        {
                            "target_pref_name": "Target A",
                            "standard_type": "IC50",
                            "standard_value": "10",
                            "standard_units": "nM"
                        }
                    ]
                }
            },
            {
                "drugbank": {
                    "name": "Drug 2"
                },
                "chembl": {
                    "activities": [
                        {
                            "target_pref_name": "Target A",
                            "standard_type": "IC50",
                            "standard_value": "50",
                            "standard_units": "nM"
                        }
                    ]
                }
            }
        ]
        
        api = BioactivityApi()
        result = await api.compare_compound_activities(
            mock_client,
            chemical_ids=["chem1", "chem2"]
        )
        
        assert result["success"] is True
        comparison = result["comparison"]
        assert len(comparison["compounds"]) == 2
        assert "Target A" in comparison["target_summary"]
        assert comparison["target_summary"]["Target A"]["compounds_tested"] == 2