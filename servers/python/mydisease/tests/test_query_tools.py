"""Tests for query tools."""

import pytest
from mydisease_mcp.tools.query import QueryApi


class TestQueryTools:
    """Test query-related tools."""
    
    @pytest.mark.asyncio
    async def test_search_disease(self, mock_client, sample_disease_hit):
        """Test basic disease search."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 5,
            "hits": [sample_disease_hit]
        }
        
        api = QueryApi()
        result = await api.search_disease(mock_client, q="Huntington")
        
        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["hits"]) == 1
        assert result["hits"][0]["name"] == "Huntington disease"
        
        mock_client.get.assert_called_once_with(
            "query",
            params={
                "q": "Huntington",
                "fields": "_id,name,mondo,orphanet,omim,umls.cui,disgenet",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_search_by_field(self, mock_client):
        """Test search by specific fields."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 2,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.search_by_field(
            mock_client,
            field_queries={
                "mondo.mondo": "MONDO:0007739",
                "inheritance.inheritance_type": "Autosomal dominant"
            },
            operator="AND"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "mondo.mondo:MONDO:0007739" in call_args
        assert 'inheritance.inheritance_type:"Autosomal dominant"' in call_args
        assert " AND " in call_args
    
    @pytest.mark.asyncio
    async def test_search_by_phenotype(self, mock_client):
        """Test searching by phenotype."""
        mock_client.get.return_value = {"total": 5, "hits": []}
        
        api = QueryApi()
        result = await api.search_by_phenotype(
            mock_client,
            phenotypes=["Seizures", "Hypotonia"],
            match_all=False
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "Seizures" in call_args
        assert "Hypotonia" in call_args
        assert " OR " in call_args
    
    @pytest.mark.asyncio
    async def test_get_field_statistics(self, mock_client):
        """Test getting field statistics."""
        mock_client.get.return_value = {
            "total": 30000,
            "took": 50,
            "hits": [],
            "facets": {
                "inheritance.inheritance_type": {
                    "total": 5,
                    "terms": [
                        {"term": "Autosomal dominant", "count": 12000},
                        {"term": "Autosomal recessive", "count": 10000},
                        {"term": "X-linked", "count": 3000}
                    ]
                }
            }
        }
        
        api = QueryApi()
        result = await api.get_field_statistics(
            mock_client,
            field="inheritance.inheritance_type"
        )
        
        assert result["success"] is True
        assert result["field"] == "inheritance.inheritance_type"
        assert result["total_diseases"] == 30000
        assert len(result["top_values"]) == 3
        assert result["top_values"][0]["value"] == "Autosomal dominant"
        assert result["top_values"][0]["percentage"] == 40.0