"""Clinical Trials MCP Server - Optimized Python Implementation.

Provides access to ClinicalTrials.gov database with composite tools.
"""

import json
from collections import Counter
from typing import Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.native.http import ProviderHTTP
from biomedmcp.pagination import page_payload

from .contracts import invalid, nct, validate_request, validate_response

TrialPhase = Literal["NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
TrialStatus = Literal[
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
    "WITHHELD",
    "UNKNOWN",
]

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query ClinicalTrials.gov",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("clinical-trials")

# Base URL for ClinicalTrials.gov API v2
BASE_URL = "https://clinicaltrials.gov/api/v2"
DEFAULT_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "ubi-clinical-trials-mcp/1.0 (+https://unibiointelligence.com)",
}


async def ct_api_request(endpoint: str, params: dict | None = None) -> dict:
    """Make request to ClinicalTrials.gov API with error handling."""
    params = params or {}
    with provider_boundary("clinical-trials"):
        name = "search" if endpoint == "studies" else "study"
        requested = nct(endpoint.removeprefix("studies/")) if name == "study" else None
        validate_request(name, params)
        try:
            result = await ProviderHTTP().get(
                f"{BASE_URL}/{endpoint}", params=params, headers=DEFAULT_HEADERS
            )
        except ResearchError as error:
            if error.code == "upstream_error":
                invalid()
            raise
        return validate_response(name, result, params=params, requested_id=requested)


def safe_error(error):
    if isinstance(error, ResearchError):
        return error.as_dict()
    try:
        value = json.loads(str(error))
        if isinstance(value, dict) and value.get("code") in {
            "invalid_source_response",
            "source_unavailable",
            "source_not_found",
            "source_rate_limited",
            "source_access_denied",
            "source_authentication_failed",
            "source_connection_rejected",
        }:
            return ResearchError(
                value["code"],
                "The trial source could not complete the request.",
                retryable=value.get("retryable") is True,
            ).as_dict()
    except (ValueError, TypeError):
        pass
    return ResearchError(
        "upstream_error", "The trial source could not complete the request.", retryable=True
    ).as_dict()


def add_filter(params, expression):
    params["filter.advanced"] = " AND ".join(filter(None, [params.get("filter.advanced"), expression]))


