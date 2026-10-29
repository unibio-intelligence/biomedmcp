"""Tests for ontology tools."""

import pytest
from mydisease_mcp.tools.ontology import OntologyApi


class TestOntologyTools:
    """Test disease ontology and classification tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_ontology(self, mock_client, sample_ontology_data):
        """Test getting disease ontology."""
        mock_client.get.return_value = sample_ontology_data
        
        api = OntologyApi()
        result = await api.get_disease_ontology(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert "mondo" in result["ontology_data"]["ontologies"]
        assert result["ontology_data"]["ontologies"]["mondo"]["id"] == "MONDO:0007739"
    
    @pytest.mark.asyncio
    async def test_get_disease_classification(self, mock_client):
        """Test getting disease classification."""
        mock_client.get.return_value = {
            "mondo": {
                "parents": [{"id": "MONDO:0000001", "label": "disease"}],
                "children": [{"id": "MONDO:0000002", "label": "child disease"}]
            }
        }
        
        api = OntologyApi()
        result = await api.get_disease_classification(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["classification"]["hierarchy"]["parents"]) == 1
        assert len(result["classification"]["hierarchy"]["children"]) == 1
    
    @pytest.mark.asyncio
    async def test_get_related_diseases(self, mock_client):
        """Test getting related diseases."""
        # Mock initial disease
        mock_client.get.side_effect = [
            {
                "name": "Test Disease",
                "mondo": {"parents": [{"id": "MONDO:0000001"}]},
                "gene": [{"symbol": "GENE1"}]
            },
            # Mock sibling search
            {
                "hits": [
                    {"_id": "sibling1", "name": "Sibling Disease"}
                ]
            },
            # Mock gene-related search
            {
                "hits": [
                    {"_id": "gene_related", "name": "Gene Related", "gene": [{"symbol": "GENE1"}]}
                ]
            }
        ]
        
        api = OntologyApi()
        result = await api.get_related_diseases(
            mock_client,
            disease_id="test-id",
            relationship_type="all"
        )
        
        assert result["success"] is True
        assert len(result["related_diseases"]["related_by_hierarchy"]) > 0
        assert len(result["related_diseases"]["related_by_genes"]) > 0
    
    @pytest.mark.asyncio
    async def test_navigate_disease_hierarchy(self, mock_client):
        """Test navigating disease hierarchy."""
        mock_client.get.side_effect = [
            {"name": "Current Disease", "mondo": {"parents": [{"id": "parent1", "label": "Parent"}]}},
            {"name": "Parent Disease", "mondo": {"parents": [{"id": "grandparent1", "label": "Grandparent"}]}}
        ]
        
        api = OntologyApi()
        result = await api.navigate_disease_hierarchy(
            mock_client,
            disease_id="test-id",
            direction="up",
            levels=2
        )
        
        assert result["success"] is True
        assert len(result["hierarchy"]["path"]) >= 2
        assert result["hierarchy"]["path"][0]["disease_name"] == "Current Disease"