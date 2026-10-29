"""Retained Ubi source depth behind a single operation registry."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Any

import jsonschema
from fastmcp import Client, FastMCP
from jsonschema.protocols import Validator

from .decoding import decode_tool_result
from .errors import ResearchError, invalid_parameters
from .runtime import digest

PROVIDERS = json.loads(files("biomedmcp").joinpath("provider_registry.json").read_text())


@dataclass(frozen=True)
class _CatalogSnapshot:
    server: FastMCP
    revision: str
    serialized: str
    validators: Mapping[str, Validator]


class SourceAdapters:
    def __init__(self, extensions=None):
        self.extensions = extensions
        self._servers = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._catalog_locks: dict[str, asyncio.Lock] = {}
        self._catalogs: dict[str, _CatalogSnapshot] = {}

    def availability(self, source: str) -> tuple[bool, str | None]:
        from .source_licensing import availability

        released, reason = availability(source)
        if not released:
            return False, reason
        if self.extensions and source in self.extensions.sources:
            return self.extensions.availability(source)
        if source not in PROVIDERS:
            return False, "Unknown source"
        info = PROVIDERS[source]
        if info.get("available") is False or source == "depmap":
            return (
                False,
                "The former public API is unavailable; curated platform data is a separate capability.",
            )
        required = info.get("required_env", [])
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            return False, "Required source credentials are not configured."
        return True, None

    async def _server(self, source: str):
        ready, reason = self.availability(source)
        if not ready:
            raise ResearchError("source_unavailable", reason or "Source unavailable")
        async with self._locks.setdefault(source, asyncio.Lock()):
            if source not in self._servers:
                try:
                    module = importlib.import_module(PROVIDERS[source]["module"])
                except ImportError as exc:
                    raise ResearchError(
                        "adapter_not_installed", f"The {source} adapter is not installed."
                    ) from exc
                self._servers[source] = module.mcp
        return self._servers[source]

    @staticmethod
    async def _catalog_revision(server):
        # Inspect live SDK metadata without opening a client/session. Hashing
        # schemas detects in-place edits as well as add/remove/version changes.
        tools = await server.list_tools()
        return digest(
            {
                "server_version": server.version,
                "tools": [
                    tool.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)
                    for tool in tools
                ],
            }
        )

    async def _catalog_snapshot(self, source):
        # Availability remains a per-request check even after the schema warms.
        await self._server(source)
        async with self._catalog_locks.setdefault(source, asyncio.Lock()):
            for _ in range(3):
                server = await self._server(source)
                revision = await self._catalog_revision(server)
                if server is not await self._server(source):
                    continue
                cached = self._catalogs.get(source)
                if cached and cached.server is server and cached.revision == revision:
                    return cached
                async with Client(server) as client:
                    tools = await client.list_tools()
                catalog = [
                    {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
                    for tool in tools
                ]
                validators = {}
                try:
                    for tool in catalog:
                        schema = deepcopy(tool["input_schema"])
                        schema.setdefault("additionalProperties", False)
                        validator = jsonschema.validators.validator_for(schema)
                        validator.check_schema(schema)
                        validators[tool["name"]] = validator(schema)
                    serialized = json.dumps(catalog, sort_keys=True, allow_nan=False)
                except (jsonschema.SchemaError, TypeError, ValueError):
                    raise ResearchError(
                        "invalid_adapter_schema", "The retained adapter schema is invalid."
                    ) from None
                # A schema changed during discovery: never publish a torn
                # catalog. Failed/cancelled discovery also leaves no cache entry.
                if server is not await self._server(source):
                    continue
                if revision != await self._catalog_revision(server):
                    continue
                snapshot = _CatalogSnapshot(server, revision, serialized, MappingProxyType(validators))
                self._catalogs[source] = snapshot
                return snapshot
        raise ResearchError(
            "adapter_schema_changed", "The adapter schema changed repeatedly; retry later.", retryable=True
        )

    async def catalog(self, source: str) -> list[dict[str, Any]]:
        if self.extensions and source in self.extensions.sources:
            # Extension catalogs and typed validators are already local. Study
            # acquisition/verification remains owned by the extension boundary.
            return deepcopy(self.extensions.catalog(source))
        return json.loads((await self._catalog_snapshot(source)).serialized)

    async def validate(self, source: str, operation: str, params: dict[str, Any]) -> None:
        from .source_licensing import require_operation

        require_operation(source, operation)
        if (source == "orange-book" and operation == "search_generic_equivalents"
            and not any(
                isinstance(params.get(key), str) and params[key].strip()
                for key in ("brand_name", "ingredient")
            )):
            raise invalid_parameters()
        if source == "mygene" and operation == "query_genes":
            from .native.mygene_permissions import check_fields

            check_fields(params.get("fields", "symbol,name,taxid,entrezgene"))
        if (
            source == "openfda"
            and operation == "search_recalls"
            and params.get("recall_type", "drug") != "drug"
        ):
            raise ResearchError(
                "source_license_unreleased", "Only drug recall enforcement facts are reviewed."
            )
        self._bounds(params)
        if self.extensions and source in self.extensions.sources:
            if source == "study":
                await self.extensions.initialize_studies()
            try:
                self.extensions.validate(source, operation, params)
            except (ValueError, jsonschema.ValidationError):
                raise invalid_parameters() from None
            return
        self._semantics(source, operation, params)
        snapshot = await self._catalog_snapshot(source)
        if operation not in snapshot.validators:
            raise ResearchError(
                "unknown_operation", f"Unknown operation for {source}; inspect capabilities first."
            )
        try:
            snapshot.validators[operation].validate(params)
        except jsonschema.ValidationError:
            raise invalid_parameters() from None
        if source == "ncbi":
            from ncbi_mcp.datasets import validate_operation

            validate_operation(operation, params)

    async def call(self, source: str, operation: str, params: dict[str, Any]) -> Any:
        await self.validate(source, operation, params)
        if self.extensions and source in self.extensions.sources:
            return await self.extensions.call(source, operation, params)
        server = await self._server(source)
        async with asyncio.timeout(40):
            async with Client(server) as client:
                result = await client.call_tool(operation, params, raise_on_error=False)
                data = decode_tool_result(result)
        if isinstance(data, dict) and (data.get("error") or data.get("success") is False):
            raise ResearchError(
                "upstream_error", f"{source} could not complete the operation.", retryable=True
            )
        if source == "mygene" and operation == "query_genes":
            from .native.mygene_permissions import projection

            data = projection(data)
        if source in {"mychem", "mydisease"}:
            from .native.annotation_permissions import projection

            data = projection(source, data)
        return data

    @staticmethod
    def _bounds(value, depth=0, key=""):
        if (
            depth > 8
            or (isinstance(value, (dict, list)) and len(value) > 1000)
            or (isinstance(value, str) and len(value) > 16000)
        ):
            raise ResearchError("invalid_parameters", "Source input exceeds its structural budget.")
        if isinstance(value, dict):
            for name, item in value.items():
                if (
                    name
                    in {
                        "limit",
                        "max_results",
                        "max_hits",
                        "page_size",
                        "pagesize",
                        "size",
                        "association_limit",
                        "compound_limit",
                        "activity_limit",
                        "batch_size",
                    }
                    and isinstance(item, int)
                    and not 1 <= item <= 100
                ):
                    raise ResearchError("invalid_parameters", "Source page limits must be 1–100.")
                SourceAdapters._bounds(item, depth + 1, name)
        elif isinstance(value, list):
            for item in value:
                SourceAdapters._bounds(item, depth + 1, key)
        elif isinstance(value, float):
            import math

            if not math.isfinite(value):
                raise ResearchError("invalid_parameters", "Nonfinite numeric input is not supported.")

    @staticmethod
    def _semantics(source, operation, params):
        if source == "ensembl":
            from ensembl_mcp.contracts import preflight

            preflight(operation, params)
        if source == "surechembl":
            from surechembl_mcp.contracts import preflight

            preflight(operation, params)
        if source == "uniprot":
            from uniprot_mcp.annotations import preflight

            preflight(operation, params)
        if source == "pdb":
            from pdb_mcp.contracts import preflight

            preflight(operation, params)
        if source == "reactome":
            from reactome_mcp.contracts import preflight

            preflight(operation, params)
        if source == "protein-atlas":
            from .hpa_records import ensembl_gene

            if "ensembl_id" in params:
                ensembl_gene(params["ensembl_id"])
            if operation == "compare_expression_profiles":
                ids = params.get("ensembl_ids")
                if (
                    not isinstance(ids, list)
                    or not 1 <= len(ids) <= 10
                    or any(not isinstance(value, str) for value in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise invalid_parameters()
                for value in ids:
                    ensembl_gene(value)
        if source == "clinical-trials":
            from clinical_trials_mcp.contracts import PHASES, STATUSES, nct, validate_query_scope

            if params.get("phase") is not None and (
                not isinstance(params["phase"], str) or params["phase"] not in PHASES
            ):
                raise invalid_parameters()
            if params.get("status") is not None and (
                not isinstance(params["status"], str) or params["status"] not in STATUSES
            ):
                raise invalid_parameters()
            if params.get("page_token") is not None and (
                not isinstance(params["page_token"], str) or not 1 <= len(params["page_token"]) <= 8192
            ):
                raise invalid_parameters()
            if operation in {"search_studies", "get_trial_statistics"}:
                validate_query_scope(
                    [
                        params.get(key)
                        for key in ("query", "condition", "intervention", "location", "sponsor")
                    ],
                    filtered=any(params.get(key) for key in ("phase", "status", "sex", "age_group")),
                )
            if operation == "get_study_details":
                nct(params.get("nct_id"))
            if operation == "compare_trials":
                ids = params.get("nct_ids", [])
                if (
                    not isinstance(ids, list)
                    or not 2 <= len(ids) <= 5
                    or any(not isinstance(value, str) for value in ids)
                    or len(set(ids)) != len(ids)
                ):
                    raise invalid_parameters()
                for value in ids:
                    nct(value)
        if source == "gtex":
            from gtex_mcp.identity import variant_selector
            from gtex_mcp.pagination import page_parameters

            page_parameters(params.get("page", 0), params.get("limit", 25))
            if params.get("dataset_id", "gtex_v10") not in {"gtex_v8", "gtex_v10"}:
                raise ResearchError(
                    "unsupported_release", "Supported GTEx releases are gtex_v8 and gtex_v10."
                )
            if operation == "query_qtl":
                if params.get("variant_id"):
                    variant_selector(params["variant_id"])
                mode = params.get("analysis_mode")
                if mode not in {"genes_list", "gene_associations", "metasoft", "dynamic"}:
                    raise ResearchError("invalid_parameters", "Unknown QTL analysis mode.")
                if params.get("qtl_type") not in {"eqtl", "sqtl"} or not params.get("tissue_id"):
                    raise ResearchError("invalid_parameters", "QTL type and tissue are required.")
                if mode != "genes_list" and not params.get("gene_id"):
                    raise ResearchError("invalid_parameters", "This QTL mode requires a gene.")
                if mode in {"dynamic", "metasoft"} and not params.get("variant_id"):
                    raise ResearchError("invalid_parameters", "This QTL mode requires a variant.")
                if mode == "metasoft" and params["qtl_type"] != "eqtl":
                    raise ResearchError("invalid_parameters", "MetaSoft is an eQTL operation.")
                if mode == "dynamic" and params.get("page", 0):
                    raise ResearchError("invalid_parameters", "Dynamic QTL has no provider pages.")
                threshold = params.get("p_value_threshold")
                if threshold is not None and (type(threshold) not in (int, float) or not 0 < threshold <= 1):
                    raise ResearchError(
                        "invalid_parameters", "Use a finite p-value threshold between zero and one."
                    )
                if mode == "dynamic" and params["qtl_type"] == "sqtl" and not params.get("phenotype_id"):
                    raise ResearchError(
                        "invalid_parameters", "Dynamic sQTL requires a qualified phenotype_id."
                    )
                if params.get("phenotype_id") and (mode != "dynamic" or params["qtl_type"] != "sqtl"):
                    raise ResearchError("invalid_parameters", "phenotype_id applies to dynamic sQTL only.")
            if operation == "get_annotation" and params.get("entity_type") not in {
                "gene",
                "transcript",
                "exon",
                "variant",
            }:
                raise ResearchError("invalid_parameters", "Select a GTEx annotation type.")
            if operation == "get_metadata":
                if params.get("info_type") not in {"service", "dataset", "tissues"}:
                    raise ResearchError("invalid_parameters", "Select a GTEx metadata mode.")
                if params.get("info_type") != "tissues" and params.get("page", 0):
                    raise ResearchError(
                        "invalid_parameters", "Service/dataset metadata have no provider pages."
                    )
