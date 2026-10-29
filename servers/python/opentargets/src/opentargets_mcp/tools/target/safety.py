# src/opentargets_mcp/tools/target/safety.py
"""
Defines API methods and MCP tools related to target safety and tractability.
"""

from typing import Any

from ...queries import OpenTargetsClient


class TargetSafetyApi:
    """
    Contains methods to query target safety, tractability, and chemical probes.
    """

    async def get_target_safety_information(
        self, client: OpenTargetsClient, ensembl_id: str
    ) -> dict[str, Any]:
        """Get safety liabilities and information for a target."""
        graphql_query = """
        query TargetSafety($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
                id
                approvedSymbol
                safetyLiabilities {
                    event
                    eventId
                    effects {
                        direction
                        dosing
                    }
                    datasource
                }
            }
        }
        """
        return await client._query(graphql_query, {"ensemblId": ensembl_id})

    async def get_target_tractability(self, client: OpenTargetsClient, ensembl_id: str) -> dict[str, Any]:
        """Get tractability assessment for a target, including antibody and small molecule tractability."""
        graphql_query = """
        query TargetTractability($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
                id
                approvedSymbol
                tractability {
                    modality
                    value
                    label
                }
            }
        }
        """
        return await client._query(graphql_query, {"ensemblId": ensembl_id})

    async def get_target_chemical_probes(self, client: OpenTargetsClient, ensembl_id: str) -> dict[str, Any]:
        """Get chemical probes for target validation, including quality scores."""
        graphql_query = """
        query TargetChemicalProbes($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
                id
                approvedSymbol
                chemicalProbes {
                    id
                    control
                    drugId
                    isHighQuality
                    mechanismOfAction
                    origin
                    probesDrugsScore
                    scoreInCells
                    scoreInOrganisms
                    targetFromSourceId
                    urls { niceName, url }
                }
            }
        }
        """
        return await client._query(graphql_query, {"ensemblId": ensembl_id})

    async def get_target_tep(self, client: OpenTargetsClient, ensembl_id: str) -> dict[str, Any]:
        """TEP is unavailable in the reviewed current provider schema."""
        from biomedmcp.errors import ResearchError

        raise ResearchError("source_unavailable", "The current Open Targets API does not expose TEP records.")

    async def get_target_prioritization(self, client: OpenTargetsClient, ensembl_id: str) -> dict[str, Any]:
        """Get target prioritization scores from various sources."""
        graphql_query = """
        query TargetPrioritisation($ensemblId: String!) {
            target(ensemblId: $ensemblId) {
                id
                approvedSymbol
                prioritisation {
                    items {
                        key
                        value
                    }
                }
            }
        }
        """
        return await client._query(graphql_query, {"ensemblId": ensembl_id})
