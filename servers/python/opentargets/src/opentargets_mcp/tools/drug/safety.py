"""Drug safety and cross-reference relations."""

from ...queries import relation

DRUG_ADVERSE_EVENTS = (
    "query DrugAdverseEvents($chemblId:String!,$size:Int!){drug(chemblId:$chemblId){id "
    "adverseEvents(page:{index:0,size:$size}){count criticalValue rows{name meddraCode count logLR}}}}"
)
DRUG_CROSS_REFERENCES = (
    "query DrugCrossReferences($chemblId:String!){drug(chemblId:$chemblId){id crossReferences{source ids}}}"
)


WINDOW = 25


class DrugSafetyApi:
    async def get_drug_adverse_events(self, client, chembl_id):
        """FAERS-derived adverse event signals (log likelihood ratios), not incidence rates."""
        data = await client._query(DRUG_ADVERSE_EVENTS, {"chemblId": chembl_id, "size": WINDOW})
        return {"drug_id": chembl_id, "adverseEvents": relation(data, "drug", "adverseEvents")}

    async def get_drug_cross_references(self, client, chembl_id):
        """External database identifiers recorded for the drug."""
        data = await client._query(DRUG_CROSS_REFERENCES, {"chemblId": chembl_id})
        return {"drug_id": chembl_id, "crossReferences": relation(data, "drug", "crossReferences")}
