"""Typed NCBI, patent, enrichment and study operations.

NCBI and EPO clients validate accessions, detect application errors, bound SRA
batches and sequence regions, and preserve patent range/identity semantics. No shell, SQL or local paths are inputs.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import transport as httpx
from .contracts import FulltextWindow, StrictModel
from .errors import ResearchError

DATABASES = {"geo": "gds", "sra": "sra", "genbank": "nuccore"}
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class NcbiSearch(StrictModel):
    database: Literal["geo", "sra", "genbank"]
    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0, le=1000)


class NcbiGet(StrictModel):
    database: Literal["geo", "sra", "genbank"]
    accession: str = Field(min_length=3, max_length=64)
    sequence: bool = False
    start: int | None = Field(default=None, ge=1)
    stop: int | None = Field(default=None, ge=1)
    strand: Literal[1, 2] = 1

    @model_validator(mode="after")
    def identity(self):
        patterns = {
            "geo": r"G(?:SE|SM|PL|DS)\d+",
            "sra": r"(?:SR[PRSX]|ER[PRSX]|DR[PRSX])\d+",
            "genbank": r"[A-Z]{1,6}_?\d+(?:\.\d+)?",
        }
        self.accession = self.accession.upper()
        if not re.fullmatch(patterns[self.database], self.accession):
            raise ValueError("Unsupported accession format for this database")
        if self.sequence or self.start is not None or self.stop is not None:
            if self.database != "genbank" or not self.sequence:
                raise ValueError("Sequence regions require database=genbank and sequence=true")
            if (
                self.start is None
                or self.stop is None
                or self.stop < self.start
                or self.stop - self.start >= 10000
            ):
                raise ValueError("Request an explicit sequence region of at most 10,000 bases")
        return self


class NcbiLinks(StrictModel):
    database: Literal["geo", "sra", "genbank"]
    uid: str = Field(pattern=r"^\d+$", max_length=32)
    destination: Literal["pubmed", "sra", "gds", "bioproject", "biosample"]


class AuthorRecord(StrictModel):
    orcid: str = Field(pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class ArticleContent(FulltextWindow):
    id: str = Field(min_length=1, max_length=256)
    offset: int = Field(default=0, ge=0, le=1000)
    limit: int = Field(default=25, ge=1, le=25)

    @model_validator(mode="after")
    def bounds(self):
        if self.id.startswith("-"):
            raise ValueError("Use a stable article ID")
        return self


class PatentSearch(StrictModel):
    query: str = Field(min_length=1, max_length=256)
    assignee: str | None = Field(default=None, max_length=128)
    inventor: str | None = Field(default=None, max_length=128)
    cpc: str | None = Field(default=None, pattern=r"^[A-HY]\d{2}[A-Z]?(?:\d+/\d+)?$")
    limit: int = Field(default=10, ge=1, le=25)
    offset: int = Field(default=0, ge=0, le=1975)


class PatentGet(StrictModel):
    publication: str = Field(pattern=r"^[A-Z]{2}(?:RE|PP|H)?\d+[A-Z]?\d?$")
    section: Literal["biblio", "family", "claims", "citations"] = "biblio"


class Enrichment(StrictModel):
    genes: list[str] = Field(min_length=1, max_length=100)
    organism: Literal["hsapiens", "mmusculus", "rnorvegicus"] = "hsapiens"
    background: list[str] | None = Field(default=None, min_length=1, max_length=1000)
    sources: list[Literal["GO:BP", "GO:MF", "GO:CC", "REAC", "WP", "HP"]] = Field(
        default_factory=lambda: ["GO:BP", "REAC"], min_length=1, max_length=6
    )
    limit: int = Field(default=10, ge=1, le=25)
    significance_threshold: float = Field(default=0.05, gt=0, le=0.2)

    @model_validator(mode="after")
    def symbols(self):
        if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", x) for x in self.genes + (self.background or [])):
            raise ValueError("Use gene identifiers, not an expression or file path")
        return self


class StudyRequest(StrictModel):
    chart: bool = False
    study: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    gene: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,40}$")
    target: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,40}$")
    type: Literal["mutations", "cna", "expression", "sv"] = "mutations"
    endpoint: Literal["os", "dfs", "pfs", "dss"] = "os"
    genes: list[str] = Field(default_factory=list, max_length=10)
    mutated: list[str] = Field(default_factory=list, max_length=10)
    amplified: list[str] = Field(default_factory=list, max_length=10)
    deleted: list[str] = Field(default_factory=list, max_length=10)
    cancer_type: list[str] = Field(default_factory=list, max_length=5)
    expression_above: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(
        default_factory=dict, max_length=10
    )
    expression_below: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(
        default_factory=dict, max_length=10
    )
    limit: int = Field(default=10, ge=1, le=25)

    @model_validator(mode="after")
    def safe_values(self):
        for value in (
            self.genes
            + self.mutated
            + self.amplified
            + self.deleted
            + list(self.expression_above)
            + list(self.expression_below)
        ):
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value):
                raise ValueError("Invalid gene symbol")
        if any(len(t) > 120 or t.startswith("-") for t in self.cancer_type):
            raise ValueError("Invalid cancer type")
        return self


class Empty(StrictModel):
    pass


MODELS = {
    "ncbi-records": {"search": NcbiSearch, "get": NcbiGet, "links": NcbiLinks},
    "orcid": {"get": AuthorRecord},
    "article-content": {"read": ArticleContent},
    "patents": {"search": PatentSearch, "get": PatentGet},
    "enrichment": {"gene_set": Enrichment},
    "study": {
        op: StudyRequest
        for op in ("query", "cohort", "survival", "compare", "co_occurrence", "filter", "top_mutated")
    },
}
MODELS["study"]["list"] = Empty


class NormalizeVariant(StrictModel):
    hgvs: str = Field(min_length=5, max_length=350)


class VariantAssertions(StrictModel):
    caid: str = Field(pattern=r"^CA\d+$")


class GeneSpecifications(StrictModel):
    gene: str = Field(pattern=r"^[A-Z0-9_.-]{1,40}$")


MODELS["clingen"] = {
    "normalize": NormalizeVariant,
    "assertions": VariantAssertions,
    "linked_data": VariantAssertions,
    "specifications": GeneSpecifications,
}


class ExtendedSources:
    def __init__(self, http=None):
        from .native.literature import Literature
        from .native.variants import Variants

        self.literature = Literature(http)
        self.variants = Variants(http)
        self._ops_token = None
        self._ops_expires = 0
        self._ops_lock = asyncio.Lock()
        self._study_lock = asyncio.Lock()
        self._studies = None
        self._study_snapshot = ContextVar("verified_study_snapshot", default=None)

    @property
    def sources(self):
        return set(MODELS)

    def studies(self):
        registry = self._study_snapshot.get()
        if registry is None:
            registry = self._studies
        if registry is None:
            raise ResearchError(
                "study_not_ready", "Study release verification has not completed.", retryable=True
            )
        return registry

    @contextmanager
    def study_snapshot(self, registry):
        """Bind acquisition and its cache identity to one verified release view."""
        token = self._study_snapshot.set(registry)
        try:
            yield
        finally:
            self._study_snapshot.reset(token)

    async def initialize_studies(self, *, recheck=False):
        from .studies import load_studies, study_registry
        from .study_workers import study_workers

        if not recheck and (registry := self._study_snapshot.get()) is not None:
            return registry
        async with self._study_lock:
            try:
                registry = await study_workers.run(load_studies if recheck else study_registry)
            except asyncio.CancelledError:
                # A cancelled refresh has not disproved the previous snapshot.
                # Initial cancellation remains unready; subsequent acquisitions
                # still verify before reading the installed release.
                raise
            except Exception:
                self._studies = None
                raise
            self._studies = registry
        return registry

    def availability(self, source):
        from .source_licensing import availability

        released, reason = availability(source)
        if not released:
            return False, reason
        if source == "patents" and not all(
            os.getenv(k) for k in ("EPO_OPS_CONSUMER_KEY", "EPO_OPS_CONSUMER_SECRET")
        ):
            return False, "EPO OPS credentials and qualified account terms are required."
        if source == "study" and not (
            self._studies
            if self._studies is not None
            else (os.getenv("UBI_PUBLIC_STUDY_DIR") and os.getenv("UBI_PUBLIC_STUDY_MANIFEST"))
            or (
                not os.getenv("UBI_PUBLIC_STUDY_DIR")
                and not os.getenv("UBI_PUBLIC_STUDY_MANIFEST")
                and (Path(__file__).parent / "data/demo/manifest.json").is_file()
            )
        ):
            return False, "No checksummed public study release is installed."
        return source in self.sources, None

    def catalog(self, source):
        return [
            {
                "name": name,
                "input_schema": model.model_json_schema(),
                "description": f"Typed {source} {name} operation.",
            }
            for name, model in MODELS.get(source, {}).items()
        ]

    def validate(self, source, operation, params):
        available, reason = self.availability(source)
        if not available:
            raise ResearchError("source_unavailable", reason or "Unknown source")
        model = MODELS.get(source, {}).get(operation)
        if model is None:
            raise ResearchError("unknown_operation", "Inspect capabilities for source operations.")
        request = model.model_validate(params)
        if source == "study" and operation != "list":
            if request.study not in self.studies():
                raise ResearchError("study_unavailable", "The study is not an installed public release.")
            if operation in {"query", "cohort", "survival", "compare"} and not request.gene:
                raise ResearchError("invalid_parameters", "This study operation requires gene.")
            if operation == "compare" and (
                not request.target or request.type not in {"expression", "mutations"}
            ):
                raise ResearchError(
                    "invalid_parameters", "Compare requires target and type expression or mutations."
                )
            fields = {
                "query": {"gene", "type"},
                "cohort": {"gene"},
                "survival": {"gene", "endpoint"},
                "compare": {"gene", "target", "type"},
                "co_occurrence": {"genes"},
                "top_mutated": {"limit"},
                "filter": {
                    "mutated",
                    "amplified",
                    "deleted",
                    "cancer_type",
                    "expression_above",
                    "expression_below",
                },
            }[operation]
            irrelevant = request.model_fields_set - fields - {"study", "chart"}
            if irrelevant:
                raise ResearchError(
                    "invalid_parameters", "Unused study parameters: " + ", ".join(sorted(irrelevant))
                )
            if operation == "co_occurrence" and len(request.genes) < 2:
                raise ResearchError("invalid_parameters", "Co-occurrence requires 2–10 genes.")
        return request

    async def call(self, source, operation, params):
        if source == "study" and self._study_snapshot.get() is None:
            registry = await self.initialize_studies()
            with self.study_snapshot(registry):
                return await self.call(source, operation, params)
        request = self.validate(source, operation, params)
        try:
            if source == "clingen":
                return await getattr(self.variants, operation)(**request.model_dump())
            if source == "ncbi-records":
                return await self.ncbi(operation, request)
            if source == "article-content":
                return await self.literature.fulltext(
                    request.id,
                    view=request.view,
                    start=request.start,
                    end=request.end,
                    limit=request.limit,
                    offset=request.offset,
                )
            if source == "orcid":
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"https://pub.orcid.org/v3.0/{request.orcid}/record",
                        headers={"Accept": "application/json"},
                    )
                    response.raise_for_status()
                    return {
                        "provider": "ORCID",
                        "orcid": request.orcid,
                        "url": f"https://orcid.org/{request.orcid}",
                        "record": response.json(),
                        "identity_policy": "Provider-qualified identity; equal names are not merged.",
                    }
            if source == "patents":
                return await self.patent(operation, request)
            if source == "enrichment":
                return await self.enrich(request)
            if source == "study":
                return await self.study(operation, request)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ResearchError(
                "source_unavailable", f"{source} returned an unavailable or invalid response.", retryable=True
            ) from exc

    async def eutils(self, endpoint, params, *, xml=False):
        return await self.literature.eutils(endpoint, params, xml=xml)

    async def ncbi(self, operation, request):
        db = DATABASES[request.database]
        if operation == "links":
            result = await self.eutils(
                "elink", {"dbfrom": db, "db": request.destination, "id": request.uid, "retmode": "json"}
            )
            return {
                "source": "NCBI E-utilities",
                "uid": request.uid,
                "database": db,
                "destination": request.destination,
                "linksets": result.get("linksets", []),
            }
        if operation == "search":
            search = await self.eutils(
                "esearch",
                {
                    "db": db,
                    "term": request.query,
                    "retmax": request.limit,
                    "retstart": request.offset,
                    "retmode": "json",
                },
            )
            ids = search["esearchresult"].get("idlist", [])
            total = int(search["esearchresult"].get("count", 0))
        else:
            search = await self.eutils(
                "esearch",
                {"db": db, "term": request.accession + "[Accession]", "retmax": 10, "retmode": "json"},
            )
            ids = search["esearchresult"].get("idlist", [])
            total = int(search["esearchresult"].get("count", 0))
        if not ids:
            return {"records": [], "total": total, "database": db, "source": "NCBI E-utilities"}
        if request.database == "sra":
            records = []
            for offset in range(0, len(ids), 5):
                root = await self.eutils(
                    "efetch", {"db": "sra", "id": ",".join(ids[offset : offset + 5])}, xml=True
                )
                for package in root.findall(".//EXPERIMENT_PACKAGE"):
                    experiment = package.find("EXPERIMENT")
                    study = package.find("STUDY")
                    sample = package.find("SAMPLE")
                    records.append(
                        {
                            "experiment": experiment.get("accession") if experiment is not None else None,
                            "study": study.get("accession") if study is not None else None,
                            "sample": sample.get("accession") if sample is not None else None,
                            "title": package.findtext(".//EXPERIMENT/TITLE"),
                            "organism": package.findtext(".//SCIENTIFIC_NAME"),
                            "library_strategy": package.findtext(".//LIBRARY_STRATEGY"),
                            "bioproject": [
                                x.text
                                for x in package.findall(".//EXTERNAL_ID")
                                if x.get("namespace") == "BioProject"
                            ],
                            "runs": [dict(x.attrib) for x in package.findall(".//RUN")[:25]],
                        }
                    )
            if operation == "get" and re.match(r"[SED]RR", request.accession):
                records = [
                    {**r, "runs": [run for run in r["runs"] if run.get("accession") == request.accession]}
                    for r in records
                ]
                records = [r for r in records if r["runs"]]
            return {
                "records": records,
                "total": total,
                "database": db,
                "source": "NCBI SRA",
                "records_are_experiments": True,
            }
        result = await self.eutils("esummary", {"db": db, "id": ",".join(ids), "retmode": "json"})
        records = [{"uid": uid, **result["result"][uid]} for uid in result["result"].get("uids", [])]
        output = {"records": records, "total": total, "database": db, "source": "NCBI E-utilities"}
        if operation == "get" and request.sequence:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{EUTILS}/efetch.fcgi",
                    params={
                        "db": db,
                        "id": request.accession,
                        "rettype": "fasta",
                        "retmode": "text",
                        "seq_start": request.start,
                        "seq_stop": request.stop,
                        "strand": request.strand,
                    },
                )
                response.raise_for_status()
                if not response.text.startswith(">") or len(response.content) > 15000:
                    raise ResearchError("invalid_sequence", "NCBI did not return a bounded FASTA record.")
                output.update(
                    sequence=response.text,
                    region={"start": request.start, "stop": request.stop, "strand": request.strand},
                    accession=request.accession,
                    coordinate_system="1-based inclusive",
                )
        return output

    async def ops(self, path, params=None):
        async with self._ops_lock:
            if self._ops_expires < time.monotonic():
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://ops.epo.org/3.2/auth/accesstoken",
                        auth=(os.environ["EPO_OPS_CONSUMER_KEY"], os.environ["EPO_OPS_CONSUMER_SECRET"]),
                        data={"grant_type": "client_credentials"},
                    )
                    response.raise_for_status()
                    self._ops_token = response.json()["access_token"]
                    self._ops_expires = time.monotonic() + 900
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://ops.epo.org/3.2/rest-services" + path,
                params=params,
                headers={"Authorization": "Bearer " + self._ops_token, "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    async def patent(self, operation, request):
        if operation == "search":

            def term(value):
                return value.replace('"', "").replace("\\", "")

            clauses = [f'(ti="{term(request.query)}" OR ab="{term(request.query)}")']
            for key, field in (("pa", "assignee"), ("in", "inventor"), ("cpc", "cpc")):
                if getattr(request, field):
                    clauses.append(f'{key}="{term(getattr(request, field))}"')
            data = await self.ops(
                "/published-data/search/biblio",
                {
                    "q": " AND ".join(clauses),
                    "Range": f"{request.offset + 1}-{request.offset + request.limit}",
                },
            )
            envelope = data.get("ops:world-patent-data", {}).get("ops:biblio-search", {})
            docs = envelope.get("ops:search-result", {}).get("exchange-documents", {})
            if isinstance(docs, list):
                records = [x["exchange-document"] for x in docs if "exchange-document" in x]
            else:
                records = docs.get("exchange-document", [])
            if isinstance(records, dict):
                records = [records]
            total = int(envelope.get("@total-result-count", 0))
            if total > request.offset and not records:
                raise ResearchError(
                    "inconsistent_provider_page", "EPO reported matches but returned no documents."
                )
            return {
                "records": records,
                "total": total,
                "source": "EPO OPS",
                "identity": "publication, country and kind; family is a separate relation",
            }
        publication = re.match(r"[A-Z]{2}(?:RE|PP|H)?\d+", request.publication)[0]
        if request.section == "family":
            path = f"/family/publication/epodoc/{publication}"
        else:
            section = "biblio" if request.section == "citations" else request.section
            path = f"/published-data/publication/epodoc/{publication}/{section}"
        return {
            "source": "EPO OPS",
            "publication": request.publication,
            "section": request.section,
            "data": await self.ops(path),
            "coverage": "Provider coverage; missing citation records do not establish absence.",
        }

    async def enrich(self, request):
        query = {
            "organism": request.organism,
            "query": request.genes,
            "sources": request.sources,
            "user_threshold": request.significance_threshold,
            "significance_threshold_method": "g_SCS",
            "no_evidences": False,
            "all_results": False,
        }
        if request.background:
            query.update(background=request.background, domain_scope="custom")
        async with httpx.AsyncClient() as client:
            response = await client.post("https://biit.cs.ut.ee/gprofiler/api/gost/profile/", json=query)
            response.raise_for_status()
            data = response.json()
        return {
            "source": "g:Profiler",
            "records": data.get("result", [])[: request.limit],
            "truncated": len(data.get("result", [])) > request.limit,
            "metadata": data.get("meta", {}),
            "organism": request.organism,
            "input_genes": request.genes,
            "background": request.background or "provider annotated-gene background",
            "multiple_testing": "g:SCS",
            "threshold": request.significance_threshold,
            "interpretation": "Overrepresentation is association, not a causal or therapeutic conclusion.",
        }

    async def study(self, operation, request):
        from .native.study import StudyAnalytics

        if not hasattr(self, "_analytics"):
            self._analytics = StudyAnalytics(registry=self.studies())
        from .study_workers import study_workers

        data = await study_workers.run(self._analytics.run, operation, request, registry=self.studies())
        if getattr(request, "chart", False):
            from .charts import study_chart

            data["chart"] = study_chart(data)
        return data
