"""Tests for clinical tools."""

import pytest
from mydisease_mcp.tools.clinical import ClinicalApi


class TestClinicalTools:
    """Test clinical information tools."""
    
    @pytest.mark.asyncio
    async def test_get_clinical_significance(self, mock_client):
        """Test getting clinical significance."""
        mock_client.get.return_value = {
            "clinvar": {
                "variant": [
                    {"clinical_significance": "Pathogenic"},
                    {"clinical_significance": "Likely pathogenic"},
                    {"clinical_significance": "Benign"}
                ]
            }
        }
        
        api = ClinicalApi()
        result = await api.get_clinical_significance(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["clinical_data"]["disease_id"] == "test-id"
        assert "Pathogenic" in result["clinical_data"]["clinvar_summary"]
        assert result["clinical_data"]["clinvar_summary"]["Pathogenic"] == 1
    
    @pytest.mark.asyncio
    async def test_get_diagnostic_criteria(self, mock_client, sample_clinical_data):
        """Test getting diagnostic criteria."""
        mock_client.get.return_value = sample_clinical_data
        
        api = ClinicalApi()
        result = await api.get_diagnostic_criteria(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["diagnostic_info"]["diagnostic_criteria"] == "Clinical diagnosis based on..."
    
    @pytest.mark.asyncio
    async def test_get_disease_prognosis(self, mock_client):
        """Test getting disease prognosis."""
        mock_client.get.return_value = {
            "prognosis": "Generally favorable",
            "life_expectancy": "Normal",
            "disease_course": "Progressive",
            "severity": "Moderate"
        }
        
        api = ClinicalApi()
        result = await api.get_disease_prognosis(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["prognosis_data"]["prognosis"] == "Generally favorable"
        assert result["prognosis_data"]["life_expectancy"] == "Normal"
    
    @pytest.mark.asyncio
    async def test_get_treatment_options(self, mock_client):
        """Test getting treatment options."""
        mock_client.get.return_value = {
            "treatment": ["Symptomatic treatment"],
            "drug_treatment": [
                {"name": "Drug A", "approved": True}
            ]
        }
        
        api = ClinicalApi()
        result = await api.get_treatment_options(
            mock_client,
            disease_id="test-id",
            include_experimental=False
        )
        
        assert result["success"] is True
        assert len(result["treatment_options"]["standard_treatments"]) == 1
        assert len(result["treatment_options"]["drug_treatments"]) == 1
    
    @pytest.mark.asyncio
    async def test_get_clinical_trials(self, mock_client):
        """Test getting clinical trials."""
        mock_client.get.return_value = {
            "clinical_trials": [
                {
                    "trial_id": "NCT12345678",
                    "title": "Test Trial",
                    "status": "recruiting"
                }
            ]
        }
        
        api = ClinicalApi()
        result = await api.get_clinical_trials(
            mock_client,
            disease_id="test-id",
            status="recruiting"
        )
        
        assert result["success"] is True
        assert len(result["trials"]["active_trials"]) == 1
        assert result["trials"]["active_trials"][0]["status"] == "recruiting"