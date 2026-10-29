# tests/test_export_tools.py
"""Tests for export tools."""

import pytest
import json
import csv
import io
from mygene_mcp.tools.export import ExportApi


class TestExportTools:
    """Test export tools."""
    
    @pytest.mark.asyncio
    async def test_export_gene_list_json(self, mock_client):
        """Test exporting gene list as JSON."""
        mock_client.post.return_value = [
            {
                "_id": "1017",
                "symbol": "CDK2",
                "name": "cyclin dependent kinase 2",
                "taxid": 9606,
                "entrezgene": 1017,
                "ensembl": {"gene": "ENSG00000123374"},
                "type_of_gene": "protein-coding"
            },
            {
                "_id": "7157",
                "symbol": "TP53",
                "name": "tumor protein p53",
                "taxid": 9606,
                "entrezgene": 7157,
                "ensembl": {"gene": "ENSG00000141510"},
                "type_of_gene": "protein-coding"
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["1017", "7157"],
            format="json"
        )
        
        # Parse JSON result
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["symbol"] == "CDK2"
        assert parsed[1]["symbol"] == "TP53"
        
        mock_client.post.assert_called_once_with(
            "gene",
            {
                "ids": ["1017", "7157"],
                "fields": "symbol,name,taxid,entrezgene,ensembl.gene,type_of_gene"
            }
        )
    
    @pytest.mark.asyncio
    async def test_export_gene_list_tsv(self, mock_client):
        """Test exporting gene list as TSV."""
        mock_client.post.return_value = [
            {
                "symbol": "CDK2",
                "name": "cyclin dependent kinase 2",
                "taxid": 9606,
                "entrezgene": 1017,
                "ensembl": {"gene": "ENSG00000123374"},
                "type_of_gene": "protein-coding"
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["1017"],
            format="tsv",
            fields=["symbol", "name", "taxid"]
        )
        
        # Parse TSV result
        reader = csv.DictReader(io.StringIO(result), delimiter="\t")
        rows = list(reader)
        
        assert len(rows) == 1
        assert rows[0]["symbol"] == "CDK2"
        assert rows[0]["name"] == "cyclin dependent kinase 2"
        assert rows[0]["taxid"] == "9606"
    
    @pytest.mark.asyncio
    async def test_export_gene_list_csv(self, mock_client):
        """Test exporting gene list as CSV."""
        mock_client.post.return_value = [
            {
                "symbol": "BRCA1",
                "name": "BRCA1 DNA repair associated",
                "taxid": 9606,
                "entrezgene": 672
            },
            {
                "symbol": "BRCA2",
                "name": "BRCA2 DNA repair associated",
                "taxid": 9606,
                "entrezgene": 675
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["672", "675"],
            format="csv",
            fields=["symbol", "name", "entrezgene"]
        )
        
        # Parse CSV result
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        
        assert len(rows) == 2
        assert rows[0]["symbol"] == "BRCA1"
        assert rows[1]["symbol"] == "BRCA2"
        assert all("," not in value for row in rows for value in row.values() if value)
    
    @pytest.mark.asyncio
    async def test_export_gene_list_xml(self, mock_client):
        """Test exporting gene list as XML."""
        mock_client.post.return_value = [
            {
                "symbol": "GAPDH",
                "name": "glyceraldehyde-3-phosphate dehydrogenase",
                "taxid": 9606,
                "entrezgene": 2597
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["2597"],
            format="xml",
            fields=["symbol", "name", "taxid", "entrezgene"]
        )
        
        # Basic XML validation
        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>')
        assert "<genes>" in result
        assert "</genes>" in result
        assert "<gene>" in result
        assert "</gene>" in result
        assert "<symbol>GAPDH</symbol>" in result
        assert "<taxid>9606</taxid>" in result
    
    @pytest.mark.asyncio
    async def test_export_gene_list_nested_fields(self, mock_client):
        """Test exporting with nested fields."""
        mock_client.post.return_value = [
            {
                "symbol": "MYC",
                "ensembl": {"gene": "ENSG00000136997"},
                "refseq": {"rna": ["NM_002467"]},
                "go": {"BP": [{"id": "GO:0006351", "term": "transcription"}]}
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["4609"],
            format="tsv",
            fields=["symbol", "ensembl.gene", "refseq.rna", "go.BP"]
        )
        
        # Parse TSV to check nested field handling
        reader = csv.DictReader(io.StringIO(result), delimiter="\t")
        rows = list(reader)
        
        assert len(rows) == 1
        assert rows[0]["symbol"] == "MYC"
        assert rows[0]["ensembl.gene"] == "ENSG00000136997"
        # Complex nested structures are JSON stringified
        assert "NM_002467" in rows[0]["refseq.rna"]
    
    @pytest.mark.asyncio
    async def test_export_gene_list_missing_fields(self, mock_client):
        """Test export handling missing fields."""
        mock_client.post.return_value = [
            {
                "symbol": "GENE1",
                "name": "test gene 1"
                # Missing other requested fields
            },
            {
                "symbol": "GENE2",
                "name": "test gene 2",
                "taxid": 9606,
                "entrezgene": 12345
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["GENE1", "GENE2"],
            format="csv",
            fields=["symbol", "name", "taxid", "entrezgene"]
        )
        
        # Parse CSV
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        
        assert len(rows) == 2
        # First gene should have empty values for missing fields
        assert rows[0]["symbol"] == "GENE1"
        assert rows[0]["taxid"] == ""  # Empty string for missing field
        assert rows[0]["entrezgene"] == ""
        # Second gene should have all values
        assert rows[1]["taxid"] == "9606"
    
    @pytest.mark.asyncio
    async def test_export_gene_list_invalid_format(self, mock_client):
        """Test export with invalid format."""
        mock_client.post.return_value = [{"symbol": "TEST"}]
        
        api = ExportApi()
        with pytest.raises(ValueError) as exc_info:
            await api.export_gene_list(
                mock_client,
                gene_ids=["TEST"],
                format="invalid"
            )
        
        assert "Unsupported format: invalid" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_export_gene_list_default_fields(self, mock_client):
        """Test export with default fields."""
        mock_client.post.return_value = [
            {
                "symbol": "AKT1",
                "name": "AKT serine/threonine kinase 1",
                "taxid": 9606,
                "entrezgene": 207,
                "ensembl": {"gene": "ENSG00000142208"},
                "type_of_gene": "protein-coding"
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["207"],
            format="tsv"
            # No fields specified, should use defaults
        )
        
        call_args = mock_client.post.call_args
        # call_args is a tuple of (args, kwargs)
        # The method is called with post("gene", post_data)
        # So post_data is the second positional argument
        post_data = call_args[0][1]  # Fixed: correct access pattern
        requested_fields = post_data["fields"].split(",")
        assert "symbol" in requested_fields
        assert "name" in requested_fields
        assert "taxid" in requested_fields
        assert "entrezgene" in requested_fields
        assert "ensembl.gene" in requested_fields
        assert "type_of_gene" in requested_fields
    
    @pytest.mark.asyncio
    async def test_export_gene_list_empty_list(self, mock_client):
        """Test exporting empty gene list."""
        mock_client.post.return_value = []
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=[],
            format="json"
        )
        
        parsed = json.loads(result)
        assert parsed == []
    
    @pytest.mark.asyncio
    async def test_export_gene_list_complex_data_in_xml(self, mock_client):
        """Test XML export with complex data types."""
        mock_client.post.return_value = [
            {
                "symbol": "COMPLEX1",
                "aliases": ["ALIAS1", "ALIAS2"],
                "pathway": {"kegg": [{"id": "hsa04110", "name": "Cell cycle"}]}
            }
        ]
        
        api = ExportApi()
        result = await api.export_gene_list(
            mock_client,
            gene_ids=["COMPLEX1"],
            format="xml",
            fields=["symbol", "aliases", "pathway"]
        )
        
        # Complex data should be JSON stringified in XML
        assert "<symbol>COMPLEX1</symbol>" in result
        assert '["ALIAS1", "ALIAS2"]' in result  # Arrays as JSON
        assert "hsa04110" in result  # Nested data as JSON