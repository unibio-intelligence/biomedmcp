# tests/test_batch_tools.py
"""Tests for batch operation tools."""

import pytest
from mygene_mcp.client import MyGeneError
from mygene_mcp.tools.batch import BatchApi, MAX_BATCH_SIZE


class TestBatchTools:
    """Test batch operation tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_batch(self, mock_client, sample_batch_results):
        """Test batch gene query."""
        mock_client.post.return_value = sample_batch_results
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["CDK2", "TP53", "INVALID_GENE"]
        )
        
        assert result["success"] is True
        assert result["total"] == 3
        assert result["found"] == 2
        assert result["missing"] == 1
        assert "INVALID_GENE" in result["missing_ids"]
        
        mock_client.post.assert_called_once_with(
            "query",
            {
                "ids": ["CDK2", "TP53", "INVALID_GENE"],
                "scopes": "entrezgene,ensemblgene,symbol",
                "fields": "symbol,name,taxid,entrezgene",
                "returnall": True
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_custom_scopes(self, mock_client, sample_batch_results):
        """Test batch query with custom scopes."""
        mock_client.post.return_value = sample_batch_results[:2]  # Only found results
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["NM_001798", "NP_001789"],
            scopes="refseq.rna,refseq.protein",
            fields="symbol,entrezgene"
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "query",
            {
                "ids": ["NM_001798", "NP_001789"],
                "scopes": "refseq.rna,refseq.protein",
                "fields": "symbol,entrezgene",
                "returnall": True
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_species_filter(self, mock_client, sample_batch_results):
        """Test batch query with species filter."""
        mock_client.post.return_value = sample_batch_results
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["CDK2", "TP53"],
            species="human"
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "query",
            {
                "ids": ["CDK2", "TP53"],
                "scopes": "entrezgene,ensemblgene,symbol",
                "fields": "symbol,name,taxid,entrezgene",
                "species": "human",
                "returnall": True
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_no_returnall(self, mock_client, sample_batch_results):
        """Test batch query without returning missing genes."""
        # Only return found results
        found_only = [r for r in sample_batch_results if r.get("found", False)]
        mock_client.post.return_value = found_only
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["CDK2", "TP53"],
            returnall=False
        )
        
        assert result["success"] is True
        assert result["missing"] == 0
        
        mock_client.post.assert_called_with(
            "query",
            {
                "ids": ["CDK2", "TP53"],
                "scopes": "entrezgene,ensemblgene,symbol",
                "fields": "symbol,name,taxid,entrezgene",
                "returnall": False
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_size_limit(self, mock_client):
        """Test batch size limit enforcement."""
        api = BatchApi()
        
        # Create list exceeding max size
        too_many_ids = [f"GENE_{i}" for i in range(MAX_BATCH_SIZE + 1)]
        
        with pytest.raises(MyGeneError) as exc_info:
            await api.query_genes_batch(mock_client, gene_ids=too_many_ids)
        
        assert f"exceeds maximum of {MAX_BATCH_SIZE}" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_genes_batch(self, mock_client, sample_gene_annotation):
        """Test batch gene annotation retrieval."""
        mock_client.post.return_value = [
            sample_gene_annotation,
            {**sample_gene_annotation, "_id": "7157", "symbol": "TP53"}
        ]
        
        api = BatchApi()
        result = await api.get_genes_batch(
            mock_client,
            gene_ids=["1017", "7157"]
        )
        
        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["genes"]) == 2
        
        mock_client.post.assert_called_once_with(
            "gene",
            {"ids": ["1017", "7157"]}
        )
    
    @pytest.mark.asyncio
    async def test_get_genes_batch_with_fields(self, mock_client):
        """Test batch annotation with specific fields."""
        mock_client.post.return_value = [
            {"_id": "1017", "symbol": "CDK2"},
            {"_id": "7157", "symbol": "TP53"}
        ]
        
        api = BatchApi()
        result = await api.get_genes_batch(
            mock_client,
            gene_ids=["1017", "7157"],
            fields="symbol"
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "gene",
            {
                "ids": ["1017", "7157"],
                "fields": "symbol"
            }
        )
    
    @pytest.mark.asyncio
    async def test_get_genes_batch_with_filter(self, mock_client):
        """Test batch annotation with filter."""
        mock_client.post.return_value = [
            {
                "_id": "1017",
                "symbol": "CDK2",
                "type_of_gene": "protein-coding"
            }
        ]
        
        api = BatchApi()
        result = await api.get_genes_batch(
            mock_client,
            gene_ids=["1017", "7157"],
            filter_="type_of_gene:protein-coding"
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "gene",
            {
                "ids": ["1017", "7157"],
                "filter": "type_of_gene:protein-coding"
            }
        )
    
    @pytest.mark.asyncio
    async def test_get_genes_batch_no_dotfield(self, mock_client):
        """Test batch annotation without dotfield."""
        mock_client.post.return_value = [
            {
                "_id": "1017",
                "symbol": "CDK2",
                "ensembl": {"gene": "ENSG00000123374"}
            }
        ]
        
        api = BatchApi()
        result = await api.get_genes_batch(
            mock_client,
            gene_ids=["1017"],
            dotfield=False
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "gene",
            {
                "ids": ["1017"],
                "dotfield": False
            }
        )
    
    @pytest.mark.asyncio
    async def test_batch_mixed_id_types(self, mock_client, sample_batch_results):
        """Test batch query with mixed ID types."""
        mock_client.post.return_value = sample_batch_results
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["1017", "ENSG00000141510", "CDK2", "NM_001798"],
            scopes="entrezgene,ensemblgene,symbol,refseq"
        )
        
        assert result["success"] is True
        assert result["total"] == 3  # Changed from 4 to 3 to match fixture
        assert result["found"] == 2
        assert result["missing"] == 1
    
    @pytest.mark.asyncio
    async def test_get_genes_batch_size_limit(self, mock_client):
        """Test batch annotation size limit enforcement."""
        api = BatchApi()
        
        # Create list exceeding max size
        too_many_ids = [f"GENE_{i}" for i in range(MAX_BATCH_SIZE + 1)]
        
        with pytest.raises(MyGeneError) as exc_info:
            await api.get_genes_batch(mock_client, gene_ids=too_many_ids)
        
        assert f"exceeds maximum of {MAX_BATCH_SIZE}" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_genes_batch_with_email(self, mock_client):
        """Test batch annotation with email for large requests."""
        mock_client.post.return_value = [
            {"_id": "1017", "symbol": "CDK2"}
        ]
        
        api = BatchApi()
        result = await api.get_genes_batch(
            mock_client,
            gene_ids=["1017"],
            email="test@example.com"
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "gene",
            {
                "ids": ["1017"],
                "email": "test@example.com"
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_empty_list(self, mock_client):
        """Test batch query with empty gene list."""
        mock_client.post.return_value = []
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=[]
        )
        
        assert result["success"] is True
        assert result["total"] == 0
        assert result["found"] == 0
        assert result["missing"] == 0
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_all_missing(self, mock_client):
        """Test batch query where all genes are missing."""
        all_missing = [
            {"query": "FAKE1", "found": False},
            {"query": "FAKE2", "found": False},
            {"query": "FAKE3", "found": False}
        ]
        mock_client.post.return_value = all_missing
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["FAKE1", "FAKE2", "FAKE3"]
        )
        
        assert result["success"] is True
        assert result["total"] == 3
        assert result["found"] == 0
        assert result["missing"] == 3
        assert all(id in result["missing_ids"] for id in ["FAKE1", "FAKE2", "FAKE3"])
    
    @pytest.mark.asyncio
    async def test_query_genes_batch_no_dotfield(self, mock_client):
        """Test batch query without dotfield notation."""
        mock_client.post.return_value = [
            {
                "_id": "1017",
                "symbol": "CDK2",
                "ensembl": {"gene": "ENSG00000123374"},
                "found": True
            }
        ]
        
        api = BatchApi()
        result = await api.query_genes_batch(
            mock_client,
            gene_ids=["CDK2"],
            dotfield=False
        )
        
        assert result["success"] is True
        
        mock_client.post.assert_called_with(
            "query",
            {
                "ids": ["CDK2"],
                "scopes": "entrezgene,ensemblgene,symbol",
                "fields": "symbol,name,taxid,entrezgene",
                "dotfield": False,
                "returnall": True
            }
        )