# src/opentargets_mcp/tools/evidence.py
"""
Defines API methods and MCP tools related to 'Evidence' linking targets and diseases.
"""
from typing import Any, Dict, List, Optional
from ..queries import OpenTargetsClient # Relative import

class EvidenceApi:
    """
    Contains methods to query evidence-specific data from the Open Targets GraphQL API.
    """

    async def get_target_disease_evidence(
        self,
        client: OpenTargetsClient,
        ensembl_id: str,
        efo_id: str,
        datasource_ids: Optional[List[str]] = None,
        size: int = 10,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get evidence linking a specific target to a specific disease."""
        # Note: The API structures evidence under the 'target' or 'disease' object.
        # This function queries via the 'target' object.
        graphql_query = """
        query TargetDiseaseEvidences(
            $ensemblId: String!,
            $efoId: String!, # API uses efoIds: [String!]
            $datasourceIds: [String!],
            $size: Int!,
            $cursor: String
        ) {
            target(ensemblId: $ensemblId) {
                evidences(
                    efoIds: [$efoId], # Pass efo_id as a list
                    datasourceIds: $datasourceIds,
                    size: $size,
                    cursor: $cursor
                ) {
                    count
                    cursor # For pagination
                    rows {
                        id # Evidence ID
                        score # Evidence score
                        datasourceId
                        datatypeId
                        diseaseFromSource
                        targetFromSourceId
                        disease { id, name } # Disease context for this evidence
                        target { id, approvedSymbol } # Target context
                        # Common evidence fields
                        literature # List of PMIDs
                        # Depending on datatypeId, specific fields will be populated, e.g.:
                        # ... on GeneticEvidence { variantId, variantRsId, gwasSampleCount, confidence }
                        # ... on SomaticMutation { functionalConsequenceId, numberOfSamplesWithMutationType, numberOfSamplesTested }
                        # ... on DrugsEvidence { clinicalPhase, clinicalStatus, mechanismOfAction, urls { name, url } }
                        # It's hard to list all specific fields due to polymorphism.
                        # The API will return relevant fields based on the evidence type.
                        # We can add specific fragments later if needed for common types.
                    }
                }
            }
        }
        """
        variables = {
            "ensemblId": ensembl_id,
            "efoId": efo_id,
            "datasourceIds": datasource_ids,
            "size": size,
            "cursor": cursor
        }
        variables = {k: v for k, v in variables.items() if v is not None}
        return await client._query(graphql_query, variables)

    async def get_target_disease_biomarkers(
        self,
        client: OpenTargetsClient,
        ensembl_id: str,
        efo_id: str,
        size: int = 10, # Number of evidence strings to check for biomarkers
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get biomarker information from evidence linking a target to a disease."""
        # Biomarkers are often part of the evidence strings.
        graphql_query = """
        query TargetDiseaseBiomarkers(
            $ensemblId: String!,
            $efoId: String!,
            $size: Int!,
            $cursor: String
        ) {
            target(ensemblId: $ensemblId) {
                evidences(efoIds: [$efoId], size: $size, cursor: $cursor) {
                    count
                    cursor
                    rows {
                        id # Evidence ID
                        score
                        datasourceId
                        datatypeId
                        biomarkerName # If available directly
                        disease { id, name }
                        target { id, approvedSymbol }
                    }
                }
            }
        }
        """
        # This tool will return evidence strings. The presence and structure of biomarker
        # data within these strings can vary. Users may need to inspect the results,
        # particularly if the evidence comes from clinical trials or specific biomarker studies.
        variables = {
            "ensemblId": ensembl_id,
            "efoId": efo_id,
            "size": size,
            "cursor": cursor
        }
        variables = {k: v for k, v in variables.items() if v is not None}
        return await client._query(graphql_query, variables)

