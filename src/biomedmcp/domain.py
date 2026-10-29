"""Ubi-owned query planning, source participation and scientific evidence assembly."""

from __future__ import annotations

import asyncio
import re

from pydantic import ValidationError
from redis.exceptions import RedisError

from .adapters import PROVIDERS, SourceAdapters
from .contracts import Entity, GetRequest, Provenance, ResearchResult, SearchRequest, Section
from .errors import ResearchError, invalid_parameters
from .evidence import article_identifiers, compose_evidence, records_from, section_from
from .extensions import ExtendedSources
from .native import REVISION
from .native.catalog import (
    ADVANCED,
    ALIASES,
    RECORD_OWNER,
    RELATIONS,
    SEARCH_SOURCES,
    SECTION_ALTERNATIVES,
    SECTION_DEPENDENCIES,
    SECTIONS,
)
from .native.civic import CivicContinuation
from .native.civic import parameters as civic_parameters
from .native.identity import gene_matches, qualify_gene
from .native.literature import article_id, plan_sources, rank_articles
from .native.providers import NativeProviders
from .pagination import MAX_PROVIDER_PAGE, PAGE_LIMIT_WARNING, page_continuation, page_from
from .runtime import ProviderRuntime, digest
from .trial_records import rank_trials


def bounded_section_page(section, next_page):
    next_page, boundary = page_continuation(next_page)
    if boundary:
        section.outcome = "partial"
        section.warnings.append(PAGE_LIMIT_WARNING)
        if isinstance(section.data, dict):
            section.data.setdefault("coverage", {}).update(boundary)
    return next_page


SEARCH_FILTERS = {
    "gene": {"species", "source"},
    "article": {
        "gene",
        "disease",
        "drug",
        "source",
        "date_from",
        "date_to",
        "open_access",
        "no_preprints",
        "sort",
        "author",
        "journal",
        "article_type",
        "ranking_mode",
    },
    "trial": {"gene", "disease", "drug", "source", "phase", "status"},
    "variant": {
        "gene",
        "hgvsp",
        "significance",
        "consequence",
        "max_frequency",
        "revel_min",
        "review_status",
        "source",
    },
    "protein": {"species", "reviewed", "existence", "disease", "source"},
    "pgx": {"gene", "drug", "cpic_level", "source"},
    "gwas": {"gene", "trait", "p_value", "source"},
    "author": {"source"},
    "diagnostic": {"source", "manufacturer"},
}
SEARCH_FILTERS["drug"] = {"source", "region", "product_type"}
for _entity in SEARCH_SOURCES:
    SEARCH_FILTERS.setdefault(_entity, {"source"})

WORKFLOWS = {
    "target_dossier": ("gene", ["expression", "target_evidence", "diseases", "druggability"]),
    "variant_evidence": ("variant", ["clinvar", "population", "civic"]),
    "drug_review": ("drug", ["label", "regulatory", "safety", "shortage", "approvals"]),
    "disease_landscape": ("disease", ["genes", "phenotypes", "pathways"]),
    "literature_review": ("article", []),
    "pathway_review": ("pathway", ["genes", "events"]),
    "negative_evidence": ("article", []),
    "study_summary": ("study", []),
    "patent_landscape": ("patent", []),
    "model_input_bundle": ("gene", ["expression", "target_evidence"]),
}


