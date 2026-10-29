"""Orange Book MCP Server - FDA therapeutic equivalence data.

Provides access to FDA's Orange Book database containing approved drug products
with therapeutic equivalence evaluations, patents, and exclusivity information.
"""

import io
import re
import zipfile
from io import StringIO

import pandas as pd
from fastmcp import FastMCP

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError, invalid_parameters, provider_tool_boundary

# Import ToolAnnotations for Anthropic compliance
try:
    from mcp.types import ToolAnnotations
    READ_ONLY_ANNOTATIONS = ToolAnnotations(
        title="Query Orange Book",
        read_only_hint=True,
        open_world_hint=True,
    )
except ImportError:
    READ_ONLY_ANNOTATIONS = None

# Create FastMCP server
mcp = FastMCP("orange-book")

# Orange Book data ZIP. The FDA media URL returns one ZIP containing
# products.txt, patent.txt, and exclusivity.txt using "~" delimiters.
ORANGE_BOOK_ZIP_URL = "https://www.fda.gov/media/76860/download?attachment"
PRODUCTS_FILE = "products.txt"
PATENTS_FILE = "patent.txt"
EXCLUSIVITY_FILE = "exclusivity.txt"

# In-memory cache for Orange Book data (refreshed periodically)
_data_cache = {}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize current FDA Orange Book column names used by the tools."""
    df = df.copy()
    if "DF;Route" in df.columns:
        split = df["DF;Route"].astype(str).str.split(";", n=1, expand=True)
        df["Dosage_Form"] = split[0]
        df["Route"] = split[1] if split.shape[1] > 1 else ""
    return df


def _normalize_application_number(application_number: str) -> str:
    """Convert NDA021462 / ANDA076543 / 214787 to Orange Book Appl_No form."""
    value = str(application_number or "").upper().strip()
    value = re.sub(r"^(NDA|ANDA|BLA|N|A|B)\s*", "", value)
    value = re.sub(r"\D", "", value)
    return value.zfill(6) if value else value


async def _fetch_orange_book_file(filename: str) -> pd.DataFrame:
    """Fetch and parse Orange Book data file."""

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(ORANGE_BOOK_ZIP_URL)
        if response.status_code == 404:
            from .openfda import fetch

            return await fetch(filename)
        response.raise_for_status()

        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                infos=archive.infolist()
                if len(infos)>10 or sum(i.file_size for i in infos)>80_000_000:
                    raise ValueError("Orange Book archive exceeds its expansion budget")
                if filename not in {PRODUCTS_FILE,PATENTS_FILE,EXCLUSIVITY_FILE}:
                    raise ValueError("Unknown Orange Book member")
                if archive.getinfo(filename).file_size>40_000_000:
                    raise ValueError("Orange Book file exceeds its size budget")
                with archive.open(filename) as handle:
                    text = handle.read().decode("latin-1")
        except (zipfile.BadZipFile, KeyError):
            raise ResearchError("invalid_source_response", "Orange Book archive is invalid or incomplete.") from None

        df = pd.read_csv(StringIO(text), sep="~", dtype=str, keep_default_na=False)
        required = {
            PRODUCTS_FILE: {"Ingredient", "DF;Route", "Trade_Name", "Applicant", "Strength", "Appl_No", "Product_No", "TE_Code", "Approval_Date", "RLD", "RS"},
            PATENTS_FILE: {"Appl_No", "Product_No", "Patent_No"},
            EXCLUSIVITY_FILE: {"Appl_No", "Product_No", "Exclusivity_Code"},
        }
        if not required[filename] <= set(df.columns):
            raise ResearchError("invalid_source_response", "Orange Book columns are incomplete.")
        df = _normalize_columns(df)
        return df


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("orange-book")
async def search_products(
    ingredient: str | None = None,
    trade_name: str | None = None,
    application_number: str | None = None,
    limit: int = 50
) -> dict:
    """
    Search for approved drug products in Orange Book.

    Args:
        ingredient: Active ingredient name (partial match)
        trade_name: Trade name/brand name (partial match)
        application_number: FDA application number (e.g., "NDA021462")
        limit: Maximum results to return (default: 50)

    Returns:
        List of matching drug products with application info, ingredients, dosage, and TE codes

    Examples:
        search_products(ingredient="ibuprofen")
        search_products(trade_name="Lipitor")
        search_products(application_number="NDA021462")
    """
    df = await _fetch_orange_book_file(PRODUCTS_FILE)

    # Apply filters
    mask = pd.Series([True] * len(df))

    if ingredient:
        mask &= df["Ingredient"].str.contains(ingredient, case=False, na=False, regex=False)

    if trade_name:
        mask &= df["Trade_Name"].str.contains(trade_name, case=False, na=False, regex=False)

    if application_number:
        normalized_application = _normalize_application_number(application_number)
        mask &= df["Appl_No"].astype(str).str.zfill(6) == normalized_application

    results = df[mask].head(limit)

    return {
        "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
        "total_found": int(mask.sum()),
        "results": results.to_dict(orient="records"),
        "filters": {
            "ingredient": ingredient,
            "trade_name": trade_name,
            "application_number": application_number
        }
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("orange-book")
async def get_therapeutic_equivalence(
    application_number: str
) -> dict:
    """
    Get therapeutic equivalence information for a drug application.

    Args:
        application_number: FDA application number (e.g., "NDA021462")

    Returns:
        Therapeutic equivalence code (TE Code) and related products

    TE Code Guide:
        - A: Therapeutically equivalent to other pharmaceutical equivalents
        - AB: Meets bioequivalence requirements
        - B: NOT therapeutically equivalent
        - BC: Extended release dosage forms with documented bioequivalence problems

    Examples:
        get_therapeutic_equivalence(application_number="NDA021462")
    """
    df = await _fetch_orange_book_file(PRODUCTS_FILE)
    normalized_application = _normalize_application_number(application_number)

    # Find products with this application number
    products = df[df["Appl_No"].astype(str).str.zfill(6) == normalized_application]

    if len(products) == 0:
        return {"error": f"No products found for application {application_number}"}

    return {
        "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
        "application_number": application_number,
        "normalized_application_number": normalized_application,
        "products": products[["Trade_Name", "Ingredient", "Dosage_Form", "Route",
                              "Strength", "TE_Code", "RLD", "RS"]].to_dict(orient="records"),
        "te_codes_used": products["TE_Code"].unique().tolist()
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("orange-book")
async def search_generic_equivalents(
    brand_name: str | None = None,
    ingredient: str | None = None,
    limit: int = 50
) -> dict:
    """
    Find generic equivalents for a brand name drug or ingredient.

    Args:
        brand_name: Brand/trade name to find generics for
        ingredient: Active ingredient name
        limit: Maximum results (default: 50)

    Returns:
        Generic products with AB-rated therapeutic equivalence

    Examples:
        search_generic_equivalents(brand_name="Lipitor")
        search_generic_equivalents(ingredient="atorvastatin")
    """
    if not any(value and value.strip() for value in (brand_name, ingredient)):
        raise invalid_parameters()
    df = await _fetch_orange_book_file(PRODUCTS_FILE)

    # Find reference listed drug (RLD) first
    if brand_name:
        rld = df[(df["Trade_Name"].str.contains(brand_name, case=False, na=False, regex=False)) &
                 (df["RLD"] == "Yes")]
        if len(rld) == 0:
            return {"error": f"No reference listed drug found for {brand_name}"}
        ingredient = rld.iloc[0]["Ingredient"]

    # Find AB-rated generics with same ingredient
    generics = df[(df["Ingredient"].str.contains(ingredient, case=False, na=False, regex=False)) &
                  (df["TE_Code"].str.startswith("AB", na=False))]

    results = generics.head(limit)

    return {
        "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
        "ingredient": ingredient,
        "reference_drug": brand_name,
        "generic_count": len(generics),
        "generics": results[["Appl_No", "Trade_Name", "Applicant", "Dosage_Form",
                             "Strength", "TE_Code", "Approval_Date"]].to_dict(orient="records")
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("orange-book")
async def get_patent_info(
    application_number: str
) -> dict:
    """
    Get patent information for a drug application.

    Args:
        application_number: FDA application number

    Returns:
        Patent numbers, expiration dates, and drug product codes

    Examples:
        get_patent_info(application_number="NDA021462")
    """
    df = await _fetch_orange_book_file(PATENTS_FILE)
    normalized_application = _normalize_application_number(application_number)

    patents = df[df["Appl_No"].astype(str).str.zfill(6) == normalized_application]

    if len(patents) == 0:
        return {
            "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
            "application_number": application_number,
            "normalized_application_number": normalized_application,
            "patents": [],
            "patent_count": 0,
            "message": "No patent data found",
        }

    return {
        "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
        "application_number": application_number,
        "normalized_application_number": normalized_application,
        "patents": patents.to_dict(orient="records"),
        "patent_count": len(patents)
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("orange-book")
async def get_exclusivity_info(
    application_number: str
) -> dict:
    """
    Get exclusivity information for a drug application.

    Args:
        application_number: FDA application number

    Returns:
        Exclusivity codes, expiration dates, and descriptions

    Examples:
        get_exclusivity_info(application_number="NDA021462")
    """
    df = await _fetch_orange_book_file(EXCLUSIVITY_FILE)
    normalized_application = _normalize_application_number(application_number)

    exclusivity = df[df["Appl_No"].astype(str).str.zfill(6) == normalized_application]

    if len(exclusivity) == 0:
        return {
            "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
            "application_number": application_number,
            "normalized_application_number": normalized_application,
            "exclusivity": [],
            "exclusivity_count": 0,
            "message": "No exclusivity data found",
        }

    return {
        "source_release": df.attrs.get("source_release", {"url": ORANGE_BOOK_ZIP_URL, "format": "fda-orangebook-text"}),
        "application_number": application_number,
        "normalized_application_number": normalized_application,
        "exclusivity": exclusivity.to_dict(orient="records"),
        "exclusivity_count": len(exclusivity)
    }


def main():
    """Main entry point."""
    mcp.run()


if __name__ == "__main__":
    main()
