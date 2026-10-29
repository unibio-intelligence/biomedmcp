"""Test script for OpenTargets composite tools."""
import asyncio
from opentargets_mcp.queries import OpenTargetsClient
from opentargets_mcp.tools.composite import CompositeTools


async def test_composite_tools():
    """Test each composite tool with simple queries."""
    client = OpenTargetsClient()
    composite = CompositeTools()

    print("=" * 60)
    print("Testing OpenTargets Composite Tools")
    print("=" * 60)

    # Test 1: Search
    print("\n1. Testing search_biomedical_entities...")
    try:
        result = await composite.search_biomedical_entities(
            client,
            query="BRCA1",
            limit=3
        )
        print(f"   ✓ Found {result.get('total_hits', 0)} total hits")
        print(f"   ✓ Targets: {len(result['results']['targets'])}")
        print(f"   ✓ Diseases: {len(result['results']['diseases'])}")
        print(f"   ✓ Drugs: {len(result['results']['drugs'])}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 2: Target Profile
    print("\n2. Testing get_target_profile...")
    try:
        result = await composite.get_target_profile(
            client,
            ensembl_id="ENSG00000012048",  # BRCA1
            sections=["identity"],
            include_diseases=False,
            include_drugs=False
        )
        target = result.get("target", {})
        print(f"   ✓ Target: {target.get('approvedSymbol', 'N/A')} - {target.get('approvedName', 'N/A')}")
        print(f"   ✓ Sections: {result.get('sections_included', [])}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 3: Disease Profile
    print("\n3. Testing get_disease_profile...")
    try:
        result = await composite.get_disease_profile(
            client,
            efo_id="EFO_0000305",  # Breast carcinoma
            sections=["identity"],
            top_n_targets=3
        )
        disease = result.get("disease", {})
        print(f"   ✓ Disease: {disease.get('name', 'N/A')}")
        print(f"   ✓ ID: {disease.get('id', 'N/A')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 4: Association Analysis
    print("\n4. Testing analyze_target_disease_association...")
    try:
        result = await composite.analyze_target_disease_association(
            client,
            ensembl_id="ENSG00000012048",  # BRCA1
            efo_id="EFO_0000305",  # Breast carcinoma
            include_biomarkers=False,
            min_score=0.0
        )
        print(f"   ✓ Overall score: {result.get('overall_score', 0):.3f}")
        print(f"   ✓ Evidence count: {result.get('evidence_count', 0)}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 5: Therapeutic Opportunities
    print("\n5. Testing discover_therapeutic_opportunities...")
    try:
        result = await composite.discover_therapeutic_opportunities(
            client,
            disease_id="EFO_0000305",  # Breast carcinoma
            ranking_strategy="genetic_evidence",
            limit=5
        )
        print(f"   ✓ Disease: {result.get('disease_name', 'N/A')}")
        print(f"   ✓ Total candidates: {result.get('total_candidates', 0)}")
        print(f"   ✓ Top opportunities: {len(result.get('opportunities', []))}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 6: Drug Mechanism
    print("\n6. Testing explore_drug_mechanism...")
    try:
        result = await composite.explore_drug_mechanism(
            client,
            drug_id="CHEMBL1201585",  # Olaparib
            include_targets=True,
            include_indications=True,
            include_adverse_events=False
        )
        drug = result.get("drug", {})
        print(f"   ✓ Drug: {drug.get('name', 'N/A')}")
        print(f"   ✓ Phase: {drug.get('maximumClinicalTrialPhase', 'N/A')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 7: Compare Targets
    print("\n7. Testing compare_targets...")
    try:
        result = await composite.compare_targets(
            client,
            ensembl_ids=["ENSG00000012048", "ENSG00000139618"],  # BRCA1, BRCA2
            comparison_aspects=["tractability"]
        )
        print(f"   ✓ Comparing {len(result.get('targets', []))} targets")
        print(f"   ✓ Matrix keys: {len(result.get('matrix', {}))}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 8: Find Similar Targets
    print("\n8. Testing find_similar_targets...")
    try:
        result = await composite.find_similar_targets(
            client,
            ensembl_id="ENSG00000012048",  # BRCA1
            similarity_criteria="pathways",
            limit=5
        )
        print(f"   ✓ Reference target: {result.get('reference_target', 'N/A')}")
        print(f"   ✓ Reference features: {result.get('reference_features_count', 0)}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 9: Target Validation Report
    print("\n9. Testing build_target_validation_report...")
    try:
        result = await composite.build_target_validation_report(
            client,
            ensembl_id="ENSG00000012048",  # BRCA1
            disease_id="EFO_0000305"  # Breast carcinoma
        )
        print(f"   ✓ Overall validation score: {result.get('overall_validation_score', 0):.3f}")
        scorecard = result.get('validation_scorecard', {})
        print(f"   ✓ Genetic evidence: {scorecard.get('genetic_evidence', 0):.3f}")
        print(f"   ✓ Recommendations: {len(result.get('recommendations', []))}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Test 10: API Metadata
    print("\n10. Testing get_api_metadata...")
    try:
        result = await composite.get_api_metadata(client)
        print(f"   ✓ Platform: {result.get('platform', 'N/A')}")
        print(f"   ✓ Composite tools version: {result.get('composite_tools_version', 'N/A')}")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    print("\n" + "=" * 60)
    print("Testing Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_composite_tools())
