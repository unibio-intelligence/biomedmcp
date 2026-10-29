"""Tests for pathway tools."""

import pytest
from mydisease_mcp.tools.pathway import PathwayApi


class TestPathwayTools:
    """Test pathway and biological process tools."""
    
    @pytest.mark.asyncio
    async def test_get_disease_pathways(self, mock_client, sample_pathway_data):
        """Test getting disease pathways."""
        mock_client.get.return_value = sample_pathway_data
        
        api = PathwayApi()
        result = await api.get_disease_pathways(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert "kegg" in result["pathways"]["pathways_by_source"]
        assert len(result["pathways"]["all_pathways"]) == 2
    
    @pytest.mark.asyncio
    async def test_search_diseases_by_pathway(self, mock_client):
        """Test searching diseases by pathway."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "kegg_pathway": {
                        "id": "hsa04110",
                        "name": "Cell cycle"
                    }
                }
            ]
        }
        
        api = PathwayApi()
        result = await api.search_diseases_by_pathway(
            mock_client,
            pathway_id="hsa04110",
            pathway_name="Cell cycle"
        )
        
        assert result["success"] is True
        assert result["total_diseases"] == 1
        assert result["diseases"][0]["pathway_associations"][0]["pathway_id"] == "hsa04110"
    
    @pytest.mark.asyncio
    async def test_get_pathway_genes(self, mock_client):
        """Test getting pathway genes."""
        mock_client.get.return_value = {
            "gene": [{"symbol": "GENE1"}],
            "kegg_pathway": {
                "id": "hsa04110",
                "genes": ["GENE1", "GENE2", "GENE3"]
            }
        }
        
        api = PathwayApi()
        result = await api.get_pathway_genes(
            mock_client,
            disease_id="test-id"
        )
        
        assert result["success"] is True
        assert len(result["pathway_genes"]["disease_genes"]) == 1
        assert len(result["pathway_genes"]["all_pathway_genes"]) == 3
        assert "GENE1" in result["pathway_genes"]["overlapping_genes"]
    
    @pytest.mark.asyncio
    async def test_get_pathway_enrichment(self, mock_client):
        """Test pathway enrichment analysis."""
        mock_client.get.return_value = {
            "hits": [
                {
                    "_id": "disease1",
                    "name": "Disease 1",
                    "gene": [{"symbol": "GENE1"}, {"symbol": "GENE2"}],
                    "kegg_pathway": {"id": "hsa04110", "name": "Cell cycle"}
                }
            ]
        }
        
        api = PathwayApi()
        result = await api.get_pathway_enrichment(
            mock_client,
            gene_list=["GENE1", "GENE2", "GENE3"],
            p_value_cutoff=0.05
        )
        
        assert result["success"] is True
        assert len(result["enriched_pathways"]) > 0