# tests/test_query_tools.py
"""Tests for enhanced query tools."""

import pytest
from mychem_mcp.tools.query import QueryApi


class TestQueryTools:
    """Test query-related tools."""
    
    @pytest.mark.asyncio
    async def test_search_chemical_basic(self, mock_client, sample_chemical_hit):
        """Test basic chemical search."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 5,
            "hits": [sample_chemical_hit]
        }
        
        api = QueryApi()
        result = await api.search_chemical(mock_client, q="aspirin")
        
        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["hits"]) == 1
        assert result["hits"][0]["name"] == "Aspirin"
        
        mock_client.get.assert_called_once_with(
            "query",
            params={
                "q": "aspirin",
                "fields": "inchikey,pubchem,chembl,drugbank,name",
                "size": 10
            }
        )
    
    @pytest.mark.asyncio
    async def test_search_chemical_by_inchikey(self, mock_client, sample_chemical_hit):
        """Test searching by InChIKey."""
        mock_client.get.return_value = {
            "total": 1,
            "took": 3,
            "hits": [sample_chemical_hit]
        }
        
        api = QueryApi()
        result = await api.search_chemical(
            mock_client,
            q="BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        )
        
        assert result["success"] is True
        assert result["hits"][0]["_id"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    
    @pytest.mark.asyncio
    async def test_search_chemical_with_pagination(self, mock_client):
        """Test search with pagination."""
        mock_client.get.return_value = {
            "total": 100,
            "took": 10,
            "hits": [{"_id": f"chem_{i}"} for i in range(10, 20)]
        }
        
        api = QueryApi()
        result = await api.search_chemical(
            mock_client,
            q="antibiotic",
            size=10,
            from_=10
        )
        
        assert result["success"] is True
        assert len(result["hits"]) == 10
        
        mock_client.get.assert_called_with(
            "query",
            params={
                "q": "antibiotic",
                "fields": "inchikey,pubchem,chembl,drugbank,name",
                "size": 10,
                "from": 10
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
                "chembl.molecule_chembl_id": "CHEMBL25",
                "drugbank.groups": "approved"
            },
            operator="AND"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "chembl.molecule_chembl_id:CHEMBL25" in call_args
        assert "drugbank.groups:approved" in call_args
        assert " AND " in call_args
    
    @pytest.mark.asyncio
    async def test_get_field_statistics(self, mock_client):
        """Test getting field statistics."""
        mock_client.get.return_value = {
            "total": 150000,
            "took": 50,
            "hits": [],
            "facets": {
                "chembl.molecule_type": {
                    "total": 5,
                    "terms": [
                        {"term": "Small molecule", "count": 120000},
                        {"term": "Antibody", "count": 5000},
                        {"term": "Protein", "count": 3000}
                    ]
                }
            }
        }
        
        api = QueryApi()
        result = await api.get_field_statistics(
            mock_client,
            field="chembl.molecule_type"
        )
        
        assert result["success"] is True
        assert result["field"] == "chembl.molecule_type"
        assert result["total_chemicals"] == 150000
        assert len(result["top_values"]) == 3
        assert result["top_values"][0]["value"] == "Small molecule"
        assert result["top_values"][0]["percentage"] == 80.0
    
    @pytest.mark.asyncio
    async def test_search_by_molecular_properties(self, mock_client):
        """Test search by molecular properties."""
        mock_client.get.return_value = {
            "total": 50,
            "took": 10,
            "hits": []
        }
        
        api = QueryApi()
        result = await api.search_by_molecular_properties(
            mock_client,
            mw_max=500,
            logp_max=5,
            hbd_max=5,
            hba_max=10
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "pubchem.molecular_weight:[* TO 500]" in call_args
        assert "pubchem.xlogp:[* TO 5]" in call_args
        assert "pubchem.h_bond_donor_count:[* TO 5]" in call_args
        assert "pubchem.h_bond_acceptor_count:[* TO 10]" in call_args
    
    @pytest.mark.asyncio
    async def test_build_complex_query(self, mock_client):
        """Test building complex queries."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 5,
            "hits": []
        }
        
        api = QueryApi()
        criteria = [
            {"type": "field", "field": "drugbank.groups", "value": "approved"},
            {"type": "range", "field": "pubchem.molecular_weight", "min": 150, "max": 500},
            {"type": "exists", "field": "chembl.max_phase"},
            {"type": "text", "value": "inhibitor"}
        ]
        
        result = await api.build_complex_query(
            mock_client,
            criteria=criteria,
            logic="AND"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "drugbank.groups:approved" in call_args
        assert "pubchem.molecular_weight:[150 TO 500]" in call_args
        assert "_exists_:chembl.max_phase" in call_args
        assert "inhibitor" in call_args
    
    @pytest.mark.asyncio
    async def test_search_by_molecular_properties_error(self, mock_client):
        """Test error when no molecular property filters specified."""
        api = QueryApi()
        
        with pytest.raises(ValueError, match="At least one molecular property"):
            await api.search_by_molecular_properties(mock_client)