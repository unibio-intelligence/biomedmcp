# tests/test_annotation_tools.py
"""Tests for annotation tools."""

import pytest
from mygene_mcp.tools.annotation import AnnotationApi


class TestAnnotationTools:
    """Test annotation-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_by_entrez(self, mock_client, sample_gene_annotation):
        """Test getting gene annotation by Entrez ID."""
        mock_client.get.return_value = sample_gene_annotation
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(mock_client, gene_id="1017")
        
        assert result["success"] is True
        assert result["gene"]["entrezgene"] == 1017
        assert result["gene"]["symbol"] == "CDK2"
        
        mock_client.get.assert_called_once_with("gene/1017", params={})
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_by_ensembl(self, mock_client, sample_gene_annotation):
        """Test getting gene annotation by Ensembl ID."""
        mock_client.get.return_value = sample_gene_annotation
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(
            mock_client,
            gene_id="ENSG00000123374"
        )
        
        assert result["success"] is True
        assert result["gene"]["ensembl"]["gene"] == "ENSG00000123374"
        
        mock_client.get.assert_called_once_with(
            "gene/ENSG00000123374",
            params={}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_with_fields(self, mock_client):
        """Test getting specific fields only."""
        mock_client.get.return_value = {
            "_id": "1017",
            "symbol": "CDK2",
            "name": "cyclin dependent kinase 2"
        }
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(
            mock_client,
            gene_id="1017",
            fields="symbol,name"
        )
        
        assert result["success"] is True
        assert "symbol" in result["gene"]
        assert "name" in result["gene"]
        
        mock_client.get.assert_called_with(
            "gene/1017",
            params={"fields": "symbol,name"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_with_species(self, mock_client, sample_gene_annotation):
        """Test gene annotation with species filter."""
        mock_client.get.return_value = sample_gene_annotation
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(
            mock_client,
            gene_id="1017",
            species="human"
        )
        
        assert result["success"] is True
        assert result["gene"]["taxid"] == 9606  # Human taxid
        
        mock_client.get.assert_called_with(
            "gene/1017",
            params={"species": "human"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_no_dotfield(self, mock_client):
        """Test disabling dotfield notation."""
        mock_client.get.return_value = {
            "_id": "1017",
            "symbol": "CDK2",
            "ensembl": {
                "gene": "ENSG00000123374"
            }
        }
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(
            mock_client,
            gene_id="1017",
            dotfield=False
        )
        
        assert result["success"] is True
        
        mock_client.get.assert_called_with(
            "gene/1017",
            params={"dotfield": "false"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_retired_id(self, mock_client):
        """Test annotation for retired gene ID."""
        # Simulating a retired ID that redirects to new one
        mock_client.get.return_value = {
            "_id": "1017",
            "symbol": "CDK2",
            "retired": 1234,  # Old ID
            "entrezgene": 1017  # New ID
        }
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(mock_client, gene_id="1234")
        
        assert result["success"] is True
        assert result["gene"]["entrezgene"] == 1017
    
    @pytest.mark.asyncio
    async def test_get_gene_annotation_all_fields(self, mock_client, sample_gene_annotation):
        """Test getting all available fields."""
        mock_client.get.return_value = sample_gene_annotation
        
        api = AnnotationApi()
        result = await api.get_gene_annotation(
            mock_client,
            gene_id="1017",
            fields=None  # Should return all fields
        )
        
        assert result["success"] is True
        assert "genomic_pos" in result["gene"]
        assert "refseq" in result["gene"]
        assert "ensembl" in result["gene"]