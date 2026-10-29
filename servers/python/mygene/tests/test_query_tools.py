# tests/test_query_tools.py
"""Tests for query tools."""

import pytest
from mygene_mcp.tools.query import QueryApi


class TestQueryTools:
    """Test query-related tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_basic(self, mock_client, sample_gene_hit):
        """Test basic gene query."""
        # Setup mock response
        mock_client.get.return_value = {
            "total": 1,
            "took": 5,
            "hits": [sample_gene_hit]
        }
        
        # Execute query
        api = QueryApi()
        result = await api.query_genes(mock_client, q="CDK2")
        
        # Verify
        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["hits"]) == 1
        assert result["hits"][0]["symbol"] == "CDK2"
        
        # Check API was called correctly
        mock_client.get.assert_called_once_with(
            "query",
            params={
                "q": "CDK2",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_with_species(self, mock_client, sample_gene_hit):
        """Test gene query with species filter."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 3,
            "hits": [sample_gene_hit]
        }
        
        api = QueryApi()
        result = await api.query_genes(
            mock_client,
            q="kinase",
            species="human",
            size=5
        )
        
        assert result["success"] is True
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "kinase",
                "fields": "symbol,name,taxid,entrezgene",
                "species": "human",
                "size": 5
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_with_facets(self, mock_client):
        """Test gene query with facets."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 10,
            "hits": [],
            "facets": {
                "taxid": {
                    "terms": [
                        {"term": 9606, "count": 50},
                        {"term": 10090, "count": 30}
                    ]
                }
            }
        }
        
        api = QueryApi()
        result = await api.query_genes(
            mock_client,
            q="kinase",
            facets="taxid",
            facet_size=20,
            size=0
        )
        
        assert result["success"] is True
        assert "facets" in result
        assert "taxid" in result["facets"]
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "kinase",
                "fields": "symbol,name,taxid,entrezgene",
                "facets": "taxid",
                "facet_size": 20,
                "size": 0
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_with_scroll(self, mock_client):
        """Test scrolling query for large results."""
        mock_client.get.return_value = {
            "total": 5000,
            "took": 50,
            "hits": [{"_id": f"gene_{i}"} for i in range(1000)],
            "_scroll_id": "DXF1ZXJ5QW5kRmV0Y2gBAAAAAAAAAD4WYm9laVYtZndUQlNsdDcwakFMNjU1QQ=="
        }
        
        api = QueryApi()
        result = await api.query_genes(
            mock_client,
            q="*",
            fetch_all=True
        )
        
        assert result["success"] is True
        assert result["scroll_id"] is not None
        assert len(result["hits"]) == 1000
        
        # Test scroll continuation
        mock_client.get.return_value = {
            "total": 5000,
            "took": 30,
            "hits": [{"_id": f"gene_{i}"} for i in range(1000, 2000)],
            "_scroll_id": "DXF1ZXJ5QW5kRmV0Y2gBAAAAAAAAAD4WYm9laVYtZndUQlNsdDcwakFMNjU1QQ=="
        }
        
        result2 = await api.query_genes(
            mock_client,
            q="*",
            scroll_id=result["scroll_id"]
        )
        
        assert result2["success"] is True
        assert len(result2["hits"]) == 1000
    
    @pytest.mark.asyncio
    async def test_query_genes_wildcard(self, mock_client):
        """Test wildcard queries."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 8,
            "hits": [
                {"symbol": "CDK1"},
                {"symbol": "CDK2"},
                {"symbol": "CDK3"}
            ]
        }
        
        api = QueryApi()
        result = await api.query_genes(mock_client, q="CDK*")
        
        assert result["success"] is True
        assert result["total"] == 10
        assert all("CDK" in hit["symbol"] for hit in result["hits"])
    
    @pytest.mark.asyncio
    async def test_query_genes_field_specific(self, mock_client, sample_gene_hit):
        """Test field-specific queries."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 3,
            "hits": [sample_gene_hit]
        }
        
        api = QueryApi()
        result = await api.query_genes(mock_client, q="entrezgene:1017")
        
        assert result["success"] is True
        assert result["hits"][0]["entrezgene"] == 1017
    
    @pytest.mark.asyncio
    async def test_query_genes_with_pagination(self, mock_client):
        """Test query with pagination."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 10,
            "hits": [{"_id": f"gene_{i}"} for i in range(10, 20)]
        }
        
        api = QueryApi()
        result = await api.query_genes(
            mock_client,
            q="cancer",
            size=10,
            from_=10
        )
        
        assert result["success"] is True
        assert len(result["hits"]) == 10
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "cancer",
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10,
                "from": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_query_genes_with_custom_fields(self, mock_client):
        """Test query with custom fields."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 5,
            "hits": [{
                "_id": "1017",
                "symbol": "CDK2",
                "ensembl.gene": "ENSG00000123374"
            }]
        }
        
        api = QueryApi()
        result = await api.query_genes(
            mock_client,
            q="CDK2",
            fields="symbol,ensembl.gene"
        )
        
        assert result["success"] is True
        assert "ensembl.gene" in result["hits"][0]
        
    @pytest.mark.asyncio
    async def test_query_genes_empty_results(self, mock_client):
        """Test query with no results."""
        mock_client.get.return_value = {
            "total": 0,
            "took": 2,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.query_genes(mock_client, q="nonexistent_gene_12345")
        
        assert result["success"] is True
        assert result["total"] == 0
        assert len(result["hits"]) == 0
    
    @pytest.mark.asyncio
    async def test_search_by_field_single(self, mock_client):
        """Test search by single field."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 3,
            "hits": [{"interpro": "IPR000001"}]
        }
        
        api = QueryApi()
        result = await api.search_by_field(
            mock_client,
            field_queries={"interpro": "IPR000001"}
        )
        
        assert result["success"] is True
        assert result["total"] == 5
        
        # Check that query was built correctly (no quotes for values without spaces)
        expected_q = 'interpro:IPR000001'
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": expected_q,
                "fields": "symbol,name,taxid,entrezgene",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_search_by_field_multiple_and(self, mock_client):
        """Test search by multiple fields with AND."""
        mock_client.get.return_value = {
            "total": 2,
            "took": 5,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.search_by_field(
            mock_client,
            field_queries={
                "interpro": "IPR000001",
                "pfam": "PF00001"
            },
            operator="AND"
        )
        
        assert result["success"] is True
        
        # Verify the query construction (no quotes for values without spaces)
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "interpro:IPR000001" in call_args
        assert "pfam:PF00001" in call_args
        assert " AND " in call_args

    @pytest.mark.asyncio
    async def test_search_by_field_multiple_or(self, mock_client):
        """Test search by multiple fields with OR."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 4,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.search_by_field(
            mock_client,
            field_queries={
                "symbol": "CDK2",
                "ensembl.gene": "ENSG00000123374"
            },
            operator="OR"
        )
        
        assert result["success"] is True
        
        # Verify the query construction (no quotes for values without spaces)
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "symbol:CDK2" in call_args
        assert "ensembl.gene:ENSG00000123374" in call_args
        assert " OR " in call_args
    
    @pytest.mark.asyncio
    async def test_search_by_field_with_spaces(self, mock_client):
        """Test search with values containing spaces."""
        mock_client.get.return_value = {
            "total": 3,
            "took": 2,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.search_by_field(
            mock_client,
            field_queries={
                "go.BP.term": "cell cycle",
                "name": "cyclin dependent kinase"
            }
        )
        
        assert result["success"] is True
        
        # Check that values with spaces are quoted
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'go.BP.term:"cell cycle"' in call_args
        assert 'name:"cyclin dependent kinase"' in call_args
    
    @pytest.mark.asyncio
    async def test_get_field_statistics(self, mock_client):
        """Test getting field statistics."""
        mock_client.get.return_value = {
            "total": 40000,
            "took": 15,
            "hits": [],
            "facets": {
                "type_of_gene": {
                    "total": 10,
                    "terms": [
                        {"term": "protein-coding", "count": 20000},
                        {"term": "ncRNA", "count": 5000},
                        {"term": "pseudo", "count": 3000}
                    ]
                }
            }
        }
        
        api = QueryApi()
        result = await api.get_field_statistics(
            mock_client,
            field="type_of_gene"
        )
        
        assert result["success"] is True
        assert result["field"] == "type_of_gene"
        assert result["total_genes"] == 40000
        assert len(result["top_values"]) == 3
        
        # Check percentages
        assert result["top_values"][0]["value"] == "protein-coding"
        assert result["top_values"][0]["count"] == 20000
        assert result["top_values"][0]["percentage"] == 50.0
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "*",
                "facets": "type_of_gene",
                "facet_size": 100,
                "size": 0
            }
        )
    
    @pytest.mark.asyncio
    async def test_get_field_statistics_with_species(self, mock_client):
        """Test field statistics with species filter."""
        mock_client.get.return_value = {
            "total": 20000,
            "took": 10,
            "hits": [],
            "facets": {
                "go.CC": {
                    "total": 50,
                    "terms": [
                        {"term": "nucleus", "count": 5000},
                        {"term": "cytoplasm", "count": 4000}
                    ]
                }
            }
        }
        
        api = QueryApi()
        result = await api.get_field_statistics(
            mock_client,
            field="go.CC",
            species="human",
            size=50
        )
        
        assert result["success"] is True
        assert result["field"] == "go.CC"
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "*",
                "facets": "go.CC",
                "facet_size": 50,
                "size": 0,
                "species": "human"
            }
        )