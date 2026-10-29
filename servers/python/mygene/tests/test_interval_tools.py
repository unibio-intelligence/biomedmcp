# tests/test_interval_tools.py
"""Tests for genomic interval query tools."""

import pytest
from mygene_mcp.tools.interval import IntervalApi


class TestIntervalTools:
    """Test genomic interval query tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_basic(self, mock_client):
        """Test basic interval query."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 10,
            "hits": [
                {"symbol": "GENE1", "genomic_pos": {"chr": "1", "start": 1000000}},
                {"symbol": "GENE2", "genomic_pos": {"chr": "1", "start": 1500000}},
                {"symbol": "GENE3", "genomic_pos": {"chr": "1", "start": 1800000}}
            ]
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="1",
            start=1000000,
            end=2000000
        )
        
        assert result["success"] is True
        assert result["total"] == 5
        assert len(result["hits"]) == 3
        assert result["interval"]["chr"] == "1"
        assert result["interval"]["start"] == 1000000
        assert result["interval"]["end"] == 2000000
        
        mock_client.get.assert_called_once_with(
            "query",
            params={
                "q": "chr1:1000000-2000000",
                "species": "human",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_with_chr_prefix(self, mock_client):
        """Test interval query when chr prefix is already included."""
        mock_client.get.return_value = {"total": 0, "took": 5, "hits": []}
        
        api = IntervalApi()
        await api.query_genes_by_interval(
            mock_client,
            chr="chr1",
            start=1000000,
            end=2000000
        )
        
        # Should handle chr prefix correctly
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "chr1:1000000-2000000",  # Not chr1chr1
                "species": "human",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_chromosome_x(self, mock_client):
        """Test interval query on chromosome X."""
        mock_client.get.return_value = {
            "total": 3,
            "took": 8,
            "hits": [
                {"symbol": "XIST"},
                {"symbol": "TSIX"},
                {"symbol": "XACT"}
            ]
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="X",
            start=73000000,
            end=74000000
        )
        
        assert result["success"] is True
        assert result["total"] == 3
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "chrX:73000000-74000000",
                "species": "human",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_mouse(self, mock_client):
        """Test interval query for mouse genes."""
        mock_client.get.return_value = {
            "total": 2,
            "took": 6,
            "hits": [
                {"symbol": "Pax6", "taxid": 10090},
                {"symbol": "Elp4", "taxid": 10090}
            ]
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="2",
            start=105000000,
            end=106000000,
            species="mouse"
        )
        
        assert result["success"] is True
        assert result["interval"]["species"] == "mouse"
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "chr2:105000000-106000000",
                "species": "mouse",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_custom_fields(self, mock_client):
        """Test interval query with custom fields."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 4,
            "hits": [{
                "symbol": "BRCA1",
                "genomic_pos": {
                    "chr": "17",
                    "start": 43044294,
                    "end": 43125483
                }
            }]
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="17",
            start=43000000,
            end=44000000,
            fields="symbol,genomic_pos"
        )
        
        assert result["success"] is True
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "chr17:43000000-44000000",
                "species": "human",
                "fields": "symbol,genomic_pos",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_large_region(self, mock_client):
        """Test interval query for large genomic region."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 50,
            "hits": [{"symbol": f"GENE{i}"} for i in range(10)]
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="1",
            start=1,
            end=50000000,  # 50MB region
            size=50
        )
        
        assert result["success"] is True
        assert result["total"] == 100
        assert len(result["hits"]) == 10  # Limited by size parameter
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "chr1:1-50000000",
                "species": "human",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 50
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_by_interval_no_results(self, mock_client):
        """Test interval query with no genes found."""
        mock_client.get.return_value = {
            "total": 0,
            "took": 3,
            "hits": []
        }
        
        api = IntervalApi()
        result = await api.query_genes_by_interval(
            mock_client,
            chr="Y",
            start=1,
            end=1000  # Very small region
        )
        
        assert result["success"] is True
        assert result["total"] == 0
        assert len(result["hits"]) == 0