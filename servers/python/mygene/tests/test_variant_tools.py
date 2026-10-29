# tests/test_variant_tools.py
"""Tests for variant tools."""

import pytest
from mygene_mcp.tools.variant import VariantApi


class TestVariantTools:
    """Test variant-related tools."""
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_basic(self, mock_client):
        """Test getting variants for a gene."""
        mock_client.get.return_value = {
            "symbol": "BRCA1",
            "name": "BRCA1 DNA repair associated",
            "clinvar": {
                "rcv": [
                    {
                        "accession": {"accession": "RCV000048420"},
                        "title": "NM_007294.3(BRCA1):c.5266dup (p.Gln1756fs)",
                        "clinical_significance": "Pathogenic",
                        "last_evaluated": "2023-06-01",
                        "review_status": "reviewed by expert panel",
                        "conditions": {
                            "name": "Hereditary breast and ovarian cancer syndrome",
                            "identifiers": [{"db": "MedGen", "value": "C2676676"}]
                        },
                        "measure_set": {
                            "measure": {
                                "type": "Duplication",
                                "name": "c.5266dup"
                            }
                        }
                    },
                    {
                        "accession": {"accession": "RCV000048421"},
                        "title": "NM_007294.3(BRCA1):c.68_69del (p.Glu23fs)",
                        "clinical_significance": "Pathogenic",
                        "measure_set": {
                            "measure": {
                                "type": "Deletion",
                                "name": "c.68_69del"
                            }
                        }
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="672"
        )
        
        assert result["success"] is True
        assert result["total_variants"] == 2
        
        clinvar_data = result["variants"]["variant_sources"]["clinvar"]
        assert clinvar_data["total"] == 2
        
        # Check variant details
        variant1 = clinvar_data["variants"][0]
        assert variant1["accession"] == "RCV000048420"
        assert variant1["clinical_significance"] == "Pathogenic"
        assert variant1["variant_type"] == "Duplication"
        assert variant1["name"] == "c.5266dup"
        
        mock_client.get.assert_called_once_with(
            "gene/672",
            params={"fields": "symbol,name,entrezgene,clinvar,snpeff,grasp"}
        )
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_clinical_significance_filter(self, mock_client):
        """Test filtering variants by clinical significance."""
        mock_client.get.return_value = {
            "symbol": "TP53",
            "clinvar": {
                "rcv": [
                    {
                        "accession": {"accession": "RCV001"},
                        "clinical_significance": "Pathogenic",
                        "measure_set": {"measure": {"type": "single nucleotide variant"}}
                    },
                    {
                        "accession": {"accession": "RCV002"},
                        "clinical_significance": "Benign",
                        "measure_set": {"measure": {"type": "single nucleotide variant"}}
                    },
                    {
                        "accession": {"accession": "RCV003"},
                        "clinical_significance": "Pathogenic",
                        "measure_set": {"measure": {"type": "Deletion"}}
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="7157",
            clinical_significance="Pathogenic"
        )
        
        assert result["success"] is True
        assert result["total_variants"] == 2
        
        # Only pathogenic variants should be included
        variants = result["variants"]["variant_sources"]["clinvar"]["variants"]
        assert len(variants) == 2
        assert all(v["clinical_significance"] == "Pathogenic" for v in variants)
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_type_filter(self, mock_client):
        """Test filtering variants by variant type."""
        mock_client.get.return_value = {
            "symbol": "CFTR",
            "clinvar": {
                "rcv": [
                    {
                        "accession": {"accession": "RCV001"},
                        "clinical_significance": "Pathogenic",
                        "measure_set": {
                            "measure": [
                                {"type": "Deletion", "name": "deltaF508"},
                                {"type": "single nucleotide variant", "name": "G542X"}
                            ]
                        }
                    },
                    {
                        "accession": {"accession": "RCV002"},
                        "clinical_significance": "Pathogenic",
                        "measure_set": {
                            "measure": {"type": "Deletion", "name": "del2,3"}
                        }
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="1080",
            variant_type="Deletion"
        )
        
        assert result["success"] is True
        # Note: RCV001 has multiple measures, only Deletion should match
        assert result["total_variants"] == 2
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_with_snpeff(self, mock_client):
        """Test variants with SNPeff annotations."""
        mock_client.get.return_value = {
            "symbol": "GENE1",
            "snpeff": {
                "ann": [
                    {
                        "effect": "missense_variant",
                        "putative_impact": "MODERATE",
                        "gene_name": "GENE1",
                        "feature_type": "transcript"
                    },
                    {
                        "effect": "stop_gained",
                        "putative_impact": "HIGH",
                        "gene_name": "GENE1",
                        "feature_type": "transcript"
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="12345"
        )
        
        assert result["success"] is True
        assert "snpeff" in result["variants"]["variant_sources"]
        
        snpeff_data = result["variants"]["variant_sources"]["snpeff"]
        assert snpeff_data["total"] == 2
        
        # Check annotation details
        ann1 = snpeff_data["annotations"][0]
        assert ann1["effect"] == "missense_variant"
        assert ann1["putative_impact"] == "MODERATE"
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_with_grasp(self, mock_client):
        """Test variants with GRASP GWAS data."""
        mock_client.get.return_value = {
            "symbol": "APOE",
            "grasp": {
                "publication": [
                    {
                        "phenotype": "Alzheimer's disease",
                        "snp_id": "rs429358",
                        "p_value": "1.2e-45",
                        "pmid": "24162737"
                    },
                    {
                        "phenotype": "Cholesterol levels",
                        "snp_id": "rs7412",
                        "p_value": "5.3e-20",
                        "pmid": "20686565"
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="348"
        )
        
        assert result["success"] is True
        assert "grasp" in result["variants"]["variant_sources"]
        
        grasp_data = result["variants"]["variant_sources"]["grasp"]
        assert grasp_data["total"] == 2
        
        # Check GWAS association details
        assoc1 = grasp_data["associations"][0]
        assert assoc1["phenotype"] == "Alzheimer's disease"
        assert assoc1["snp_id"] == "rs429358"
        assert assoc1["p_value"] == "1.2e-45"
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_no_variants(self, mock_client):
        """Test gene with no variant data."""
        mock_client.get.return_value = {
            "symbol": "HOUSEKEEPING",
            "name": "housekeeping gene"
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="99999"
        )
        
        assert result["success"] is True
        assert result["total_variants"] == 0
        assert result["variants"]["variant_sources"] == {}
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_multiple_measures(self, mock_client):
        """Test handling multiple measures in a single RCV."""
        mock_client.get.return_value = {
            "symbol": "MLH1",
            "clinvar": {
                "rcv": {
                    "accession": {"accession": "RCV000123"},
                    "clinical_significance": "Pathogenic",
                    "measure_set": {
                        "measure": [
                            {
                                "type": "Deletion",
                                "name": "Exon 1-2 deletion"
                            },
                            {
                                "type": "Duplication",
                                "name": "Exon 3 duplication"
                            }
                        ]
                    }
                }
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="4292"
        )
        
        assert result["success"] is True
        
        # Should handle both measures properly
        variants = result["variants"]["variant_sources"]["clinvar"]["variants"]
        assert len(variants) == 1  # Still one RCV entry
        assert variants[0]["variant_type"] in ["Deletion", "Duplication"]
    
    @pytest.mark.asyncio
    async def test_get_gene_variants_case_insensitive_filter(self, mock_client):
        """Test case-insensitive clinical significance filter."""
        mock_client.get.return_value = {
            "symbol": "BRCA2",
            "clinvar": {
                "rcv": [
                    {
                        "accession": {"accession": "RCV001"},
                        "clinical_significance": "Pathogenic",  # Capital P
                        "measure_set": {"measure": {"type": "Deletion"}}
                    },
                    {
                        "accession": {"accession": "RCV002"},
                        "clinical_significance": "pathogenic",  # lowercase p
                        "measure_set": {"measure": {"type": "Insertion"}}
                    }
                ]
            }
        }
        
        api = VariantApi()
        result = await api.get_gene_variants(
            mock_client,
            gene_id="675",
            clinical_significance="pathogenic"  # lowercase input
        )
        
        assert result["success"] is True
        assert result["total_variants"] == 2  # Should match both