# tests/test_metadata_tools.py
"""Tests for metadata tools."""

import pytest
from mygene_mcp.tools.metadata import MetadataApi


class TestMetadataTools:
    """Test metadata-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_mygene_metadata(self, mock_client, sample_metadata):
        """Test retrieving API metadata."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_mygene_metadata(mock_client)
        
        assert result["success"] is True
        assert "metadata" in result
        assert result["metadata"]["build_version"] == "20240101"
        assert "stats" in result["metadata"]
        
        mock_client.get.assert_called_once_with("metadata")
    
    @pytest.mark.asyncio
    async def test_get_available_fields(self, mock_client):
        """Test getting available fields."""
        mock_client.get.return_value = {
            "entrezgene": {
                "type": "integer",
                "description": "Entrez gene ID"
            },
            "symbol": {
                "type": "string",
                "description": "Gene symbol"
            },
            "name": {
                "type": "string",
                "description": "Gene name"
            },
            "ensembl.gene": {
                "type": "string",
                "description": "Ensembl gene ID"
            },
            "refseq.rna": {
                "type": "array",
                "description": "RefSeq RNA accessions"
            }
        }
        
        api = MetadataApi()
        result = await api.get_available_fields(mock_client)
        
        assert result["success"] is True
        assert "fields" in result
        assert "entrezgene" in result["fields"]
        assert "symbol" in result["fields"]
        assert "ensembl.gene" in result["fields"]
        
        mock_client.get.assert_called_once_with("metadata/fields")
    
    @pytest.mark.asyncio
    async def test_get_species_list(self, mock_client, sample_species_facets):
        """Test getting species list."""
        mock_client.get.return_value = sample_species_facets
        
        api = MetadataApi()
        result = await api.get_species_list(mock_client)
        
        assert result["success"] is True
        assert result["total_species"] == 5
        assert len(result["species"]) == 5
        
        # Check common species names
        species_dict = {s["taxid"]: s["name"] for s in result["species"]}
        assert species_dict[9606] == "human"
        assert species_dict[10090] == "mouse"
        assert species_dict[10116] == "rat"
        assert species_dict[7227] == "fruitfly"
        assert species_dict[6239] == "nematode"
        
        # Check gene counts
        human_species = next(s for s in result["species"] if s["taxid"] == 9606)
        assert human_species["gene_count"] == 40000
        
        mock_client.get.assert_called_once_with(
            "query",
            params={
                "q": "*",
                "facets": "taxid",
                "facet_size": 1000,
                "size": 0
            }
        )
    
    @pytest.mark.asyncio
    async def test_get_species_list_with_unknown_species(self, mock_client):
        """Test species list with unknown taxonomy IDs."""
        mock_client.get.return_value = {
            "total": 100,
            "hits": [],
            "facets": {
                "taxid": {
                    "terms": [
                        {"term": 9606, "count": 40000},
                        {"term": 123456, "count": 100},  # Unknown species
                        {"term": 789012, "count": 50}     # Unknown species
                    ]
                }
            }
        }
        
        api = MetadataApi()
        result = await api.get_species_list(mock_client)
        
        assert result["success"] is True
        assert result["total_species"] == 3
        
        # Check unknown species formatting
        species_dict = {s["taxid"]: s["name"] for s in result["species"]}
        assert species_dict[9606] == "human"
        assert species_dict[123456] == "taxid:123456"
        assert species_dict[789012] == "taxid:789012"
    
    @pytest.mark.asyncio
    async def test_metadata_build_info(self, mock_client, sample_metadata):
        """Test metadata build information."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_mygene_metadata(mock_client)
        
        metadata = result["metadata"]
        assert "build_date" in metadata
        assert "build_version" in metadata
        assert "app_revision" in metadata
        assert metadata["genome_assembly"]["human"] == "GRCh38"
        assert metadata["genome_assembly"]["mouse"] == "GRCm39"
    
    @pytest.mark.asyncio
    async def test_metadata_stats(self, mock_client, sample_metadata):
        """Test metadata statistics."""
        mock_client.get.return_value = sample_metadata
        
        api = MetadataApi()
        result = await api.get_mygene_metadata(mock_client)
        
        stats = result["metadata"]["stats"]
        assert stats["total"] == 20000000
        assert stats["human"] == 40000
        assert stats["mouse"] == 35000