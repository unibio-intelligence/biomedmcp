"""Public API surfaces for MyGene MCP tool classes.

`ALL_TOOLS` and `API_CLASS_MAP` were removed in v0.3.0. FastMCP now handles tool
registration and dispatching directly in `mygene_mcp.server`.
"""

from .advanced import AdvancedQueryApi
from .annotation import AnnotationApi
from .batch import BatchApi
from .chemical import ChemicalApi
from .disease import DiseaseApi
from .expression import ExpressionApi
from .go import GOApi
from .homology import HomologyApi
from .interval import IntervalApi
from .metadata import MetadataApi
from .pathway import PathwayApi
from .query import QueryApi
from .variant import VariantApi
from .export import ExportApi
from .unified import UnifiedTools

__all__ = [
    "AdvancedQueryApi",
    "AnnotationApi",
    "BatchApi",
    "ChemicalApi",
    "DiseaseApi",
    "ExpressionApi",
    "GOApi",
    "HomologyApi",
    "IntervalApi",
    "MetadataApi",
    "PathwayApi",
    "QueryApi",
    "VariantApi",
    "ExportApi",
    "UnifiedTools",
]


def __getattr__(name: str):
    if name == "ALL_TOOLS":
        import warnings

        warnings.warn(
            "ALL_TOOLS is deprecated in v0.3.0. Tools are now managed by FastMCP.",
            DeprecationWarning,
            stacklevel=2,
        )
        return []
    if name == "API_CLASS_MAP":
        import warnings

        warnings.warn(
            "API_CLASS_MAP is deprecated in v0.3.0. FastMCP handles tool dispatch.",
            DeprecationWarning,
            stacklevel=2,
        )
        return {}
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
