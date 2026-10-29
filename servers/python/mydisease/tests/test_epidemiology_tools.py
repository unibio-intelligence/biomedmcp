"""Tests for epidemiology tools."""

import pytest
from mydisease_mcp.tools.epidemiology import EpidemiologyApi


class TestEpidemiologyTools:
    """Test epidemiological data tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_prevalence(self, mock_client, sample_epidemiology_data):
        """Test getting disease prevalence."""
        mock_client.get.return_value = sample_epidemiology_data
        
        api = EpidemiologyApi()
        result = await api.get_disease_prevalence(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["prevalence_data"]["disease_id"] == "test-id"
        assert result["prevalence_data"]["global_prevalence"]["value"] == "1-9 / 100 000"
    
    @pytest.mark.asyncio
    async def test_get_disease_incidence(self, mock_client):
        """Test getting disease incidence."""
        mock_client.get.return_value = {
            "incidence": [
                {
                    "value": "0.38 per 100,000",
                    "year": "2020",
                    "region": "Europe"
                }
            ]
        }
        
        api = EpidemiologyApi()
        result = await api.get_disease_incidence(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["incidence_data"]["annual_incidence"]) == 1
        assert result["incidence_data"]["annual_incidence"][0]["year"] == "2020"
    
    @pytest.mark.asyncio
    async def test_get_demographic_data(self, mock_client):
        """Test getting demographic data."""
        mock_client.get.return_value = {
            "age_of_onset": "Adult",
            "sex_ratio": "M:F = 1:1",
            "ethnicity": [
                {"population": "European", "frequency": "Higher"}
            ]
        }
        
        api = EpidemiologyApi()
        result = await api.get_demographic_data(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert result["demographics"]["age_of_onset"] == "Adult"
        assert result["demographics"]["sex_distribution"] == "M:F = 1:1"
        assert len(result["demographics"]["ethnic_distribution"]) == 1
    
    @pytest.mark.asyncio
    async def test_get_geographic_distribution(self, mock_client):
        """Test getting geographic distribution."""
        mock_client.get.return_value = {
            "geographic_distribution": [
                {
                    "region": "Europe",
                    "prevalence": "0.01",
                    "status": "endemic"
                }
            ],
            "prevalence": [
                {
                    "region": "North America",
                    "value": "0.005"
                }
            ]
        }
        
        api = EpidemiologyApi()
        result = await api.get_geographic_distribution(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["geographic_distribution"]["regions"]) == 2
        assert "Europe" in result["geographic_distribution"]["endemic_areas"]