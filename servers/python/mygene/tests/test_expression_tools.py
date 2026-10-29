# tests/test_expression_tools.py
"""Tests for expression tools."""

import pytest
from mygene_mcp.tools.expression import ExpressionApi


class TestExpressionTools:
    """Test expression-related tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_tissue(self, mock_client):
        """Test querying genes by tissue expression."""
        mock_client.get.return_value = {
            "total": 50,
            "took": 10,
            "hits": [
                {
                    "symbol": "BDNF",
                    "hpa": {"tissue": {"brain": "high"}},
                    "gtex": {"tissue": {"brain": 45.2}}
                }
            ]
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(
            mock_client,
            tissue="brain"
        )
        
        assert result["success"] is True
        assert result["total"] == 50
        assert "hpa.tissue" in result["query"]
        assert "brain" in result["query"]
        
        # Verify complex tissue query
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "hpa.tissue" in call_args or "gtex.tissue" in call_args or "biogps.tissue" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_level(self, mock_client):
        """Test querying genes by expression level."""
        mock_client.get.return_value = {
            "total": 30,
            "took": 8,
            "hits": []
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(
            mock_client,
            expression_level="high",
            dataset="hpa"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "hpa.expression_level:\"high\"" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_cell_type(self, mock_client):
        """Test querying genes by cell type."""
        mock_client.get.return_value = {
            "total": 15,
            "took": 5,
            "hits": []
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(
            mock_client,
            cell_type="mitochondria"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "hpa.subcellular_location:\"mitochondria\"" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_dataset(self, mock_client):
        """Test querying genes with data from specific dataset."""
        mock_client.get.return_value = {
            "total": 1000,
            "took": 20,
            "hits": []
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(
            mock_client,
            dataset="gtex"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:gtex" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_combined(self, mock_client):
        """Test combined expression query."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 3,
            "hits": []
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(
            mock_client,
            tissue="liver",
            expression_level="high",
            dataset="hpa",
            species="human"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]
        assert "liver" in call_args["q"]
        assert "high" in call_args["q"]
        assert call_args["species"] == "human"
    
    @pytest.mark.asyncio
    async def test_query_genes_by_expression_default(self, mock_client):
        """Test default expression query."""
        mock_client.get.return_value = {
            "total": 20000,
            "took": 50,
            "hits": []
        }
        
        api = ExpressionApi()
        result = await api.query_genes_by_expression(mock_client)
        
        assert result["success"] is True
        
        # Should query for genes with any expression data
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:hpa" in call_args or "_exists_:gtex" in call_args
    
    @pytest.mark.asyncio
    async def test_get_gene_expression_profile_basic(self, mock_client):
        """Test getting expression profile for a gene."""
        mock_client.get.return_value = {
            "symbol": "CDK2",
            "name": "cyclin dependent kinase 2",
            "entrezgene": 1017,
            "hpa": {
                "tissue": [
                    {"name": "brain", "level": "medium"},
                    {"name": "liver", "level": "low"}
                ],
                "subcellular_location": ["nucleus", "cytoplasm"],
                "rna_tissue_specificity": {"specificity": "low tissue specificity"}
            },
            "gtex": {
                "brain": 25.4,
                "liver": 10.2
            }
        }
        
        api = ExpressionApi()
        result = await api.get_gene_expression_profile(
            mock_client,
            gene_id="1017"
        )
        
        assert result["success"] is True
        assert result["expression_profile"]["gene_id"] == "1017"
        assert result["expression_profile"]["symbol"] == "CDK2"
        
        # Check HPA data processing
        hpa_data = result["expression_profile"]["expression_data"]["hpa"]
        assert len(hpa_data["tissues"]) == 2
        assert hpa_data["subcellular_location"] == ["nucleus", "cytoplasm"]
        
        # Check GTEx data
        assert "gtex" in result["expression_profile"]["expression_data"]
        
        mock_client.get.assert_called_once_with(
            "gene/1017",
            params={"fields": "hpa,gtex,biogps,exac,symbol,name,entrezgene"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_expression_profile_specific_datasets(self, mock_client):
        """Test getting expression profile with specific datasets."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "hpa": {
                "tissue": [{"name": "ubiquitous", "level": "high"}]
            }
        }
        
        api = ExpressionApi()
        result = await api.get_gene_expression_profile(
            mock_client,
            gene_id="7157",
            datasets=["hpa"]
        )
        
        assert result["success"] is True
        
        mock_client.get.assert_called_with(
            "gene/7157",
            params={"fields": "hpa,symbol,name,entrezgene"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_expression_profile_biogps(self, mock_client):
        """Test expression profile with BioGPS data."""
        mock_client.get.return_value = {
            "symbol": "GAPDH",
            "biogps": {
                "104": 1000.5,  # Tissue ID: expression value
                "105": 2000.3
            }
        }
        
        api = ExpressionApi()
        result = await api.get_gene_expression_profile(
            mock_client,
            gene_id="GAPDH"
        )
        
        assert result["success"] is True
        assert "biogps" in result["expression_profile"]["expression_data"]
    
    @pytest.mark.asyncio
    async def test_get_gene_expression_profile_exac(self, mock_client):
        """Test expression profile with ExAC data."""
        mock_client.get.return_value = {
            "symbol": "BRCA1",
            "exac": {
                "expression": {
                    "adipose_tissue": 15.2,
                    "brain": 8.5
                }
            }
        }
        
        api = ExpressionApi()
        result = await api.get_gene_expression_profile(
            mock_client,
            gene_id="672"
        )
        
        assert result["success"] is True
        assert "exac" in result["expression_profile"]["expression_data"]
        assert result["expression_profile"]["expression_data"]["exac"]["adipose_tissue"] == 15.2
    
    @pytest.mark.asyncio
    async def test_get_gene_expression_profile_no_data(self, mock_client):
        """Test expression profile when no expression data available."""
        mock_client.get.return_value = {
            "symbol": "UNKNOWN",
            "name": "unknown gene"
        }
        
        api = ExpressionApi()
        result = await api.get_gene_expression_profile(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["expression_profile"]["expression_data"] == {}