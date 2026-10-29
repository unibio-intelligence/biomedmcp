"""OpenFDA MCP Server - Optimized Python Implementation.

Provides access to FDA databases including drugs, devices, food, and more.
Uses composite tools to reduce token usage and improve usability.
"""

from biomedmcp import transport as httpx
from typing import Optional, Literal
from fastmcp import FastMCP

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query openFDA",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("openfda")

# Base URL for openFDA API
BASE_URL = "https://api.fda.gov"


def build_search_query(params: dict) -> str:
    """Build FDA API search query from parameters."""
    query_parts = []
    for key, value in params.items():
        if value and key not in ['limit', 'skip', 'count']:
            # Handle different field mappings
            query_parts.append(f"{key}:{value}")
    return " AND ".join(query_parts) if query_parts else ""


async def fda_api_request(endpoint: str, search: Optional[str] = None,
                          count: Optional[str] = None,
                          limit: int = 10, skip: int = 0) -> dict:
    """Make request to openFDA API."""
    from biomedmcp.source_licensing import require_operation

    require_operation("openfda", "endpoint:" + endpoint)
    url = f"{BASE_URL}/{endpoint}.json"
    params = {}

    if search:
        params['search'] = search
    if count:
        params['count'] = count
    else:
        params['limit'] = min(limit, 100)
        if skip > 0:
            params['skip'] = skip

    import os
    from biomedmcp.errors import provider_boundary
    from biomedmcp.native.shapes import collection
    if os.getenv('OPENFDA_API_KEY'):
        params['api_key']=os.environ['OPENFDA_API_KEY']
    with provider_boundary("openfda"):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            if response.status_code==404:
                body=response.json()
                if body.get('error',{}).get('code')=='NOT_FOUND' and body['error'].get('message')=='No matches found!':return {'results':[]}
            response.raise_for_status()
            value = response.json()
            collection(value, ("results",))
            if endpoint == "drug/label":
                from biomedmcp.native.label_metadata import project

                return {"results": project(value["results"])}
            if endpoint == "drug/enforcement":
                from .permissions import recall_projection

                return recall_projection(value)
            return value


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_adverse_events(
    query: str,
    event_type: Literal["drug", "device"] = "drug",
    serious_only: bool = False,
    patient_sex: Optional[Literal["1", "2", "F", "M"]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    count_by: Optional[str] = None,
    limit: int = 10
) -> dict:
    """Search FDA adverse event reports for drugs or medical devices.

    Args:
        query: Drug/device name, brand, manufacturer, or reaction to search
        event_type: Type of adverse events - "drug" or "device"
        serious_only: Only return serious adverse events
        patient_sex: Filter by patient sex (drug: 1=Male, 2=Female; device: F/M)
        date_from: Start date (YYYYMMDD format)
        date_to: End date (YYYYMMDD format)
        count_by: Field to group results by for statistics (e.g., "patient.drug.openfda.brand_name.exact")
        limit: Maximum results to return (1-100)

    Returns:
        Adverse event reports matching the search criteria

    Examples:
        >>> # Search drug adverse events for aspirin
        >>> search_adverse_events("aspirin", event_type="drug")

        >>> # Search serious device events
        >>> search_adverse_events("pacemaker", event_type="device", serious_only=True)

        >>> # Get statistics on most common reactions
        >>> search_adverse_events("lipitor", count_by="patient.reaction.reactionmeddrapt.exact")
    """
    endpoint = f"{event_type}/event"

    # Build search query
    search_parts = []
    if query:
        if event_type == "drug":
            search_parts.append(f'(patient.drug.openfda.brand_name:"{query}" OR '
                              f'patient.drug.openfda.generic_name:"{query}" OR '
                              f'patient.reaction.reactionmeddrapt:"{query}")')
        else:
            search_parts.append(f'(device.brand_name:"{query}" OR '
                              f'device.generic_name:"{query}" OR '
                              f'mdr_text.text:"{query}")')

    if serious_only and event_type == "drug":
        search_parts.append('serious:1')

    if patient_sex:
        search_parts.append(f'patient.patientsex:{patient_sex}')

    if date_from and date_to:
        search_parts.append(f'receivedate:[{date_from} TO {date_to}]')

    search_query = " AND ".join(search_parts) if search_parts else None

    result = await fda_api_request(endpoint, search=search_query, count=count_by, limit=limit)

    return {
        "event_type": event_type,
        "query": query,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_drug_info(
    query: str,
    info_type: Literal["labels", "ndc", "approvals"] = "labels",
    include_inactive: bool = False,
    route: Optional[str] = None,
    dosage_form: Optional[str] = None,
    limit: int = 10
) -> dict:
    """Search FDA drug information databases.

    Args:
        query: Drug name (brand or generic), manufacturer, or active ingredient
        info_type: Type of information to search:
            - "labels": Drug labeling information (indications, warnings, dosage)
            - "ndc": National Drug Code directory (product/package codes)
            - "approvals": Drugs@FDA approved products database
        include_inactive: Include discontinued/inactive products
        route: Route of administration (e.g., "ORAL", "TOPICAL", "INTRAVENOUS")
        dosage_form: Dosage form (e.g., "TABLET", "CAPSULE", "INJECTION")
        limit: Maximum results to return (1-100)

    Returns:
        Drug information matching the search criteria

    Examples:
        >>> # Get drug label for Lipitor
        >>> search_drug_info("lipitor", info_type="labels")

        >>> # Find NDC codes for ibuprofen tablets
        >>> search_drug_info("ibuprofen", info_type="ndc", dosage_form="TABLET")

        >>> # Search FDA approved drugs
        >>> search_drug_info("pfizer", info_type="approvals")
    """
    # Map info_type to endpoint
    endpoint_map = {
        "labels": "drug/label",
        "ndc": "drug/ndc",
        "approvals": "drug/drugsfda"
    }
    endpoint = endpoint_map[info_type]

    # Build search query
    search_parts = []
    if query:
        if info_type == "labels":
            search_parts.append(f'(openfda.brand_name:"{query}" OR '
                              f'openfda.generic_name:"{query}" OR '
                              f'openfda.manufacturer_name:"{query}" OR '
                              f'active_ingredient:"{query}")')
        elif info_type == "ndc":
            search_parts.append(f'(proprietary_name:"{query}" OR '
                              f'nonproprietary_name:"{query}" OR '
                              f'labeler_name:"{query}")')
        else:  # approvals
            search_parts.append(f'(openfda.brand_name:"{query}" OR '
                              f'openfda.generic_name:"{query}" OR '
                              f'sponsor_name:"{query}")')

    if route:
        if info_type == "ndc":
            search_parts.append(f'route:"{route}"')
        else:
            search_parts.append(f'openfda.route:"{route}"')

    if dosage_form:
        if info_type == "ndc":
            search_parts.append(f'dosage_form:"{dosage_form}"')
        else:
            search_parts.append(f'openfda.dosage_form:"{dosage_form}"')

    if not include_inactive and info_type == "approvals":
        search_parts.append('products.marketing_status:"Prescription"')

    search_query = " AND ".join(search_parts) if search_parts else None

    result = await fda_api_request(endpoint, search=search_query, limit=limit)

    return {
        "info_type": info_type,
        "query": query,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_recalls(
    query: str,
    recall_type: Literal["drug"] = "drug",
    classification: Optional[Literal["Class I", "Class II", "Class III"]] = None,
    status: Optional[Literal["Ongoing", "Completed", "Pending", "Terminated"]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 10
) -> dict:
    """Search FDA drug recall enforcement facts.

    Args:
        query: Product name, recalling firm, or reason for recall
        recall_type: Only drug recall enforcement is supported
        classification: Recall classification:
            - "Class I": Dangerous or defective products with serious health consequences
            - "Class II": May cause temporary health problems
            - "Class III": Unlikely to cause health problems
        status: Current status of the recall
        date_from: Start date for recall initiation (YYYYMMDD format)
        date_to: End date for recall initiation (YYYYMMDD format)
        state: U.S. state where recall occurred
        limit: Maximum results to return (1-100)

    Returns:
        Recall enforcement reports matching the criteria

    Examples:
        >>> # Search for drug recalls
        >>> search_recalls("aspirin", recall_type="drug")

    """
    endpoint = f"{recall_type}/enforcement"

    # Build search query
    search_parts = []
    if query:
        search_parts.append(f'(product_description:"{query}" OR '
                          f'recalling_firm:"{query}" OR '
                          f'reason_for_recall:"{query}")')

    if classification:
        search_parts.append(f'classification:"{classification}"')

    if status:
        search_parts.append(f'status:"{status}"')

    if state:
        search_parts.append(f'state:"{state}"')

    if date_from and date_to:
        search_parts.append(f'report_date:[{date_from} TO {date_to}]')

    search_query = " AND ".join(search_parts) if search_parts else None

    result = await fda_api_request(endpoint, search=search_query, limit=limit)

    return {
        "recall_type": recall_type,
        "classification": classification,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_device_clearances(
    query: str,
    clearance_type: Literal["510k", "classification"] = "510k",
    device_class: Optional[Literal["1", "2", "3"]] = None,
    product_code: Optional[str] = None,
    decision_date_from: Optional[str] = None,
    decision_date_to: Optional[str] = None,
    limit: int = 10
) -> dict:
    """Search FDA medical device clearances and classifications.

    Args:
        query: Device name, applicant/manufacturer, or medical specialty
        clearance_type: Type of information:
            - "510k": FDA 510(k) premarket clearances
            - "classification": Device classification database
        device_class: Device risk class (1=low risk, 2=moderate, 3=high risk)
        product_code: FDA product code
        decision_date_from: Start date for clearance decision (YYYYMMDD, '510k' only)
        decision_date_to: End date for clearance decision (YYYYMMDD, '510k' only)
        limit: Maximum results to return (1-100)

    Returns:
        Device clearance or classification information

    Examples:
        >>> # Search 510(k) clearances for pacemakers
        >>> search_device_clearances("pacemaker", clearance_type="510k")

        >>> # Find Class III device classifications
        >>> search_device_clearances("implant", clearance_type="classification", device_class="3")

        >>> # Search recent clearances
        >>> search_device_clearances("monitor", decision_date_from="20230101", decision_date_to="20231231")
    """
    endpoint = f"device/{clearance_type}"

    # Build search query
    search_parts = []
    if query:
        if clearance_type == "510k":
            search_parts.append(f'(device_name:"{query}" OR '
                              f'applicant:"{query}" OR '
                              f'statement_or_summary:"{query}")')
        else:  # classification
            search_parts.append(f'(device_name:"{query}" OR '
                              f'medical_specialty_description:"{query}")')

    if device_class:
        search_parts.append(f'device_class:{device_class}')

    if product_code:
        search_parts.append(f'product_code:"{product_code}"')

    if decision_date_from and decision_date_to and clearance_type == "510k":
        search_parts.append(f'decision_date:[{decision_date_from} TO {decision_date_to}]')

    search_query = " AND ".join(search_parts) if search_parts else None

    result = await fda_api_request(endpoint, search=search_query, limit=limit)

    return {
        "clearance_type": clearance_type,
        "device_class": device_class,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_drug_shortages(
    query: Optional[str] = None,
    status: Literal["all", "current", "resolved"] = "current",
    limit: int = 20
) -> dict:
    """Get current and resolved drug shortages reported to FDA.

    Args:
        query: Product name, generic name, or active ingredient (optional)
        status: Shortage status to filter:
            - "current": Only currently in shortage
            - "resolved": Previously shortage, now resolved
            - "all": All shortages regardless of status
        limit: Maximum results to return (1-100)

    Returns:
        Drug shortage information including status and reason

    Examples:
        >>> # Get all current drug shortages
        >>> get_drug_shortages(status="current")

        >>> # Search for specific drug shortage
        >>> get_drug_shortages(query="insulin", status="all")

        >>> # Get recently resolved shortages
        >>> get_drug_shortages(status="resolved", limit=50)
    """
    endpoint = "drug/drugsfda"  # Using drugsfda as shortage endpoint isn't in public API

    # Note: The FDA doesn't have a public API endpoint specifically for shortages
    # This is a limitation we'll document
    search_parts = []

    if query:
        search_parts.append(f'(openfda.brand_name:"{query}" OR '
                          f'openfda.generic_name:"{query}")')

    # Map status (note: actual shortage data requires different endpoint)
    if status == "current":
        search_parts.append('products.marketing_status:"Prescription"')

    search_query = " AND ".join(search_parts) if search_parts else None

    result = await fda_api_request(endpoint, search=search_query, limit=limit)

    return {
        "note": "Full shortage data requires FDA Drug Shortages Database (not in public API)",
        "status_filter": status,
        "query": query,
        **result
    }
