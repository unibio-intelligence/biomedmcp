# tests/test_clinical_tools.py
"""Tests for clinical tools."""

import pytest
from mychem_mcp.tools.clinical import ClinicalApi


class TestClinicalTools:
    """Test clinical trial and FDA approval tools."""
    
    @pytest.mark.asyncio
    async def test_get_clinical_trials(self, mock_client, sample_clinical_trials):
        """Test getting clinical trials."""
        mock_client.get.return_value = sample_clinical_trials
        
        api = ClinicalApi()
        result = await api.get_clinical_trials(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        assert result["total_trials"] == 2
        trials = result["trials"]["clinical_trials"]
        
        assert trials[0]["nct_id"] == "NCT01234567"
        assert trials[0]["phase"] == "Phase 3"
        assert trials[0]["source"] == "drugbank"
    
    @pytest.mark.asyncio
    async def test_get_fda_approval(self, mock_client, sample_fda_approval):
        """Test getting FDA approval status."""
        mock_client.get.return_value = sample_fda_approval
        
        api = ClinicalApi()
        result = await api.get_fda_approval(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        fda_data = result["fda_data"]
        assert fda_data["approval_status"] == "Approved"
        assert fda_data["approval_details"]["max_phase"] == 4
        assert "fda_label" in fda_data["approval_details"]
    
    @pytest.mark.asyncio
    async def test_get_fda_approval_phase3(self, mock_client):
        """Test FDA approval for Phase 3 drug."""
        mock_client.get.return_value = {
            "chembl": {"max_phase": 3}
        }
        
        api = ClinicalApi()
        result = await api.get_fda_approval(
            mock_client,
            chemical_id="test-id"
        )
        
        assert result["success"] is True
        assert result["fda_data"]["approval_status"] == "Phase 3"