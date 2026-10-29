# tests/test_advanced_tools.py
"""Tests for advanced query tools."""

import pytest
from mygene_mcp.tools.advanced import AdvancedQueryApi


class TestAdvancedTools:
    """Test advanced query tools."""
    
    @pytest.mark.asyncio
    async def test_build_complex_query_must(self, mock_client):
        """Test building query with MUST clauses."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 5,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            must=[
                {"field": "taxid", "value": "9606"},
                {"field": "type_of_gene", "value": "protein-coding"}
            ]
        )
        
        assert result["success"] is True
        assert result["total"] == 10
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "taxid:\"9606\"" in call_args
        assert "type_of_gene:\"protein-coding\"" in call_args
        assert " AND " in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query_should(self, mock_client):
        """Test building query with SHOULD clauses."""
        mock_client.get.return_value = {
            "total": 20,
            "took": 8,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            should=[
                {"field": "symbol", "value": "TP53"},
                {"field": "symbol", "value": "BRCA1"},
                {"field": "symbol", "value": "EGFR"}
            ]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "symbol:\"TP53\"" in call_args
        assert "symbol:\"BRCA1\"" in call_args
        assert "symbol:\"EGFR\"" in call_args
        assert " OR " in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query_must_not(self, mock_client):
        """Test building query with MUST_NOT clauses."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 15,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            must=[{"field": "taxid", "value": "9606"}],
            must_not=[
                {"field": "type_of_gene", "value": "pseudo"},
                {"field": "type_of_gene", "value": "other"}
            ]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "taxid:\"9606\"" in call_args
        assert "NOT type_of_gene:\"pseudo\"" in call_args
        assert "NOT type_of_gene:\"other\"" in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query_combined(self, mock_client):
        """Test building complex query with all clause types."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 3,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            must=[{"field": "taxid", "value": "9606"}],
            should=[
                {"field": "go.BP", "value": "GO:0006468"},
                {"field": "go.MF", "value": "GO:0004672"}
            ],
            must_not=[{"field": "status", "value": "withdrawn"}]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should have all components
        assert "taxid:\"9606\"" in call_args
        assert "GO:0006468" in call_args or "GO:0004672" in call_args
        assert "NOT status:\"withdrawn\"" in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query_with_filters(self, mock_client):
        """Test building query with additional filters."""
        mock_client.get.return_value = {
            "total": 30,
            "took": 10,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            must=[{"field": "symbol", "value": "CDK*"}],
            filters={
                "taxid": [9606, 10090],
                "type_of_gene": "protein-coding"
            }
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "symbol:\"CDK*\"" in call_args
        assert "taxid:\"9606\"" in call_args or "taxid:\"10090\"" in call_args
        assert "type_of_gene:\"protein-coding\"" in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query_with_aggregations(self, mock_client):
        """Test building query with aggregations."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 20,
            "hits": [],
            "facets": {
                "type_of_gene": {
                    "terms": [
                        {"term": "protein-coding", "count": 80},
                        {"term": "ncRNA", "count": 20}
                    ]
                },
                "taxid": {
                    "terms": [
                        {"term": 9606, "count": 60},
                        {"term": 10090, "count": 40}
                    ]
                }
            }
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(
            mock_client,
            must=[{"field": "_exists_", "value": "pathway"}],
            aggregations={
                "type_of_gene": {"size": 10},
                "taxid": {"size": 5}
            }
        )
        
        assert result["success"] is True
        assert "aggregations" in result
        assert "type_of_gene" in result["aggregations"]
        assert "taxid" in result["aggregations"]
        
        call_args = mock_client.get.call_args[1]["params"]
        assert call_args["facets"] == "type_of_gene,taxid"
    
    @pytest.mark.asyncio
    async def test_build_complex_query_empty(self, mock_client):
        """Test building query with no clauses (match all)."""
        mock_client.get.return_value = {
            "total": 50000,
            "took": 100,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.build_complex_query(mock_client)
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert call_args == "*"
    
    @pytest.mark.asyncio
    async def test_query_with_filters_basic(self, mock_client):
        """Test query with basic filters."""
        mock_client.get.return_value = {
            "total": 50,
            "took": 10,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.query_with_filters(
            mock_client,
            q="kinase",
            type_of_gene=["protein-coding"],
            taxid=[9606]
        )
        
        assert result["success"] is True
        assert result["filters_applied"]["type_of_gene"] == ["protein-coding"]
        assert result["filters_applied"]["taxid"] == [9606]
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "kinase" in call_args
        assert "type_of_gene:\"protein-coding\"" in call_args
        assert "taxid:9606" in call_args
    
    @pytest.mark.asyncio
    async def test_query_with_filters_chromosome(self, mock_client):
        """Test query with chromosome filter."""
        mock_client.get.return_value = {
            "total": 200,
            "took": 25,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.query_with_filters(
            mock_client,
            q="cancer",
            chromosome=["1", "2", "X"]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "genomic_pos.chr:\"1\"" in call_args
        assert "genomic_pos.chr:\"2\"" in call_args
        assert "genomic_pos.chr:\"X\"" in call_args
    
    @pytest.mark.asyncio
    async def test_query_with_filters_existence(self, mock_client):
        """Test query with existence filters."""
        mock_client.get.return_value = {
            "total": 80,
            "took": 15,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.query_with_filters(
            mock_client,
            q="*",
            ensembl_gene_exists=True,
            refseq_exists=True,
            has_go_annotation=True,
            has_pathway_annotation=False
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:ensembl.gene" in call_args
        assert "_exists_:refseq" in call_args
        assert "_exists_:go" in call_args
        assert "NOT _exists_:pathway" in call_args
    
    @pytest.mark.asyncio
    async def test_query_with_filters_multiple_gene_types(self, mock_client):
        """Test query with multiple gene type filters."""
        mock_client.get.return_value = {
            "total": 150,
            "took": 20,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.query_with_filters(
            mock_client,
            q="transcription",
            type_of_gene=["protein-coding", "lncRNA", "miRNA"]
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "type_of_gene:\"protein-coding\"" in call_args
        assert "type_of_gene:\"lncRNA\"" in call_args
        assert "type_of_gene:\"miRNA\"" in call_args
        assert " OR " in call_args
    
    @pytest.mark.asyncio
    async def test_query_with_filters_all_filters(self, mock_client):
        """Test query with all available filters."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 2,
            "hits": []
        }
        
        api = AdvancedQueryApi()
        result = await api.query_with_filters(
            mock_client,
            q="BRCA*",
            type_of_gene=["protein-coding"],
            chromosome=["17", "13"],
            taxid=[9606],
            ensembl_gene_exists=True,
            refseq_exists=True,
            has_go_annotation=True,
            has_pathway_annotation=True,
            size=20
        )
        
        assert result["success"] is True
        assert result["total"] == 5
        
        # Check all filters were applied
        filters = result["filters_applied"]
        assert filters["type_of_gene"] == ["protein-coding"]
        assert filters["chromosome"] == ["17", "13"]
        assert filters["taxid"] == [9606]
        assert filters["ensembl_gene_exists"] is True
        assert filters["refseq_exists"] is True
        assert filters["has_go_annotation"] is True
        assert filters["has_pathway_annotation"] is True
        
        # Verify query construction
        call_args = mock_client.get.call_args[1]["params"]
        query = call_args["q"]
        assert "BRCA*" in query
        assert all(filter_term in query for filter_term in [
            "type_of_gene", "genomic_pos.chr", "taxid",
            "_exists_:ensembl", "_exists_:refseq",
            "_exists_:go", "_exists_:pathway"
        ])
        assert call_args["size"] == 20