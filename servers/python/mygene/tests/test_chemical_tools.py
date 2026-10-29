# tests/test_chemical_tools.py
"""Tests for chemical interaction tools."""

import pytest
from mygene_mcp.tools.chemical import ChemicalApi


class TestChemicalTools:
    """Test chemical/drug interaction tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_name(self, mock_client):
        """Test querying genes by chemical name."""
        mock_client.get.return_value = {
            "total": 50,
            "took": 10,
            "hits": [
                {
                    "symbol": "PTGS2",
                    "pharmgkb": {
                        "chemical": [
                            {
                                "name": "aspirin",
                                "id": "PA448497",
                                "type": "Drug"
                            }
                        ]
                    }
                }
            ]
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(
            mock_client,
            chemical_name="aspirin"
        )
        
        assert result["success"] is True
        assert result["total"] == 50
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should search across multiple databases
        assert "pharmgkb.chemical.name" in call_args
        assert "aspirin" in call_args
        assert "chebi.name" in call_args or "drugbank.name" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_id_chembl(self, mock_client):
        """Test querying genes by ChEMBL ID."""
        mock_client.get.return_value = {
            "total": 10,
            "took": 5,
            "hits": []
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(
            mock_client,
            chemical_id="CHEMBL25"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'chembl.molecule_chembl_id:"CHEMBL25"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_id_drugbank(self, mock_client):
        """Test querying genes by DrugBank ID."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 3,
            "hits": []
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(
            mock_client,
            chemical_id="DB00619"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'drugbank.id:"DB00619"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_id_chebi(self, mock_client):
        """Test querying genes by ChEBI ID."""
        mock_client.get.return_value = {
            "total": 15,
            "took": 4,
            "hits": []
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(
            mock_client,
            chemical_id="CHEBI:15365"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'chebi.id:"CHEBI:15365"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_interaction_type(self, mock_client):
        """Test querying genes by interaction type."""
        mock_client.get.return_value = {
            "total": 25,
            "took": 6,
            "hits": []
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(
            mock_client,
            chemical_name="warfarin",
            interaction_type="substrate"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "warfarin" in call_args
        assert 'pharmgkb.type:"substrate"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_chemical_default(self, mock_client):
        """Test default chemical query."""
        mock_client.get.return_value = {
            "total": 15000,
            "took": 80,
            "hits": []
        }
        
        api = ChemicalApi()
        result = await api.query_genes_by_chemical(mock_client)
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:pharmgkb" in call_args or "_exists_:chebi" in call_args
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_basic(self, mock_client):
        """Test getting chemical interactions for a gene."""
        mock_client.get.return_value = {
            "symbol": "CYP2C19",
            "name": "cytochrome P450 family 2 subfamily C member 19",
            "pharmgkb": {
                "chemical": [
                    {
                        "name": "clopidogrel",
                        "id": "PA449053",
                        "type": "substrate"
                    },
                    {
                        "name": "omeprazole",
                        "id": "PA450704",
                        "type": "substrate"
                    }
                ]
            }
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="1557"
        )
        
        assert result["success"] is True
        assert result["total_interactions"] == 2
        
        pharmgkb_data = result["chemical_interactions"]["chemical_sources"]["pharmgkb"]
        assert pharmgkb_data["total"] == 2
        
        # Check chemical details
        chem1 = pharmgkb_data["chemicals"][0]
        assert chem1["name"] == "clopidogrel"
        assert chem1["type"] == "substrate"
        
        mock_client.get.assert_called_once_with(
            "gene/1557",
            params={"fields": "symbol,name,entrezgene,pharmgkb,chebi,chembl,drugbank"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_chebi(self, mock_client):
        """Test getting ChEBI chemical data."""
        mock_client.get.return_value = {
            "symbol": "ACHE",
            "chebi": [
                {
                    "id": "CHEBI:38462",
                    "name": "donepezil",
                    "definition": "An acetylcholinesterase inhibitor"
                },
                {
                    "id": "CHEBI:7809",
                    "name": "physostigmine",
                    "definition": "A carbamate ester"
                }
            ]
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="43"
        )
        
        assert result["success"] is True
        
        chebi_data = result["chemical_interactions"]["chemical_sources"]["chebi"]
        assert chebi_data["total"] == 2
        assert chebi_data["compounds"][0]["name"] == "donepezil"
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_chembl(self, mock_client):
        """Test getting ChEMBL target data."""
        mock_client.get.return_value = {
            "symbol": "EGFR",
            "chembl": {
                "target_component": [
                    {
                        "target_chembl_id": "CHEMBL203",
                        "component_type": "PROTEIN",
                        "accession": "P00533"
                    }
                ]
            }
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="1956"
        )
        
        assert result["success"] is True
        assert "chembl" in result["chemical_interactions"]["chemical_sources"]
        
        chembl_data = result["chemical_interactions"]["chemical_sources"]["chembl"]
        assert chembl_data["total"] == 1
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_drugbank(self, mock_client):
        """Test getting DrugBank data."""
        mock_client.get.return_value = {
            "symbol": "VKORC1",
            "drugbank": {
                "id": "DB00682",
                "name": "warfarin",
                "groups": ["approved"]
            }
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="79001"
        )
        
        assert result["success"] is True
        
        drugbank_data = result["chemical_interactions"]["chemical_sources"]["drugbank"]
        assert drugbank_data["total"] == 1
        assert drugbank_data["drugs"][0]["name"] == "warfarin"
        assert "approved" in drugbank_data["drugs"][0]["groups"]
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_source_filter(self, mock_client):
        """Test getting chemical interactions with source filter."""
        mock_client.get.return_value = {
            "symbol": "CYP3A4",
            "pharmgkb": {
                "chemical": [{"name": "simvastatin"}]
            },
            "chebi": [{"name": "simvastatin acid"}],
            "drugbank": [{"name": "simvastatin"}]
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="1576",
            sources=["pharmgkb", "drugbank"]
        )
        
        assert result["success"] is True
        assert "pharmgkb" in result["chemical_interactions"]["chemical_sources"]
        assert "drugbank" in result["chemical_interactions"]["chemical_sources"]
        assert "chebi" not in result["chemical_interactions"]["chemical_sources"]
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_no_chemicals(self, mock_client):
        """Test gene with no chemical interactions."""
        mock_client.get.return_value = {
            "symbol": "UNKNOWN",
            "name": "unknown gene"
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["total_interactions"] == 0
        assert result["chemical_interactions"]["chemical_sources"] == {}
    
    @pytest.mark.asyncio
    async def test_get_gene_chemical_interactions_single_chemical(self, mock_client):
        """Test handling single chemical entry (not list)."""
        mock_client.get.return_value = {
            "symbol": "GENE1",
            "pharmgkb": {
                "chemical": {  # Single dict, not list
                    "name": "drug1",
                    "id": "PA1234"
                }
            },
            "chebi": {  # Single dict
                "id": "CHEBI:1234",
                "name": "compound1"
            }
        }
        
        api = ChemicalApi()
        result = await api.get_gene_chemical_interactions(
            mock_client,
            gene_id="12345"
        )
        
        assert result["success"] is True
        assert result["total_interactions"] == 2
        
        # Single items should be converted to lists
        pharmgkb_chems = result["chemical_interactions"]["chemical_sources"]["pharmgkb"]["chemicals"]
        assert isinstance(pharmgkb_chems, list)
        assert len(pharmgkb_chems) == 1
        
        chebi_compounds = result["chemical_interactions"]["chemical_sources"]["chebi"]["compounds"]
        assert isinstance(chebi_compounds, list)
        assert len(chebi_compounds) == 1