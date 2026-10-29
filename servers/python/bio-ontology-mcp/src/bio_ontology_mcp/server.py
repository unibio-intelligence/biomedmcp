#!/usr/bin/env python3
"""BioOntology MCP Server - Search and explore biological ontologies"""

import os
import re
from typing import Annotated, Optional
from urllib.parse import quote

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, provider_boundary

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query BioPortal Ontologies",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Initialize FastMCP server
mcp = FastMCP("bio-ontology-mcp")

# Get API key from environment
BIOONTOLOGY_API_KEY = os.getenv("BIOONTOLOGY_API_KEY", "")
BASE_URL = "https://data.bioontology.org"


async def make_request(endpoint: str, params: dict | None = None):
    """Make an authenticated request to the BioOntology API"""
    with provider_boundary("bio-ontology"):
        key = os.getenv("BIOONTOLOGY_API_KEY", "")
        if not key:
            raise ResearchError("source_unavailable", "BioOntology credentials are not configured.")
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{BASE_URL}{endpoint}", params=params or {},
                headers={"Authorization": f"apikey token={key}"},
            )
            response.raise_for_status()
            return response.json()


# Search & Discovery Tools

@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_terms(
    query: str,
    ontologies: Optional[str] = None,
    require_exact_match: Optional[bool] = None,
    suggest: Optional[bool] = None,
    also_search_views: Optional[bool] = None,
    require_definitions: Optional[bool] = None,
    also_search_properties: Optional[bool] = None,
    also_search_obsolete: Optional[bool] = None,
    cui: Optional[str] = None,
    semantic_types: Optional[str] = None,
    include: Optional[str] = None,
    page: Optional[int] = None,
    pagesize: Optional[int] = None,
    language: Optional[str] = None
) -> str:
    """Search across ontology terms with advanced filtering options

    Args:
        query: Search query for ontology terms
        ontologies: Comma-separated list of ontology acronyms to search in
        require_exact_match: Require exact match (default: false)
        suggest: Enable suggestion mode for type-ahead (default: false)
        also_search_views: Include ontology views in search (default: false)
        require_definitions: Only return terms with definitions (default: false)
        also_search_properties: Search in properties as well (default: false)
        also_search_obsolete: Include obsolete terms (default: false)
        cui: Comma-separated CUIs to filter by
        semantic_types: Comma-separated semantic types to filter by
        include: Comma-separated attributes to include (e.g., prefLabel,synonym,definition)
        page: Page number (default: 1)
        pagesize: Results per page (default: 50, max: 500)
        language: Language code (e.g., en, fr)
    """
    params = {"q": query}

    if ontologies: params["ontologies"] = ontologies
    if require_exact_match is not None: params["require_exact_match"] = require_exact_match
    if suggest is not None: params["suggest"] = suggest
    if also_search_views is not None: params["also_search_views"] = also_search_views
    if require_definitions is not None: params["require_definitions"] = require_definitions
    if also_search_properties is not None: params["also_search_properties"] = also_search_properties
    if also_search_obsolete is not None: params["also_search_obsolete"] = also_search_obsolete
    if cui: params["cui"] = cui
    if semantic_types: params["semantic_types"] = semantic_types
    if include: params["include"] = include
    if page: params["page"] = page
    if pagesize: params["pagesize"] = pagesize
    if language: params["language"] = language

    try:
        data = await make_request("/search", params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error searching terms: {str(e)}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_properties(
    query: str,
    ontologies: Optional[str] = None,
    require_exact_match: Optional[bool] = None,
    also_search_views: Optional[bool] = None,
    require_definitions: Optional[bool] = None,
    include: Optional[str] = None,
    ontology_types: Optional[str] = None,
    property_types: Optional[str] = None,
    page: Optional[int] = None,
    pagesize: Optional[int] = None
) -> str:
    """Search ontology properties by their labels and IDs

    Args:
        query: Search query for properties
        ontologies: Comma-separated list of ontology acronyms
        require_exact_match: Require exact match (default: false)
        also_search_views: Include ontology views (default: false)
        require_definitions: Only return properties with definitions (default: false)
        include: Attributes to include (default: label,labelGenerated,definition,parents)
        ontology_types: Ontology types to include (e.g., ONTOLOGY,VALUE_SET_COLLECTION)
        property_types: Property types (object,annotation,datatype)
        page: Page number (default: 1)
        pagesize: Results per page (default: 50, max: 500)
    """
    params = {"q": query}

    if ontologies: params["ontologies"] = ontologies
    if require_exact_match is not None: params["require_exact_match"] = require_exact_match
    if also_search_views is not None: params["also_search_views"] = also_search_views
    if require_definitions is not None: params["require_definitions"] = require_definitions
    if include: params["include"] = include
    if ontology_types: params["ontology_types"] = ontology_types
    if property_types: params["property_types"] = property_types
    if page: params["page"] = page
    if pagesize: params["pagesize"] = pagesize

    try:
        data = await make_request("/property_search", params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error searching properties: {str(e)}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def search_ontologies(
    query: Optional[Annotated[str, Field(min_length=1, max_length=200)]] = None,
    include_views: Optional[bool] = None,
    limit: Annotated[int, Field(ge=1, le=25)] = 25,
    offset: Annotated[int, Field(ge=0, le=10000)] = 0,
) -> dict:
    """List ontologies, optionally filtering acronym/name locally.

    The provider's ontology collection is not a term search. Offset/limit
    continue the filtered collection, whose contents may change over time.
    """
    with provider_boundary("bio-ontology"):
        params = {"include": "acronym,name", "display_links": False, "display_context": False}
        if include_views is not None:
            params["include_views"] = include_views
        data = await make_request("/ontologies", params)
        if not isinstance(data, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("acronym"), str)
            or not isinstance(row.get("name"), str) for row in data
        ):
            raise ResearchError("invalid_source_response", "Invalid ontology collection.")
        rows = [row for row in data if query is None or query.casefold() in
                (row["acronym"] + " " + row["name"]).casefold()]
        return {"collection": rows[offset:offset + limit], "total": len(rows),
                "next_offset": offset + limit if offset + limit < len(rows) else None,
                "filter_scope": "ontology acronym and name; not class terms", "source": "bio-ontology"}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_ontology_info(
    acronym: str,
    include_views: Optional[bool] = None
) -> str:
    """Get detailed information about a specific ontology

    Args:
        acronym: Ontology acronym (e.g., NCIT, GO, MESH)
        include_views: Include ontology views (default: false)
    """
    params = {}
    if include_views is not None:
        params["include_views"] = include_views

    try:
        data = await make_request(f"/ontologies/{acronym}", params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error fetching ontology info: {str(e)}"


# Text Analysis Tools

@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def annotate_text(
    text: str,
    ontologies: Optional[str] = None,
    semantic_types: Optional[str] = None,
    expand_semantic_types_hierarchy: Optional[bool] = None,
    expand_class_hierarchy: Optional[bool] = None,
    class_hierarchy_max_level: Optional[int] = None,
    expand_mappings: Optional[bool] = None,
    stop_words: Optional[str] = None,
    minimum_match_length: Optional[int] = None,
    exclude_numbers: Optional[bool] = None,
    whole_word_only: Optional[bool] = None,
    exclude_synonyms: Optional[bool] = None,
    longest_only: Optional[bool] = None
) -> str:
    """Analyze text and identify relevant ontology terms with configurable parameters

    Args:
        text: Text to annotate with ontology terms
        ontologies: Comma-separated ontology acronyms to use for annotation
        semantic_types: Comma-separated semantic types to filter by
        expand_semantic_types_hierarchy: Include children of semantic types (default: false)
        expand_class_hierarchy: Include class ancestors in annotation (default: false)
        class_hierarchy_max_level: Maximum hierarchy depth (default: 0)
        expand_mappings: Use manual mappings (UMLS, REST, CUI, OBOXREF) (default: false)
        stop_words: Comma-separated custom stop words
        minimum_match_length: Minimum character length for matches
        exclude_numbers: Exclude numeric matches (default: false)
        whole_word_only: Match whole words only (default: true)
        exclude_synonyms: Exclude synonym matches (default: false)
        longest_only: Return only longest matches (default: false)
    """
    params = {"text": text}

    if ontologies: params["ontologies"] = ontologies
    if semantic_types: params["semantic_types"] = semantic_types
    if expand_semantic_types_hierarchy is not None: params["expand_semantic_types_hierarchy"] = expand_semantic_types_hierarchy
    if expand_class_hierarchy is not None: params["expand_class_hierarchy"] = expand_class_hierarchy
    if class_hierarchy_max_level is not None: params["class_hierarchy_max_level"] = class_hierarchy_max_level
    if expand_mappings is not None: params["expand_mappings"] = expand_mappings
    if stop_words: params["stop_words"] = stop_words
    if minimum_match_length is not None: params["minimum_match_length"] = minimum_match_length
    if exclude_numbers is not None: params["exclude_numbers"] = exclude_numbers
    if whole_word_only is not None: params["whole_word_only"] = whole_word_only
    if exclude_synonyms is not None: params["exclude_synonyms"] = exclude_synonyms
    if longest_only is not None: params["longest_only"] = longest_only

    try:
        data = await make_request("/annotator", params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error annotating text: {str(e)}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def recommend_ontologies(
    input: str,
    input_type: Optional[int] = None,
    output_type: Optional[int] = None,
    max_elements_set: Optional[int] = None,
    wc: Optional[float] = None,
    wa: Optional[float] = None,
    wd: Optional[float] = None,
    ws: Optional[float] = None,
    ontologies: Optional[str] = None
) -> str:
    """Get ontology recommendations for text or keywords with customizable weights

    Args:
        input: Input text or comma-separated keywords
        input_type: Input type: 1=text, 2=keywords (default: 1)
        output_type: Output type: 1=individual ontologies, 2=ontology sets (default: 1)
        max_elements_set: Max ontologies per set (2-4, default: 3)
        wc: Weight for coverage criterion (0-1, default: 0.55)
        wa: Weight for acceptance criterion (0-1, default: 0.15)
        wd: Weight for detail criterion (0-1, default: 0.15)
        ws: Weight for specialization criterion (0-1, default: 0.15)
        ontologies: Comma-separated ontology acronyms to limit evaluation to
    """
    params = {"input": input}

    if input_type is not None: params["input_type"] = input_type
    if output_type is not None: params["output_type"] = output_type
    if max_elements_set is not None: params["max_elements_set"] = max_elements_set
    if wc is not None: params["wc"] = wc
    if wa is not None: params["wa"] = wa
    if wd is not None: params["wd"] = wd
    if ws is not None: params["ws"] = ws
    if ontologies: params["ontologies"] = ontologies

    try:
        data = await make_request("/recommender", params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error recommending ontologies: {str(e)}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def batch_annotate(
    texts: list[str],
    ontologies: Optional[str] = None,
    longest_only: Optional[bool] = None,
    whole_word_only: Optional[bool] = None
) -> str:
    """Process multiple texts for annotation efficiently

    Args:
        texts: Array of texts to annotate (max 10)
        ontologies: Comma-separated ontology acronyms
        longest_only: Return only longest matches (default: true)
        whole_word_only: Match whole words only (default: true)
    """
    if not texts or len(texts) > 10:
        return "Error: texts must be a list of 1-10 items"

    results = []

    for text in texts:
        params = {"text": text}
        if ontologies: params["ontologies"] = ontologies
        if longest_only is not None: params["longest_only"] = longest_only
        if whole_word_only is not None: params["whole_word_only"] = whole_word_only

        try:
            data = await make_request("/annotator", params)
            results.append({"text": text, "annotations": data, "success": True})
        except Exception as e:
            results.append({"text": text, "error": str(e), "success": False})

    import json
    return json.dumps({"batch_results": results}, indent=2)


# Ontology Navigation Tools

@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_class_info(
    ontology: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")],
    class_id: Annotated[str, Field(min_length=1, max_length=2048)],
    include: Optional[str] = None
) -> dict:
    """Get detailed information about a specific ontology class

    Args:
        ontology: Ontology acronym
        class_id: Class ID/URI (URL-encoded if necessary)
        include: Comma-separated attributes to include (e.g., prefLabel,definition,parents,children)
    """
    params = {}
    if include:
        params["include"] = include + ",prefLabel"

    with provider_boundary("bio-ontology"):
        _ontology_path(ontology)
        encoded_class_id = quote(class_id, safe='')
        data = await make_request(f"/ontologies/{ontology}/classes/{encoded_class_id}", params)
        _class_record(data)
        if data["@id"] != class_id:
            raise ResearchError("invalid_source_response", "Ontology class identity changed.")
        return data


def _ontology_path(ontology):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", ontology):
        raise ResearchError("invalid_parameters", "Invalid ontology acronym.")
    return f"/ontologies/{ontology}"


def _class_record(row):
    if not isinstance(row, dict) or not isinstance(row.get("@id"), str) or not row["@id"]:
        raise ResearchError("invalid_source_response", "Invalid ontology class identity.")
    if not isinstance(row.get("prefLabel"), str) or not row["prefLabel"]:
        raise ResearchError("invalid_source_response", "Invalid ontology class label.")


def _page(data, page, pagesize, record_validator):
    if (
        not isinstance(data, dict) or not isinstance(data.get("collection"), list)
        or len(data["collection"]) > pagesize or type(data.get("page")) is not int
        or data["page"] != page or type(data.get("pageCount")) is not int
        or data["pageCount"] < 0
    ):
        raise ResearchError("invalid_source_response", "Invalid ontology page response.")
    for row in data["collection"]:
        record_validator(row)
    return {**data, "next_page": page + 1 if page < data["pageCount"] else None,
            "source": "bio-ontology"}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_ontology_classes(
    ontology: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")],
    page: Annotated[int, Field(ge=1, le=10000)] = 1,
    pagesize: Annotated[int, Field(ge=1, le=25)] = 25,
) -> dict:
    """Retrieve a provider page of classes with labels and original class URIs."""
    with provider_boundary("bio-ontology"):
        data = await make_request(_ontology_path(ontology) + "/classes", {"page": page, "pagesize": pagesize})
        return _page(data, page, pagesize, _class_record)


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_mappings(
    ontology: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")],
    class_id: Optional[Annotated[str, Field(min_length=1, max_length=2048)]] = None,
    page: Annotated[int, Field(ge=1, le=10000)] = 1,
    pagesize: Annotated[int, Field(ge=1, le=25)] = 25,
) -> dict:
    """Retrieve mapping assertions for an ontology or class.

    Preserve classes, source and process. A mapping is not automatically
    biological equivalence; its generating process determines its meaning.
    """
    with provider_boundary("bio-ontology"):
        path = _ontology_path(ontology)
        if class_id is not None:
            path += "/classes/" + quote(class_id, safe="")
        data = await make_request(
            path + "/mappings", {} if class_id is not None else {"page": page, "pagesize": pagesize}
        )

        def validate(row):
            if not isinstance(row, dict) or not isinstance(row.get("classes"), list) or len(row["classes"]) != 2:
                raise ResearchError("invalid_source_response", "Invalid mapping class pair.")
            if any(not isinstance(item, dict) or not isinstance(item.get("@id"), str) for item in row["classes"]):
                raise ResearchError("invalid_source_response", "Invalid mapping class identity.")
            if not isinstance(row.get("source"), str) or not row["source"]:
                raise ResearchError("invalid_source_response", "Missing mapping source.")
            if row.get("process") is not None and not isinstance(row["process"], (dict, str)):
                raise ResearchError("invalid_source_response", "Invalid mapping process attribution.")

        if class_id is not None:
            if not isinstance(data, list) or len(data) > 10000:
                raise ResearchError("invalid_source_response", "Invalid class mapping collection.")
            for row in data:
                validate(row)
            offset = (page - 1) * pagesize
            result = {"collection": data[offset:offset + pagesize], "total": len(data), "page": page,
                      "next_page": page + 1 if offset + pagesize < len(data) else None,
                      "pagination_mode": "local window of provider class collection", "source": "bio-ontology"}
        else:
            result = _page(data, page, pagesize, validate)
        result["interpretation"] = "Mapping assertions retain provider source/process; equivalence is not assumed."
        result["missing_process_count"] = sum(row.get("process") is None for row in result["collection"])
        return result


# Analytics & Metadata Tools

@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_ontology_metrics(ontology: str) -> str:
    """Get usage statistics and quality metrics for an ontology

    Args:
        ontology: Ontology acronym
    """
    try:
        data = await make_request(f"/ontologies/{ontology}/metrics")
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error fetching ontology metrics: {str(e)}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
async def get_analytics_data(
    month: Optional[int] = None,
    year: Optional[int] = None,
    ontology: Optional[str] = None
) -> str:
    """Get visitor statistics and popularity trends with optional date filtering

    Args:
        month: Month (1-12) for specific data
        year: Year for specific data (2013+)
        ontology: Specific ontology acronym (optional)
    """
    params = {}
    if month is not None: params["month"] = month
    if year is not None: params["year"] = year

    endpoint = "/analytics"
    if ontology:
        endpoint = f"/ontologies/{ontology}/analytics"

    try:
        data = await make_request(endpoint, params)
        import json
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Error fetching analytics data: {str(e)}"


def main():
    """Run the BioOntology MCP server"""
    mcp.run()


if __name__ == "__main__":
    main()
