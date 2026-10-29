"""Public API surfaces for MyDisease MCP tool classes.

`ALL_TOOLS` and `API_CLASS_MAP` were removed in v0.3.0. FastMCP now handles tool
registration and dispatching directly in `mydisease_mcp.server`.
"""

from .annotation import AnnotationApi
from .batch import BatchApi
from .clinical import ClinicalApi
from .drug import DrugApi
from .epidemiology import EpidemiologyApi
from .export import ExportApi
from .gene_association import GeneAssociationApi
from .gwas import GWASApi
from .mapping import MappingApi
from .metadata import MetadataApi
from .ontology import OntologyApi
from .pathway import PathwayApi
from .phenotype import PhenotypeApi
from .query import QueryApi
from .variant import VariantApi

__all__ = [
    "AnnotationApi",
    "BatchApi",
    "ClinicalApi",
    "DrugApi",
    "EpidemiologyApi",
    "ExportApi",
    "GeneAssociationApi",
    "GWASApi",
    "MappingApi",
    "MetadataApi",
    "OntologyApi",
    "PathwayApi",
    "PhenotypeApi",
    "QueryApi",
    "VariantApi",
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
