# tests/test_disease_tools.py
"""Tests for disease association tools."""

import pytest
from mygene_mcp.tools.disease import DiseaseApi


class TestDiseaseTools:
    """Test disease-related tools."""
    
    @pytest.mark.asyncio
    async def test_query_genes_by_disease_name_with_source(self, mock_client):
        """Test querying genes by disease name with specific source."""
        mock_client.get.return_value = {
            "total": 200,
            "took": 20,
            "hits": [
                {
                    "symbol": "BRCA1",
                    "disgenet": {
                        "diseases": [
                            {
                                "disease_name": "Breast Cancer",
                                "disease_id": "C0006142",
                                "score": 0.9
                            }
                        ]
                    }
                }
            ]
        }
        
        api = DiseaseApi()
        result = await api.query_genes_by_disease(
            mock_client,
            disease_name="Breast Cancer",
            source="disgenet"
        )
        
        assert result["success"] is True
        assert result["total"] == 200
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'disgenet.diseases.disease_name:"Breast Cancer"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_disease_name_all_sources(self, mock_client):
        """Test querying genes by disease name across all sources."""
        mock_client.get.return_value = {
            "total": 300,
            "took": 25,
            "hits": []
        }
        
        api = DiseaseApi()
        result = await api.query_genes_by_disease(
            mock_client,
            disease_name="alzheimer disease"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        # Should search across multiple sources
        assert "disgenet.diseases.disease_name" in call_args
        assert "clinvar.rcv.conditions.name" in call_args
        assert "omim.name" in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_disease_id_omim(self, mock_client):
        """Test querying genes by OMIM disease ID."""
        mock_client.get.return_value = {
            "total": 5,
            "took": 3,
            "hits": []
        }
        
        api = DiseaseApi()
        result = await api.query_genes_by_disease(
            mock_client,
            disease_id="OMIM:114480"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'omim.omim_id:"114480"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_disease_id_umls(self, mock_client):
        """Test querying genes by UMLS disease ID."""
        mock_client.get.return_value = {
            "total": 150,
            "took": 15,
            "hits": []
        }
        
        api = DiseaseApi()
        result = await api.query_genes_by_disease(
            mock_client,
            disease_id="C0006142"
        )
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert 'disgenet.diseases.disease_id:"C0006142"' in call_args
    
    @pytest.mark.asyncio
    async def test_query_genes_by_disease_default(self, mock_client):
        """Test default disease query."""
        mock_client.get.return_value = {
            "total": 20000,
            "took": 100,
            "hits": []
        }
        
        api = DiseaseApi()
        result = await api.query_genes_by_disease(mock_client)
        
        assert result["success"] is True
        
        call_args = mock_client.get.call_args[1]["params"]["q"]
        assert "_exists_:disgenet" in call_args or "_exists_:clinvar" in call_args
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_basic(self, mock_client):
        """Test getting disease associations for a gene."""
        mock_client.get.return_value = {
            "symbol": "BRCA1",
            "name": "BRCA1 DNA repair associated",
            "disgenet": {
                "diseases": [
                    {
                        "disease_id": "C0006142",
                        "disease_name": "Breast Cancer",
                        "score": 0.9,
                        "source": "BEFREE"
                    },
                    {
                        "disease_id": "C0029925",
                        "disease_name": "Ovarian Cancer",
                        "score": 0.85,
                        "source": "CURATED"
                    }
                ]
            }
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="672"
        )
        
        assert result["success"] is True
        assert result["total_associations"] == 2
        
        disgenet_data = result["disease_associations"]["disease_sources"]["disgenet"]
        assert disgenet_data["total"] == 2
        assert len(disgenet_data["diseases"]) == 2
        
        # Check disease details
        breast_cancer = disgenet_data["diseases"][0]
        assert breast_cancer["disease_id"] == "C0006142"
        assert breast_cancer["disease_name"] == "Breast Cancer"
        assert breast_cancer["score"] == 0.9
        
        mock_client.get.assert_called_once_with(
            "gene/672",
            params={"fields": "symbol,name,entrezgene,disgenet,clinvar,omim"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_clinvar(self, mock_client):
        """Test getting ClinVar disease associations."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "clinvar": {
                "rcv": [
                    {
                        "accession": {"accession": "RCV000013399"},
                        "conditions": {
                            "name": "Li-Fraumeni syndrome",
                            "identifiers": [{"db": "MedGen", "value": "C0023434"}]
                        },
                        "clinical_significance": "Pathogenic",
                        "last_evaluated": "2023-01-01"
                    },
                    {
                        "accession": {"accession": "RCV000013400"},
                        "conditions": {
                            "name": "Hereditary cancer-predisposing syndrome"
                        },
                        "clinical_significance": "Likely pathogenic"
                    }
                ]
            }
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="7157"
        )
        
        assert result["success"] is True
        assert result["total_associations"] == 2
        
        clinvar_data = result["disease_associations"]["disease_sources"]["clinvar"]
        assert clinvar_data["total"] == 2
        
        # Check variant details
        variant1 = clinvar_data["variants"][0]
        assert variant1["rcv_accession"] == "RCV000013399"
        assert variant1["conditions"]["name"] == "Li-Fraumeni syndrome"
        assert variant1["clinical_significance"] == "Pathogenic"
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_omim(self, mock_client):
        """Test getting OMIM disease associations."""
        mock_client.get.return_value = {
            "symbol": "CFTR",
            "omim": [
                {
                    "omim_id": "219700",
                    "name": "CYSTIC FIBROSIS",
                    "inheritance": "Autosomal recessive"
                },
                {
                    "omim_id": "277180",
                    "name": "SWEAT CHLORIDE ELEVATION WITHOUT CF",
                    "inheritance": "Autosomal dominant"
                }
            ]
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="1080"
        )
        
        assert result["success"] is True
        assert result["total_associations"] == 2
        
        omim_data = result["disease_associations"]["disease_sources"]["omim"]
        assert omim_data["total"] == 2
        assert omim_data["diseases"][0]["name"] == "CYSTIC FIBROSIS"
        assert omim_data["diseases"][0]["inheritance"] == "Autosomal recessive"
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_source_filter(self, mock_client):
        """Test getting disease associations with source filter."""
        mock_client.get.return_value = {
            "symbol": "APOE",
            "disgenet": {
                "diseases": [{"disease_name": "Alzheimer Disease"}]
            },
            "clinvar": {
                "rcv": [{"conditions": {"name": "Hyperlipoproteinemia"}}]
            },
            "omim": {
                "omim_id": "104310",
                "name": "ALZHEIMER DISEASE 2"
            }
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="348",
            sources=["disgenet", "omim"]
        )
        
        assert result["success"] is True
        assert "disgenet" in result["disease_associations"]["disease_sources"]
        assert "omim" in result["disease_associations"]["disease_sources"]
        assert "clinvar" not in result["disease_associations"]["disease_sources"]
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_no_diseases(self, mock_client):
        """Test gene with no disease associations."""
        mock_client.get.return_value = {
            "symbol": "HOUSEKEEPING",
            "name": "housekeeping gene"
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["total_associations"] == 0
        assert result["disease_associations"]["disease_sources"] == {}
    
    @pytest.mark.asyncio
    async def test_get_gene_disease_associations_single_disease(self, mock_client):
        """Test handling single disease entry (not list)."""
        mock_client.get.return_value = {
            "symbol": "GENE1",
            "disgenet": {
                "diseases": {  # Single dict, not list
                    "disease_id": "C0001",
                    "disease_name": "Test Disease"
                }
            }
        }
        
        api = DiseaseApi()
        result = await api.get_gene_disease_associations(
            mock_client,
            gene_id="12345"
        )
        
        assert result["success"] is True
        assert result["total_associations"] == 1
        
        # Single disease should be converted to list
        diseases = result["disease_associations"]["disease_sources"]["disgenet"]["diseases"]
        assert isinstance(diseases, list)
        assert len(diseases) == 1