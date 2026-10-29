"""Tests for export tools."""

import pytest
import json
import csv
import io
from mydisease_mcp.tools.export import ExportApi


class TestExportTools:
    """Test data export tools."""
    
    @pytest.mark.asyncio
    async def test_export_disease_list_json(self, mock_client):
        """Test exporting diseases as JSON."""
        mock_client.post.return_value = [
            {"_id": "MONDO:0007739", "name": "Huntington disease"},
            {"_id": "MONDO:0011122", "name": "Achondroplasia"}
        ]
        
        api = ExportApi()
        result = await api.export_disease_list(
            mock_client,
            disease_ids=["MONDO:0007739", "MONDO:0011122"],
            format="json"
        )
        
        # Parse JSON result
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["name"] == "Huntington disease"
    
    @pytest.mark.asyncio
    async def test_export_disease_comparison_markdown(self, mock_client):
        """Test exporting disease comparison as markdown."""
        mock_client.post.return_value = [
            {
                "_id": "MONDO:0007739",
                "name": "Huntington disease",
                "inheritance": {"inheritance_type": "Autosomal dominant"},
                "gene": [{"symbol": "HTT"}]
            },
            {
                "_id": "MONDO:0011122",
                "name": "Achondroplasia",
                "inheritance": {"inheritance_type": "Autosomal dominant"},
                "gene": [{"symbol": "FGFR3"}]
            }
        ]
        
        api = ExportApi()
        result = await api.export_disease_comparison(
            mock_client,
            disease_ids=["MONDO:0007739", "MONDO:0011122"],
            format="markdown"
        )
        
        assert "# Disease Comparison" in result
        assert "Huntington disease" in result
        assert "Achondroplasia" in result
        assert "HTT" in result
        assert "FGFR3" in result
    
    @pytest.mark.asyncio
    async def test_export_gene_disease_matrix(self, mock_client):
        """Test exporting gene-disease matrix."""
        # Mock search results
        mock_client.get.side_effect = [
            {"hits": [{"_id": "disease1"}, {"_id": "disease2"}]},  # GENE1
            {"hits": [{"_id": "disease2"}]}  # GENE2
        ]
        
        # Mock disease data
        mock_client.post.return_value = [
            {
                "_id": "disease1",
                "name": "Disease 1",
                "gene": [{"symbol": "GENE1"}]
            },
            {
                "_id": "disease2",
                "name": "Disease 2",
                "gene": [{"symbol": "GENE1"}, {"symbol": "GENE2"}]
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_disease_matrix(
            mock_client,
            gene_list=["GENE1", "GENE2"],
            format="csv"
        )
        
        # Parse CSV
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        
        assert rows[0] == ["Disease ID", "Disease Name", "GENE1", "GENE2"]
        assert len(rows) == 3  # Header + 2 diseases