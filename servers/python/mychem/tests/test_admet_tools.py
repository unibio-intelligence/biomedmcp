# tests/test_admet_tools.py
"""Tests for ADMET tools."""

import pytest
from mychem_mcp.tools.admet import ADMETApi


class TestADMETTools:
    """Test ADMET property tools."""
    
    @pytest.mark.asyncio
    async def test_get_admet_properties(self, mock_client, sample_admet_data):
        """Test getting ADMET properties."""
        mock_client.get.return_value = sample_admet_data
        
        api = ADMETApi()
        result = await api.get_admet_properties(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        admet = result["admet_properties"]
        assert admet["chemical_id"] == "test-id"
        assert "absorption" in admet
        assert "distribution" in admet
        assert "metabolism" in admet
        assert "excretion" in admet
        assert "toxicity" in admet
        assert "physicochemical" in admet
        
        # Check ChEMBL data
        assert admet["absorption"]["chembl"]["bioavailability"] == "High"
        assert admet["metabolism"]["chembl"]["cyp_substrate"] == ["CYP2C9", "CYP3A4"]
        
        # Check physicochemical
        assert admet["physicochemical"]["molecular_weight"] == 180.16
        assert admet["physicochemical"]["logp"] == 1.2
    
    @pytest.mark.asyncio
    async def test_predict_toxicity(self, mock_client):
        """Test toxicity prediction."""
        mock_client.get.return_value = {
            "chembl": {"toxicity": {"class": "Low"}},
            "drugbank": {"toxicity": "Low toxicity"},
            "pubchem": {"ld50": "200 mg/kg"},
            "ghs": {"hazard_statements": ["H302"]}
        }
        
        api = ADMETApi()
        result = await api.predict_toxicity(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        toxicity = result["toxicity_data"]
        assert toxicity["chemical_id"] == "test-id"
        assert toxicity["chembl_toxicity"]["class"] == "Low"
        assert toxicity["acute_toxicity"]["ld50"] == "200 mg/kg"
        assert "H302" in toxicity["hazard_classification"]["ghs"]