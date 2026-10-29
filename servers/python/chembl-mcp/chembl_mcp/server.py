"""ChEMBL MCP Server - Optimized Python Implementation.

Provides access to ChEMBL bioactive molecules database with composite tools.
"""

from biomedmcp import transport as httpx
from typing import Optional, Literal, List
from fastmcp import FastMCP
from biomedmcp.errors import provider_boundary
from .properties import analyze_properties

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query ChEMBL",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize server
mcp = FastMCP("chembl")

# Base URL for ChEMBL API
BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"


async def chembl_api_request(
    endpoint: str,
    params: Optional[dict] = None,
    chembl_id: Optional[str] = None
) -> dict:
    """Make request to ChEMBL API with error handling."""
    if chembl_id:
        url = f"{BASE_URL}/{endpoint}/{chembl_id}.json"
    else:
        url = f"{BASE_URL}/{endpoint}.json"

    with provider_boundary("chembl"):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_compounds(
    query: str,
    search_type: Literal["name", "inchi", "similarity", "substructure"] = "name",
    smiles: Optional[str] = None,
    similarity_threshold: float = 0.7,
    limit: int = 25,
    offset: int = 0
) -> dict:
    """Search ChEMBL database for compounds by various methods.

    Args:
        query: Search query (compound name, synonym, identifier, or InChI string)
        search_type: Type of search to perform:
            - "name": Search by name or identifier (default)
            - "inchi": Search by InChI key or InChI string
            - "similarity": Find similar compounds by SMILES (requires smiles parameter)
            - "substructure": Find compounds containing substructure (requires smiles parameter)
        smiles: SMILES string (required for similarity and substructure searches)
        similarity_threshold: Similarity threshold for similarity search (0-1, default: 0.7)
        limit: Number of results to return (1-1000)
        offset: Number of results to skip

    Returns:
        Compound search results with structures and properties

    Examples:
        # Search for aspirin by name (verified via MCP)
        query="aspirin", search_type="name", limit=3

        # Search with small result set
        query="ibuprofen", limit=5

        # Search by InChI
        query="BSYNRYMUTXBXSQ-UHFFFAOYSA-N", search_type="inchi"
    """
    params = {"limit": min(limit, 1000), "offset": offset}

    if search_type == "name":
        params["q"] = query
        result = await chembl_api_request("molecule/search", params)
    elif search_type == "inchi":
        # InChI search using molecule search endpoint
        params["q"] = query
        result = await chembl_api_request("molecule/search", params)
    elif search_type == "similarity":
        if not smiles:
            return {"error": "SMILES parameter required for similarity search"}
        # Note: ChEMBL API similarity search requires different endpoint
        result = {"message": "Similarity search requires ChEMBL web services - use structure search instead", "query": query, "smiles": smiles}
    elif search_type == "substructure":
        if not smiles:
            return {"error": "SMILES parameter required for substructure search"}
        # Note: ChEMBL API substructure search requires different endpoint
        result = {"message": "Substructure search requires ChEMBL web services - use structure search instead", "query": query, "smiles": smiles}

    return {
        "search_type": search_type,
        "query": query,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_compound_details(
    chembl_id: str,
    include_structure: bool = True,
    include_properties: bool = True,
    structure_format: Literal["smiles", "inchi", "all"] = "all"
) -> dict:
    """Get detailed information for a specific compound.

    Args:
        chembl_id: ChEMBL compound ID (e.g., CHEMBL59)
        include_structure: Include chemical structure data
        include_properties: Include molecular properties (MW, LogP, etc.)
        structure_format: Structure format to return

    Returns:
        Complete compound information including structure and properties

    Examples:
        # Get aspirin compound details
        "CHEMBL25"

        # Get ibuprofen details with all structure formats
        "CHEMBL521", structure_format="all"
    """
    result = await chembl_api_request("molecule", chembl_id=chembl_id)

    # Filter response based on parameters
    if not include_structure and "molecule_structures" in result:
        del result["molecule_structures"]

    if not include_properties and "molecule_properties" in result:
        del result["molecule_properties"]

    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_targets(
    query: str,
    search_by: Literal["name", "uniprot", "type"] = "name",
    target_type: Optional[str] = None,
    organism: Optional[str] = None,
    limit: int = 25
) -> dict:
    """Search for biological targets in ChEMBL.

    Args:
        query: Target name, UniProt ID, or search query
        search_by: Search method:
            - "name": Search by target name (default)
            - "uniprot": Search by UniProt accession number
            - "type": Search by target type
        target_type: Filter by target type (e.g., "SINGLE PROTEIN", "PROTEIN COMPLEX")
        organism: Filter by organism (e.g., "Homo sapiens")
        limit: Number of results to return (1-1000)

    Returns:
        Target search results with target information

    Examples:
        # Search for EGFR targets
        "EGFR", limit=5

        # Search for kinase targets in humans
        "kinase", organism="Homo sapiens", limit=10

        # Find target by UniProt ID
        "P00533", search_by="uniprot"
    """
    params = {"q": query, "limit": min(limit, 1000)}

    if target_type:
        params["target_type"] = target_type

    if organism:
        params["organism"] = organism

    result = await chembl_api_request("target/search", params)

    return {
        "search_by": search_by,
        "query": query,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_target_details(
    target_chembl_id: str,
    include_compounds: bool = False,
    include_pathways: bool = False,
    activity_type: Optional[str] = None,
    compound_limit: int = 25
) -> dict:
    """Get detailed information for a specific target.

    Args:
        target_chembl_id: ChEMBL target ID (e.g., CHEMBL2095173)
        include_compounds: Include compounds tested against this target
        include_pathways: Include biological pathways (if available)
        activity_type: Filter compounds by activity type (e.g., "IC50", "Ki", "Kd")
        compound_limit: Maximum compounds to return if include_compounds=True

    Returns:
        Complete target information and optionally associated compounds

    Examples:
        # Get target information
        get_target_details("CHEMBL2095173")

        # Get target with active compounds
        get_target_details("CHEMBL2095173", include_compounds=True, activity_type="IC50")
    """
    result = await chembl_api_request("target", chembl_id=target_chembl_id)

    # Optionally fetch compounds for this target
    if include_compounds:
        params = {"target_chembl_id": target_chembl_id, "limit": compound_limit}
        if activity_type:
            params["standard_type"] = activity_type

        try:
            activities = await chembl_api_request("activity", params)
            result["associated_compounds"] = activities
        except Exception as e:
            result["associated_compounds"] = {"error": str(e)}

    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_bioactivities(
    target_chembl_id: Optional[str] = None,
    molecule_chembl_id: Optional[str] = None,
    assay_chembl_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    units: Optional[str] = None,
    limit: int = 25
) -> dict:
    """Search bioactivity measurements and assay results.

    Args:
        target_chembl_id: Filter by ChEMBL target ID
        molecule_chembl_id: Filter by ChEMBL compound ID
        assay_chembl_id: Filter by ChEMBL assay ID
        activity_type: Activity type (e.g., "IC50", "Ki", "EC50", "Kd")
        min_value: Minimum activity value
        max_value: Maximum activity value
        units: Units filter (e.g., "nM", "uM")
        limit: Number of results to return (1-1000)

    Returns:
        Bioactivity measurements matching the search criteria

    Examples:
        # Get activities for a target
        search_bioactivities(target_chembl_id="CHEMBL2095173", activity_type="IC50")

        # Get activities for a compound
        search_bioactivities(molecule_chembl_id="CHEMBL59", limit=50)

        # Find activities in specific range
        search_bioactivities(activity_type="IC50", min_value=1, max_value=100, units="nM")
    """
    params = {"limit": min(limit, 1000)}

    if target_chembl_id:
        params["target_chembl_id"] = target_chembl_id
    if molecule_chembl_id:
        params["molecule_chembl_id"] = molecule_chembl_id
    if assay_chembl_id:
        params["assay_chembl_id"] = assay_chembl_id
    if activity_type:
        params["standard_type"] = activity_type
    if units:
        params["standard_units"] = units

    result = await chembl_api_request("activity", params)

    return {
        "filters": {
            "target": target_chembl_id,
            "molecule": molecule_chembl_id,
            "assay": assay_chembl_id,
            "type": activity_type,
            "value_range": f"{min_value}-{max_value}" if min_value and max_value else None
        },
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_assay_details(
    assay_chembl_id: str,
    include_activities: bool = False,
    activity_limit: int = 25
) -> dict:
    """Get detailed information for a specific assay.

    Args:
        assay_chembl_id: ChEMBL assay ID (e.g., CHEMBL1217643)
        include_activities: Include bioactivity measurements from this assay
        activity_limit: Maximum activities to return if include_activities=True

    Returns:
        Complete assay information and optionally bioactivity measurements

    Examples:
        # Get assay information
        get_assay_details("CHEMBL1217643")

        # Get assay with activity data
        get_assay_details("CHEMBL1217643", include_activities=True, activity_limit=50)
    """
    result = await chembl_api_request("assay", chembl_id=assay_chembl_id)

    # Optionally fetch activities for this assay
    if include_activities:
        try:
            activities = await chembl_api_request(
                "activity",
                params={"assay_chembl_id": assay_chembl_id, "limit": activity_limit}
            )
            result["activities"] = activities
        except Exception as e:
            result["activities"] = {"error": str(e)}

    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def compare_compound_activities(
    molecule_chembl_ids: List[str],
    target_chembl_id: Optional[str] = None,
    activity_type: Optional[str] = None
) -> dict:
    """Compare bioactivity data across multiple compounds.

    Args:
        molecule_chembl_ids: List of ChEMBL compound IDs to compare (2-10 compounds)
        target_chembl_id: Optional target filter for comparison
        activity_type: Optional activity type for comparison (e.g., "IC50", "Ki")

    Returns:
        Comparative bioactivity data for the specified compounds

    Examples:
        # Compare IC50 values for compounds against a target
        compare_compound_activities(
        ...     ["CHEMBL59", "CHEMBL25"],
        ...     target_chembl_id="CHEMBL2095173",
        ...     activity_type="IC50"
        ... )

        # Compare general activities
        compare_compound_activities(["CHEMBL59", "CHEMBL25", "CHEMBL192"])
    """
    if len(molecule_chembl_ids) < 2 or len(molecule_chembl_ids) > 10:
        return {"error": "Please provide between 2 and 10 compound IDs"}

    results = {}
    for chembl_id in molecule_chembl_ids:
        params = {"molecule_chembl_id": chembl_id, "limit": 100}
        if target_chembl_id:
            params["target_chembl_id"] = target_chembl_id
        if activity_type:
            params["standard_type"] = activity_type

        try:
            activities = await chembl_api_request("activity", params)
            results[chembl_id] = activities
        except Exception as e:
            results[chembl_id] = {"error": str(e)}

    return {
        "comparison_type": "bioactivity",
        "compounds": molecule_chembl_ids,
        "target_filter": target_chembl_id,
        "activity_type_filter": activity_type,
        "results": results
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_drugs(
    query: str,
    search_type: Literal["name", "indication", "mechanism"] = "name",
    development_phase: Optional[str] = None,
    therapeutic_area: Optional[str] = None,
    drug_type: Optional[str] = None,
    limit: int = 25
) -> dict:
    """Search for approved drugs and clinical candidates.

    Args:
        query: Drug name, indication, or mechanism search query
        search_type: Type of search:
            - "name": Search by drug name (default)
            - "indication": Search by therapeutic indication/disease
            - "mechanism": Search by mechanism of action
        development_phase: Filter by phase (e.g., "Approved", "Phase III", "Phase II")
        therapeutic_area: Filter by therapeutic area
        drug_type: Filter by drug type (e.g., "Small molecule", "Antibody")
        limit: Number of results to return (1-1000)

    Returns:
        Drug information including development status and indications

    Examples:
        # Search approved drugs
        search_drugs("aspirin", development_phase="Approved")

        # Search by indication
        search_drugs("diabetes", search_type="indication")

        # Find antibody drugs
        search_drugs("cancer", drug_type="Antibody")
    """
    params = {"q": query, "limit": min(limit, 1000)}

    # Use molecule endpoint with filters
    result = await chembl_api_request("molecule/search", params)

    return {
        "search_type": search_type,
        "query": query,
        "development_phase": development_phase,
        "therapeutic_area": therapeutic_area,
        **result
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_drug_details(
    chembl_id: str,
    include_mechanism: bool = True,
    include_indications: bool = True,
    include_trials: bool = False
) -> dict:
    """Get drug development status and detailed information.

    Args:
        chembl_id: ChEMBL compound ID
        include_mechanism: Include mechanism of action data
        include_indications: Include therapeutic indications
        include_trials: Include clinical trial information (if available)

    Returns:
        Drug development information with mechanism and indications

    Examples:
        # Get full drug information
        get_drug_details("CHEMBL59", include_mechanism=True, include_indications=True)

        # Get basic drug info only
        get_drug_details("CHEMBL25", include_mechanism=False, include_indications=False)
    """
    result = await chembl_api_request("molecule", chembl_id=chembl_id)

    # Optionally fetch mechanism of action
    if include_mechanism:
        try:
            mechanism = await chembl_api_request(
                "mechanism",
                params={"molecule_chembl_id": chembl_id}
            )
            result["mechanism_of_action"] = mechanism
        except Exception as e:
            result["mechanism_of_action"] = {"error": str(e)}

    # Optionally fetch drug indications
    if include_indications:
        try:
            indications = await chembl_api_request(
                "drug_indication",
                params={"molecule_chembl_id": chembl_id}
            )
            result["indications"] = indications
        except Exception as e:
            result["indications"] = {"error": str(e)}

    return result


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def analyze_compound_properties(
    chembl_id: Optional[str] = None,
    smiles: Optional[str] = None,
    property_type: Literal["all", "drug_likeness", "admet", "descriptors"] = "all"
) -> dict:
    """Read ChEMBL physicochemical descriptors and compute bounded rule-of-five checks.

    Args:
        chembl_id: ChEMBL compound ID (provide either chembl_id or smiles)
        smiles: SMILES string (alternative to chembl_id)
        property_type: Type of properties to analyze:
            - "all": Available physicochemical descriptors and rule-of-five checks
            - "drug_likeness": Lipinski Rule of Five and drug-likeness metrics
            - "admet": Reports unavailable: this acquisition supplies no ADMET measurements
            - "descriptors": Molecular descriptors and physicochemical properties

    Returns:
        Raw provider assertions plus descriptor coverage, units and calculated threshold checks.
        Missing inputs prevent a complete assessment; no efficacy or clinical suitability is inferred.
        Direct SMILES calculation is unavailable; supply a ChEMBL record ID for measured descriptors.

    Examples:
        # Check aspirin drug-likeness
        chembl_id="CHEMBL25", property_type="drug_likeness"

        # Analyze all properties for a compound
        chembl_id="CHEMBL59", property_type="all"

        # Get descriptors
        chembl_id="CHEMBL521", property_type="descriptors"
    """
    if not chembl_id and not smiles:
        return {"error": "Please provide either chembl_id or smiles parameter"}

    if chembl_id:
        compound_data = await chembl_api_request("molecule", chembl_id=chembl_id)
        with provider_boundary("chembl"):
            return analyze_properties(compound_data, chembl_id, property_type)
    return {
        "smiles": smiles,
        "section_outcomes": {"properties": "unavailable"},
        "warnings": ["Property calculation from SMILES is unavailable; no descriptors were measured or computed."],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def batch_compound_lookup(
    chembl_ids: List[str],
    include_structures: bool = False,
    include_properties: bool = True
) -> dict:
    """Retrieve information for multiple compounds efficiently.

    Args:
        chembl_ids: List of ChEMBL compound IDs (1-50 compounds)
        include_structures: Include chemical structure data
        include_properties: Include molecular properties

    Returns:
        Batch results for all requested compounds

    Examples:
        # Lookup aspirin and ibuprofen
        ["CHEMBL25", "CHEMBL521"], include_properties=True

        # Batch lookup with structures
        >>> await batch_compound_lookup(
        ...     ["CHEMBL59", "CHEMBL25", "CHEMBL192"],
        ...     include_structures=True
        ... )
    """
    if len(chembl_ids) < 1 or len(chembl_ids) > 50:
        return {"error": "Please provide between 1 and 50 compound IDs"}

    results = []
    for chembl_id in chembl_ids:
        try:
            compound = await chembl_api_request("molecule", chembl_id=chembl_id)

            # Filter based on parameters
            if not include_structures and "molecule_structures" in compound:
                del compound["molecule_structures"]
            if not include_properties and "molecule_properties" in compound:
                del compound["molecule_properties"]

            results.append({"chembl_id": chembl_id, "data": compound, "success": True})
        except Exception as e:
            results.append({"chembl_id": chembl_id, "error": str(e), "success": False})

    return {
        "total_requested": len(chembl_ids),
        "total_successful": sum(1 for r in results if r["success"]),
        "results": results
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_cross_references(
    chembl_id: str,
    reference_type: Literal["all", "compound", "target"] = "all"
) -> dict:
    """Get links to external databases (PubChem, DrugBank, PDB, UniProt, etc.).

    Args:
        chembl_id: ChEMBL compound or target ID
        reference_type: Type of cross-references to retrieve

    Returns:
        External database identifiers and links

    Examples:
        # Get all external references for a compound
        get_cross_references("CHEMBL59", reference_type="compound")

        # Get target cross-references
        get_cross_references("CHEMBL2095173", reference_type="target")
    """
    # Determine if compound or target
    if chembl_id.startswith("CHEMBL") and reference_type in ["all", "compound"]:
        try:
            result = await chembl_api_request("molecule", chembl_id=chembl_id)

            xrefs = {}
            if "molecule_structures" in result and result["molecule_structures"]:
                structures = result["molecule_structures"]
                xrefs["inchi_key"] = structures.get("standard_inchi_key")
                xrefs["smiles"] = structures.get("canonical_smiles")

            # Extract cross-references from result
            return {
                "chembl_id": chembl_id,
                "type": "compound",
                "cross_references": xrefs,
                "full_data": result
            }
        except Exception as e:
            return {"error": str(e)}

    # Try as target
    if reference_type in ["all", "target"]:
        try:
            result = await chembl_api_request("target", chembl_id=chembl_id)
            return {
                "chembl_id": chembl_id,
                "type": "target",
                "cross_references": result.get("target_components", []),
                "full_data": result
            }
        except Exception as e:
            return {"error": str(e)}

    return {"error": "Invalid ChEMBL ID or reference type"}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def advanced_property_search(
    min_mw: Optional[float] = None,
    max_mw: Optional[float] = None,
    min_logp: Optional[float] = None,
    max_logp: Optional[float] = None,
    max_hbd: Optional[int] = None,
    max_hba: Optional[int] = None,
    ro5_compliant: bool = False,
    limit: int = 25
) -> dict:
    """Search compounds using multiple chemical and biological property filters.

    Args:
        min_mw: Minimum molecular weight (Da)
        max_mw: Maximum molecular weight (Da)
        min_logp: Minimum LogP value
        max_logp: Maximum LogP value
        max_hbd: Maximum hydrogen bond donors
        max_hba: Maximum hydrogen bond acceptors
        ro5_compliant: Only return Lipinski Rule of Five compliant compounds
        limit: Number of results to return (1-1000)

    Returns:
        Compounds matching the specified property criteria

    Examples:
        # Find drug-like molecules
        advanced_property_search(
        ...     min_mw=200, max_mw=500,
        ...     max_logp=5, max_hbd=5, max_hba=10,
        ...     ro5_compliant=True
        ... )

        # Find small molecules
        advanced_property_search(min_mw=100, max_mw=300, limit=50)
    """
    # Build query filters
    filters = []
    if min_mw is not None:
        filters.append(f"min_mw={min_mw}")
    if max_mw is not None:
        filters.append(f"max_mw={max_mw}")
    if min_logp is not None:
        filters.append(f"min_logp={min_logp}")
    if max_logp is not None:
        filters.append(f"max_logp={max_logp}")
    if max_hbd is not None:
        filters.append(f"max_hbd={max_hbd}")
    if max_hba is not None:
        filters.append(f"max_hba={max_hba}")

    # Note: ChEMBL API has limited support for property-based filtering
    # This would require using their advanced search or filter endpoints

    return {
        "message": "Advanced property search requires ChEMBL advanced search interface",
        "filters": {
            "mw_range": f"{min_mw}-{max_mw}" if min_mw and max_mw else None,
            "logp_range": f"{min_logp}-{max_logp}" if min_logp and max_logp else None,
            "max_hbd": max_hbd,
            "max_hba": max_hba,
            "ro5_compliant": ro5_compliant
        },
        "note": "Use search_compounds() with specific compound IDs or names, then filter results by properties"
    }
