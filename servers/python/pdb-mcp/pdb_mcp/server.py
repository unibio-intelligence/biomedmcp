"""PDB (Protein Data Bank) MCP Server - Python Implementation.

Provides access to the RCSB Protein Data Bank for protein structure data,
3D coordinates, quality metrics, and cross-references.

Based on TypeScript implementation with 5 focused tools - no reduction needed.
"""

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_tool_boundary
from biomedmcp.native.shapes import invalid_shape

from . import contracts

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query Protein Data Bank",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("pdb")

# Base URLs
RCSB_DATA_API = "https://data.rcsb.org/rest/v1"
RCSB_SEARCH_API = "https://search.rcsb.org/rcsbsearch/v2"
RCSB_FILES = "https://files.rcsb.org/download"
TIMEOUT = 30.0


async def api_request(
    base_url: str, endpoint: str, method: str = "GET", json_data: dict | None = None
) -> dict:
    """Make API request to RCSB PDB with error handling.

    Args:
        base_url: Base URL for the API
        endpoint: API endpoint path
        method: HTTP method (GET or POST)
        json_data: JSON body for POST requests

    Returns:
        API response as dictionary
    """
    headers = {
        "User-Agent": "PDB-MCP-Server/2.0.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        url = f"{base_url}/{endpoint}"

        if method.upper() == "GET":
            response = await client.get(url, headers=headers)
        elif method.upper() == "POST":
            response = await client.post(url, json=json_data, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        if response.status_code == 204:
            if base_url != RCSB_SEARCH_API or response.content:
                invalid_shape()
            return contracts.NO_CONTENT
        try:
            return response.json()
        except ValueError:
            invalid_shape()


async def download_file(url: str) -> str:
    """Download file from RCSB PDB.

    Args:
        url: File URL

    Returns:
        File content as string
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client, client.stream("GET", url) as response:
        response.raise_for_status()
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > contracts.FILE_BYTES:
                raise ResearchError(
                    "source_response_budget",
                    "Structure file exceeds the inline byte budget; no scientific absence is inferred.",
                )
            content.extend(chunk)
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            invalid_shape()


def validate_pdb_id(pdb_id: str) -> str:
    """Validate and normalize PDB ID.

    Args:
        pdb_id: PDB ID to validate

    Returns:
        Normalized PDB ID (lowercase)

    Raises:
        ValueError: If PDB ID is invalid
    """
    return contracts.pdb_id(pdb_id)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("pdb")
async def search_structures(
    query: str,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    sort_by: Literal[
        "score", "rcsb_accession_info.initial_release_date", "rcsb_entry_info.resolution_combined"
    ] = "score",
    sort_direction: Literal["asc", "desc"] = "desc",
    experimental_method: Literal[
        "ELECTRON CRYSTALLOGRAPHY",
        "ELECTRON MICROSCOPY",
        "EPR",
        "FIBER DIFFRACTION",
        "FLUORESCENCE TRANSFER",
        "INFRARED SPECTROSCOPY",
        "NEUTRON DIFFRACTION",
        "POWDER DIFFRACTION",
        "SOLID-STATE NMR",
        "SOLUTION NMR",
        "SOLUTION SCATTERING",
        "THEORETICAL MODEL",
        "X-RAY DIFFRACTION",
    ]
    | None = None,
    resolution_range: str | None = None,
    offset: Annotated[int, Field(ge=0, le=100000000)] = 0,
) -> dict:
    """Search experimental PDB archive entries by keyword, protein name, or PDB ID.

    Uses RCSB PDB's full-text search with optional filters for experimental method
    and resolution. Computed models are excluded from this archive search.

    Args:
        query: Search query (protein name, keyword, PDB ID, UniProt ID, etc.)
        limit: Number of results to return (1-100)
        sort_by: Documented RCSB field: score, rcsb_accession_info.initial_release_date, or rcsb_entry_info.resolution_combined
        sort_direction: Ascending or descending provider sort
        experimental_method: Filter by experimental method
        resolution_range: Resolution range filter (e.g., "1.0-2.0" in Angstroms)

    Returns:
        Search results with structure metadata

    Examples:
        >>> # Search for hemoglobin structures
        >>> search_structures("hemoglobin", limit=10)

        >>> # Search for high-resolution X-ray structures
        >>> search_structures("kinase", experimental_method="X-RAY DIFFRACTION",
        ...                   resolution_range="0.0-2.0")

        >>> # Search by PDB ID
        >>> search_structures("1ABC")
    """
    contracts.preflight("search_structures", locals())

    # Build search query
    search_query: dict = {
        "query": {"type": "terminal", "service": "full_text", "parameters": {"value": query}},
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": offset, "rows": limit},
            "results_content_type": ["experimental"],
            "results_verbosity": "minimal",
            "sort": [{"sort_by": sort_by, "direction": sort_direction}],
        },
    }

    # Add filters if provided
    filters = []

    if experimental_method:
        filters.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "exptl.method",
                    "operator": "exact_match",
                    "value": experimental_method,
                },
            }
        )

    if resolution_range:
        min_val, max_val = contracts.resolution_range(resolution_range)

        filters.append(
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entry_info.resolution_combined",
                    "operator": "range",
                    "value": {"from": min_val, "to": max_val, "include_lower": True, "include_upper": True},
                },
            }
        )

    # Apply filters if any
    if filters:
        search_query["query"] = {
            "type": "group",
            "logical_operator": "and",
            "nodes": [search_query["query"], *filters],
        }

    result = await api_request(RCSB_SEARCH_API, "query", method="POST", json_data=search_query)

    return contracts.search(result, label={"query": query}, limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("pdb")
async def get_structure_info(pdb_id: str, format: Literal["json", "pdb", "mmcif", "xml"] = "json") -> dict:
    """Get detailed information for a specific PDB structure.

    Retrieves comprehensive structure information including experimental details,
    resolution, organism, associated proteins, and more.

    Args:
        pdb_id: PDB ID (4-character code, e.g., "1ABC", "4HHB")
        format: Output format (json for metadata, pdb/mmcif/xml for coordinates)

    Returns:
        Structure information in requested format

    Examples:
        >>> # Get structure metadata in JSON
        >>> get_structure_info("4HHB")

        >>> # Get structure coordinates in PDB format
        >>> get_structure_info("4HHB", format="pdb")

        >>> # Get structure in mmCIF format
        >>> get_structure_info("1ABC", format="mmcif")
    """
    pdb_id = validate_pdb_id(pdb_id)

    if format == "json":
        # Get JSON metadata
        result = await api_request(RCSB_DATA_API, f"core/entry/{pdb_id}")
        result = await contracts.workers.run(contracts.entry, result, pdb_id)
        return {
            "pdb_id": pdb_id,
            "format": "json",
            "data": result,
            "url": f"https://www.rcsb.org/structure/{pdb_id}",
            "source_release": contracts.observed_release(result),
        }
    else:
        # Download file format
        extension = "cif" if format == "mmcif" else format
        url = f"{RCSB_FILES}/{pdb_id}.{extension}"
        content = await download_file(url)
        checked = await contracts.workers.run(contracts.coordinates, content, requested=pdb_id, format=format)

        return {
            "pdb_id": pdb_id,
            "format": format,
            "content": content,
            "download_url": url,
            "url": url,
            **checked,
        }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("pdb")
async def download_structure(
    pdb_id: str, format: Literal["pdb", "mmcif", "xml"] = "pdb", assembly_id: str | None = None
) -> dict:
    """Download structure coordinates in various formats.

    Downloads protein structure files in standard formats. Optionally download
    specific biological assemblies.

    Args:
        pdb_id: PDB ID (4-character code)
        format: File format (pdb, mmcif or xml); assembly downloads support pdb or mmcif
        assembly_id: Biological assembly ID (e.g., "1", "2") - downloads specific assembly if provided

    Returns:
        Structure file content and download information

    Examples:
        >>> # Download structure in PDB format
        >>> download_structure("4HHB")

        >>> # Download specific biological assembly in mmCIF format
        >>> download_structure("4HHB", format="mmcif", assembly_id="1")

        >>> # Download current text coordinates
        >>> download_structure("1ABC", format="mmcif")
    """
    contracts.preflight("download_structure", locals())
    pdb_id = validate_pdb_id(pdb_id)

    # Build download URL
    extension = "cif" if format == "mmcif" else format

    if assembly_id and format == "pdb":
        url = f"{RCSB_FILES}/{pdb_id}.pdb{assembly_id}"
    elif assembly_id:
        url = f"{RCSB_FILES}/{pdb_id}-assembly{assembly_id}.{extension}"
    else:
        url = f"{RCSB_FILES}/{pdb_id}.{extension}"

    content = await download_file(url)
    checked = await contracts.workers.run(
        contracts.coordinates, content, requested=pdb_id, format=format, assembly_id=assembly_id
    )

    return {
        "pdb_id": pdb_id,
        "format": format,
        "assembly_id": assembly_id,
        "download_url": url,
        "url": url,
        "content": content,
        "content_length": len(content),
        **checked,
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("pdb")
async def search_by_uniprot(
    uniprot_id: str,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
    offset: Annotated[int, Field(ge=0, le=100000000)] = 0,
) -> dict:
    """Find PDB structures associated with a UniProt accession.

    Searches for all PDB structures that contain a protein with the specified
    UniProt accession. Useful for finding all structures of a particular protein.

    Args:
        uniprot_id: UniProt accession number (e.g., "P69905", "Q9Y6K9")
        limit: Number of results to return (1-100)

    Returns:
        List of PDB structures associated with the UniProt ID

    Examples:
        >>> # Find all structures for hemoglobin alpha chain
        >>> search_by_uniprot("P69905")

        >>> # Find structures for a specific human protein
        >>> search_by_uniprot("Q9Y6K9", limit=50)
    """
    contracts.preflight("search_by_uniprot", locals())

    # Build UniProt search query
    search_query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
                "operator": "exact_match",
                "value": uniprot_id,
            },
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": offset, "rows": limit},
            "results_content_type": ["experimental"],
            "results_verbosity": "minimal",
            "sort": [{"sort_by": "score", "direction": "desc"}],
        },
    }

    result = await api_request(RCSB_SEARCH_API, "query", method="POST", json_data=search_query)

    return contracts.search(result, label={"uniprot_id": uniprot_id}, limit=limit, offset=offset)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("pdb")
async def get_structure_quality(pdb_id: str) -> dict:
    """Get structure metadata and embedded wwPDB validation summaries.

    Retains source entry metadata and available validation summary categories.
    Resolution units are angstroms; missing measurements remain unknown.
    This does not perform independent structural validation or quality ranking.

    Args:
        pdb_id: PDB ID (4-character code)

    Returns:
        Structure quality metrics and validation report

    Examples:
        >>> # Get quality metrics for a structure
        >>> get_structure_quality("4HHB")

        >>> # Check validation for a specific structure
        >>> get_structure_quality("1ABC")
    """
    pdb_id = validate_pdb_id(pdb_id)

    result = await api_request(RCSB_DATA_API, f"core/entry/{pdb_id}")
    return await contracts.workers.run(contracts.quality, result, pdb_id)
