"""Public API surfaces for MyChem MCP tool classes.

`ALL_TOOLS` and `API_CLASS_MAP` were removed in v0.3.0. FastMCP now handles tool
registration and dispatching directly in `mychem_mcp.server`.
"""

from .admet import ADMETApi
from .annotation import AnnotationApi
from .batch import BatchApi
from .bioactivity import BioactivityApi
from .biological_context import BiologicalContextApi
from .clinical import ClinicalApi
from .drug import DrugApi
from .export import ExportApi
from .mapping import MappingApi
from .metadata import MetadataApi
from .patent import PatentApi
from .query import QueryApi
from .structure import StructureApi

__all__ = [
    "ADMETApi",
    "AnnotationApi",
    "BatchApi",
    "BioactivityApi",
    "BiologicalContextApi",
    "ClinicalApi",
    "DrugApi",
    "ExportApi",
    "MappingApi",
    "MetadataApi",
    "PatentApi",
    "QueryApi",
    "StructureApi",
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