def build_query_filters(
    condition: str | None = None,
    intervention: str | None = None,
    sponsor: str | None = None,
    location: str | None = None,
    **kwargs,
) -> dict:
    """Build query parameters for API request."""
    params = {}

    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    if sponsor:
        params["query.lead"] = sponsor
    if location:
        params["query.locn"] = location

    # Add any additional kwargs
    for key, value in kwargs.items():
        if value is not None:
            params[key] = value

    return params


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_studies(
    query: str | None = None,
    condition: str | None = None,
    intervention: str | None = None,
    location: str | None = None,
    sponsor: str | None = None,
    phase: TrialPhase | None = None,
    status: TrialStatus | None = None,
    sex: Literal["ALL", "FEMALE", "MALE"] | None = None,
    age_group: Literal["CHILD", "ADULT", "OLDER_ADULT"] | None = None,
    page_size: int = 10,
    page_token: str | None = None,
    count_total: bool = True,
) -> dict:
    """Search for clinical trials with comprehensive filters.

    Args:
        query: General search term (searches across all fields)
        condition: Medical condition or disease
        intervention: Treatment, drug, device, or intervention
        location: Geographic location (city, state, country, or facility)
        sponsor: Sponsor name or organization
        phase: Study phase filter
        status: Recruitment status filter
        sex: Sex eligibility filter
        age_group: Age group filter
        page_size: Number of results to return (1-100)
        page_token: Continuation token from a previous response
        count_total: Include totalCount for coverage/audit workflows

    Returns:
        Clinical trial search results with study information

    Examples:
        # Search for diabetes trials
        condition="diabetes", page_size=10

        # Search recruiting cancer trials
        condition="cancer", status="RECRUITING", page_size=5

        # Search by intervention and phase
        intervention="pembrolizumab", phase="PHASE3"

        # General keyword search
        query="COVID-19 vaccine", page_size=25
    """
    params = build_query_filters(
        condition=condition, intervention=intervention, sponsor=sponsor, location=location
    )

    # Add general query if provided
    if query:
        params["query.term"] = query

    # The provider's default order is not relevance order. Keep this fixed
    # across cursor pages rather than ranking a default-ordered tiny sample.
    params["sort"] = "@relevance"

    # Add filters
    if phase:
        add_filter(params, f"AREA[Phase]{phase}")

    if status:
        params["filter.overallStatus"] = status

    if sex:
        params["filter.advanced"] = " AND ".join(
            filter(None, [params.get("filter.advanced"), f"AREA[Sex]{sex}"])
        )

    if age_group:
        params["filter.advanced"] = " AND ".join(
            filter(None, [params.get("filter.advanced"), f"AREA[StdAge]{age_group}"])
        )

    # Set page size
    params["pageSize"] = max(1, min(page_size, 100))
    if page_token:
        params["pageToken"] = page_token
    if count_total:
        params["countTotal"] = True

    result = await ct_api_request("studies", params)

    return {
        "search_criteria": {
            "query": query,
            "condition": condition,
            "intervention": intervention,
            "location": location,
            "sponsor": sponsor,
            "phase": phase,
            "status": status,
            "page_size": params["pageSize"],
            "page_token": page_token,
            "count_total": count_total,
        },
        **result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_study_details(
    nct_id: str, include_full_protocol: bool = True, include_results: bool = True
) -> dict:
    """Get detailed information about a specific clinical trial.

    Args:
        nct_id: NCT ID of the study (e.g., NCT00000419)
        include_full_protocol: Include complete protocol section
        include_results: Include published results if available

    Returns:
        Complete study details including protocol, eligibility, contacts, and results

    Examples:
        # Get full study details
        get_study_details("NCT04368728")

        # Get basic study info only
        get_study_details("NCT04368728", include_full_protocol=False, include_results=False)
    """
    nct(nct_id)
    fields = (
        ["ProtocolSection"]
        if include_full_protocol
        else ["IdentificationModule", "StatusModule", "DesignModule"]
    )
    fields.append("HasResults")
    if include_results:
        fields.append("ResultsSection")
    result = await ct_api_request(f"studies/{nct_id}", {"fields": ",".join(fields)})

    canonical = result["protocolSection"]["identificationModule"]["nctId"]
    return {"nct_id": nct_id, **result, "url": f"https://clinicaltrials.gov/study/{canonical}"}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_by_filters(
    filter_type: Literal["location", "condition", "intervention", "sponsor", "dates"] = "condition",
    primary_value: str = "",
    country: str | None = None,
    state: str | None = None,
    city: str | None = None,
    facility: str | None = None,
    phase: TrialPhase | None = None,
    status: TrialStatus | None = None,
    intervention_type: Literal["DRUG", "DEVICE", "BIOLOGICAL", "PROCEDURE", "BEHAVIORAL", "OTHER"]
    | None = None,
    sponsor_type: Literal["INDUSTRY", "NIH", "FED", "OTHER"] | None = None,
    start_date_from: str | None = None,
    start_date_to: str | None = None,
    completion_date_from: str | None = None,
    completion_date_to: str | None = None,
    page_size: int = 10,
) -> dict:
    """Search clinical trials with specialized filters based on type.

    Args:
        filter_type: Type of specialized filter to apply
        primary_value: Main search value (condition, intervention, sponsor name, etc.)
        country: Country filter (for location searches)
        state: State/province filter (for location searches)
        city: City filter (for location searches)
        facility: Facility name (for location searches)
        phase: Study phase filter
        status: Recruitment status filter
        intervention_type: Type of intervention (for intervention searches)
        sponsor_type: Type of sponsor (for sponsor searches)
        start_date_from: Start date from (YYYY-MM-DD) for date searches
        start_date_to: Start date to (YYYY-MM-DD) for date searches
        completion_date_from: Completion date from (YYYY-MM-DD) for date searches
        completion_date_to: Completion date to (YYYY-MM-DD) for date searches
        page_size: Number of results to return (1-100)

    Returns:
        Clinical trial search results based on specified filters

    Examples:
        # Search by location
        search_by_filters(
        ...     filter_type="location",
        ...     country="United States",
        ...     state="California",
        ...     city="San Francisco"
        ... )

        # Search by condition with phase filter
        search_by_filters(
        ...     filter_type="condition",
        ...     primary_value="lung cancer",
        ...     phase="PHASE3",
        ...     status="RECRUITING"
        ... )

        # Search by sponsor
        search_by_filters(
        ...     filter_type="sponsor",
        ...     primary_value="Pfizer",
        ...     sponsor_type="INDUSTRY"
        ... )

        # Search by date range
        search_by_filters(
        ...     filter_type="dates",
        ...     start_date_from="2023-01-01",
        ...     start_date_to="2024-12-31",
        ...     primary_value="cancer"
        ... )
    """
    params = {"pageSize": min(page_size, 100)}

    if filter_type == "location":
        location_parts = []
        if facility:
            location_parts.append(facility)
        if city:
            location_parts.append(city)
        if state:
            location_parts.append(state)
        if country:
            location_parts.append(country)

        if location_parts:
            params["query.locn"] = ", ".join(location_parts)

    elif filter_type == "condition":
        if primary_value:
            params["query.cond"] = primary_value

    elif filter_type == "intervention":
        if primary_value:
            params["query.intr"] = primary_value
        if intervention_type:
            add_filter(params, f"AREA[InterventionType]{intervention_type}")

    elif filter_type == "sponsor":
        if primary_value:
            params["query.lead"] = primary_value
        if sponsor_type:
            add_filter(params, f"AREA[LeadSponsorClass]{sponsor_type}")

    elif filter_type == "dates":
        if primary_value:
            params["query.cond"] = primary_value
        if start_date_from:
            add_filter(params, f"AREA[StartDate]RANGE[{start_date_from}, {start_date_to or 'MAX'}]")
        if completion_date_from:
            add_filter(
                params,
                f"AREA[PrimaryCompletionDate]RANGE[{completion_date_from}, {completion_date_to or 'MAX'}]",
            )

    # Add common filters
    if phase:
        add_filter(params, f"AREA[Phase]{phase}")
    if status:
        params["filter.overallStatus"] = status

    result = await ct_api_request("studies", params)

    return {"filter_type": filter_type, "filters_applied": params, **result}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_recruiting_studies(
    condition: str | None = None,
    location: str | None = None,
    age_group: Literal["CHILD", "ADULT", "OLDER_ADULT"] | None = None,
    sex: Literal["ALL", "FEMALE", "MALE"] | None = None,
    include_contacts: bool = True,
    page_size: int = 10,
) -> dict:
    """Get currently recruiting clinical trials with contact information.

    Args:
        condition: Medical condition to filter by
        location: Geographic location filter
        age_group: Age group eligibility
        sex: Sex eligibility
        include_contacts: Include contact and location information
        page_size: Number of results to return (1-50)

    Returns:
        Currently recruiting trials with contact and enrollment information

    Examples:
        # Find recruiting cancer trials
        get_recruiting_studies(condition="breast cancer", location="New York")

        # Find pediatric trials
        get_recruiting_studies(age_group="CHILD", include_contacts=True)

        # Find trials for women
        get_recruiting_studies(condition="ovarian cancer", sex="FEMALE")
    """
    params = {"filter.overallStatus": "RECRUITING", "pageSize": min(page_size, 50)}

    if condition:
        params["query.cond"] = condition
    if location:
        params["query.locn"] = location
    if age_group:
        params["filter.advanced"] = " AND ".join(
            filter(None, [params.get("filter.advanced"), f"AREA[StdAge]{age_group}"])
        )
    if sex:
        params["filter.advanced"] = " AND ".join(
            filter(None, [params.get("filter.advanced"), f"AREA[Sex]{sex}"])
        )

    if include_contacts:
        params["fields"] = "ContactsLocationsModule,IdentificationModule,StatusModule,ConditionsModule"

    result = await ct_api_request("studies", params)

    return {
        "recruitment_status": "RECRUITING",
        "filters": {"condition": condition, "location": location, "age_group": age_group, "sex": sex},
        **result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_completed_studies_with_results(
    condition: str | None = None,
    intervention: str | None = None,
    completed_after: str | None = None,
    has_results: bool = True,
    page_size: int = 10,
) -> dict:
    """Find completed clinical trials with published results.

    Args:
        condition: Medical condition to filter by
        intervention: Treatment or intervention to filter by
        completed_after: Find studies completed after this date (YYYY-MM-DD)
        has_results: Only return studies with published results
        page_size: Number of results to return (1-100)

    Returns:
        Completed trials with results data

    Examples:
        # Find completed COVID-19 trials with results
        get_completed_studies_with_results(
        ...     condition="COVID-19",
        ...     has_results=True
        ... )

        # Find drug trials completed recently
        get_completed_studies_with_results(
        ...     intervention="pembrolizumab",
        ...     completed_after="2023-01-01"
        ... )
    """
    params = {"filter.overallStatus": "COMPLETED", "pageSize": min(page_size, 100)}

    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.intr"] = intervention
    if completed_after:
        add_filter(params, f"AREA[PrimaryCompletionDate]RANGE[{completed_after}, MAX]")
    if has_results:
        add_filter(params, "AREA[HasResults]true")
        params["fields"] = "ProtocolSection,ResultsSection"

    result = await ct_api_request("studies", params)

    return {
        "status": "COMPLETED",
        "has_results": has_results,
        "filters": {"condition": condition, "intervention": intervention, "completed_after": completed_after},
        **result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_trial_statistics(
    group_by: Literal["phase", "status", "studyType", "condition", "sponsor"] = "phase",
    condition: str | None = None,
    phase: TrialPhase | None = None,
    status: TrialStatus | None = None,
    page_size: int = 25,
    page_token: str | None = None,
) -> dict:
    """Count study memberships in one bounded provider window; not a population estimate.

    Missing grouping fields stay unavailable. A study can belong to several
    phase/condition groups; their sum can exceed the unique study denominator.
    Records retain the exact study IDs and grouping values used by these counts;
    retrieve a trial separately for its full protocol. Follow public next_actions
    for additional windows; counts are not cumulative.
    """
    params = {"pageSize": page_size, "countTotal": True}
    if condition:
        params["query.cond"] = condition
    if phase:
        add_filter(params, f"AREA[Phase]{phase}")
    if status:
        params["filter.overallStatus"] = status
    if page_token is not None:
        params["pageToken"] = page_token
    result = await ct_api_request("studies", params)
    rows = result["studies"]
    counts, missing, memberships = Counter(), 0, []
    for row in rows:
        protocol = row["protocolSection"]
        if group_by == "phase":
            values = protocol.get("designModule", {}).get("phases", [])
        elif group_by == "condition":
            values = protocol.get("conditionsModule", {}).get("conditions", [])
        else:
            value = (
                protocol.get("statusModule", {}).get("overallStatus")
                if group_by == "status"
                else protocol.get("designModule", {}).get("studyType")
                if group_by == "studyType"
                else protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name")
            )
            values = [value] if value else []
        unique = {value for value in values if value.strip()}
        if not unique:
            missing += 1
        counts.update(unique)
        memberships.append(
            {
                "nct_id": protocol["identificationModule"]["nctId"],
                "group_values": sorted(unique),
                "missing_group_field": not unique,
            }
        )
    token, total = result.get("nextPageToken"), result.get("totalCount")
    complete = page_token is None and token is None and total is not None and total == len(rows)
    page = page_payload(
        memberships, raw_count=len(rows), exhausted=token is None, continuation=token, total=total
    )
    return {
        "group_by": group_by,
        "filters": {"condition": condition, "phase": phase, "status": status},
        "total_count": total,
        "counts": dict(sorted(counts.items())),
        "coverage": {
            "acquired_studies": len(rows),
            "grouped_studies": len(rows) - missing,
            "missing_group_fields": missing,
            "complete": complete,
            "scope": "one provider-returned window; not a representative sample",
            "multi_label_groups": group_by in {"phase", "condition"},
        },
        "section_outcomes": {
            "coverage": {"outcome": "data" if complete else "partial"},
            "groups": {
                "outcome": "unavailable"
                if missing == len(rows) and rows
                else "partial"
                if missing
                else "data"
            },
        },
        **page,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_specialized_trials(
    specialty_type: Literal["rare_disease", "pediatric", "similar_to_nct"] = "pediatric",
    search_value: str = "",
    nct_id: str | None = None,
    age_range: Literal["INFANT", "CHILD", "ADOLESCENT"] | None = None,
    status: TrialStatus | None = None,
    page_size: int = 10,
) -> dict:
    """Search for specialized clinical trial categories.

    Args:
        specialty_type: Type of specialized search:
            - "rare_disease": Rare diseases and orphan conditions
            - "pediatric": Trials for children and adolescents
            - "similar_to_nct": Find trials similar to a reference NCT ID
        search_value: Search term (rare disease name, pediatric condition, etc.)
        nct_id: Reference NCT ID (required for similar_to_nct searches)
        age_range: Pediatric age range filter
        status: Recruitment status filter
        page_size: Number of results to return (1-50)

    Returns:
        Specialized trial search results

    Examples:
        # Search rare disease trials
        search_specialized_trials(
        ...     specialty_type="rare_disease",
        ...     search_value="Huntington's disease",
        ...     status="RECRUITING"
        ... )

        # Search pediatric trials
        search_specialized_trials(
        ...     specialty_type="pediatric",
        ...     search_value="leukemia",
        ...     age_range="CHILD"
        ... )

        # Find similar studies
        search_specialized_trials(
        ...     specialty_type="similar_to_nct",
        ...     nct_id="NCT04368728"
        ... )
    """
    params = {"pageSize": min(page_size, 50)}

    if specialty_type == "rare_disease":
        if search_value:
            params["query.cond"] = search_value
        # Add rare disease filter
        params["query.term"] = f"{search_value} rare disease orphan"

    elif specialty_type == "pediatric":
        if search_value:
            params["query.cond"] = search_value
        add_filter(params, "AREA[StdAge]CHILD")
        if age_range == "INFANT":
            add_filter(params, "AREA[MinimumAge]RANGE[MIN, 1 year]")
        elif age_range == "ADOLESCENT":
            add_filter(
                params, "AREA[MinimumAge]RANGE[MIN, 17 years] AND AREA[MaximumAge]RANGE[12 years, MAX]"
            )

    elif specialty_type == "similar_to_nct":
        if not nct_id:
            return {"error": "nct_id is required for similar_to_nct searches"}

        ref_study = await get_study_details(nct_id, include_full_protocol=True, include_results=False)
        conditions = ref_study["protocolSection"].get("conditionsModule", {}).get("conditions", [])
        if not conditions:
            raise ResearchError(
                "source_unavailable", "The reference trial supplies no conditions for discovery."
            )
        params["query.cond"] = " OR ".join(conditions[:3])

    # Add common filters
    if status:
        params["filter.overallStatus"] = status

    result = await ct_api_request("studies", params)

    return {
        "specialty_type": specialty_type,
        "search_value": search_value,
        "reference_nct_id": nct_id,
        **result,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def compare_trials(
    nct_ids: list[str],
    comparison_fields: list[Literal["phase", "status", "enrollment", "dates", "outcomes"]] | None = None,
) -> dict:
    """Compare multiple clinical trials side by side.

    Args:
        nct_ids: List of NCT IDs to compare (2-5 trials)
        comparison_fields: Fields to compare across trials

    Returns:
        Comparative analysis of the specified trials

    Examples:
        # Compare two trials
        compare_trials(
        ...     ["NCT04368728", "NCT04280705"],
        ...     comparison_fields=["phase", "status", "enrollment"]
        ... )
    """
    comparison_fields = ["phase", "status"] if comparison_fields is None else comparison_fields
    if not 2 <= len(nct_ids) <= 5 or len(set(nct_ids)) != len(nct_ids):
        raise ResearchError("invalid_parameters", "Compare two to five distinct NCT identifiers.")
    for value in nct_ids:
        nct(value)
    if not comparison_fields or len(set(comparison_fields)) != len(comparison_fields):
        raise ResearchError("invalid_parameters", "Select each comparison field once.")
    comparisons, statuses = [], {}
    for nct_id in nct_ids:
        try:
            record = await get_study_details(nct_id, include_full_protocol=True, include_results=False)
            protocol = record["protocolSection"]
            values = {
                "phase": protocol.get("designModule", {}).get("phases"),
                "status": protocol.get("statusModule", {}).get("overallStatus"),
                "enrollment": protocol.get("designModule", {}).get("enrollmentInfo"),
                "dates": {
                    key: protocol.get("statusModule", {}).get(key)
                    for key in ("startDateStruct", "primaryCompletionDateStruct", "completionDateStruct")
                    if key in protocol.get("statusModule", {})
                },
                "outcomes": protocol.get("outcomesModule"),
            }
            fields = {
                key: {
                    "outcome": "data" if values[key] else "unavailable",
                    "value": values[key] if values[key] else None,
                }
                for key in comparison_fields
            }
            if "enrollment" in fields:
                enrollment = values["enrollment"]
                if not enrollment or "count" not in enrollment:
                    fields["enrollment"] = {"outcome": "unavailable", "value": None}
                elif "type" not in enrollment:
                    fields["enrollment"]["outcome"] = "partial"
            outcome = "partial" if any(field["outcome"] != "data" for field in fields.values()) else "data"
            comparisons.append(
                {
                    "nct_id": nct_id,
                    "canonical_nct_id": protocol["identificationModule"]["nctId"],
                    "data": record,
                    "fields": fields,
                    "success": True,
                }
            )
            statuses[nct_id] = {"outcome": outcome}
        except (ResearchError, ToolError) as error:
            safe = safe_error(error)
            comparisons.append({"nct_id": nct_id, "error": safe, "success": False})
            statuses[nct_id] = {"outcome": "unavailable", "error": safe}
    return {
        "comparison_type": "clinical_trials",
        "nct_ids": nct_ids,
        "comparison_fields": comparison_fields,
        "results": comparisons,
        "section_outcomes": statuses,
        "interpretation": "Separate registry assertions; enrollment counts are not comparable efficacy or safety outcomes. Preserve ACTUAL versus ESTIMATED enrollment and each endpoint's measure/timeframe.",
    }
