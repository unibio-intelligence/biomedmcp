# src/opentargets_mcp/tools/drug/identity.py
"""
Defines API methods and MCP tools related to a drug's identity and classification.
"""
from typing import Any, Dict
from ...queries import OpenTargetsClient

class DrugIdentityApi:
    """
    Contains methods to query a drug's identity and cross-references.
    """
    async def get_drug_info(self, client: OpenTargetsClient, chembl_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific drug by its ChEMBL ID."""
        graphql_query = """
        query DrugInfo($chemblId: String!) { drug(chemblId: $chemblId) { id name description drugType maximumClinicalStage synonyms { label source } tradeNames { label source } drugWarnings { warningType description country year } mechanismsOfAction { rows { mechanismOfAction targetName actionType targets { id approvedSymbol approvedName biotype } references { source ids urls } } } indications { count rows { id maxClinicalStage disease { id name therapeuticAreas { id name } } clinicalReports { id source clinicalStage url } } } } }
        """
        return await client._query(graphql_query, {"chemblId": chembl_id})

    async def get_drug_cross_references(self, client: OpenTargetsClient, chembl_id: str) -> Dict[str, Any]:
        """Get cross-references to other databases for a drug."""
        graphql_query = """
        query DrugCrossReferences($chemblId: String!) {
            drug(chemblId: $chemblId) {
                id
                name
                synonyms { label source }
                crossReferences {
                    source
                    ids
                }
                parentMolecule {
                    id
                    name
                }
                childMolecules {
                    id
                    name
                    drugType
                }
            }
        }
        """
        return await client._query(graphql_query, {"chemblId": chembl_id})
