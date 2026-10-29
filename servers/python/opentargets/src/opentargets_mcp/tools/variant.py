# src/opentargets_mcp/tools/variant.py
"""
Defines API methods and MCP tools related to 'Variant' entities in Open Targets.
"""

from typing import Any

from ..queries import OpenTargetsClient


class VariantApi:
    """
    Contains methods to query variant-specific data from the Open Targets GraphQL API.
    """

    async def get_variant_info(
        self, client: OpenTargetsClient, variant_id: str, include_functional_consequences: bool = True
    ) -> dict[str, Any]:
        """Get detailed information about a specific variant by its ID."""
        graphql_query = """
        query VariantInfo($variantId: String!, $functional: Boolean!) {
            variant(variantId: $variantId) {
                id
                variantDescription
                chromosome
                position
                referenceAllele
                alternateAllele
                hgvsId
                rsIds
                dbXrefs {
                    id
                    source
                }
                alleleFrequencies {
                    populationName
                    alleleFrequency
                }
                mostSevereConsequence {
                    id
                    label
                }
                transcriptConsequences @include(if: $functional) {
                    transcriptId
                    aminoAcidChange
                    codons
                    consequenceScore
                    impact
                    lofteePrediction
                    polyphenPrediction
                    siftPrediction
                    isEnsemblCanonical
                    distanceFromTss
                    uniprotAccessions
                    target {
                        id
                        approvedSymbol
                    }
                    variantConsequences {
                        id
                        label
                    }
                }
                variantEffect @include(if: $functional) {
                    score
                    normalisedScore
                    method
                    assessment
                    assessmentFlag
                    target {
                        id
                        approvedSymbol
                    }
                }
            }
        }
        """
        return await client._query(
            graphql_query, {"variantId": variant_id, "functional": include_functional_consequences}
        )

    async def get_variant_credible_sets(
        self,
        client: OpenTargetsClient,
        variant_id: str,
        study_types: list[str] | None = None,
        page_index: int = 0,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """Get credible sets associated with a variant."""
        graphql_query = """
query VariantCredibleSets($variantId:String!,$studyTypes:[StudyTypeEnum!],$pageIndex:Int!,$pageSize:Int!){variant(variantId:$variantId){id rsIds credibleSets(studyTypes:$studyTypes,page:{index:$pageIndex,size:$pageSize}){count rows{studyLocusId studyId studyType chromosome position pValueMantissa pValueExponent
finemappingMethod confidence qtlGeneId
variant{id chromosome position referenceAllele alternateAllele rsIds}
study{id studyType projectId traitFromSource pubmedId nSamples nCases nControls target{id approvedSymbol} diseases{id name}} region beta zScore standardError credibleSetIndex credibleSetlog10BF purityMeanR2 purityMinR2}}}}
        """
        variables = {
            "variantId": variant_id,
            "studyTypes": study_types,
            "pageIndex": page_index,
            "pageSize": page_size,
        }
        variables = {k: v for k, v in variables.items() if v is not None}
        return await client._query(graphql_query, variables)

    async def get_variant_pharmacogenomics(
        self, client: OpenTargetsClient, variant_id: str, page_index: int = 0, page_size: int = 10
    ) -> dict[str, Any]:
        """Get pharmacogenomics data for a variant."""
        graphql_query = """
        query VariantPharmacogenomics($variantId: String!) {
            variant(variantId: $variantId) {
                id
                rsIds
                pharmacogenomics {
                    variantId
                    variantRsId
                    variantFunctionalConsequenceId
                    targetFromSourceId
                    genotypeId
                    genotype
                    genotypeAnnotationText
                    phenotypeText
                    phenotypeFromSourceId
                    pgxCategory
                    evidenceLevel
                    datasourceId
                    datatypeId
                    studyId
                    literature
                    haplotypeId
                    haplotypeFromSourceId
                    isDirectTarget
                    variantFunctionalConsequence {
                        id
                        label
                    }
                    target {
                        id
                        approvedSymbol
                        approvedName
                    }
                    drugs {
                        drugId
                        drugFromSource
                        drug {
                            id
                            name
                            drugType
                        }
                    }
                }
            }
        }
        """
        return await client._query(
            graphql_query, {"variantId": variant_id, "pageIndex": page_index, "pageSize": page_size}
        )

    async def get_variant_evidences(
        self,
        client: OpenTargetsClient,
        variant_id: str,
        datasource_ids: list[str] | None = None,
        size: int = 10,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Get evidence associated with a variant."""
        graphql_query = """
        query VariantEvidences(
            $variantId: String!,
            $datasourceIds: [String!],
            $size: Int!,
            $cursor: String
        ) {
            variant(variantId: $variantId) {
                id
                rsIds
                evidences(
                    datasourceIds: $datasourceIds,
                    size: $size,
                    cursor: $cursor
                ) {
                    count
                    cursor
                    rows {
                        id
                        score
                        datasourceId
                        datatypeId
                        # variantId  <- THIS LINE WAS REMOVED
                        variantRsId
                        variantFunctionalConsequence { id label }
                        confidence
                        literature
                        studyId
                        beta
                        betaConfidenceIntervalLower
                        betaConfidenceIntervalUpper
                        pValueMantissa
                        pValueExponent
                        oddsRatio
                        oddsRatioConfidenceIntervalLower
                        oddsRatioConfidenceIntervalUpper
                        target {
                            id
                            approvedSymbol
                        }
                        disease {
                            id
                            name
                        }
                        variantFunctionalConsequence {
                            id
                            label
                        }
                    }
                }
            }
        }
        """
        variables = {"variantId": variant_id, "datasourceIds": datasource_ids, "size": size, "cursor": cursor}
        variables = {k: v for k, v in variables.items() if v is not None}
        return await client._query(graphql_query, variables)
