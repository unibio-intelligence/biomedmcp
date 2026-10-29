# tests/test_pathway_tools.py
"""Tests for pathway tools."""

import pytest
from mygene_mcp.tools.pathway import PathwayApi


class TestPathwayTools:
    """Test pathway-related tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_pathway_id_with_source(self, mock_client):
        """Test querying genes by pathway ID with specific source."""
        mock_client.get.return_value = {
            "total": 25,
            "took": 5,
            "hits": [
                {
                    "symbol": "CDK2",
                    "pathway": {
                        "kegg": [
                            {"id": "hsa04110", "name": "Cell cycle"}
                        ]
                    }
                }
            ]
        }
        
        api = PathwayApi()
        result = await api.query_genes_by_pathway(
            mock_client,
            pathway_id="hsa04110",
            source="kegg"
        )
        
        assert result["success"] is True
        assert result["total"] == 25
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'pathway.kegg.id:"hsa04110"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_pathway_id_no_source(self, mock_client):
        """Test querying genes by pathway ID across all sources."""
        mock_client.get.return_value = {
            "total": 30,
            "took": 8,
            "hits": []
        }
        
        api = PathwayApi()
        result = await api.query_genes_by_pathway(
            mock_client,
            pathway_id="R-HSA-69278"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should search across multiple sources
        assert "pathway.kegg.id" in call_args or "pathway.reactome.id" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_pathway_name(self, mock_client):
        """Test querying genes by pathway name."""
        mock_client.get.return_value = {
            "total": 45,
            "took": 10,
            "hits": []
        }
        
        api = PathwayApi()
        result = await api.query_genes_by_pathway(
            mock_client,
            pathway_name="Cell cycle",
            source="kegg"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'pathway.kegg.name:"Cell cycle"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_pathway_name_all_sources(self, mock_client):
        """Test querying genes by pathway name across all sources."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 15,
            "hits": []
        }
        
        api = PathwayApi()
        result = await api.query_genes_by_pathway(
            mock_client,
            pathway_name="Apoptosis"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should include multiple pathway sources
        assert "kegg.name" in call_args
        assert "reactome.name" in call_args
        assert "wikipathways.name" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_pathway_default(self, mock_client):
        """Test default pathway query (all genes with pathway data)."""
        mock_client.get.return_value = {
            "total": 10000,
            "took": 50,
            "hits": []
        }
        
        api = PathwayApi()
        result = await api.query_genes_by_pathway(mock_client)
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:pathway" in call_args
    
    @pytest.mark.asyncio
    async def test_get_gene_pathways_basic(self, mock_client):
        """Test getting pathways for a gene."""
        mock_client.get.return_value = {
            "symbol": "CDK2",
            "name": "cyclin dependent kinase 2",
            "pathway": {
                "kegg": [
                    {"id": "hsa04110", "name": "Cell cycle"},
                    {"id": "hsa05203", "name": "Viral carcinogenesis"}
                ],
                "reactome": [
                    {"id": "R-HSA-69278", "name": "Cell Cycle"}
                ],
                "wikipathways": {
                    "id": "WP179",
                    "name": "Cell cycle"
                }
            }
        }
        
        api = PathwayApi()
        result = await api.get_gene_pathways(
            mock_client,
            gene_id="1017"
        )
        
        assert result["success"] is True
        assert result["total_pathways"] == 4
        assert "kegg" in result["pathways"]["pathways"]
        assert len(result["pathways"]["pathways"]["kegg"]) == 2
        assert "reactome" in result["pathways"]["pathways"]
        assert "wikipathways" in result["pathways"]["pathways"]
        
        mock_client.get.assert_called_once_with(
            "gene/1017",
            params={"fields": "symbol,name,entrezgene,pathway"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_pathways_with_sources(self, mock_client):
        """Test getting pathways with source filter."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "pathway": {
                "kegg": [{"id": "hsa04115", "name": "p53 signaling pathway"}],
                "reactome": [{"id": "R-HSA-69541", "name": "p53-Dependent G1 DNA Damage Response"}],
                "biocarta": [{"id": "h_p53pathway", "name": "p53 Signaling Pathway"}]
            }
        }
        
        api = PathwayApi()
        result = await api.get_gene_pathways(
            mock_client,
            gene_id="7157",
            sources=["kegg", "reactome"]
        )
        
        assert result["success"] is True
        assert "kegg" in result["pathways"]["pathways"]
        assert "reactome" in result["pathways"]["pathways"]
        assert "biocarta" not in result["pathways"]["pathways"]
        assert result["total_pathways"] == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_pathways_single_item(self, mock_client):
        """Test pathways when source returns single item instead of list."""
        mock_client.get.return_value = {
            "symbol": "GENE1",
            "pathway": {
                "kegg": {"id": "hsa00001", "name": "Test pathway"},  # Single dict, not list
                "reactome": [{"id": "R-HSA-12345", "name": "Test"}]
            }
        }
        
        api = PathwayApi()
        result = await api.get_gene_pathways(
            mock_client,
            gene_id="12345"
        )
        
        assert result["success"] is True
        # Single item should be converted to list
        assert isinstance(result["pathways"]["pathways"]["kegg"], list)
        assert len(result["pathways"]["pathways"]["kegg"]) == 1
        assert result["total_pathways"] == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_pathways_no_pathways(self, mock_client):
        """Test gene with no pathway annotations."""
        mock_client.get.return_value = {
            "symbol": "UNKNOWN",
            "name": "unknown gene"
        }
        
        api = PathwayApi()
        result = await api.get_gene_pathways(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["total_pathways"] == 0
        assert result["pathways"]["pathways"] == {}
    
    @pytest.mark.asyncio
    async def test_get_gene_pathways_all_sources(self, mock_client):
        """Test getting pathways from all available sources."""
        mock_client.get.return_value = {
            "symbol": "AKT1",
            "pathway": {
                "kegg": [{"id": "hsa04151", "name": "PI3K-Akt signaling pathway"}],
                "reactome": [{"id": "R-HSA-199418", "name": "Negative regulation of the PI3K/AKT network"}],
                "wikipathways": [{"id": "WP4172", "name": "PI3K-Akt Signaling Pathway"}],
                "netpath": [{"id": "NetPath_11", "name": "TCR signaling"}],
                "biocarta": [{"id": "h_aktPathway", "name": "AKT Signaling Pathway"}],
                "pid": [{"id": "pi3kcipathway", "name": "Class I PI3K signaling events"}]
            }
        }
        
        api = PathwayApi()
        result = await api.get_gene_pathways(
            mock_client,
            gene_id="207"
        )
        
        assert result["success"] is True
        assert len(result["pathway_sources"]) == 6
        assert all(source in result["pathways"]["pathways"] 
                  for source in ["kegg", "reactome", "wikipathways", "netpath", "biocarta", "pid"])