class ResearchService:
    def __init__(self, adapters=None, runtime=None, http=None):
        self.extensions = ExtendedSources(http=http)
        self.adapters = adapters or SourceAdapters(self.extensions)
        self.providers = NativeProviders(self.adapters, http=http)
        self.runtime = runtime or ProviderRuntime()
        from .recovery import EvidenceStore
        from .runtime import ResultCache

        self.evidence = EvidenceStore(getattr(self.runtime, "cache", None) or ResultCache(),
                                     signing_key=self.runtime.cursors.key)

    async def read_evidence(self, uri, *, scope):
        from .runtime import remaining_budget

        try:
            async with asyncio.timeout(remaining_budget(10)):
                return await self.evidence.read(uri, scope=scope, availability=self.source_availability)
        except TimeoutError:
            raise ResearchError(
                "evidence_timeout", "Evidence recovery exceeded its deadline; retry later.", retryable=True
            ) from None
        except (OSError, RedisError):
            raise ResearchError(
                "evidence_unavailable",
                "Evidence storage is unavailable; retry or repeat the original request.",
                retryable=True,
            ) from None

    async def _invoke(self, source, operation, params, call, **kwargs):
        from .source_licensing import require, require_operation

        require_operation(source, operation)
        for dependency in kwargs.get("attribution", ()):
            require(dependency)
        if source != "study":
            return await self._acquire(source, operation, params, call, **kwargs)
        registry = await self.extensions.initialize_studies()

        async def verified_call():
            result = await call()
            from .studies import study_registry
            from .study_workers import study_workers

            if await study_workers.run(study_registry) != registry:
                raise ResearchError("study_version_changed", "Study release changed during acquisition.")
            return result

        with self.extensions.study_snapshot(registry):
            return await self._acquire(source, operation, params, verified_call, **kwargs)

    async def _acquire(
        self,
        source,
        operation,
        params,
        call,
        *,
        scope,
        freshness="cached_if_fresh",
        record_id=None,
        version=None,
        identity=None,
        capture=None,
        attribution=(),
    ):
        request_key = {
            "operation": operation,
            "params": params,
            "version": version,
            "implementation": REVISION,
        }
        if source == "monarch":
            from .native.monarch import CACHE_PROJECTION

            request_key["projection"] = CACHE_PROJECTION
        if source == "orange-book":
            request_key["projection"] = "orange-book-official-json-v2"
        if source == "reactome":
            request_key["projection"] = "reactome-ebi-search-v1"
        if source == "cpic":
            request_key["projection"] = "cpic-gene-drug-discovery-v1"
        if source == "openfda" and operation == "get:label":
            request_key["projection"] = "spl-label-text-v2"
        if source in {"pmc", "europepmc"} and operation == "get:fulltext":
            request_key["projection"] = "jats-floating-table-rows-v1"
        if source == "alphamissense":
            request_key["projection"] = "exact-region-allele-v2"
        if source == "eve":
            request_key["projection"] = "canonical-protein-asm-v1"
        if source == "study":
            # Shared parsed inputs are checksummed by native analysis. A cached
            # final result must not bypass those checks when filesystem metadata
            # cannot distinguish a content edit. Coalescing/index reuse remain.
            freshness = "fresh"
            request_key["study_registry"] = digest(self.extensions.studies())
        if identity:
            request_key["qualified_identity"] = (await identity())["qualified_identity"]
        record, cached = await self.runtime.invoke(
            source,
            request_key,
            call,
            scope=scope,
            freshness=freshness,
        )
        if capture is not None:
            capture(record["payload"])
        section, proof = section_from(
            source,
            record,
            cached,
            record_id=record_id,
            version=version,
            row_limit=100 if source in {"europepmc", "pmc"} and operation == "get:fulltext" else 25,
        )
        if attribution:
            proof.sources = sorted({source, *attribution})
        from .source_licensing import notice

        for participant in sorted({source, *attribution}):
            permission_notice = notice(
                participant,
                version=proof.source_version if participant == source else None,
                retrieved_at=proof.retrieved_at,
            )
            if permission_notice:
                section.warnings.append(permission_notice)
        from .evidence import visible_payload

        section.recovery = await self.evidence.publish(
            visible_payload(record["payload"]), proof, section.recovery, scope=scope
        )
        return section, proof

    async def _safe(self, source, operation, params, call, **kwargs):
        try:
            return await self._invoke(source, operation, params, call, **kwargs)
        except ResearchError as exc:
            return Section(
                outcome="ambiguous"
                if exc.code == "ambiguous_identifier"
                else "unavailable"
                if exc.code
                in {
                    "source_unavailable",
                    "source_response_budget",
                    "source_rate_limited",
                    "source_authentication_failed",
                    "source_access_denied",
                    "source_license_unreleased",
                    "source_license_unavailable",
                    "study_data_unavailable",
                    "study_assay_unavailable",
                    "study_gene_unavailable",
                    "study_measurements_unavailable",
                    "operation_timeout",
                    "provider_busy",
                    "cache_unavailable",
                    "provider_budget_unavailable",
                }
                else "error",
                error=exc.as_dict(),
            ), None
        except (TimeoutError, OSError):
            return Section(
                outcome="unavailable",
                error=ResearchError(
                    "source_timeout",
                    "Provider deadline or transport failed; no absence can be inferred.",
                    retryable=True,
                ).as_dict(),
            ), None
        except Exception as exc:
            # Adapter HTTP errors are sanitized here; keys/queries never leak.
            import httpx

            if isinstance(exc, (httpx.HTTPError, KeyError, ValueError, TypeError)):
                return Section(
                    outcome="error",
                    error=ResearchError(
                        "invalid_source_response",
                        "Provider returned an unavailable or invalid response.",
                        retryable=True,
                    ).as_dict(),
                ), None
            raise

    @staticmethod
    def _outcome(sections):
        values = [s.outcome for s in sections]
        good = any(x in {"data", "empty", "partial"} for x in values)
        failed = any(x in {"error", "unavailable", "partial", "ambiguous"} for x in values)
        if good and failed:
            return "partial"
        if "ambiguous" in values:
            return "ambiguous"
        if failed:
            return "error"
        return "data" if "data" in values else "empty"

    def _source_route(self, source, operation, params):
        if source == "opentargets" and operation == "query_genetics" and params.get("gene_id"):
            raise ResearchError(
                "canonical_route_required",
                'Gene genetics uses get(entity="gene",sections=["genetics"]). Advanced genetics selects a variant, study or credible-set identity.',
            )
        if operation not in ADVANCED.get(source, set()):
            routes = []
            for kind, owner in RECORD_OWNER.items():
                if owner == source:
                    routes.append(f'get(entity="{kind}",id=...,sections=["record"])')
            for kind, sources in SEARCH_SOURCES.items():
                if source in sources:
                    tool = (
                        "literature_search"
                        if kind == "article"
                        else "trial_search"
                        if kind == "trial"
                        else "search"
                    )
                    selector = "" if kind in {"article", "trial"} else f'entity="{kind}",'
                    routes.append(f"{tool}({selector}query=...)")
            guidance = "; ".join(routes) or "Inspect the section routes in capabilities."
            raise ResearchError(
                "canonical_route_required",
                f'{source}/{operation} is not a public advanced operation. Canonical routes: {guidance}. capabilities(source="{source}") lists section routes and distinct advanced operations.',
            )
        # NCBI common sequence aliases are deliberately absent. All three
        # sequence/repository databases use this single parameterized route.
        if (
            source == "chembl"
            and operation == "search_compounds"
            and params.get("search_type", "name") == "name"
        ):
            pass  # ChEMBL compound structures/bioactivity catalog is source-specific, not drug identity.

    async def source(
        self, source, operation, params, *, scope, freshness="cached_if_fresh", _plan_only=False
    ):
        self._source_route(source, operation, params)
        if len(str(params)) > 32000:
            raise ResearchError("invalid_parameters", "Source parameters exceed their budget.")
        await self.adapters.validate(source, operation, params)
        source_cursor = None
        pair_cursor = False
        if source == "surechembl" and operation == "search_similar_structures":
            from .native.surechembl_search import SearchContinuation

            source_cursor = SearchContinuation(self.runtime)
        if source == "opentargets":
            if operation == "query_genetics":
                from .native.opentargets_variant_evidence import VariantContinuation

                source_cursor = VariantContinuation(self.runtime)
            elif operation == "analyze_association" or (
                operation == "analyze_advanced" and params.get("analysis_type") == "validate"
            ):
                from .native.opentargets_pair_evidence import PairContinuation

                source_cursor = PairContinuation(self.runtime)
                pair_cursor = True
        if source_cursor is not None:
            cursor_position = source_cursor.preflight(params, scope)
        if _plan_only:
            return None
        source_params = params
        if source_cursor is not None:
            source_params, cursor_state = await source_cursor.resume(params, scope, cursor_position)

        async def acquire_source():
            value = await self.adapters.call(source, operation, source_params)
            if source_cursor is not None and isinstance(value, dict):
                reason = source_cursor.boundary(value, cursor_state)
                if reason is not None:
                    if source == "surechembl":
                        source_cursor.partial(value, reason)
                    elif pair_cursor:
                        from .native.opentargets_pair_evidence import partial

                        partial(value, reason)
                    else:
                        value["section_outcomes"]["evidences"] = {"outcome": "partial"}
                        value["evidences"]["coverage"]["continuation_status"] = reason
            return value

        captured = {}
        section, evidence = await self._safe(
            source,
            operation,
            params,
            acquire_source,
            scope=scope,
            freshness=freshness,
            capture=lambda payload: captured.setdefault("payload", payload),
            version=params.get("dataset_id", "gtex_v10")
            if source == "gtex"
            and (operation == "get_sample" or params.get("info_type") in {"dataset", "tissues"})
            else None,
        )
        actions = []
        payload = captured.get("payload")
        if source_cursor is not None and evidence and isinstance(payload, dict):
            cursor_params = params
            if pair_cursor and payload.get("_provider_pages", {}).get("pair_evidence") is not None:
                cursor_params = source_cursor.request(payload, params, operation)
            issued, reason = await source_cursor.issue(payload, cursor_params, scope, cursor_state, freshness)
            actions.extend(issued)
            if reason is not None:
                section.outcome = "partial"
                section.warnings.append(
                    source_cursor.label
                    + " continuation is unavailable: "
                    + reason
                    + ". Acquired records remain available; no absence is inferred."
                )
                if source == "surechembl" and isinstance(section.data, dict):
                    source_cursor.partial(section.data, reason)
                elif pair_cursor and isinstance(section.data, dict):
                    from .native.opentargets_pair_evidence import analysis

                    analysis(section.data)["coverage"]["continuation_status"] = reason
                elif isinstance(section.data, dict) and isinstance(section.data.get("evidences"), dict):
                    section.data["evidences"]["coverage"]["continuation_status"] = reason
        if source_cursor is not None and isinstance(payload, dict):
            credible = payload.get("credible_sets")
            if isinstance(credible, dict) and credible.get("continuation_page") is not None:
                # Each relation continues independently. An evidence cursor is
                # scoped to its original request, so never reuse it on a new locus page.
                following = {
                    **params,
                    "page_index": credible["continuation_page"],
                    "include_evidences": False,
                }
                following.pop("evidence_cursor", None)
                actions.append(
                    {
                        "tool": "query_source",
                        "arguments": {
                            "source": source,
                            "operation": operation,
                            "params": following,
                            "freshness": freshness,
                        },
                    }
                )
        if (
            source == "clinical-trials"
            and operation == "get_trial_statistics"
            and evidence
            and isinstance(payload, dict)
            and "_provider_page" in payload
        ):
            page = page_from(payload, offset=0, limit=params.get("page_size", 25))
            if page.continuation:
                actions.append(
                    {
                        "tool": "query_source",
                        "arguments": {
                            "source": source,
                            "operation": operation,
                            "params": {**params, "page_token": page.continuation},
                            "freshness": freshness,
                        },
                    }
                )
        if (
            source == "surechembl"
            and operation == "get_patent_statistics"
            and evidence
            and isinstance(payload, dict)
            and "_provider_page" in payload
        ):
            from surechembl_mcp.contracts import MAX_PAGE

            following = params.get("page", 1) + 1
            if not payload["_provider_page"]["exhausted"] and following <= MAX_PAGE:
                actions.append(
                    {
                        "tool": "query_source",
                        "arguments": {
                            "source": source,
                            "operation": operation,
                            "params": {**params, "page": following},
                            "freshness": freshness,
                        },
                    }
                )
        if source == "pdb" and evidence and isinstance(payload, dict) and "_provider_page" in payload:
            page = page_from(payload, offset=params.get("offset", 0), limit=params.get("limit", 25))
            if page.next_offset is not None:
                if page.next_offset <= 100_000_000:
                    actions.append(
                        {
                            "tool": "query_source",
                            "arguments": {
                                "source": source,
                                "operation": operation,
                                "params": {**params, "offset": page.next_offset},
                                "freshness": freshness,
                            },
                        }
                    )
                else:
                    section.outcome = "partial"
                    section.warnings.append(
                        "RCSB continuation exceeds the supported offset; acquired structures remain available and no exhaustion is inferred."
                    )
                    if isinstance(section.data, dict):
                        section.data.setdefault("coverage", {}).update(
                            continuation_status="unavailable", next_provider_offset=page.next_offset
                        )
        if source == "gtex" and evidence and isinstance(payload, dict) and "_provider_page" in payload:
            page = page_from(payload, offset=params.get("page", 0), limit=min(params.get("limit", 25), 25))
            if page.next_offset is not None:
                actions.append(
                    {
                        "tool": "query_source",
                        "arguments": {
                            "source": source,
                            "operation": operation,
                            "params": {
                                **params,
                                "dataset_id": params.get("dataset_id", "gtex_v10"),
                                "limit": payload["coverage"]["effective_page_size"],
                                "page": page.next_offset,
                            },
                            "freshness": freshness,
                        },
                    }
                )
        if (
            source == "ncbi"
            and operation
            in {
                "search_ncbi_data",
                "get_genome_data",
                "get_taxonomy_data",
                "get_assembly_data",
                "search_project_sample",
                "find_orthologs",
            }
            and isinstance(payload, dict)
            and "_provider_page" in payload
            and evidence
        ):
            page = page_from(payload, offset=0, limit=25)
            pages = {"page_token": page}
            if operation == "get_taxonomy_data":
                for parameter, extra_page in payload.get("_provider_pages", {}).items():
                    if parameter in {"names_page_token", "genome_page_token"}:
                        pages[parameter] = page_from(
                            {"records": [], "_provider_page": extra_page}, offset=0, limit=25
                        )
            for parameter, page in pages.items():
                if page.continuation:
                    actions.append(
                        {
                            "tool": "query_source",
                            "arguments": {
                                "source": source,
                                "operation": operation,
                                "params": {**params, parameter: page.continuation},
                                "freshness": freshness,
                            },
                        }
                    )
                    if section.outcome == "empty":
                        section.outcome = "partial"
                        section.warnings.append(
                            "This provider window has no records; continuation remains available."
                        )
        return ResearchResult(
            outcome=section.outcome,
            sections={source: section},
            provenance=[evidence] if evidence else [],
            truncated=section.truncated,
            next_actions=actions,
        )

    def _search_plan(self, request):
        entity = request.entity.value
        if entity == "sequence":
            raise ResearchError(
                "canonical_route_required",
                'Use query_source(source="ncbi-records", operation="search", params={database:genbank|geo|sra,query:...}). This is the single route for sequence repositories.',
            )
        active = {
            k: v
            for k, v in request.filters.model_dump(mode="json", exclude_none=True).items()
            if v != [] and not (k == "species" and v == 9606)
        }
        unsupported = set(active) - SEARCH_FILTERS.get(entity, set())
        if unsupported:
            raise ResearchError(
                "unsupported_filter", "Unsupported filters: " + ", ".join(sorted(unsupported))
            )
        if entity == "article":
            return active, plan_sources(active)
        if entity == "variant":
            from .native.variants import search_filters

            _, active = search_filters(request.query, active)
        if entity == "drug":
            region = active.get("region")
            selected = active.get("source")
            if selected and selected not in SEARCH_SOURCES[entity]:
                raise ResearchError("unsupported_source", "Select mychem, ema or who for drugs.")
            region_sources = {
                "us": ["mychem"],
                "eu": ["ema"],
                "who": ["who"],
                "all": ["mychem", "ema", "who"],
            }
            choices = region_sources.get(region, SEARCH_SOURCES[entity])
            if selected and region and selected not in choices:
                raise ResearchError(
                    "source_plan_conflict", "Source does not belong to the requested regulatory region."
                )
            if active.get("product_type") and (selected != "who" and region != "who"):
                raise ResearchError("unsupported_filter", "product_type requires WHO source/region.")
            return active, [selected] if selected else choices if region else ["mychem"]
        selected = active.get("source") or SEARCH_SOURCES[entity][0]
        if selected not in SEARCH_SOURCES[entity]:
            raise ResearchError("unsupported_source", "Select one of: " + ", ".join(SEARCH_SOURCES[entity]))
        if (
            entity == "diagnostic"
            and active.get("manufacturer")
            and selected not in {"fda-devices", "who-ivd"}
        ):
            raise ResearchError(
                "unsupported_filter", "Manufacturer filtering requires source=fda-devices or who-ivd."
            )
        if entity == "pgx" and len(active.get("drug", [])) > 1:
            raise ResearchError("invalid_parameters", "PGx search accepts one drug.")
        if entity == "variant" and active.get("hgvsp"):
            from .native.variants import protein_change

            if not protein_change(active["hgvsp"]):
                raise ResearchError("invalid_parameters", "Use an exact protein change.")
        return active, [selected]

    async def search(self, request: SearchRequest, *, scope, _plan_only=False):
        if request.entity == Entity.study:
            await self.extensions.initialize_studies()
        active, sources = self._search_plan(request)
        entity = request.entity.value
        query = {
            **request.model_dump(mode="json", exclude={"cursor", "freshness"}),
            "implementation": REVISION,
            "contract": "2.0",
        }
        if entity == "pathway":
            # A ContentService cursor cannot resume against a different index's
            # ranked window, even when its query and public contract are equal.
            query["source_projection"] = "reactome-ebi-search-v1"
        if entity == "pgx":
            query["source_projection"] = "cpic-gene-drug-discovery-v1"
        if "species" not in SEARCH_FILTERS.get(entity, set()):
            # The shared model's human default is not an applied filter for these entities.
            query["filters"].pop("species", None)
        offset = (
            self.runtime.cursors.decode(request.cursor, query=query, scope=scope) if request.cursor else 0
        )
        if offset and entity in {"patent", "study"}:
            raise ResearchError("unsupported_cursor", "This source does not expose a qualified continuation.")
        if _plan_only:
            return None
        state = {
            "seen": [],
            "pending": [],
            "evidence": [],
            "sections": {},
            "providers": {
                s: {"offset": 0, "continuation": None, "exhausted": False, "pages": 0} for s in sources
            },
        }
        if request.cursor:
            state = await self.runtime.cache.get("page:" + digest(request.cursor))
            if state is None:
                raise ResearchError("expired_cursor", "Page state expired; restart the search.")
            # Retained overflow can satisfy a page without invoking a provider.
            # Recheck its boundary owners before any cached records are reused.
            from .source_licensing import require_operation

            for source in {proof["source"] for proof in state["evidence"]}:
                require_operation(source, "search")
        seen = set(state["seen"])
        rows = state["pending"]
        sections = {s: Section.model_validate(v) for s, v in state["sections"].items()}
        proofs = {v["evidence_id"]: Provenance.model_validate(v) for v in state["evidence"]}
        positions = state["providers"]
        failed = set()
        coverage = {
            s: {**p["coverage"], "windows_scanned": 0, "raw_rows_scanned": 0, "filtered_rows": 0}
            for s, p in positions.items()
            if "coverage" in p
        }

        def row_keys(row):
            ids = article_identifiers(row) if entity == "article" else set()
            if not ids:
                identity = row.get("id") or row.get("_id") or row.get("primaryAccession") or row.get("nct_id")
                if entity == "trial":
                    identity = identity or row.get("protocolSection", {}).get("identificationModule", {}).get(
                        "nctId"
                    )
                ids = {
                    str(
                        identity
                        or digest(
                            {
                                k: v
                                for k, v in row.items()
                                if k
                                not in {
                                    "evidence_ids",
                                    "sources",
                                    "primary_source",
                                    "_provider_ranks",
                                    "ranking",
                                }
                            }
                        )
                    )
                }
            return {digest({"entity": entity, "id": key}) for key in ids}

        def eligible_rows():
            ranked = (
                rank_articles(
                    rows,
                    request.query,
                    active.get("ranking_mode") or "hybrid",
                    active.get("sort") or "relevance",
                    request.limit,
                    retain_overflow=True,
                )
                if entity == "article"
                else rank_trials(rows, request.query)
                if entity == "trial"
                else rows
            )
            unique, keys = [], set(seen)
            for row in ranked:
                identifiers = row_keys(row)
                if identifiers & seen:
                    # Learn newly observed aliases for a previously delivered
                    # identity, so a later DOI-only row cannot reintroduce it.
                    seen.update(identifiers)
                elif not identifiers & keys:
                    unique.append(row)
                keys.update(identifiers)
            return unique

        async def run(source):
            position = positions[source]
            page = None
            acquired_rows = []
            # Acquisition and delivery limits are distinct. Rank a bounded
            # trial candidate window and retain undelivered rows in the cursor.
            acquisition_limit = max(20, request.limit) if entity == "trial" else request.limit

            def capture(payload):
                nonlocal page, acquired_rows
                from .receipts import _safe_request

                acquired_rows, _ = _safe_request(records_from(payload))
                page = page_from(
                    payload,
                    offset=position["offset"],
                    limit=acquisition_limit,
                    bounded=entity in {"patent", "study"},
                )
                if not page.exhausted and (
                    page.continuation == position["continuation"]
                    and (page.next_offset is None or page.next_offset <= position["offset"])
                ):
                    raise ResearchError("invalid_source_response", "Provider continuation did not advance.")

            continuation = position["continuation"]
            result = await self._safe(
                source,
                "search",
                {
                    "entity": entity,
                    "query": request.query,
                    "filters": active,
                    "limit": acquisition_limit,
                    "offset": position["offset"],
                    "continuation": continuation,
                },
                lambda: self.providers.search(
                    entity,
                    source,
                    request.query,
                    active,
                    acquisition_limit,
                    position["offset"],
                    **({"continuation": continuation} if continuation is not None else {}),
                ),
                scope=scope,
                freshness=request.freshness,
                capture=capture,
            )
            return source, result, page, acquired_rows

        # Scan at most three source windows per request. A filtered/duplicate-only
        # window is not exhaustion; remaining work is carried by the signed cursor.
        for _ in range(3):
            if len(eligible_rows()) >= request.limit:
                break
            participants = [
                s
                for s in sources
                if s not in failed
                and not positions[s]["exhausted"]
                and positions[s]["offset"] < 1000
                and positions[s]["pages"] < 500
            ]
            if not participants:
                break
            results = await asyncio.gather(*(run(source) for source in participants))
            for source, (section, proof), page, acquired_rows in results:
                old = sections.get(source)
                sections[source] = section
                if not proof:
                    failed.add(source)
                    if old and old.outcome in {"data", "partial"}:
                        sections[source] = Section(
                            outcome="partial",
                            error=section.error,
                            evidence_ids=old.evidence_ids,
                            warnings=[
                                *old.warnings,
                                "A later provider window failed; earlier evidence is retained.",
                            ],
                        )
                    continue
                proofs[proof.evidence_id] = proof
                if old and old.outcome in {"data", "partial"} and section.outcome == "empty":
                    sections[source] = old
                sections[source].evidence_ids = sorted(
                    {
                        *(old.evidence_ids if old else []),
                        *section.evidence_ids,
                    }
                )
                position = positions[source]
                records = acquired_rows
                rows.extend(
                    {
                        **r,
                        "sources": sorted(set(r.get("sources", [])) | {source}),
                        "primary_source": source,
                        "_provider_ranks": {source: position["offset"] + i + 1},
                        **({"source_evidence_ids": r["evidence_ids"]} if "evidence_ids" in r else {}),
                        # Provider-supplied identifier-like strings remain
                        # source data; only this service can mint citations.
                        "evidence_ids": [proof.evidence_id],
                        **(
                            {
                                "source_assertions": [
                                    {**assertion, "evidence_ids": [proof.evidence_id]}
                                    for assertion in r["source_assertions"]
                                ]
                            }
                            if entity == "article" and r.get("record_type") == "literature"
                            else {}
                        ),
                        **(
                            {
                                "identities": [
                                    {**identity, "evidence_ids": [proof.evidence_id]}
                                    for identity in r["identities"]
                                ]
                            }
                            if entity == "article" and r.get("record_type") == "literature"
                            else {}
                        ),
                    }
                    for i, r in enumerate(records)
                )
                position.update(
                    offset=page.next_offset
                    if page.next_offset is not None
                    else position["offset"] + page.raw_count,
                    continuation=page.continuation,
                    exhausted=page.exhausted,
                    pages=position["pages"] + 1,
                )
                coverage[source] = {
                    **page.public_metadata(),
                    "consumed_offset": position["offset"],
                    "windows_scanned": coverage.get(source, {}).get("windows_scanned", 0) + 1,
                    "raw_rows_scanned": coverage.get(source, {}).get("raw_rows_scanned", 0) + page.raw_count,
                    "filtered_rows": coverage.get(source, {}).get("filtered_rows", 0) + page.filtered_count,
                }
                position["coverage"] = coverage[source]
        unique = eligible_rows()
        delivered, pending = unique[: request.limit], unique[request.limit :]
        for row in delivered:
            seen.update(row_keys(row))
        cursor = None
        warnings = []
        more = pending or any(
            not p["exhausted"] and p["offset"] < 1000 and p["pages"] < 500 for p in positions.values()
        )
        if more and (proofs or request.cursor) and offset + len(delivered) <= 1000:
            cursor = self.runtime.cursors.encode(query=query, scope=scope, offset=offset + len(delivered))
            pending_proofs = {key for row in pending for key in row.get("evidence_ids", [])} | {
                key for section in sections.values() for key in section.evidence_ids
            }
            saved = await self.runtime.cache.put(
                "page:" + digest(cursor),
                {
                    "seen": sorted(seen),
                    "pending": pending,
                    "providers": positions,
                    "sections": {
                        s: Section(
                            outcome=v.outcome, error=v.error, warnings=v.warnings, evidence_ids=v.evidence_ids
                        ).model_dump(mode="json")
                        for s, v in sections.items()
                    },
                    "evidence": [
                        p.model_dump(mode="json") for key, p in proofs.items() if key in pending_proofs
                    ],
                },
                3600,
            )
            if saved is False:
                cursor = None
                warnings.append("Continuation state exceeded its storage budget; refine the search.")
        retrieval_limited = any(
            not p["exhausted"] and (p["offset"] >= 1000 or p["pages"] >= 500) for p in positions.values()
        )
        if retrieval_limited:
            warnings.append(
                "The bounded retrieval limit was reached; refine the search. Provider coverage is incomplete."
            )
        for source, position in positions.items():
            metadata = position.get("coverage", {})
            if (
                position["exhausted"]
                and metadata.get("total") is not None
                and position["offset"] < metadata["total"]
            ):
                warnings.append(
                    f"{source} reports more results than its accessible continuation exposes; refine the query. Coverage is incomplete."
                )
        if cursor and len(delivered) < request.limit:
            warnings.append(
                "The scan budget ended before a full eligible page; continue with next_cursor. This is not evidence of absence."
            )
        if len(sources) > 1:
            warnings.append(
                "Federated pages are independently ranked source windows, not a globally exhaustive ranking. Use an explicit source for provider ordering and route-limited continuation."
            )
        if request.cursor:
            warnings.append("Live source pagination may change; already returned identities are suppressed.")
        query["execution"] = {
            "sources": sources,
            "requested_filters": active,
            "source_participation": {s: v.outcome for s, v in sections.items()},
            "pagination": "provider continuation with retained overflow; at most three windows per source/request",
            "source_pagination": coverage,
            "sort_scope": "federated_windows"
            if len(sources) > 1
            else "window"
            if entity == "trial"
            or (
                entity == "article"
                and active.get("sort", "relevance") == "relevance"
                and active.get("ranking_mode", "hybrid") != "provider"
            )
            else next(iter(coverage.values()), {}).get("sort_scope", "not_established"),
            "ranking": active.get(
                "ranking_mode",
                "hybrid"
                if entity == "article"
                else "title_condition_overlap"
                if entity == "trial"
                else "provider",
            ),
            **(
                {"candidate_window_limit": max(20, request.limit), "ranking_scope": "acquired_windows"}
                if entity == "trial"
                else {}
            ),
        }
        from .summaries import summarize_records

        visible = [{k: v for k, v in row.items() if k != "_provider_ranks"} for row in delivered]
        original = visible
        cut = False
        if request.output == "summary":
            visible, cut = summarize_records(visible)
        if any(row.get("date_validation", {}).get("status") == "future_dated" for row in visible):
            warnings.append(
                "Some provider publication dates are in the future; inspect date_validation. These can be scheduled issue dates and do not confirm publication."
            )
        result = ResearchResult(
            entity=request.entity,
            outcome=("partial" if cursor or retrieval_limited else "empty")
            if not delivered and all(v.outcome in {"data", "empty"} for v in sections.values())
            else self._outcome(sections.values()),
            records=visible,
            sections={
                s: Section(outcome=v.outcome, error=v.error, warnings=v.warnings, evidence_ids=v.evidence_ids)
                for s, v in sections.items()
            },
            provenance=list(proofs.values()),
            next_cursor=cursor,
            truncated=cut
            or len(unique) > request.limit
            or retrieval_limited
            or any(s.truncated for s in sections.values()),
            query=query,
            warnings=warnings,
        )
        if cut:
            result._omitted_evidence = {"records": original}
            result.query.setdefault("output_omissions", {})["summary"] = {
                "record_count": len(visible),
                "recovery": "composed_recovery",
                "interpretation": "Bounded excerpts; omitted fields and items are not absence.",
            }
        return result

    def _sections(self, entity):
        return set(SECTIONS.get(entity, {}))

    def _get_plan(self, request):
        entity = request.entity.value
        names = request.sections or ["record"]
        if entity == "sequence":
            raise ResearchError(
                "canonical_route_required",
                "Use query_source(ncbi-records,get) for bounded GenBank/GEO/SRA reads.",
            )
        if len(names) != len(set(names)):
            raise ResearchError("duplicate_section", "Select each section once.")
        if "all" in names:
            raise ResearchError("unbounded_sections", "Select explicit sections from capabilities.")
        for name in names:
            if name in ALIASES.get(entity, {}):
                raise ResearchError(
                    "canonical_route_required",
                    f"Use section {ALIASES[entity][name]}; aliases are not exposed.",
                )
            if name != "record" and name not in SECTIONS.get(entity, {}):
                raise ResearchError("unknown_section", "Unknown section: " + name)
        if request.assembly and entity != "variant":
            raise ResearchError("invalid_assembly", "Assembly applies to variant coordinates only.")
        if entity == "variant":
            self.providers.variants.validate(request.id, request.assembly)
        if entity == "protein" and "domains" in names:
            from .native.interpro import accession

            accession(request.id)
        if entity == "protein" and "complexes" in names:
            from .native.complexportal import accession

            accession(request.id)
        if entity == "article":
            article_id(request.id)
        if request.species != 9606 and (
            entity not in {"gene", "protein"}
            or any(
                n
                not in (
                    {"record", "domains", "complexes"}
                    if entity == "protein"
                    else {"record", "protein", "go", "pathways"}
                )
                for n in names
            )
        ):
            raise ResearchError("unsupported_species", "Selected sections are human-specific.")
        if set(request.section_parameters) - set(names):
            raise ResearchError("unsupported_section_parameters", "Parameters must target selected sections.")
        allowed = {
            "transcripts": {"limit", "page"},
            "exons": {"limit", "page"},
            "genetics": {"limit", "page"},
            "gwas": {"limit", "page"},
            "expression": {"tissue_id", "limit", "query_type", "page"},
            "eqtl": {"tissue_id", "limit", "p_value_threshold", "analysis_mode", "variant_id", "page"},
            "sqtl": {
                "tissue_id",
                "limit",
                "p_value_threshold",
                "analysis_mode",
                "variant_id",
                "phenotype_id",
                "page",
            },
            "fulltext": {"view", "start", "end"},
            "assets": {"limit", "offset"},
            "cbioportal": {"molecular_profile_id", "sample_list_id"},
            "civic": {"limit", "collection", "cursor"},
            "domains": {"limit", "cursor"},
            "complexes": {"limit", "cursor"},
        }
        for name, params in request.section_parameters.items():
            if set(params) - allowed.get(name, set()):
                raise ResearchError("unsupported_section_parameters", "Unsupported parameters for " + name)
            self.adapters._bounds(params)
            if name == "genetics":
                from .native.opentargets_workflows import bounded

                bounded(params.get("limit", 10))
                bounded(params.get("page", 0), 0, MAX_PROVIDER_PAGE)
            if name == "domains":
                from .native.interpro import parameters

                parameters(params)
            if name == "civic":
                civic_parameters(params, public=True)
            if name == "complexes":
                from .native.complexportal import parameters

                parameters(params)
            if entity == "gene" and name == "expression":
                if params.get("query_type", "gene_median") not in {"gene_median", "gene_tissue"}:
                    raise ResearchError(
                        "invalid_parameters", "Gene expression sections support gene_median or gene_tissue."
                    )
                if params.get("query_type") == "gene_tissue" and not params.get("tissue_id"):
                    raise ResearchError("missing_tissue", "gene_tissue requires tissue_id.")
            if entity == "gene" and name in {"eqtl", "sqtl"}:
                mode = params.get("analysis_mode", "gene_associations")
                if mode not in {"gene_associations", "metasoft", "dynamic"}:
                    raise ResearchError("invalid_parameters", "Unsupported gene QTL mode.")
                if mode in {"metasoft", "dynamic"} and not params.get("variant_id"):
                    raise ResearchError("invalid_parameters", "QTL comparison requires variant_id.")
                if mode == "metasoft" and name != "eqtl":
                    raise ResearchError("invalid_parameters", "MetaSoft is an eQTL analysis.")
                if mode == "dynamic" and params.get("page", 0):
                    raise ResearchError(
                        "invalid_parameters", "Dynamic QTL is a single calculation, without provider pages."
                    )
                if name == "sqtl" and mode == "dynamic" and not params.get("phenotype_id"):
                    raise ResearchError(
                        "invalid_parameters",
                        "Dynamic sQTL requires phenotype_id from a qualified association.",
                    )
                if params.get("phenotype_id") and (name != "sqtl" or mode != "dynamic"):
                    raise ResearchError("invalid_parameters", "phenotype_id applies to dynamic sQTL only.")
        for name in set(names) & {"eqtl", "sqtl"}:
            if not request.section_parameters.get(name, {}).get("tissue_id"):
                raise ResearchError("missing_tissue", name + " requires tissue_id.")
        if (
            "cbioportal" in names
            and not {"molecular_profile_id", "sample_list_id"}
            <= request.section_parameters.get("cbioportal", {}).keys()
        ):
            raise ResearchError(
                "missing_cohort", "cBioPortal requires molecular_profile_id and sample_list_id."
            )
        if request.source_versions:
            if set(request.source_versions) != {"gtex"} or not set(names) & {
                "expression",
                "eqtl",
                "sqtl",
                "transcripts",
                "exons",
            }:
                raise ResearchError(
                    "unsupported_version_pin", "Only selected GTEx sections support a release pin."
                )
            if request.source_versions["gtex"] not in {"gtex_v8", "gtex_v10"}:
                raise ResearchError("unsupported_release", "GTEx release must be gtex_v8 or gtex_v10.")
        if entity == "article" and set(names) & {"fulltext", "assets"}:
            from .extensions import ArticleContent

            for name in set(names) & {"fulltext", "assets"}:
                try:
                    ArticleContent(
                        id=request.id,
                        view="assets"
                        if name == "assets"
                        else request.section_parameters.get(name, {}).get("view", "outline"),
                        **{k: v for k, v in request.section_parameters.get(name, {}).items() if k != "view"},
                    )
                except ValidationError:
                    raise invalid_parameters() from None
        owners = {}
        for name in names:
            source = RECORD_OWNER[entity] if name == "record" else SECTIONS[entity][name]
            dependencies = set()
            alternatives = SECTION_ALTERNATIVES.get(entity, {}).get(name, [])
            if request.sources and alternatives:
                chosen = set(request.sources) & set(alternatives)
                if len(chosen) > 1:
                    raise ResearchError("ambiguous_source", "Select one owner for each section.")
                if chosen:
                    source = next(iter(chosen))
            if entity == "drug" and name == "record" and request.sources:
                if len(request.sources) != 1 or request.sources[0] not in SEARCH_SOURCES["drug"]:
                    raise ResearchError("ambiguous_source", "Select one source for a drug record.")
                source = request.sources[0]

            if name == "record" and entity == "article":
                kind, _ = article_id(request.id)
                source = (
                    "pubmed" if kind == "pmid" else "europepmc"
                )
                if request.sources:
                    if len(request.sources) != 1 and names == ["record"]:
                        raise ResearchError("invalid_parameters", "One source owns an article record read.")
                    if len(request.sources) == 1:
                        source = request.sources[0]
                    if source not in {"pubmed", "europepmc"}:
                        raise ResearchError(
                            "unsupported_source",
                            "Article records support pubmed or europepmc.",
                        )
            if name == "record" and entity == "author":
                source = ("orcid" if request.id.startswith("orcid:") else
                          "openalex")
            if name == "record" and entity == "patent":
                source = "patents"
            dependencies = SECTION_DEPENDENCIES.get((entity, name), set())
            if (entity == "article" and name in {"fulltext", "assets"} and source == "pmc"
                    and article_id(request.id)[0] != "pmcid"):
                dependencies = dependencies | {"pubmed"}
            if entity == "variant" and name == "civic":
                kind, _ = self.providers.variants.validate(request.id, request.assembly)
                if kind != "protein":
                    dependencies = dependencies | {"myvariant"}
            if entity == "variant" and name == "predictions":
                from .native.alphamissense import plan

                kind, _ = plan(request.id, request.assembly)
                dependencies = {"uniprot"} if kind == "protein" else {"ensembl"}
            if entity == "variant" and name == "eve":
                from .native.eve import plan

                plan(request.id, request.assembly)
            if entity == "variant" and name == "population":
                from .native.gnomad import direct_population_identity

                if direct_population_identity(request.id, request.assembly) is not None:
                    dependencies = dependencies - {"myvariant"}
            if (
                entity == "gene"
                and source == "gtex"
                and (
                    request.id.isdecimal()
                    or any(n not in {"expression", "eqtl", "sqtl", "transcripts", "exons"} for n in names)
                )
            ):
                dependencies = dependencies | {"mygene"}
            required = dependencies | {source}
            if request.sources and not required <= set(request.sources):
                raise ResearchError(
                    "source_plan_conflict",
                    f"{name} requires "
                    + ", ".join(sorted(required))
                    + ". Explicit sources constrain identity resolution too; use an exact source-owned identifier or include its dependencies.",
                )
            owners[name] = (source, sorted(dependencies))
        if request.sources and set(request.sources) - set().union(
            *({s} | set(d) for s, d in owners.values())
        ):
            raise ResearchError("unused_source", "A selected source does not participate in these sections.")
        return owners

    async def get(self, request: GetRequest, *, scope, _plan_only=False):
        if request.entity == Entity.study:
            await self.extensions.initialize_studies()
        owners = self._get_plan(request)
        # Validate retained-client schemas during batch preflight, before reads.
        for name, (source, _) in owners.items():
            if request.entity == Entity.pathway:
                from .native.providers import identifier

                identifier(
                    request.id,
                    r"R-[A-Z]{3}-[1-9][0-9]*",
                    "Use a Reactome stable pathway ID; research(pathway_review) also accepts an exact pathway name.",
                )
                await self.adapters.validate(
                    "reactome",
                    "get_pathway_info",
                    {
                        "pathway_id": request.id,
                        "detail_level": "basic"
                        if name == "record"
                        else "participants"
                        if name == "genes"
                        else "hierarchy",
                    },
                )
            if source == "gtex":
                params = {
                    "gene_id": request.id,
                    "limit": 25,
                    **request.section_parameters.get(name, {}),
                    "dataset_id": request.source_versions.get("gtex", "gtex_v10"),
                }
                if name == "expression":
                    params.setdefault("query_type", "gene_median")
                    operation = "query_expression"
                elif name in {"transcripts", "exons"}:
                    params["entity_type"] = "transcript" if name == "transcripts" else "exon"
                    params["entity_id"] = params.pop("gene_id")
                    operation = "get_annotation"
                else:
                    params.setdefault("analysis_mode", "gene_associations")
                    params["qtl_type"] = name
                    operation = "query_qtl"
                await self.adapters.validate(source, operation, params)
        if _plan_only:
            return None
        civic = CivicContinuation(self.runtime)
        execution_request, civic_scanned = request, 0
        if "civic" in owners:
            params, civic_scanned = await civic.resume(request, scope=scope)
            execution_request = request.model_copy(
                update={"section_parameters": {**request.section_parameters, "civic": params}}
            )
        from .native.interpro import Continuation as InterProContinuation

        interpro_continuation = InterProContinuation(self.runtime)
        interpro_state = None
        if request.entity == Entity.protein and "domains" in owners:
            params, interpro_state = await interpro_continuation.resume(request, scope=scope)
            execution_request = execution_request.model_copy(
                update={"section_parameters": {**execution_request.section_parameters, "domains": params}}
            )
        context = {}
        from .native.complexportal import Continuation as ComplexContinuation

        complex_continuation = ComplexContinuation(self.runtime)
        if request.entity == Entity.protein and "complexes" in owners:
            params = await complex_continuation.resume(request, scope=scope)
            execution_request = execution_request.model_copy(
                update={"section_parameters": {**execution_request.section_parameters, "complexes": params}}
            )
        identity_key = ("gene", request.id, request.species)
        needs_gene = request.entity == Entity.gene and any(
            source == "mygene" or "mygene" in dependencies for source, dependencies in owners.values()
        )
        if needs_gene:

            async def load_identity():
                record, _ = await self.runtime.invoke(
                    "mygene",
                    {
                        "operation": "gene_identity",
                        "params": {"id": request.id, "species": request.species},
                        "version": None,
                        "implementation": REVISION,
                    },
                    lambda: self.providers.gene(request.id, request.species),
                    scope=scope,
                    freshness=request.freshness,
                )
                return record["payload"]

            context[identity_key] = asyncio.create_task(load_identity())

        captured = {}

        async def run(name, owner):
            source, dependencies = owner
            fn = (
                (
                    lambda: self.providers.record(
                        request.entity.value,
                        request.id,
                        source=source,
                        species=request.species,
                        assembly=request.assembly,
                        context=context,
                    )
                )
                if name == "record"
                else (
                    lambda: self.providers.section(
                        request.entity.value, request.id, name, execution_request, context, source=source
                    )
                )
            )
            result = await self._safe(
                source,
                "get:" + name,
                request.model_dump(mode="json"),
                fn,
                scope=scope,
                freshness=request.freshness,
                record_id=request.id,
                identity=(
                    lambda: self.providers.record(
                        "gene", request.id, species=request.species, context=context
                    )
                )
                if needs_gene and (source == "mygene" or "mygene" in dependencies)
                else None,
                version=request.source_versions.get(source) or ("gtex_v10" if source == "gtex" else None),
                capture=lambda payload: captured.setdefault(name, payload),
                attribution=dependencies,
            )
            # Fail over only unconstrained article-content reads. The replacement
            # gets its own source gate, cache entry, evidence and provenance.
            if (
                request.entity == Entity.article
                and name in {"fulltext", "assets"}
                and source == "europepmc"
                and not request.sources
                and result[0].error
                and result[0].error.get("code") in {"source_unavailable", "source_not_found"}
            ):
                original_code = result[0].error["code"]
                fallback_dependencies = {"pubmed"} if article_id(request.id)[0] != "pmcid" else set()
                result = await self._safe(
                    "pmc", "get:" + name, request.model_dump(mode="json"),
                    lambda: self.providers.section(
                        "article", request.id, name, execution_request, context, source="pmc"
                    ),
                    scope=scope, freshness=request.freshness, record_id=request.id,
                    capture=lambda payload: captured.setdefault(name, payload),
                    attribution=fallback_dependencies,
                )
                result[0].warnings.append(
                    f"Europe PMC acquisition failed ({original_code}); attempted NCBI PMC instead."
                )
            if result[1] and dependencies:
                result[0].warnings.append("Identity dependencies: " + ", ".join(dependencies) + ".")
            if (
                name == "record"
                and request.entity == Entity.article
                and result[1]
                and isinstance(result[0].data, dict)
                and result[0].data.get("record_type") == "literature"
            ):
                for key in ("source_assertions", "identities"):
                    for row in result[0].data[key]:
                        row["evidence_ids"] = [result[1].evidence_id]
            if (
                name == "record"
                and request.entity == Entity.trial
                and result[1]
                and isinstance(result[0].data, dict)
                and result[0].data.get("record_type") == "trial"
            ):
                result[0].data["evidence_ids"] = [result[1].evidence_id]
            return name, result

        try:
            results = await asyncio.gather(*(run(n, o) for n, o in owners.items()))
        finally:
            tasks = list(context.values())
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        sections = {n: s for n, (s, _) in results}
        qualified = None
        if needs_gene:
            task = context[identity_key]
            if not task.cancelled() and task.exception() is None:
                qualified = task.result()["qualified_identity"]
        actions = []
        for name, (source, _) in owners.items():
            proof = dict(results)[name][1]
            if proof is not None:
                source = proof.source
            payload = captured.get(name)
            if name == "fulltext" and isinstance(payload, dict) and payload.get("truncated") is True:
                sections[name].truncated = True
                parameters = request.section_parameters.get(name, {})
                end = parameters.get("end", 100)
                if end < 100000:
                    actions.append(
                        {
                            "tool": "get",
                            "arguments": {
                                **request.model_dump(mode="json", exclude_none=True),
                                "sections": [name],
                                "sources": [source],
                                "id": payload.get("pmcid", request.id),
                                "section_parameters": {
                                    name: {"view": "lines", "start": end + 1, "end": min(end + 100, 100000)}
                                },
                            },
                        }
                    )
                else:
                    sections[name].warnings.append(
                        "Further article lines exceed the supported 100000-line address range."
                    )
            if name == "gwas" and request.entity == Entity.variant and isinstance(payload, dict):
                parameters = request.section_parameters.get(name, {})
                limit = parameters.get("limit", 10)
                page = page_from(payload, offset=parameters.get("page", 0) * limit, limit=limit)
                sections[name].warnings.extend(payload.get("warnings", []))
                next_page = bounded_section_page(
                    sections[name], None if page.next_offset is None else page.next_offset // limit
                )
                if page.next_offset is not None and next_page is None:
                    continue
                if page.next_offset is not None:
                    sections[name].outcome = "partial"
                    sections[name].warnings.append(
                        "Further GWAS source windows remain; use the supplied continuation action."
                    )
                    actions.append(
                        {
                            "tool": "get",
                            "arguments": {
                                **request.model_dump(mode="json", exclude_none=True),
                                "sections": [name],
                                "sources": [source],
                                "section_parameters": {name: {"limit": limit, "page": next_page}},
                            },
                        }
                    )
                continue
            if name == "domains" and request.entity == Entity.protein and isinstance(payload, dict):
                actions.extend(
                    await interpro_continuation.issue(payload, request, scope=scope, state=interpro_state)
                )
                sections[name].warnings.extend(payload.get("warnings", []))
                if isinstance(sections[name].data, dict):
                    sections[name].data["coverage"] = payload["coverage"]
                continue
            if name == "complexes" and request.entity == Entity.protein and isinstance(payload, dict):
                actions.extend(await complex_continuation.issue(payload, request, scope=scope))
                sections[name].warnings = list(
                    dict.fromkeys([*sections[name].warnings, *payload.get("warnings", [])])
                )
                if isinstance(sections[name].data, dict):
                    sections[name].data["coverage"] = payload["coverage"]
                continue
            if name == "civic" and isinstance(payload, dict):
                for arguments in await civic.issue(payload, request, scope=scope, scanned=civic_scanned):
                    selected = self._get_plan(GetRequest.model_validate(arguments))[name]
                    arguments["sources"] = sorted({selected[0], *selected[1]})
                    actions.append({"tool": "get", "arguments": arguments})
                sections[name].warnings = list(
                    dict.fromkeys([*sections[name].warnings, *payload.get("warnings", [])])
                )
                for collection, coverage in payload.get("coverage", {}).items():
                    if "continuation_status" in coverage and isinstance(sections[name].data, dict):
                        sections[name].data["coverage"][collection]["continuation_status"] = coverage[
                            "continuation_status"
                        ]
                continue
            if source != "gtex" or not isinstance(payload, dict) or "_provider_page" not in payload:
                continue
            parameters = request.section_parameters.get(name, {})
            page = page_from(
                payload, offset=parameters.get("page", 0), limit=min(parameters.get("limit", 25), 25)
            )
            if page.next_offset is None:
                continue
            next_page = bounded_section_page(sections[name], page.next_offset)
            if next_page is None:
                continue
            arguments = {
                **request.model_dump(mode="json", exclude_none=True),
                "id": payload.get("gene_identity", {}).get("gencode_id", request.id),
                "sections": [name],
                "section_parameters": {
                    name: {
                        **parameters,
                        **(
                            {"variant_id": payload["variant_identity"]["variant_id"]}
                            if payload.get("variant_identity")
                            else {}
                        ),
                        "limit": payload["coverage"]["effective_page_size"],
                        "page": next_page,
                    }
                },
                "source_versions": {"gtex": request.source_versions.get("gtex", "gtex_v10")},
                "sources": [],
            }
            # A single-section recovery request needs only that section's
            # identity dependencies, not unrelated sources from the parent.
            recovery = GetRequest.model_validate(arguments)
            selected = self._get_plan(recovery)[name]
            arguments["sources"] = sorted({selected[0], *selected[1]})
            actions.append({"tool": "get", "arguments": arguments})
        return ResearchResult(
            entity=request.entity,
            outcome=self._outcome(sections.values()),
            sections=sections,
            provenance=[p for _, (_, p) in results if p],
            truncated=any(s.truncated for s in sections.values()),
            next_actions=actions,
            query={
                **request.model_dump(mode="json"),
                **({"qualified_identity": qualified} if qualified else {}),
                "provider_plan": {
                    n: {"source": s, "identity_dependencies": d} for n, (s, d) in owners.items()
                },
            },
        )

    async def resolve(self, query, *, entity=None, species=9606, assembly=None, scope, _plan_only=False):
        if not query.strip() or len(query) > 512:
            raise ResearchError("invalid_identifier", "Use a bounded nonempty identifier.")
        if entity is None:
            if re.fullmatch(r"(?:rs\d+|.+ [A-Z][0-9]+[A-Z*]|chr.+:.+:.+:.+)", query):
                entity = Entity.variant
            elif query.startswith(("PMC", "10.")):
                entity = Entity.article
            elif re.fullmatch(r"NCT\d{8}", query):
                entity = Entity.trial
            elif query.startswith("HP:"):
                entity = Entity.phenotype
            elif query.startswith(("MONDO:", "DOID:", "OMIM:")):
                entity = Entity.disease
            elif query.startswith("R-"):
                entity = Entity.pathway
            else:
                if assembly:
                    raise ResearchError(
                        "invalid_assembly", "Select a variant identity before applying assembly scope."
                    )
                if _plan_only:
                    return None
                return ResearchResult(
                    outcome="ambiguous",
                    warnings=[
                        "Specify entity to distinguish genes, drugs, diseases and authors; names are never merged across types."
                    ],
                    next_actions=[
                        {
                            "tool": "resolve",
                            "arguments": {
                                "query": query,
                                "entity": e,
                                **({"species": species} if e in {"gene", "protein"} else {}),
                            },
                        }
                        for e in (
                            ["gene", "protein"] if species != 9606 else ["gene", "drug", "disease", "author"]
                        )
                    ],
                )
        if assembly and entity != Entity.variant:
            raise ResearchError("invalid_assembly", "Assembly applies to variant coordinates only.")
        if species != 9606 and entity not in {Entity.gene, Entity.protein}:
            raise ResearchError("unsupported_species", "This entity has no nonhuman species scope.")
        if entity in {Entity.variant, Entity.article, Entity.trial, Entity.pathway} or (
            entity == Entity.phenotype and query.startswith("HP:")
        ):
            return await self.get(
                GetRequest(entity=entity, id=query, species=species, assembly=assembly),
                scope=scope,
                _plan_only=_plan_only,
            )
        request = SearchRequest(
            entity=entity,
            query=query,
            output="full",
            filters={"species": species} if entity in {Entity.gene, Entity.protein} else {},
            limit=10,
        )
        if _plan_only:
            return await self.search(request, scope=scope, _plan_only=True)
        result = await self.search(request, scope=scope)
        if entity == Entity.gene:
            for row in result.records:
                qualify_gene(row, species)
            exact = [row for row in result.records if gene_matches(row, query, species)]
        else:
            exact = [
                r
                for r in result.records
                if str(r.get("symbol") or r.get("id") or r.get("_id") or "").casefold() == query.casefold()
            ]
        if result.records:
            result.outcome = "data" if len(exact) == 1 else "ambiguous"
        result.query["resolution_policy"] = {
            "method": "exact_identity",
            "exact_matches": len(exact),
            "candidate_count": len(result.records),
            "provider_score_used_for_identity": False,
            "rule": "One exact species-qualified symbol or stable ID resolves. Aliases and ranked names remain candidates, regardless of the score gap.",
        }
        if entity == Entity.gene:
            for row in result.records:
                aliases = row.get("alias") or []
                aliases = aliases if isinstance(aliases, list) else [aliases]
                row["identity_match"] = (
                    "exact"
                    if row in exact
                    else "alias"
                    if query.casefold() in {str(a).casefold() for a in aliases}
                    else "candidate"
                )
        result.next_actions = [
            {
                "tool": "get",
                "arguments": {
                    "entity": entity.value,
                    "id": str(r.get("_id") or r.get("id") or r.get("primaryAccession") or r.get("symbol")),
                    **({"species": species} if entity in {Entity.gene, Entity.protein} else {}),
                },
            }
            for r in (exact or result.records)[:5]
            if r.get("_id") or r.get("id") or r.get("primaryAccession") or r.get("symbol")
        ]
        result.warnings.append(
            "Search candidates are not evidence of exact identity. Select a qualified stable identifier."
        )
        return result

    async def _gene_discovery_text(self, identity, *, scope):
        symbol, species = identity["symbol"], identity["species"]
        if species == 9606:
            return symbol, None
        section, proof = await self._safe(
            "ncbi",
            "taxonomy_identity",
            {"species": species},
            lambda: self.providers.ncbi_summary("taxonomy", f"{species}[uid]", limit=1),
            scope=scope,
            record_id=str(species),
        )
        rows = records_from(section.data)
        if section.outcome != "data" or len(rows) != 1 or str(rows[0].get("uid")) != str(species):
            raise ResearchError(
                "unresolved_identity", "Species-qualified discovery requires an exact taxonomy record."
            )
        name = rows[0].get("scientificname")
        if not isinstance(name, str) or not re.fullmatch(r"[\w .()-]{1,180}", name):
            raise ResearchError("invalid_source_response", "Taxonomy record lacks a safe scientific name.")
        return f'{symbol} AND "{name}"', proof

    async def _disease_discovery(self, value, *, scope):
        async def acquire():
            return self.providers.disease_identity(value, await self.providers.record("disease", value))

        return await self._safe(
            "mydisease",
            "get:record",
            {"entity": "disease", "id": value, "projection": "preferred-label-v1"},
            acquire,
            scope=scope,
            record_id=value,
        )

    async def relate(
        self, entity, id, relation, *, scope, limit=10, species=9606, assembly=None, _plan_only=False
    ):
        if relation in self._sections(entity.value):
            raise ResearchError(
                "canonical_route_required",
                f'Use get(entity="{entity.value}",id=...,sections=["{relation}"]); entity sections are not duplicated as relations.',
            )
        if relation not in RELATIONS.get(entity.value, []):
            raise ResearchError(
                "unknown_relation",
                f"Valid {entity.value} relations: "
                + (", ".join(RELATIONS.get(entity.value, [])) or "none")
                + f'. Inspect capabilities(entity="{entity.value}").',
            )
        if not 1 <= limit <= 25 or not id or len(id) > 512:
            raise ResearchError("invalid_parameters", "Invalid bounded relation request.")
        if assembly and entity != Entity.variant:
            raise ResearchError("invalid_assembly", "Assembly applies to variant coordinates only.")
        if species != 9606 and (entity != Entity.gene or relation != "articles"):
            raise ResearchError(
                "unsupported_species",
                "Nonhuman gene discovery supports articles; clinical trials concern human participants.",
            )
        if entity == Entity.variant:
            self.providers.variants.validate(id, assembly)
        if entity == Entity.article:
            if relation == "recommendations" and (id.startswith(("openalex:", "https://openalex.org/")) or re.fullmatch(r"W\d+", id)):
                from .native.openalex import identity
                identity(id, "W")
            else:
                article_id(id)
        if _plan_only:
            return None
        if entity in {Entity.gene, Entity.drug, Entity.disease}:
            query, identity, proofs = id, None, []
            if entity == Entity.gene:
                section, proof = await self._safe(
                    "mygene",
                    "gene_identity",
                    {"id": id, "species": species},
                    lambda: self.providers.gene(id, species),
                    scope=scope,
                    record_id=id,
                )
                if section.outcome != "data":
                    return ResearchResult(
                        entity=entity, outcome=section.outcome, sections={"identity": section}
                    )
                identity = section.data["qualified_identity"]
                query, taxon_proof = await self._gene_discovery_text(identity, scope=scope)
                proofs = [p for p in (proof, taxon_proof) if p]
            elif entity == Entity.disease:
                section, proof = await self._disease_discovery(id, scope=scope)
                if section.outcome != "data":
                    return ResearchResult(
                        entity=entity, outcome=section.outcome, sections={"identity": section}
                    )
                identity = section.data
                query = identity["label"]
                proofs = [proof] if proof else []
            result = await self.search(
                SearchRequest(
                    entity="article" if relation == "articles" else "trial", query=query, limit=limit
                ),
                scope=scope,
            )
            result.provenance.extend(proofs)
            result.query.update(
                relationship_evidence="discovery",
                relation_from={"entity": entity.value, "id": id, "species": species},
            )
            if identity:
                result.query["qualified_identity"] = identity
                result.query["execution"]["identity_dependencies"] = [
                    "mydisease" if entity == Entity.disease else "mygene",
                    *(["ncbi"] if species != 9606 else []),
                ]
            result.warnings.append(
                "Name-based co-mention search is discovery, not proof of a biological relationship. Verify identity, species and experimental context in each record."
            )
            return result
        if entity == Entity.article:
            if relation == "authors":
                source = (
                    "pubmed"
                    if article_id(id)[0] == "pmid"
                    else "europepmc"
                )
                fn = lambda: self._article_authors(id, source)
            elif relation == "entities":
                source = "pubtator"
                fn = lambda: self.providers.annotations(id)
            elif relation == "recommendations":
                source = "openalex"
                fn = lambda: self.providers.openalex.recommendations(id, limit)
            elif relation in {"citations", "references"}:
                source = "europepmc"
                fn = lambda: self.providers.literature.open_graph(id, relation, limit)
        elif entity == Entity.author:
            from .native.openalex import identity

            identity(id, "A")
            source = "openalex"
            fn = lambda: self.providers.openalex.author_works(id, limit)
        elif entity == Entity.variant:
            source = "myvariant" if relation == "structure" else "pubmed"
            fn = lambda: self._variant_relation(id, relation, limit, assembly)
        captured = {}
        section, proof = await self._safe(
            source,
            "relate",
            {
                "entity": entity.value,
                "id": id,
                "relation": relation,
                "limit": limit,
                "species": species,
                "assembly": assembly,
            },
            fn,
            scope=scope,
            record_id=id,
            capture=lambda payload: captured.setdefault("payload", payload),
            attribution=("europepmc",) if source == "openalex" and id.upper().startswith("PMC") else (),
        )
        actions = []
        continuation = (
            captured.get("payload", {}).get("_interpro_continuation")
            if isinstance(captured.get("payload"), dict)
            else None
        )
        if entity == Entity.variant and relation == "structure" and continuation:
            from .native.interpro import Continuation as InterProContinuation

            request = GetRequest(
                entity="protein", id=continuation["protein_identity"]["accession"], sections=["domains"]
            )
            actions = await InterProContinuation(self.runtime).issue(
                continuation, request, scope=scope, state={"scanned": 0, "seen": []}
            )
            section.warnings.extend(continuation.get("warnings", []))
            section.data["interpro_coverage"]["continuation_status"] = continuation["coverage"].get(
                "continuation_status"
            )
        return ResearchResult(
            entity=entity,
            outcome=section.outcome,
            sections={relation: section},
            next_actions=actions,
            provenance=[proof] if proof else [],
            query={
                "entity": entity.value,
                "id": id,
                "relation": relation,
                "species": species,
                "assembly": assembly,
            },
        )

    async def _article_authors(self, id, source):
        return (await self.providers.literature.get(id, source)).get("author_records", [])

    async def _variant_relation(self, id, relation, limit, assembly=None):
        record = await self.providers.variants.resolve(id, assembly)
        if record.get("resolution") != "exact":
            raise ResearchError(
                "ambiguous_identifier", "Select an exact variant before acquiring related evidence."
            )
        if relation == "structure":
            return await self.providers.variant_structure(record)
        from .native.variants import protein_change

        identity = record.get("identity", {})
        if not isinstance(identity, dict) or not identity.get("gene") or not identity.get("change"):
            raise ResearchError(
                "unresolved_identity", "Variant literature requires one gene and protein change."
            )
        query = identity["gene"] + " " + identity["change"]
        rows = await self.providers.literature.search_source("pubmed", query, {}, limit)
        for row in rows:
            text = (row.get("title") or "") + " " + (row.get("abstract") or "")
            gene_present = bool(
                re.search(
                    r"(?<![A-Za-z0-9])" + re.escape(identity["gene"]) + r"(?![A-Za-z0-9])",
                    text,
                    re.IGNORECASE,
                )
            )
            changes = [
                protein_change(m)
                for m in re.findall(r"(?:p\.)?(?:[A-Z][a-z]{2}|[A-Z])[0-9]+(?:[A-Z][a-z]{2}|[A-Z*])", text)
            ]
            row["identity_verification"] = (
                "co_mentioned_in_title_abstract"
                if gene_present and identity["change"] in changes
                else "unconfirmed"
            )
            row["identity_warning"] = (
                "Co-mention is not proof that a statement concerns this allele; inspect annotated context/full text."
            )
        return {
            "identity": identity,
            "records": rows,
            "verification_scope": "title_and_abstract",
            "sources": ["pubmed", "myvariant"],
        }

    async def research(
        self,
        workflow: str,
        focus: str,
        *,
        scope: str,
        sections: list[str] | None = None,
        section_parameters: dict | None = None,
        species: int = 9606,
        assembly: str | None = None,
        _plan_only=False,
    ):
        if workflow not in WORKFLOWS:
            raise ResearchError("unknown_workflow", "Inspect capabilities for supported research workflows.")
        entity, defaults = WORKFLOWS[workflow]
        requested_focus = focus
        if assembly and entity != "variant":
            raise ResearchError("invalid_assembly", "Assembly applies to variant coordinates only.")
        if species != 9606 and entity not in {"gene", "protein"}:
            raise ResearchError("unsupported_species", "This workflow has no nonhuman species scope.")
        if entity == "pathway" and not re.fullmatch(r"R-[A-Z]{3}-[1-9][0-9]*", focus):
            self._search_plan(SearchRequest(entity="pathway", query=focus))
            if set(sections or defaults) - {"record", "genes", "events"}:
                raise ResearchError("unknown_section", "Pathway sections: record, genes, events.")
            if section_parameters:
                raise ResearchError(
                    "unsupported_section_parameters", "Pathway sections have no section arguments."
                )
            if _plan_only:
                return None
            candidates = await self.search(
                SearchRequest(entity="pathway", query=focus, limit=10, output="full"), scope=scope
            )
            exact = [
                r
                for r in candidates.records
                if str(r.get("name") or r.get("displayName") or "").casefold() == focus.casefold()
            ]
            if (
                len(exact) != 1
                or candidates.next_cursor
                or candidates.truncated
                or candidates.outcome != "data"
            ):
                candidates.outcome = "ambiguous" if candidates.records else candidates.outcome
                candidates.query["workflow"] = workflow
                candidates.warnings.append(
                    "Select one exact Reactome stable ID before building a pathway review."
                )
                return candidates
            focus = exact[0].get("stId") or exact[0].get("id")
        if _plan_only:
            if workflow not in {
                "literature_review",
                "patent_landscape",
                "study_summary",
                "negative_evidence",
            }:
                await self.get(
                    GetRequest(
                        entity=entity,
                        id=focus,
                        sections=sections if sections is not None else defaults,
                        section_parameters=section_parameters or {},
                        species=species,
                        assembly=assembly,
                    ),
                    scope=scope,
                    _plan_only=True,
                )
            return None
        if workflow == "negative_evidence":
            result = await self.search(SearchRequest(entity="article", query=focus, limit=10), scope=scope)
            result.query.update(
                workflow=workflow, coverage="One bounded federated literature search", universal_absence=False
            )
            result.warnings.append(
                "No matching records is scoped to this query, sources and retrieval time; it does not establish universal absence."
            )
            return result
        if workflow in {"literature_review", "patent_landscape", "study_summary"}:
            return await self.search(SearchRequest(entity=entity, query=focus), scope=scope)
        request = GetRequest(
            entity=entity,
            id=focus,
            sections=sections if sections is not None else defaults,
            section_parameters=section_parameters or {},
            species=species,
            assembly=assembly,
        )
        await self.get(request, scope=scope, _plan_only=True)
        identity, identity_proof = None, None
        if entity == "gene":
            identity_section, identity_proof = await self._safe(
                "mygene",
                "gene_identity",
                {"id": focus, "species": species},
                lambda: self.providers.gene(focus, species),
                scope=scope,
                record_id=focus,
            )
            if identity_section.outcome != "data":
                return ResearchResult(
                    entity=entity,
                    outcome=identity_section.outcome,
                    sections={"identity": identity_section},
                    query={"workflow": workflow, "focus": focus, "species": species},
                )
            identity = identity_section.data["qualified_identity"]
        result = await self.get(request, scope=scope)
        if entity == "pathway":
            pathway_identity, pathway_proof = await self._safe(
                "reactome",
                "get:record",
                {"entity": "pathway", "id": focus},
                lambda: self.providers.record("pathway", focus),
                scope=scope,
                record_id=focus,
            )
            if pathway_proof:
                result.provenance.append(pathway_proof)
            if pathway_identity.outcome == "data":
                data = pathway_identity.data
                basic = data.get("basic", data)
                paper_focus = basic.get("displayName") or requested_focus
            else:
                paper_focus = requested_focus
        else:
            paper_focus = focus
        if identity_proof and identity_proof.evidence_id not in {p.evidence_id for p in result.provenance}:
            result.provenance.append(identity_proof)
        if identity:
            result.query["qualified_identity"] = identity
        try:
            disease_identity = None
            if entity == "disease":
                disease_section, disease_proof = await self._disease_discovery(focus, scope=scope)
                if disease_proof:
                    result.provenance.append(disease_proof)
                if disease_section.outcome != "data":
                    raise ResearchError(
                        "unresolved_identity",
                        "Disease literature discovery requires an exact preferred label.",
                    )
                disease_identity = disease_section.data
                paper_focus = disease_identity["label"]
                result.query["qualified_identity"] = disease_identity
            paper_query, taxon_proof = (
                await self._gene_discovery_text(identity, scope=scope) if identity else (paper_focus, None)
            )
            if assembly:
                paper_query += ' AND "' + assembly.upper().replace("GRCH", "GRCh") + '"'
            papers = await self.search(
                SearchRequest(
                    entity="article",
                    query=paper_query,
                    limit=5,
                    output="full" if entity == "pathway" else "summary",
                ),
                scope=scope,
            )
            if entity == "pathway":
                from .native.literature import focus_matches

                acquired = (papers._omitted_evidence or {}).get("records", papers.records)
                before = len(acquired)
                papers.records = [r for r in acquired if focus_matches(r, paper_focus)]
                # Rebuild record recovery from the scientifically filtered window.
                # The search envelope may have omitted rows before this predicate.
                papers._omitted_evidence = None
                omissions = papers.query.get("output_omissions", {})
                for key in ("records_before_budget", "records_removed", "scope", "recovery"):
                    omissions.pop(key, None)
                papers.query["relevance_filter"] = {
                    "policy": "Exact pathway phrase in title, or phrase plus mechanistic context in abstract",
                    "filtered_weak_comentions": before - len(papers.records),
                    "scope": "Fetched candidate window only; no exhaustive absence claim.",
                }
                if not papers.records and before:
                    papers.outcome = "partial"
                    papers.warnings.append(
                        "All fetched literature candidates were weak co-mentions; refine the query or continue the candidate search."
                    )
                from .summaries import summarize_records

                original = papers.records
                papers.records, cut = summarize_records(original)
                if cut:
                    papers.truncated = True
                    papers._omitted_evidence = {"records": original}
                    papers.query.setdefault("output_omissions", {})["summary"] = {
                        "record_count": len(papers.records),
                        "recovery": "composed_recovery",
                        "interpretation": "Bounded excerpts; omitted fields and items are not absence.",
                    }
            papers.query["relationship_evidence"] = "discovery"
            papers.query["scientific_scope"] = {
                "entity": entity,
                "id": focus,
                "species": species,
                "assembly": assembly,
            }
            if identity:
                papers.query["qualified_identity"] = identity
                papers.query["execution"]["identity_dependencies"] = [
                    "mygene",
                    *(["ncbi"] if species != 9606 else []),
                ]
            if disease_identity:
                papers.query["qualified_identity"] = disease_identity
                papers.query["execution"]["identity_dependencies"] = ["mydisease"]
            papers.warnings.append(
                "Name-based co-mention search is discovery, not proof of a biological relationship. Verify identity, species and experimental context in each record."
            )
            if taxon_proof:
                papers.provenance.append(taxon_proof)
            result.sections["literature"] = await compose_evidence(
                papers, store=self.evidence, scope=scope, operation="literature_search"
            )
            result.provenance.extend(papers.provenance)
            result.truncated |= papers.truncated
        except (ResearchError, TimeoutError):
            result.sections["literature"] = Section(
                outcome="unavailable", warnings=["Literature retrieval failed; absence cannot be inferred."]
            )
            if result.outcome != "error":
                result.outcome = "partial"
        if workflow in {"variant_evidence", "drug_review", "disease_landscape"}:
            try:
                related = await self.relate(
                    Entity(entity),
                    focus,
                    "trials" if entity != "variant" else "articles",
                    scope=scope,
                    limit=5,
                    species=species,
                    assembly=assembly,
                )
                result.sections[
                    "related_articles" if entity == "variant" else "related_trials"
                ] = await compose_evidence(related, store=self.evidence, scope=scope, operation="relate")
                result.provenance.extend(related.provenance)
                result.truncated |= related.truncated
            except (ResearchError, TimeoutError):
                result.sections["related_evidence"] = Section(
                    outcome="unavailable", warnings=["Related retrieval failed; absence cannot be inferred."]
                )
        result.query["workflow"] = workflow
        if workflow == "model_input_bundle":
            result.warnings.append(
                "Map units and assumptions in a Ubi modeling preview before submitting a run."
            )
        result.outcome = self._outcome(result.sections.values())
        return ResearchResult.model_validate(result.model_dump())

    def source_availability(self, source):
        import os

        from .source_licensing import availability

        released, reason = availability(source)
        if not released:
            return False, reason

        if source in set(PROVIDERS) | self.extensions.sources:
            return self.adapters.availability(source)
        required = {"nci": "NCI_API_KEY", "oncokb": "ONCOKB_TOKEN", "disgenet": "DISGENET_API_KEY"}
        if source in required and not os.getenv(required[source]):
            return False, "Required provider credentials are not configured."
        if source in {"oncokb", "disgenet"} and source not in os.getenv("UBI_LICENSED_SOURCES", "").split(
            ","
        ):
            return False, "Licensed source access is not configured."
        known = {s for sources in SEARCH_SOURCES.values() for s in sources} | {
            s for sections in SECTIONS.values() for s in sections.values()
        }
        return (source in known, None if source in known else "Unknown source")

    async def capabilities(self, *, source=None, entity=None):
        from .source_licensing import operation_allowed, review
        from .source_policy import source_names

        if source and source not in source_names():
            raise ResearchError("unsupported_source", "Choose a source listed by capabilities.")
        if (source == "study" or (source is None and entity is None)) and self.source_availability("study")[
            0
        ]:
            await self.extensions.initialize_studies()
        if source:
            routes = []
            for kind, sources in SEARCH_SOURCES.items():
                if source in sources:
                    routes.append({"tool": "search", "entity": kind, "source": source})
            for kind, owner in RECORD_OWNER.items():
                if owner == source:
                    routes.append({"tool": "get", "entity": kind, "sections": ["record"]})
            for kind, sections in SECTIONS.items():
                names = [n for n, s in sections.items() if s == source]
                if names:
                    routes.append({"tool": "get", "entity": kind, "sections": names})
            for kind, names in SECTION_ALTERNATIVES.items():
                for name, choices in names.items():
                    if source in choices and SECTIONS[kind][name] != source:
                        routes.append(
                            {"tool": "get", "entity": kind, "sections": [name], "sources": [source]}
                        )
            if source == "openalex":
                routes.extend([{ "tool": "relate", "entity": "author", "relation": "articles", "id_format": "openalex:A…"},
                               {"tool": "relate", "entity": "article", "relation": "recommendations", "id_format": "PMID, PMCID, DOI or openalex:W…"}])
            if source == "orcid":
                routes.append({"tool": "get", "entity": "author", "id_format": "orcid:<ORCID>"})
            if source == "europepmc":
                routes.extend({"tool": "relate", "entity": "article", "relation": relation,
                               "id_format": "PMID, PMCID or DOI"} for relation in ("citations", "references"))
            ready, reason = self.source_availability(source)
            if source == "openfda":
                routes = [
                    {**r, "sections": [s for s in r["sections"] if operation_allowed(source, "get:" + s)]}
                    if "sections" in r
                    else r
                    for r in routes
                ]
                routes = [r for r in routes if "sections" not in r or r["sections"]]
            ops = await self.adapters.catalog(source) if ready and source in ADVANCED else []
            if source == "openfda":
                from copy import deepcopy

                ops = deepcopy(ops)
                for op in ops:
                    if op["name"] == "search_recalls":
                        op["input_schema"]["properties"]["recall_type"]["enum"] = ["drug"]
            if source == "ncbi":
                import copy

                ops = copy.deepcopy(ops)
                for operation in ops:
                    if operation["name"] == "search_ncbi_data":
                        operation["input_schema"]["properties"]["data_type"]["enum"] = [
                            "genomes",
                            "assemblies",
                            "taxonomy",
                            "viruses",
                            "features",
                        ]
            return {
                "source": source,
                "configured": ready,
                "health": "not_probed",
                "reason": reason,
                "license_review": review(source),
                "canonical_routes": routes,
                **(
                    {
                        "installed_studies": [r for r in self.extensions.studies().values()],
                        "study_guidance": "ubi_synthetic is an invented demonstration. Install a verified public release for biological cohort analysis.",
                    }
                    if source == "study" and ready
                    else {}
                ),
                "operations": [
                    o
                    for o in ops
                    if o["name"] in ADVANCED.get(source, set()) and operation_allowed(source, o["name"])
                ],
            }
        if entity:
            entity_sources = (
                set(SEARCH_SOURCES.get(entity.value, ()))
                | set(SECTIONS.get(entity.value, {}).values())
                | {
                    source
                    for choices in SECTION_ALTERNATIVES.get(entity.value, {}).values()
                    for source in choices
                }
            )
            if entity.value == "gene":
                entity_sources.add("mygene")
            if entity.value == "article":
                entity_sources.add("openalex")
            return {
                "entity": entity.value,
                "search_supported": bool(SEARCH_SOURCES.get(entity.value)),
                "search_sources": SEARCH_SOURCES.get(entity.value, []),
                "get_supported": entity.value in RECORD_OWNER,
                "record_owner": RECORD_OWNER.get(entity.value),
                "sections": SECTIONS.get(entity.value, {}),
                "section_dependencies": {
                    name: sorted({owner} | SECTION_DEPENDENCIES.get((entity.value, name), set()))
                    for name, owner in SECTIONS.get(entity.value, {}).items()
                },
                "section_guidance": {
                    "annotations": "Use go for gene ontology annotations; article annotations use PubTator."
                }
                if entity == Entity.gene
                else {},
                "resolution_policy": "One exact species-qualified symbol/ID resolves; aliases remain ambiguous candidates. Provider scores rank discovery only.",
                "conditional_identity_dependencies": {
                    "eve": {
                        "uniprot": "Exact reviewed canonical human protein; no genomic mapping inferred."
                    },
                    "predictions": {
                        "uniprot": "Gene/protein-change input: one exact reviewed canonical human sequence.",
                        "ensembl": "Genomic, rsID or accession HGVS input: keep each returned allele/transcript context.",
                    },
                    "civic": {
                        "myvariant": "Non-protein identifiers must resolve to one allele and one gene/protein change."
                    }
                }
                if entity == Entity.variant
                else {},
                "section_source_choices": SECTION_ALTERNATIVES.get(entity.value, {}),
                "relations": RELATIONS.get(entity.value, []),
                "source_permissions": {source: review(source) for source in sorted(entity_sources)},
                "search_filters": sorted(SEARCH_FILTERS.get(entity.value, set())),
                "pagination": {
                    "cursor_ttl_seconds": 3600,
                    "max_source_windows_per_request": 3,
                    "max_source_offset": 1000,
                    "max_source_pages": 500,
                    "overflow": "retained with original evidence",
                    "coverage": "accessible provider windows; inspect source_pagination and warnings",
                    "sort_scope": "local and federated reranking covers fetched windows",
                },
                **(
                    {
                        "article_sort_sources": {
                            "relevance": ["pubmed", "europepmc", "pubtator", "litsense2"],
                            "date": ["pubmed", "europepmc"],
                            "citations": ["europepmc"],
                        }
                    }
                    if entity == Entity.article
                    else {}
                ),
                "schemas": {
                    "search": SearchRequest.model_json_schema(),
                    "get": GetRequest.model_json_schema(),
                },
                "source_policy": "Explicit source selection never silently falls back. Get sources restricts section owners and identity dependencies. Explicit sections omit the default record.",
            }
        return {
            "product": "biomedmcp",
            "implementation": REVISION,
            "entities": [e.value for e in Entity],
            "workflows": list(WORKFLOWS),
            "relations": RELATIONS,
            "outcome_policy": "empty means a successful bounded query with zero records; error/unavailable mean acquisition failure and never establish absence.",
            "output_modes": {
                "summary": "Default bounded record excerpts with evidence recovery",
                "full": "Retained fields within the output byte budget",
            },
            "sources": [
                {
                    "id": source,
                    "configured": self.source_availability(source)[0],
                    "reason": self.source_availability(source)[1],
                    "license_review": review(source),
                    "health": "not_probed",
                }
                for source in sorted(
                    (
                        set(PROVIDERS)
                        | self.extensions.sources
                        | {s for values in SEARCH_SOURCES.values() for s in values}
                        | {s for values in SECTIONS.values() for s in values.values()}
                    )
                    - {"article-content"}
                )
            ],
            "routing": "search/get own entity acquisition, relate owns graph traversal, research composes these, batch repeats them. query_source exposes only distinct advanced operations. GenBank/GEO/SRA share ncbi-records with an explicit database selector. No provider servers are mounted or separately exposed.",
        }
