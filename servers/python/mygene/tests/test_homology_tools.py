# tests/test_homology_tools.py
"""Tests for homology tools."""

import pytest
from mygene_mcp.tools.homology import HomologyApi


class TestHomologyTools:
    """Test homology-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_basic(self, mock_client):
        """Test getting orthologs for a gene."""
        mock_client.get.return_value = {
            "symbol": "CDK2",
            "name": "cyclin dependent kinase 2",
            "entrezgene": 1017,
            "homologene": {
                "id": 55866,
                "genes": [
                    [9606, 1017],      # Human (self)
                    [10090, 12566],    # Mouse
                    [10116, 362817],   # Rat
                    [7227, 42453]      # Fly
                ]
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="1017"
        )
        
        assert result["success"] is True
        assert "homologene" in result["ortholog_data"]["orthologs"]
        
        # Should exclude self (human CDK2)
        homologene_orthologs = result["ortholog_data"]["orthologs"]["homologene"]
        assert len(homologene_orthologs) == 3
        assert all(orth["entrezgene"] != 1017 for orth in homologene_orthologs)
        
        # Check ortholog details
        mouse_ortholog = next(o for o in homologene_orthologs if o["taxid"] == 10090)
        assert mouse_ortholog["entrezgene"] == 12566
        assert mouse_ortholog["homologene_id"] == 55866
        
        mock_client.get.assert_called_once_with(
            "gene/1017",
            params={"fields": "symbol,name,entrezgene,homologene,ensembl.homologene,pantherdb.ortholog"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_target_species(self, mock_client):
        """Test getting orthologs with target species filter."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "homologene": {
                "id": 460,
                "genes": [
                    [9606, 7157],    # Human
                    [10090, 22059],  # Mouse
                    [10116, 24842],  # Rat
                    [9544, 455214],  # Rhesus
                    [9615, 403869]   # Dog
                ]
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="7157",
            target_species=["mouse", "rat"]
        )
        
        assert result["success"] is True
        
        homologene_orthologs = result["ortholog_data"]["orthologs"]["homologene"]
        assert len(homologene_orthologs) == 2
        assert all(orth["taxid"] in [10090, 10116] for orth in homologene_orthologs)
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_taxid_filter(self, mock_client):
        """Test getting orthologs with taxid as target species."""
        mock_client.get.return_value = {
            "symbol": "BRCA1",
            "homologene": {
                "id": 5276,
                "genes": [
                    [9606, 672],     # Human
                    [10090, 12189],  # Mouse
                    [10116, 497672]  # Rat
                ]
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="672",
            target_species=["10090", "10116"]
        )
        
        assert result["success"] is True
        
        homologene_orthologs = result["ortholog_data"]["orthologs"]["homologene"]
        assert len(homologene_orthologs) == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_ensembl(self, mock_client):
        """Test getting orthologs with Ensembl data."""
        mock_client.get.return_value = {
            "symbol": "GAPDH",
            "ensembl": {
                "homologene": [
                    {"id": "ENSMUSG00000057666", "species": "mouse"},
                    {"id": "ENSRNOG00000018630", "species": "rat"}
                ]
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="GAPDH"
        )
        
        assert result["success"] is True
        assert "ensembl" in result["ortholog_data"]["orthologs"]
        assert len(result["ortholog_data"]["orthologs"]["ensembl"]) == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_pantherdb(self, mock_client):
        """Test getting orthologs with PANTHER data."""
        mock_client.get.return_value = {
            "symbol": "AKT1",
            "pantherdb": {
                "ortholog": [
                    {"id": "PTHR24352:SF165", "species": "MOUSE"},
                    {"id": "PTHR24352:SF166", "species": "RAT"}
                ]
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="207"
        )
        
        assert result["success"] is True
        assert "pantherdb" in result["ortholog_data"]["orthologs"]
        assert len(result["ortholog_data"]["orthologs"]["pantherdb"]) == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_source_filter(self, mock_client):
        """Test getting orthologs with source filter."""
        mock_client.get.return_value = {
            "symbol": "MYC",
            "homologene": {
                "id": 31092,
                "genes": [[9606, 4609], [10090, 17869]]
            },
            "ensembl": {
                "homologene": [{"id": "ENSMUSG00000022346"}]
            },
            "pantherdb": {
                "ortholog": {"id": "PTHR11956:SF5"}
            }
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="4609",
            sources=["homologene"]
        )
        
        assert result["success"] is True
        assert "homologene" in result["ortholog_data"]["orthologs"]
        assert "ensembl" not in result["ortholog_data"]["orthologs"]
        assert "pantherdb" not in result["ortholog_data"]["orthologs"]
    
    @pytest.mark.asyncio
    async def test_get_gene_orthologs_no_homology(self, mock_client):
        """Test gene with no ortholog data."""
        mock_client.get.return_value = {
            "symbol": "UNKNOWN",
            "name": "unknown gene"
        }
        
        api = HomologyApi()
        result = await api.get_gene_orthologs(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["ortholog_data"]["orthologs"] == {}
    
    @pytest.mark.asyncio
    async def test_query_homologous_genes_basic(self, mock_client):
        """Test finding homologous genes across species."""
        mock_client.get.return_value = {
            "total": 3,
            "took": 5,
            "hits": [
                {
                    "symbol": "CDK2",
                    "entrezgene": 1017,
                    "taxid": 9606,
                    "homologene": {"id": 55866}
                },
                {
                    "symbol": "Cdk2",
                    "entrezgene": 12566,
                    "taxid": 10090,
                    "homologene": {"id": 55866}
                },
                {
                    "symbol": "Cdk2",
                    "entrezgene": 362817,
                    "taxid": 10116,
                    "homologene": {"id": 55866}
                }
            ]
        }
        
        api = HomologyApi()
        result = await api.query_homologous_genes(
            mock_client,
            gene_symbol="CDK2",
            species_list=["human", "mouse", "rat"]
        )
        
        assert result["success"] is True
        assert result["total_genes"] == 3
        assert len(result["homology_groups"]) == 1
        
        # Check homology group
        group = result["homology_groups"][0]
        assert group["homologene_id"] == 55866
        assert len(group["genes"]) == 3
        
        # Verify query construction
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "CDK2" in call_args
        assert "human" in call_args or "mouse" in call_args or "rat" in call_args
    
    @pytest.mark.asyncio
    async def test_query_homologous_genes_multiple_groups(self, mock_client):
        """Test finding genes with multiple homology groups."""
        mock_client.get.return_value = {
            "total": 4,
            "took": 8,
            "hits": [
                # Group 1
                {
                    "symbol": "GENE1",
                    "taxid": 9606,
                    "homologene": {"id": 1001}
                },
                {
                    "symbol": "Gene1",
                    "taxid": 10090,
                    "homologene": {"id": 1001}
                },
                # Group 2 (different gene with same symbol)
                {
                    "symbol": "GENE1",
                    "taxid": 7227,
                    "homologene": {"id": 2001}
                },
                {
                    "symbol": "gene1",
                    "taxid": 6239,
                    "homologene": {"id": 2001}
                }
            ]
        }
        
        api = HomologyApi()
        result = await api.query_homologous_genes(
            mock_client,
            gene_symbol="GENE1",
            species_list=["human", "mouse", "fly", "worm"]
        )
        
        assert result["success"] is True
        assert len(result["homology_groups"]) == 2
        
        # Check both groups
        group1 = next(g for g in result["homology_groups"] if g["homologene_id"] == 1001)
        assert len(group1["genes"]) == 2
        
        group2 = next(g for g in result["homology_groups"] if g["homologene_id"] == 2001)
        assert len(group2["genes"]) == 2
    
    @pytest.mark.asyncio
    async def test_query_homologous_genes_no_homology_data(self, mock_client):
        """Test genes without homology information."""
        mock_client.get.return_value = {
            "total": 2,
            "took": 3,
            "hits": [
                {
                    "symbol": "NOVEL1",
                    "taxid": 9606
                    # No homologene data
                },
                {
                    "symbol": "Novel1",
                    "taxid": 10090
                    # No homologene data
                }
            ]
        }
        
        api = HomologyApi()
        result = await api.query_homologous_genes(
            mock_client,
            gene_symbol="NOVEL1",
            species_list=["human", "mouse"]
        )
        
        assert result["success"] is True
        assert result["total_genes"] == 2
        assert len(result["homology_groups"]) == 0