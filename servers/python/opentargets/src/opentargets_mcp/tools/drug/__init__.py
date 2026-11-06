"""Drug record, mechanism-of-action and indication projections."""

from ...queries import relation

# The drug root record is the anchor of mechanism exploration; optional relations follow.
DRUG_RECORD = "query DrugMechanism($chemblId:String!){drug(chemblId:$chemblId){id name description maximumClinicalStage}}"
DRUG_TARGETS = (
    "query DrugTargets($chemblId:String!){drug(chemblId:$chemblId){id mechanismsOfAction{rows{"
    "mechanismOfAction actionType targetName targets{id approvedSymbol approvedName} references{source ids urls}}}}}"
)
DRUG_INDICATIONS = (
    "query DrugIndications($chemblId:String!){drug(chemblId:$chemblId){id indications{count rows{"
    "id maxClinicalStage disease{id name} clinicalReports{id source clinicalStage trialPhase trialOverallStatus url}}}}}"
)


async def drug_mechanisms(client, chembl_id):
    """Mechanism rows with their resolved targets; null when the source reports none."""
    return relation(await client._query(DRUG_TARGETS, {"chemblId": chembl_id}), "drug", "mechanismsOfAction")


async def drug_indications(client, chembl_id):
    """Indication rows with their clinical reports."""
    return relation(await client._query(DRUG_INDICATIONS, {"chemblId": chembl_id}), "drug", "indications")
