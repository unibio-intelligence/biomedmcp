# tests/test_export_tools.py
"""Tests for export tools."""

import pytest
import json
import csv
import io
from mychem_mcp.tools.export import ExportApi


class TestExportTools:
    """Test data export tools."""
    
    @pytest.mark.asyncio
    async def test_export_chemical_list_json(self, mock_client):
        """Test exporting chemicals as JSON."""
        mock_client.post.return_value = [
            {"_id": "chem1", "name": "Chemical 1"},
            {"_id": "chem2", "name": "Chemical 2"}
        ]
        
        api = ExportApi()
        result = await api.export_chemical_list(
            mock_client,
            chemical_ids=["chem1", "chem2"],
            format="json"
        )
        
        # Parse JSON result
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["name"] == "Chemical 1"
    
    @pytest.mark.asyncio
    async def test_export_chemical_list_csv(self, mock_client):
        """Test exporting chemicals as CSV."""
        mock_client.post.return_value = [
            {
                "_id": "chem1",
                "name": "Chemical 1",
                "pubchem": {"cid": 123}
            },
            {
                "_id": "chem2",
                "name": "Chemical 2",
                "pubchem": {"cid": 456}
            }
        ]
        
        api = ExportApi()
        result = await api.export_chemical_list(
            mock_client,
            chemical_ids=["chem1", "chem2"],
            format="csv",
            fields=["inchikey", "name", "pubchem.cid"]
        )
        
        # Parse CSV result
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["name"] == "Chemical 1"
        assert rows[0]["pubchem.cid"] == "123"
    
    @pytest.mark.asyncio
    async def test_export_chemical_list_tsv(self, mock_client):
        """Test exporting chemicals as TSV."""
        mock_client.post.return_value = [{"_id": "chem1", "name": "Chemical 1"}]
        
        api = ExportApi()
        result = await api.export_chemical_list(
            mock_client,
            chemical_ids=["chem1"],
            format="tsv"
        )
        
        # Check TSV format
        assert "\t" in result
        assert "inchikey\tname" in result.split("\n")[0]
    
    @pytest.mark.asyncio
    async def test_export_filtered_dataset(self, mock_client):
        """Test exporting filtered dataset with pagination."""
        # Mock paginated results
        mock_client.get.side_effect = [
            {"total": 25, "hits": [{"_id": f"chem{i}"} for i in range(10)]},
            {"total": 25, "hits": [{"_id": f"chem{i}"} for i in range(10, 20)]},
            {"total": 25, "hits": [{"_id": f"chem{i}"} for i in range(20, 25)]},
        ]
        
        api = ExportApi()
        result = await api.export_filtered_dataset(
            mock_client,
            query="test",
            filters={"drugbank.groups": "approved"},
            format="json",
            max_results=25,
            batch_size=10
        )
        
        data = json.loads(result)
        assert len(data) == 25
        assert data[0]["_id"] == "chem0"
        assert data[24]["_id"] == "chem24"
    
    @pytest.mark.asyncio
    async def test_export_compound_comparison(self, mock_client):
        """Test exporting compound comparison."""
        mock_client.post.return_value = [
            {
                "_id": "chem1",
                "drugbank": {"name": "Aspirin"},
                "pubchem": {"molecular_weight": 180.16},
                "chembl": {"max_phase": 4}
            },
            {
                "_id": "chem2",
                "chembl": {"pref_name": "Ibuprofen", "max_phase": 4},
                "pubchem": {"molecular_weight": 206.28}
            }
        ]
        
        api = ExportApi()
        result = await api.export_compound_comparison(
            mock_client,
            chemical_ids=["chem1", "chem2"],
            comparison_fields=["name", "molecular_weight", "chembl.max_phase"],
            format="csv"
        )
        
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["name"] == "Aspirin"
        assert rows[1]["name"] == "Ibuprofen"
        assert rows[0]["molecular_weight"] == "180.16"
    
    @pytest.mark.asyncio
    async def test_export_activity_profile(self, mock_client):
        """Test exporting activity profile."""
        mock_client.get.return_value = {
            "drugbank": {
                "name": "Test Drug",
                "indication": "Test indication",
                "targets": [{"name": "Target 1"}]
            },
            "chembl": {
                "activities": [
                    {
                        "target_pref_name": "Target 1",
                        "standard_type": "IC50",
                        "standard_value": "50",
                        "standard_units": "nM"
                    }
                ]
            }
        }
        
        api = ExportApi()
        result = await api.export_activity_profile(
            mock_client,
            chemical_id="test-id",
            format="json"
        )
        
        profile = json.loads(result)
        assert profile["basic_info"]["name"] == "Test Drug"
        assert profile["therapeutic_info"]["indication"] == "Test indication"
        assert len(profile["targets"]) == 1
        assert "Target 1" in profile["activities"]