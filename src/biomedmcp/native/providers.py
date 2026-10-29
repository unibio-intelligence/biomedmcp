"""Native scientific acquisition. Retained Ubi clients are reused in-process.

External provider selectors are closed enums in the catalog. URLs never come
from tool arguments. A missing annotation is not synthesized from a name match.
"""

import asyncio
import os
import re

from ..errors import ResearchError
from ..pagination import numeric_total, page_payload
from ..trial_records import trial_record
from . import complexportal, gwas, interpro, monarch, ols
from .http import ProviderHTTP, segment
from .identity import gene_matches, qualify_gene
from .literature import PUBTATOR, Literature, article_id
from .shapes import collection, invalid_shape
from .string import ADDED_NODES, network
from .variants import Variants


def identifier(value, pattern, message):
    if not re.fullmatch(pattern, value):
        raise ResearchError("invalid_identifier", message)
    return value


async def once(context, key, call):
    if key not in context:
        context[key] = asyncio.create_task(call())
    return await asyncio.shield(context[key])


class NativeProviders:
    def __init__(self, adapters, http=None):
        self.adapters = adapters
        self.http = http or ProviderHTTP()
        self.literature = Literature(self.http)
        from .openalex import OpenAlex

        self.openalex = OpenAlex(self.http)
        self.variants = Variants(self.http)
        from .regulatory import Regulatory

        self.regulatory = Regulatory(self.http)

    async def adapter(self, source, operation, **params):
        return await self.adapters.call(source, operation, params)

    async def gene(self, value, species=9606):
        query = await self.adapter(
            "mygene",
            "query_genes",
            query=value,
            fields="symbol,name,taxid,entrezgene,ensembl,HGNC,alias,uniprot,go",
            species=str(species),
            limit=25,
        )
        rows = collection(query, ("hits",))
        exact = [r for r in rows if gene_matches(r, value, species)]
        if len(exact) != 1:
            if len(exact) > 1:
                raise ResearchError(
                    "ambiguous_identifier",
                    "Multiple exact gene records; choose a species-qualified stable identifier.",
                )
            raise ResearchError(
                "unresolved_identity",
                "No exact gene identity; use resolve to inspect candidates before joining sources.",
            )
        row = exact[0]
        identity = qualify_gene(row, species)
        ensembl = identity["ensembl_ids"]
        return {
            **row,
            "qualified_identity": identity,
            "ensembl_id": ensembl[0] if len(ensembl) == 1 else None,
            "url": f"https://mygene.info/v3/gene/{row.get('_id')}",
        }

    async def search(self, entity, source, query, filters, limit, offset, *, continuation=None):
        if entity == "gene":
            return await self.adapter(
                "mygene",
                "query_genes",
                query=query,
                fields="symbol,name,taxid,entrezgene,ensembl,alias",
                species=str(filters.get("species", 9606)),
                limit=limit,
                from_=offset,
            )
        if entity == "variant":
            return await self.variants.search(query, filters, limit, offset)
        if entity == "article":
            return await self.literature.search_source(
                source, query, filters, limit, offset, continuation=continuation, include_page=True
            )
        if entity == "protein":
            clauses = [f"({query})", f"organism_id:{filters.get('species', 9606)}"]
            if filters.get("reviewed") is not None:
                clauses.append("reviewed:" + str(filters["reviewed"]).lower())
            if filters.get("existence"):
                clauses.append(f"existence:{filters['existence']}")
            clauses += [f'cc_disease:"{x.replace(chr(34), "")}"' for x in filters.get("disease", [])]
            # Retained client now owns exact offset-aware HTTP pagination too.
            return await self.adapter(
                "uniprot",
                "query_proteins",
                query=" AND ".join(clauses),
                query_type="advanced",
                limit=limit,
                offset=offset,
                **({"page_cursor": continuation} if continuation else {}),
            )
        if entity == "drug" and source == "ema":
            return await self.regulatory.ema(query, limit=limit, offset=offset)
        if entity == "drug" and source == "who":
            return await self.regulatory.who(
                query,
                product_type=filters.get("product_type") or "finished_pharma",
                limit=limit,
                offset=offset,
            )
        if entity == "drug":
            return await self.adapter("mychem", "search_chemical", q=query, size=limit, from_=offset)
        if entity == "disease":
            return await self.adapter("mydisease", "search_disease", q=query, size=limit, from_=offset)
        if entity == "phenotype":
            return await ols.search(self.http, query, limit, offset)
        if entity == "trial":
            if source == "nci":
                key = os.getenv("NCI_API_KEY")
                if not key:
                    raise ResearchError("source_unavailable", "NCI trials require a configured NCI_API_KEY.")
                params = {"keyword": query, "size": limit, "from": offset}
                if filters.get("gene"):
                    params["biomarkers.name"] = filters["gene"]
                if filters.get("phase"):
                    params["phase.phase"] = filters["phase"]
                if filters.get("status"):
                    params["current_trial_status"] = filters["status"]
                if filters.get("disease"):
                    params["diseases.name"] = filters["disease"]
                if filters.get("drug"):
                    params["interventions.name"] = filters["drug"]
                data = await self.http.get(
                    "https://clinicaltrialsapi.cancer.gov/api/v2/trials",
                    params=params,
                    headers={"x-api-key": key},
                )
                rows = [trial_record(row, source) for row in collection(data, ("data",))]
                total = numeric_total(data.get("total"))
                exhausted = offset + len(rows) >= total if total is not None else len(rows) < limit
                return page_payload(
                    rows,
                    raw_count=len(rows),
                    total=total,
                    exhausted=exhausted,
                    next_offset=None if exhausted else offset + len(rows),
                    exhaustion_basis="total" if total is not None else "short_window",
                )
            args = {
                "query": " ".join([query, filters.get("gene", "")]).strip(),
                "page_size": limit,
                "count_total": True,
            }
            if filters.get("disease"):
                args["condition"] = " OR ".join(filters["disease"])
            if filters.get("drug"):
                args["intervention"] = " OR ".join(filters["drug"])
            for key in ["phase", "status"]:
                if filters.get(key):
                    args[key] = filters[key]
            if continuation:
                args["page_token"] = continuation
            elif offset:
                raise ResearchError(
                    "unsupported_cursor", "ClinicalTrials.gov requires its returned page token."
                )
            value = await self.adapter("clinical-trials", "search_studies", **args)
            rows = [trial_record(row, "clinical-trials") for row in collection(value, ("studies",))]
            token = value.get("nextPageToken")
            return page_payload(
                rows,
                raw_count=len(rows),
                exhausted=token is None,
                continuation=token,
                total=numeric_total(value.get("totalCount")),
            )
        if entity == "pathway":
            result = await self.adapter(
                "reactome", "search_pathways", query=query, limit=limit, offset=offset
            )
            payload = page_payload(
                result["records"],
                raw_count=result["raw_count"],
                total=result["total"],
                exhausted=result["exhausted"],
                next_offset=None if result["exhausted"] else offset + result["raw_count"],
                exhaustion_basis="total",
            )
            payload["source_input"] = {
                "endpoint": result["search_endpoint"],
                "search_index": result["search_index"],
                "offset": offset,
                "limit": limit,
                "species": result["species"],
                "type": "Pathway",
                "filters_forced": True,
                "source_response_sha256": result["source_response_sha256"],
            }
            payload["warnings"] = result["warnings"]
            return payload
        if entity == "patent":
            return await self.adapter(
                "surechembl", "query_patents", query=query, limit=limit, page=offset // limit + 1
            )
        if entity == "study":
            from ..study_metadata import study_metadata_record

            return {
                "studies": [
                    study_metadata_record(r)
                    for r in self.adapters.extensions.studies().values()
                    if query.casefold() in str(r).casefold()
                ]
            }
        if entity == "pgx":
            return await self.pgx(query, "interactions", filters, limit, offset, discovery=True)
        if entity == "gwas":
            return await self.gwas(query, filters, limit, offset, include_page=True)
        if entity == "author":
            if source == "openalex":
                return await self.openalex.search_authors(query, limit, offset)
            raise ResearchError("unsupported_source", "Author discovery uses OpenAlex.")
        if entity == "diagnostic":
            if source == "who-ivd":
                return await self.regulatory.who(
                    query,
                    product_type="ivd",
                    limit=limit,
                    offset=offset,
                    manufacturer=filters.get("manufacturer"),
                )
            if source == "fda-devices":
                return await self.fda(
                    "device/510k",
                    f'device_name:"{query}"',
                    limit,
                    offset,
                    manufacturer=filters.get("manufacturer"),
                )
            return await self.ncbi_summary("gtr", query, limit, offset)
        if entity == "adverse-event":
            return await self.fda("drug/event", f'patient.drug.medicinalproduct:"{query}"', limit, offset)
        raise ResearchError("unsupported_search", "Inspect capabilities for supported entity searches.")

    async def ncbi_summary(self, database, query, limit=10, offset=0):
        result = await self.literature.eutils(
            "esearch", {"db": database, "term": query, "retmode": "json", "retmax": limit, "retstart": offset}
        )
        ids = collection(result, ("esearchresult", "idlist"), element=str)
        if not ids:
            return []
        data = await self.literature.eutils(
            "esummary", {"db": database, "id": ",".join(ids), "retmode": "json"}
        )
        uids = collection(data, ("result", "uids"), element=str)
        if not set(ids).issubset(uids):
            invalid_shape()
        rows = [data["result"].get(uid) for uid in uids]
        if any(not isinstance(row, dict) or not row or row.get("error") for row in rows):
            invalid_shape()
        return rows

    async def fda(self, path, query, limit=10, offset=0, manufacturer=None):
        if manufacturer:
            query += f' AND applicant:"{manufacturer.replace(chr(34), "")}"'
        from openfda_mcp.server import fda_api_request

        value = await fda_api_request(path, search=query, limit=limit, skip=offset)
        return collection(value, ("results",))

    async def pgx(self, focus, section, filters=None, limit=10, offset=0, *, discovery=False):
        filters = filters or {}
        gene = filters.get("gene")
        drugs = filters.get("drug", [])
        untyped = discovery and not gene and not drugs
        if not gene and not drugs and not untyped:
            gene = focus
        if gene:
            identifier(gene, r"[A-Za-z0-9_.-]{1,40}", "Use a gene symbol for CPIC.")
        field = "genesymbol"
        value = (
            f"eq.{gene.upper()}"
            if gene
            else f"ilike.*{drugs[0].replace('*', '').replace('%', '')}*"
            if drugs
            else None
        )
        if drugs:
            field = "drugname"
        table = {
            "interactions": "pair_view",
            "recommendations": "recommendation_view",
            "frequencies": "population_frequency_view",
            "guidelines": "guideline_summary_view",
            "annotations": "pair_view",
        }[section]
        if section == "recommendations" and gene:
            field = f"lookupkey->>{gene.upper()}"
            value = "not.is.null"
        if section == "guidelines" and gene:
            field = "genes"
            value = f'cs.[{{"symbol":"{gene.upper()}"}}]'
        if section == "frequencies" and drugs:
            raise ResearchError("unsupported_filter", "Population frequencies require a gene, not a drug.")
        params = {field: value, "select": "*", "limit": limit, "offset": offset}
        if untyped:
            # PostgREST quoted literals keep punctuation inside the user's term
            # from becoming OR grammar. Do not guess that a drug name is a gene.
            term = focus.replace("*", "").replace("%", "").strip()
            if not term or any(ord(c) < 32 for c in term):
                raise ResearchError("invalid_parameters", "Use a nonempty CPIC gene or drug search term.")

            def quoted(text):
                return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

            params.pop(field)
            params["or"] = f"(genesymbol.eq.{quoted(term.upper())},drugname.ilike.{quoted('*' + term + '*')})"
        if discovery:
            params["order"] = "pairid.asc"
        if gene and drugs and section in {"interactions", "annotations"}:
            params["genesymbol"] = "eq." + gene.upper()
            params["drugname"] = "ilike.*" + drugs[0].replace("*", "").replace("%", "") + "*"
        if filters.get("cpic_level"):
            params["cpiclevel"] = "eq." + filters["cpic_level"]
        return collection(await self.http.get("https://api.cpicpgx.org/v1/" + table, params=params), ())

    async def gwas(self, focus, filters=None, limit=10, offset=0, *, include_page=False):
        filters = filters or {}
        params = gwas.query(focus, filters, limit, offset)
        data = await self.http.get(gwas.BASE, params=params)
        payload = gwas.window(data, params, filters.get("p_value"))
        return payload if include_page else payload["records"]

    @staticmethod
    def disease_identity(value, payload):
        row = payload.get("disease", payload) if isinstance(payload, dict) else None
        if not isinstance(row, dict) or row.get("_id") != value:
            raise ResearchError(
                "unresolved_identity", "Disease text discovery requires an exact disease record."
            )
        namespace = value.split(":", 1)[0]
        annotation, identity_field, label_field = {
            "MONDO": ("mondo", "mondo", "label"),
            "DOID": ("disease_ontology", "doid", "name"),
        }.get(namespace, (None, None, None))
        selected = row.get(annotation) if annotation else None
        if selected is not None:
            if not isinstance(selected, dict) or selected.get(identity_field) != value:
                raise ResearchError(
                    "unresolved_identity", "Disease annotation does not match the requested identity."
                )
            label = selected.get(label_field)
        else:
            label = row.get("name")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label) > 512
            or any(ord(c) < 32 for c in label)
        ):
            raise ResearchError(
                "unresolved_identity",
                "The exact disease record has no qualified preferred label for text discovery.",
            )
        return {"id": value, "label": label, "source": "mydisease"}

    async def record(self, entity, value, *, source=None, species=9606, assembly=None, context=None):
        context = context if context is not None else {}
        if entity == "gene":
            return await once(context, ("gene", value, species), lambda: self.gene(value, species))
        if entity == "variant":
            return await once(
                context, ("variant", value, assembly), lambda: self.variants.resolve(value, assembly)
            )
        if entity == "article":
            return await self.literature.get(value, source)
        if entity == "protein":
            identifier(
                value,
                r"(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2})(?:-\d+)?",
                "Use a UniProt accession; resolve names first.",
            )
            return await once(
                context,
                ("protein", value),
                lambda: self.adapter(
                    "uniprot",
                    "query_proteins",
                    query=value,
                    query_type="accession",
                    include_sequence=True,
                    include_features=True,
                    fields=[
                        "accession",
                        "id",
                        "protein_name",
                        "gene_names",
                        "organism_name",
                        "length",
                        "reviewed",
                        "xref_pdb",
                        "xref_alphafolddb",
                        "xref_refseq",
                    ],
                ),
            )
        if entity == "trial":
            identifier(value, r"NCT\d{8}", "Use a ClinicalTrials.gov NCT identifier.")
            result = await once(
                context,
                ("trial", value),
                lambda: self.adapter(
                    "clinical-trials",
                    "get_study_details",
                    nct_id=value,
                    include_full_protocol=True,
                    include_results=True,
                ),
            )
            record = trial_record(result, "clinical-trials")
            if {"namespace": "nct", "value": value} not in record["identities"]:
                invalid_shape()
            return record
        if entity == "drug" and source == "ema":
            return await self.regulatory.ema(value)
        if entity == "drug" and source == "who":
            return await self.regulatory.who(value)
        if entity == "drug":
            return await once(
                context,
                ("drug", value),
                lambda: self.adapter("mychem", "get_chemical_by_id", chemical_id=value, dotfield=False),
            )
        if entity == "disease":
            return await once(
                context,
                ("disease", value),
                lambda: self.adapter("mydisease", "get_disease_by_id", disease_id=value, dotfield=False),
            )
        if entity == "pathway":
            identifier(value, r"R-[A-Z]{3}-\d+", "Use a Reactome stable pathway ID.")
            return await self.adapter("reactome", "get_pathway_info", pathway_id=value, detail_level="basic")
        if entity == "pgx":
            return await self.pgx(value, "interactions")
        if entity == "gwas":
            identity = identifier(value, r"[1-9]\d*", "Use a positive GWAS association ID.")
            data = await self.http.get(gwas.BASE + "/" + segment(identity))
            result = gwas.record(data, requested_id=identity)
            if result["p_value_status"] == "conflicting_representations":
                result["section_outcomes"] = {"p_value_interpretation": {"outcome": "partial"}}
                result["warnings"] = [
                    "Conflicting p-value representations are preserved without selecting one."
                ]
            return result
        if entity == "phenotype":
            return await ols.record(self.http, identifier(value, r"HP:\d{7}", "Use an HPO term identifier."))
        if entity == "diagnostic":
            return await self.ncbi_summary(
                "gtr", identifier(value, r"(?:GTR)?\d+(?:\.\d+)?", "Use a GTR test accession.")
            )
        if entity == "adverse-event":
            return await self.fda(
                "drug/event",
                f'safetyreportid:"{identifier(value, r"[0-9]+", "Use a FAERS safety report ID.")}"',
                1,
            )
        if entity == "author":
            if source == "openalex":
                return await self.openalex.get_author(value)
            if value.startswith("orcid:"):
                return await self.adapters.extensions.call("orcid", "get", {"orcid": value[6:]})
            raise ResearchError("invalid_identifier", "Use openalex:A… or orcid:<ORCID> for an author.")
        if entity == "patent":
            return await self.adapters.extensions.call(
                "patents", "get", {"publication": value, "section": "biblio"}
            )
        if entity == "study":
            from ..study_metadata import study_metadata_record

            study = self.adapters.extensions.studies().get(value)
            if not study:
                raise ResearchError("study_unavailable", "Study is not an installed verified release.")
            return study_metadata_record(study)
        raise ResearchError("unsupported_get", "Inspect capabilities for supported entity reads.")

    async def section(self, entity, value, name, request, context, source=None):
        params = request.section_parameters.get(name, {})
        if name == "civic" and entity in {"drug", "disease"}:
            from .civic import named_identity

            record = await self.record(entity, value, context=context)
            identity = named_identity(record, value, entity)
            evidence = await self.variants.civic(identity["name"], entity, **params)
            return {**evidence, "qualified_identity": identity}
        if entity == "drug" and source == "ema":
            return await self.regulatory.ema(value, name)
        if entity == "drug" and source == "who":
            return await self.regulatory.who(value)

        if entity == "gene":
            if name in {"expression", "eqtl", "sqtl", "transcripts", "exons"}:
                if ("gene", value, request.species) in context:
                    gene = await self.record("gene", value, species=request.species, context=context)
                    value = gene["ensembl_id"]
                    if not value:
                        raise ResearchError(
                            "unresolved_identity",
                            "Shared GTEx enrichment requires one exact Ensembl gene identity.",
                        )
                args = {
                    "gene_id": value,
                    "limit": 25,
                    **params,
                    "dataset_id": request.source_versions.get("gtex", "gtex_v10"),
                }
                if name == "expression":
                    return await self.adapter(
                        "gtex", "query_expression", query_type=args.pop("query_type", "gene_median"), **args
                    )
                if name in {"transcripts", "exons"}:
                    return await self.adapter(
                        "gtex",
                        "get_annotation",
                        entity_type="transcript" if name == "transcripts" else "exon",
                        entity_id=args.pop("gene_id"),
                        **args,
                    )
                return await self.adapter(
                    "gtex",
                    "query_qtl",
                    analysis_mode=args.pop("analysis_mode", "gene_associations"),
                    qtl_type=name,
                    **args,
                )
            # Every remaining gene section uses one exact identity. Providers
            # expecting symbols receive symbols; stable-ID fields stay typed.
            gene = await self.record("gene", value, species=request.species, context=context)
            value = gene["qualified_identity"]["symbol"]
            if name in {"target_evidence", "diseases", "druggability", "genetics", "hpa", "go"}:
                if name == "go":
                    return gene.get("go", {})
                ensembl = gene.get("ensembl_id")
                if not ensembl:
                    raise ResearchError(
                        "unresolved_identity", "This section requires one exact Ensembl gene identity."
                    )
                if name == "hpa":
                    return await self.adapter("protein-atlas", "get_expression_data", ensembl_id=ensembl)
                if name == "genetics":
                    from .opentargets_workflows import qualified_gene_genetics

                    value = await self.adapter(
                        "opentargets",
                        "query_genetics",
                        query_type="study",
                        gene_id=ensembl,
                        include_credible_sets=True,
                        limit=params.get("limit", 10),
                        page_index=params.get("page", 0),
                    )
                    result = qualified_gene_genetics(
                        value, gene, ensembl, limit=params.get("limit", 10), page_index=params.get("page", 0)
                    )
                    if result["continuation"] is not None:
                        result["continuation"]["arguments"].update(
                            id=request.id,
                            species=request.species,
                            sources=request.sources,
                            freshness=request.freshness,
                        )
                    return result
                from .opentargets import disease_associations, druggability, target_profile

                async def acquired_target():
                    payload = await self.adapter(
                        "opentargets",
                        "get_entity",
                        entity_type="target",
                        entity_id=ensembl,
                        sections=["identity", "biology", "safety", "tractability"],
                        include_associations=True,
                        association_limit=10,
                    )
                    return target_profile(payload, gene["qualified_identity"], ensembl)

                data = await once(
                    context,
                    ("opentargets", ensembl),
                    acquired_target,
                )
                if name == "diseases":
                    return disease_associations(data)
                if name == "druggability":
                    return druggability(data)
                return data
            if name == "pathways":
                return await self.adapter(
                    "reactome", "find_pathways_by_gene", gene=value, species=str(request.species)
                )
            if name == "protein":
                return await self.adapter(
                    "uniprot",
                    "query_proteins",
                    query=f"gene_exact:{value} AND organism_id:{request.species}",
                    query_type="advanced",
                    limit=10,
                )
            if name == "constraint":
                from .gnomad import constraint

                return await constraint(self.http, gene["qualified_identity"])
            if name == "clingen":
                from .clingen import gene_candidates

                if not gene["qualified_identity"]["hgnc_id"]:
                    raise ResearchError(
                        "unresolved_identity", "ClinGen gene matching requires a qualified HGNC identity."
                    )
                rows = await self.http.get(
                    "https://search.clinicalgenome.org/api/genes/look/" + segment(value)
                )
                return gene_candidates(rows, gene["qualified_identity"])
            if name == "gencc":
                return await self.gencc(value)
        if entity == "variant":
            if name == "eve":
                from .eve import acquire

                return await acquire(self.http, value, request.assembly)
            if name == "predictions":
                from .alphamissense import acquire

                return await acquire(self.http, value, request.assembly)
            if name in {"oncokb", "hotspots"}:
                kind, identity = self.variants.validate(value)
                if kind != "protein":
                    raise ResearchError(
                        "unresolved_identity", "This section requires gene plus protein change."
                    )
                if name == "oncokb":
                    if "oncokb" not in os.getenv("UBI_LICENSED_SOURCES", "").split(",") or not os.getenv(
                        "ONCOKB_TOKEN"
                    ):
                        raise ResearchError(
                            "source_unavailable", "OncoKB requires a licensed configured account."
                        )
                    return await self.http.get(
                        "https://www.oncokb.org/api/v1/annotate/mutations/byProteinChange",
                        params={"hugoSymbol": identity["gene"], "alteration": identity["change"]},
                        headers={"Authorization": "Bearer " + os.environ["ONCOKB_TOKEN"]},
                    )
                rows = await self.http.get(
                    "https://www.cancerhotspots.org/api/hotspots/single/byGene/" + segment(identity["gene"])
                )
                position = int(identity["change"][1:-1])
                return {
                    "records": [
                        r
                        for r in rows
                        if str(r.get("residue", "")).strip() in {str(position), identity["change"][:-1]}
                        or r.get("aminoAcidPosition", {}).get("start") == position
                    ],
                    "identity": identity,
                    "interpretation": "Residue recurrence across a source cohort; it is not an exact allele prevalence or clinical classification.",
                }
            if name == "civic":
                return await self.variants.civic(value, assembly=request.assembly, **params)
            if name == "gwas":
                limit = params.get("limit", 10)
                return await self.gwas(
                    identifier(value, r"rs[1-9]\d*", "GWAS variant evidence requires a dbSNP rsID."),
                    limit=limit,
                    offset=params.get("page", 0) * limit,
                    include_page=True,
                )
            if name == "clinvar":
                from .clinvar import assertions

                return await assertions(self.variants, value, request.assembly)
            if name == "population":
                from .gnomad import direct_population_identity

                direct = direct_population_identity(value, request.assembly)
                if direct is not None:
                    # The returned allele and assembly are checked before evidence is emitted.
                    return await self.variants.population({"identity": direct})
            record = await self.record("variant", value, assembly=request.assembly, context=context)
            if record.get("resolution") != "exact":
                raise ResearchError(
                    "ambiguous_identifier"
                    if record.get("resolution") == "ambiguous"
                    else "unresolved_identity",
                    "Exact allele resolution is required for this section.",
                )
            if name == "population":
                return await self.variants.population(record)
            annotation = record["annotation"]
            if name == "conservation":
                return {
                    k: annotation.get("dbnsfp", {}).get(k)
                    for k in ["gerp", "phylop100way_vertebrate", "phastcons100way_vertebrate"]
                    if annotation.get("dbnsfp", {}).get(k) is not None
                }
            if name in {"clinvar", "cosmic", "cgi"}:
                return annotation.get(name, {})
            if name == "cbioportal":
                return await self.cbioportal(record, params)
        if entity == "article":
            if name in {"fulltext", "assets"}:
                return await self.literature.fulltext(
                    value,
                    view="assets" if name == "assets" else params.get("view", "outline"),
                    source=source or "europepmc",
                    **{k: v for k, v in params.items() if k != "view"},
                )
            if name == "indexing":
                data = await self.literature.get(value, "pubmed")
                return {
                    k: data[k]
                    for k in ["mesh", "publication_types", "is_retracted", "author_records"]
                    if k in data
                }
            if name == "annotations":
                return await self.annotations(value)
        if entity == "trial":
            data = await self.record("trial", value, context=context)
            raw = data.get("study", data)
            protocol = raw.get("protocolSection", raw.get("protocol", {}))
            mapping = {
                "eligibility": "eligibilityModule",
                "contacts": "contactsLocationsModule",
                "locations": "contactsLocationsModule",
                "outcomes": "outcomesModule",
                "arms": "armsInterventionsModule",
                "references": "referencesModule",
            }
            module = protocol.get(mapping[name])
            if not module:
                raise ResearchError(
                    "source_unavailable",
                    "The requested trial protocol module was not supplied; no absence can be inferred.",
                )
            return module
        if entity == "drug":
            if name in {"label", "regulatory", "safety", "shortage"}:
                endpoint = {
                    "label": "drug/label",
                    "regulatory": "drug/drugsfda",
                    "safety": "drug/event",
                    "shortage": "drug/shortages",
                }[name]
                field = (
                    "patient.drug.medicinalproduct"
                    if name == "safety"
                    else "generic_name"
                    if name == "shortage"
                    else "openfda.generic_name"
                )
                query = f'{field}:"{value.replace(chr(34), "")}"'
                if name == "label":
                    return {
                        "records": await self.fda(endpoint, query, limit=1),
                        "coverage": {
                            "record_limit": 1,
                            "scope": "One matching manufacturer-submitted SPL label record; not all manufacturers or proof of latest approved labeling.",
                        },
                    }
                return await self.fda(endpoint, query)
            if name in {"targets", "indications", "interactions"}:
                operation = {
                    "targets": "get_drug_targets",
                    "indications": "get_disease_associations",
                    "interactions": "get_drug_interactions",
                }[name]
                return await self.adapter(
                    "mychem", operation, **{"chemical_id" if name == "indications" else "drug_id": value}
                )
            if name == "approvals":
                return await self.adapter("orange-book", "search_products", ingredient=value, limit=25)
        if entity == "disease":
            if name in {"genes", "phenotypes", "models"}:
                identifier(
                    value,
                    r"(?:MONDO|OMIM|DOID|ORPHANET):\d+",
                    "Monarch requires a qualified disease identifier; resolve names first.",
                )
                return await monarch.associations(self.http, value, name)
            if name == "pathways":
                payload = await self.record("disease", value, context=context)
                disease_identity = self.disease_identity(value, payload)
                label = disease_identity["label"]
                result = await self.adapter("reactome", "find_pathways_by_disease", disease=label)
                return {
                    **result,
                    "disease_identity": disease_identity,
                    "warnings": [
                        *result.get("warnings", []),
                        "Preferred-label text matches are discovery candidates, not verified ontology-to-pathway associations.",
                    ],
                }
            if name in {"variants", "prevalence", "survival", "clinical_features"}:
                operation = {
                    "variants": "get_disease_variants",
                    "prevalence": "get_disease_prevalence",
                    "survival": "get_disease_prognosis",
                    "clinical_features": "get_diagnostic_criteria",
                }[name]
                return await self.adapter("mydisease", operation, disease_id=value)
        if entity == "pathway":
            return await self.adapter(
                "reactome",
                "get_pathway_info",
                pathway_id=value,
                detail_level="participants" if name == "genes" else "hierarchy",
            )
        if entity == "pgx":
            return await self.pgx(value, name)
        if entity == "protein":
            if name == "domains":
                interpro.accession(value)
                identity = interpro.protein_identity(
                    await self.record("protein", value, context=context), value, request.species
                )
                if params.get("length") is not None and identity["length"] != params["length"]:
                    raise ResearchError(
                        "identity_mismatch", "UniProt sequence length changed during InterPro continuation."
                    )
                return await interpro.acquire(
                    self.http,
                    identity,
                    limit=params.get("limit", 25),
                    after=params.get("after"),
                    scanned=params.get("scanned", 0),
                    total=params.get("total"),
                    release=params.get("release"),
                    seen=params.get("seen", ()),
                )
            if name == "complexes":
                identity = complexportal.protein_identity(
                    await self.record("protein", value, context=context), value, request.species
                )
                return await complexportal.acquire(self.http, identity, **params)
            if name == "structures":
                data = await self.record("protein", value, context=context)
                return [
                    r
                    for r in data.get("uniProtKBCrossReferences", [])
                    if r.get("database") in {"PDB", "AlphaFoldDB"}
                ]
        if entity == "diagnostic":
            if name == "regulatory":
                return await self.fda(
                    "device/510k",
                    f'k_number:"{identifier(value, r"K\d{6}", "Device clearance lookup requires a K number.")}"',
                )
            data = await self.record("diagnostic", value)
            return [{k: v for k, v in row.items() if k in {"uid", "name", name}} for row in data]
        if entity == "adverse-event":
            data = await once(context, ("faers", value), lambda: self.record(entity, value))
            rows = []
            for row in data:
                patient = row.get("patient", {})
                if name == "reactions":
                    rows.extend(patient.get("reaction", []))
                elif name == "concomitant":
                    rows.extend(r for r in patient.get("drug", []) if r.get("drugcharacterization") == "2")
                elif name == "outcomes":
                    rows.append({k: v for k, v in row.items() if k.startswith("serious")})
                else:
                    rows.append(
                        {
                            "safetyreportid": value,
                            "interpretation": "Spontaneous reports do not establish causality, incidence or comparative drug safety.",
                        }
                    )
            return rows
        if entity == "patent":
            return await self.adapters.extensions.call(
                "patents", "get", {"publication": value, "section": name}
            )
        if name == "civic":
            return await self.variants.civic(
                value,
                entity,
                entrez_id=gene["qualified_identity"].get("entrez_id") if entity == "gene" else None,
                **params,
            )
        if name == "diagnostics":
            return await self.ncbi_summary("gtr", value)
        if name == "funding":
            result = await self.http.post(
                "https://api.reporter.nih.gov/v2/projects/search",
                {
                    "criteria": {
                        "advanced_text_search": {
                            "operator": "and",
                            "search_field": "all",
                            "search_text": value,
                        }
                    },
                    "offset": 0,
                    "limit": 10,
                },
            )
            return {
                "records": collection(result, ("results",)),
                "warnings": [
                    "Name-based co-mention discovery of funded projects does not prove a gene or disease relationship."
                ],
            }
        if name == "interactions":
            response = await self.http.get(
                "https://string-db.org/api/json/network",
                params={
                    "identifiers": value,
                    "species": request.species,
                    "add_nodes": ADDED_NODES,
                    "network_type": "functional",
                    "caller_identity": "biomedmcp",
                },
            )
            return network(response, symbol=value, species=request.species)
        if name == "disgenet":
            if "disgenet" not in os.getenv("UBI_LICENSED_SOURCES", "").split(",") or not os.getenv(
                "DISGENET_API_KEY"
            ):
                raise ResearchError("source_unavailable", "DISGENET requires a licensed configured account.")
            return await self.http.get(
                "https://api.disgenet.com/api/v1/gda/summary",
                params={
                    "gene_symbol" if entity == "gene" else "disease": value,
                    "page_number": 0,
                    "page_size": 25,
                },
                headers={"Authorization": "Bearer " + os.environ["DISGENET_API_KEY"]},
            )
        raise ResearchError("unknown_section", "Section has no native implementation.")

    async def gencc(self, gene):
        from .gencc import acquire

        return await acquire(self.http, gene)

    async def annotations(self, value):
        kind, parsed = article_id(value)
        if kind not in {"pmid", "pmcid"}:
            raise ResearchError(
                "invalid_identifier", "PubTator annotations require a PMID or PMCID; resolve DOI first."
            )
        return await self.http.get(
            f"{PUBTATOR}/publications/export/biocjson",
            params={"pmids" if kind == "pmid" else "pmcids": parsed},
        )

    async def cbioportal(self, record, params):
        # Public cohort denominator and profile are always explicit.
        if not params.get("molecular_profile_id") or not params.get("sample_list_id"):
            raise ResearchError(
                "missing_cohort", "cBioPortal requires molecular_profile_id and sample_list_id."
            )
        annotations = record.get("annotation", {})
        entrez = (annotations.get("dbnsfp") or {}).get("genename")
        if not isinstance(entrez, str):
            raise ResearchError("unresolved_identity", "A single gene is required for the cohort lookup.")
        gene = await self.gene(entrez)
        data = await self.http.post(
            f"https://www.cbioportal.org/api/molecular-profiles/{segment(params['molecular_profile_id'])}/mutations/fetch",
            {"sampleListId": params["sample_list_id"], "entrezGeneIds": [int(gene["entrezgene"])]},
        )
        identity = record.get("identity", {})
        change = identity.get("change") if isinstance(identity, dict) else None
        if not change:
            raise ResearchError(
                "unresolved_identity", "Cohort variant evidence requires exact protein identity."
            )
        rows = [r for r in data if r.get("proteinChange") == change]
        return {
            "records": rows,
            "molecular_profile_id": params["molecular_profile_id"],
            "sample_list_id": params["sample_list_id"],
            "interpretation": "Matched mutation records; cohort prevalence requires an assayed-sample denominator.",
        }

    async def variant_structure(self, record):

        identity = record.get("identity") or {}
        if not isinstance(identity, dict) or not identity.get("gene") or not identity.get("change"):
            raise ResearchError(
                "unresolved_identity", "Structure mapping requires an exact gene/protein change."
            )
        gene = identity["gene"]
        change = identity["change"]
        if not isinstance(change, str) or not re.fullmatch(r"[A-Z][1-9][0-9]*[A-Z*]", change):
            raise ResearchError(
                "invalid_identifier", "Structure mapping requires a positive protein residue substitution."
            )
        position = int(change[1:-1])
        found = await self.adapter(
            "uniprot",
            "query_proteins",
            query=f"gene_exact:{gene} AND organism_id:9606 AND reviewed:true",
            query_type="advanced",
            limit=10,
            include_sequence=True,
            include_features=True,
            fields=["accession", "id", "gene_names", "length", "xref_pdb", "xref_alphafolddb", "xref_refseq"],
        )
        rows = found.get("results", [])
        if len(rows) != 1:
            raise ResearchError(
                "ambiguous_identifier", "Select one reviewed UniProt protein before mapping this residue."
            )
        protein = rows[0]
        sequence = protein.get("sequence", {}).get("value", "")
        if position > len(sequence) or sequence[position - 1] != change[0]:
            raise ResearchError(
                "identity_mismatch",
                "Requested reference amino acid does not match the selected UniProt sequence.",
            )
        accession = protein["primaryAccession"]
        structures = []
        for ref in protein.get("uniProtKBCrossReferences", []):
            if ref.get("database") == "PDB":
                properties = {p["key"]: p["value"] for p in ref.get("properties", [])}
                ranges = [
                    (int(a), int(b)) for a, b in re.findall(r"=(\d+)-(\d+)", properties.get("Chains", ""))
                ]
                structures.append(
                    {
                        "pdb_id": ref["id"],
                        "chains": properties.get("Chains"),
                        "method": properties.get("Method"),
                        "resolution": properties.get("Resolution"),
                        "covers_requested_sequence_position": any(a <= position <= b for a, b in ranges)
                        if ranges
                        else None,
                    }
                )
        qualified = interpro.protein_identity(found, accession, 9606)
        if not any(g.get("geneName", {}).get("value") == gene for g in protein.get("genes", [])):
            raise ResearchError("identity_mismatch", "Selected UniProt gene does not match the variant gene.")
        matches, acquired, page = [], [], None
        statuses = {"uniprot": {"outcome": "data", "sources": ["uniprot"]}}
        state = {"scanned": 0, "seen": []}
        total, release, after = None, None, None
        for _ in range(4):
            try:
                page = await interpro.acquire(
                    self.http,
                    qualified,
                    after=after,
                    scanned=state["scanned"],
                    total=total,
                    release=release,
                    seen=state["seen"],
                )
            except ResearchError as error:
                statuses["interpro"] = {
                    "outcome": "partial" if acquired else "unavailable",
                    "sources": ["interpro"] if acquired else [],
                    "error": error.as_dict(),
                }
                page = None
                break
            acquired.extend(page["records"])
            matches.extend(interpro.overlaps(page, position))
            total, release = page["coverage"]["total_entries"], page["source_release"]
            statuses["interpro"] = {"outcome": "data" if matches else "empty", "sources": ["interpro"]}
            if page["_provider_page"]["exhausted"]:
                break
            state = {
                "scanned": state["scanned"] + len(page["records"]),
                "seen": [*state["seen"], *[r["metadata"]["accession"] for r in page["records"]]],
            }
            after = page["_provider_page"]["continuation"]
            statuses["interpro"]["outcome"] = "partial"
        continuation = None
        if page is not None and not page["_provider_page"]["exhausted"]:
            # Reuse ordinary protein continuation without replaying this prefix.
            continuation = {
                **page,
                "records": acquired,
                "_provider_page": {**page["_provider_page"], "raw_count": len(acquired)},
            }
        domains = [match for match in matches if match["entry_type"] == "domain"]
        return {
            "identity": identity,
            "protein": {"accession": accession, "length": len(sequence)},
            "position": position,
            "reference_amino_acid": change[0],
            "alternate_amino_acid": change[-1],
            "position_confidence": "Reference residue verified on the selected canonical sequence; transcript/isoform mapping is not inferred.",
            "domains": domains,
            "interpro_matches": matches,
            "interpro_coverage": {
                "acquired_entries": len(acquired),
                "total_entries": total,
                "complete": page is not None and page["_provider_page"]["exhausted"],
                "source_release": release,
                "interpretation": "Predicted entry fragment overlaps, preserving entry type; no variant effect or experimental function is inferred. Accession/species/length agree; identical UniProt and InterPro sequence releases are not established.",
            },
            "_interpro_continuation": continuation,
            "structures": structures,
            "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{accession}",
            "coordinate_system": "1-based UniProt sequence; experimental PDB author residue numbering is not mapped.",
            "section_outcomes": statuses,
            "sources": ["myvariant", "uniprot", *(["interpro"] if acquired or page is not None else [])],
        }
