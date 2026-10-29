"""Documented bounded NCBI assembly and annotation acquisition contracts."""

import json
import math
import re
from importlib.resources import files
from urllib.parse import quote

from jsonschema import Draft7Validator

from biomedmcp.errors import ResearchError
from biomedmcp.pagination import numeric_total, page_payload

CONTRACT = json.loads(files("ncbi_mcp").joinpath("contracts.json").read_text())
ACCESSION = r"GC[AF]_[0-9]+\.[0-9]+"
VALIDATORS = {}
for _path, _methods in CONTRACT["paths"].items():
    _schema = _methods["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    VALIDATORS[_path] = Draft7Validator({**_schema, "components": CONTRACT["components"]})


def invalid_parameters(message):
    raise ResearchError("invalid_parameters", message)


def selector(value):
    if (
        not value
        or len(str(value)) > 512
        or "," in str(value)
        or "/" in str(value)
        or any(ord(char) < 32 for char in str(value))
    ):
        invalid_parameters("Use a single bounded NCBI taxon, name or assembly accession.")
    return quote(str(value), safe="")


def search_plan(arguments):
    kind = arguments.get("data_type", "genomes")
    if kind == "taxonomy":
        if (
            any(
                arguments.get(field) is not None for field in ("chromosome", "feature_type", "assembly_level")
            )
            or arguments.get("assembly_source", "all") != "all"
        ):
            invalid_parameters("Assembly and feature filters do not apply to taxonomy.")
        selected = arguments.get("tax_id") or arguments.get("organism")
        if selected is not None and arguments["query"] != str(selected):
            invalid_parameters(
                "Taxonomy search accepts one taxon selector; do not supply conflicting query text."
            )
        plan = taxonomy_plan(
            {
                "tax_id": arguments.get("tax_id"),
                "organism": arguments.get("organism")
                or (arguments["query"] if not arguments.get("tax_id") else None),
                "page_size": arguments.get("max_results", 25),
                "page_token": arguments.get("page_token"),
            }
        )
        if arguments.get("rank"):
            rank = arguments["rank"].upper().replace(" ", "_")
            if rank not in CONTRACT["components"]["schemas"]["v2reportsRankType"]["enum"]:
                invalid_parameters("Select an NCBI taxonomy rank from the provider contract.")
            plan["params"]["ranks"] = rank
        return plan
    if kind not in {"genomes", "assemblies"}:
        return None
    if any(arguments.get(field) is not None for field in ("chromosome", "feature_type", "rank")):
        invalid_parameters("Chromosome, feature type and taxonomy rank do not filter assembly reports.")
    if arguments.get("tax_id") is not None and arguments.get("organism") is not None:
        invalid_parameters("Select one taxon identity: tax_id or organism.")
    query = arguments["query"]
    selector(query)
    taxon = arguments.get("tax_id") or arguments.get("organism")
    params = {"page_size": arguments.get("max_results", 25), "returned_content": "COMPLETE"}
    if arguments.get("page_token"):
        params["page_token"] = arguments["page_token"]
    if arguments.get("assembly_level"):
        params["filters.assembly_level"] = arguments["assembly_level"]
    if arguments.get("assembly_source", "all") != "all":
        params["filters.assembly_source"] = arguments["assembly_source"]
    requested_accession = None
    if re.fullmatch(ACCESSION, query):
        if taxon is not None:
            invalid_parameters(
                "An exact assembly accession already selects its identity; remove the taxon selector."
            )
        template = "/genome/accession/{accessions}/dataset_report"
        endpoint = "genome/accession/" + selector(query) + "/dataset_report"
        role, requested_accession = "accession", query
    elif taxon is not None or kind == "genomes":
        template = "/genome/taxon/{taxons}/dataset_report"
        endpoint = "genome/taxon/" + selector(taxon or query) + "/dataset_report"
        role = "within_taxon_search_text" if taxon is not None and query != str(taxon) else "taxon"
        if role == "within_taxon_search_text":
            params["filters.search_text"] = query
    else:
        template = "/genome/assembly_name/{assembly_names}/dataset_report"
        endpoint = "genome/assembly_name/" + selector(query) + "/dataset_report"
        role = "assembly_name"
    return {
        "template": template,
        "endpoint": endpoint,
        "params": params,
        "query_role": role,
        "accession": requested_accession,
    }


def genome_plan(arguments):
    accession = arguments["accession"]
    if not re.fullmatch(ACCESSION, accession):
        invalid_parameters("Use an exact versioned GCF_ or GCA_ assembly accession.")
    annotation = arguments.get("info_type", "full") == "annotation"
    fields = ("chromosome", "start_position", "end_position", "symbols", "gene_types")
    if not annotation and any(arguments.get(field) is not None for field in fields):
        invalid_parameters("Annotation filters require info_type=annotation.")
    start, end = arguments.get("start_position"), arguments.get("end_position")
    if (start is None) != (end is None) or (
        start is not None and (not arguments.get("chromosome") or start > end)
    ):
        invalid_parameters("A region requires a chromosome and ordered start/end positions.")
    params = {"page_size": arguments.get("page_size", 25) if annotation else 1}
    if annotation:
        template = "/genome/accession/{accession}/annotation_report"
        endpoint = "genome/accession/" + accession + "/annotation_report"
        if arguments.get("chromosome"):
            chromosome = arguments["chromosome"]
            if not re.fullmatch(r"[A-Za-z0-9_.]+", chromosome):
                invalid_parameters(
                    "Use a chromosome name or sequence accession without a location expression."
                )
            params["locations"] = chromosome if start is None else f"{chromosome}:{start}-{end}"
        for field in ("symbols", "gene_types"):
            if arguments.get(field):
                if any("," in item or any(ord(char) < 32 for char in item) for item in arguments[field]):
                    invalid_parameters("Each annotation filter must be one bounded value.")
                params[field] = ",".join(arguments[field])
    else:
        template = "/genome/accession/{accessions}/dataset_report"
        endpoint = "genome/accession/" + accession + "/dataset_report"
        params["returned_content"] = "COMPLETE"
    if arguments.get("page_token"):
        params["page_token"] = arguments["page_token"]
    return {
        "template": template,
        "endpoint": endpoint,
        "params": params,
        "accession": accession,
        "annotation": annotation,
    }


def validate_operation(operation, arguments):
    if operation in {"find_orthologs", "get_virus_info"}:
        from .gene_reports import ortholog_plans, virus_plan

        ortholog_plans(arguments) if operation == "find_orthologs" else virus_plan(arguments)
    elif operation == "search_ncbi_data":
        search_plan(arguments)
    elif operation == "get_genome_data":
        genome_plan(arguments)
    elif operation == "get_taxonomy_data":
        taxonomy_plan(arguments)
        if arguments.get("genome_page_token") and arguments.get("info_type", "info") != "organism":
            invalid_parameters("Genome continuation requires info_type=organism.")
        if arguments.get("names_page_token") and not arguments.get("include_synonyms"):
            invalid_parameters("Name continuation requires include_synonyms=true.")
    elif operation == "get_assembly_data":
        assembly_plan(arguments)
        if arguments.get("report_type") == "quality" and not any(
            arguments.get(field, True)
            for field in ("include_checkm", "include_busco", "include_contamination")
        ):
            invalid_parameters("Select at least one requested quality measurement.")
    elif operation == "search_project_sample":
        association_plan(arguments)


def taxonomy_plan(arguments, *, names=False):
    tax_id, organism = arguments.get("tax_id"), arguments.get("organism")
    if (tax_id is None) == (organism is None):
        invalid_parameters("Select exactly one tax_id or organism name.")
    value = tax_id if tax_id is not None else organism
    params = {"page_size": arguments.get("page_size", 25)}
    if not names:
        params["returned_content"] = "COMPLETE"
    if arguments.get("page_token"):
        params["page_token"] = arguments["page_token"]
    suffix = "name_report" if names else "dataset_report"
    return {
        "template": "/taxonomy/taxon/{taxons}/" + suffix,
        "endpoint": "taxonomy/taxon/" + selector(value) + "/" + suffix,
        "params": params,
        "taxonomy": True,
        "names": names,
        "tax_id": tax_id,
    }


def assembly_plan(arguments):
    accession = arguments["assembly_accession"]
    kind = arguments.get("report_type", "info")
    plan = genome_plan(
        {
            "accession": accession,
            "info_type": "annotation" if kind == "annotation_report" else "full",
            "page_size": arguments.get("page_size", 25),
            "page_token": arguments.get("page_token"),
        }
    )
    if kind == "sequence_report":
        plan.update(
            template="/genome/accession/{accession}/sequence_reports",
            endpoint="genome/accession/" + accession + "/sequence_reports",
            sequence=True,
        )
        plan["params"] = {"page_size": arguments.get("page_size", 25)}
        if arguments.get("page_token"):
            plan["params"]["page_token"] = arguments["page_token"]
    return plan


def association_plan(arguments):
    kind, accession = arguments.get("search_type", "bioproject"), arguments["accession"]
    pattern = r"PRJ(?:NA|EB|DB)[0-9]+" if kind == "bioproject" else r"SAM(?:N[0-9]+|EA[0-9]+|D[0-9]+)"
    if not re.fullmatch(pattern, accession):
        invalid_parameters("Use a BioProject or BioSample accession matching search_type.")
    if arguments.get("data_type", "genomes") not in {"genomes", "assemblies"}:
        invalid_parameters(
            "This operation acquires genome assembly associations; select genomes or assemblies."
        )
    params = {"page_size": arguments.get("max_results", 25), "returned_content": "COMPLETE"}
    if arguments.get("page_token"):
        params["page_token"] = arguments["page_token"]
    placeholder = "bioprojects" if kind == "bioproject" else "biosample_ids"
    return {
        "template": "/genome/" + kind + "/{" + placeholder + "}/dataset_report",
        "endpoint": "genome/" + kind + "/" + accession + "/dataset_report",
        "params": params,
        "association_kind": kind,
        "association_accession": accession,
    }


def invalid_response():
    raise ResearchError("invalid_source_response", "NCBI returned an invalid or unqualified dataset report.")


def project_accessions(value):
    if isinstance(value, list):
        return {accession for item in value for accession in project_accessions(item)}
    if isinstance(value, dict):
        result = set()
        for key, item in value.items():
            if key in {"accession", "parent_accession", "parent_accessions"}:
                result.update(
                    [item]
                    if isinstance(item, str)
                    else item
                    if isinstance(item, list) and all(isinstance(entry, str) for entry in item)
                    else []
                )
            elif isinstance(item, (dict, list)):
                result.update(project_accessions(item))
        return result
    return set()


def quality_projection(report, arguments):
    checkm = report.get("checkm_info", {})
    busco = report.get("annotation_info", {}).get("busco", {})
    for name, value in checkm.items():
        if name in {"completeness", "contamination", "completeness_percentile"} and (
            value < 0 or (name != "contamination" and value > 100)
        ):
            invalid_response()
    for name, value in busco.items():
        if (
            name in {"complete", "single_copy", "duplicated", "fragmented", "missing"}
            and not 0 <= value <= 100
        ):
            invalid_response()
        if name == "total_count" and (not value.isdigit() or int(value) < 1):
            invalid_response()
    values = {
        "checkm": (
            arguments.get("include_checkm", True),
            checkm if "completeness" in checkm else None,
            "percent",
            "Assembly marker completeness; retain marker set and CheckM version.",
        ),
        "busco": (
            arguments.get("include_busco", True),
            busco
            if any(
                field in busco for field in ("complete", "single_copy", "duplicated", "fragmented", "missing")
            )
            else None,
            "provider_native_score",
            "Annotation protein-mode BUSCO scores; retain lineage/version and raw scale; no percent conversion is applied.",
        ),
        "contamination": (
            arguments.get("include_contamination", True),
            {
                key: value
                for key, value in checkm.items()
                if key
                in {
                    "contamination",
                    "checkm_marker_set",
                    "checkm_marker_set_rank",
                    "checkm_species_tax_id",
                    "checkm_version",
                }
            }
            if "contamination" in checkm
            else None,
            "percent",
            "CheckM marker contamination estimate; this does not establish comprehensive contamination screening.",
        ),
    }
    return {
        name: {
            "outcome": "data" if value is not None else "unavailable",
            "value": value,
            "units": units,
            "interpretation": note,
        }
        for name, (requested, value, units, note) in values.items()
        if requested
    }


def validate_assembly_measures(report):
    stats = report.get("assembly_stats", {})
    for name, schema in CONTRACT["components"]["schemas"]["v2reportsAssemblyStats"]["properties"].items():
        if name not in stats:
            continue
        value = stats[name]
        if schema.get("format") == "uint64" and (not value.isdigit() or int(value) < 0):
            invalid_response()
        if schema.get("type") in {"integer", "number"} and value < 0:
            invalid_response()
    if "gc_percent" in stats and stats["gc_percent"] > 100:
        invalid_response()
    quality_projection(report, {})


def qualified_page(payload, plan, *, include_annotation=True, summary=False):
    if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
        invalid_response()
    pending = [(payload, 0)]
    inspected = 0
    while pending:
        value, depth = pending.pop()
        inspected += 1
        if depth > 24 or inspected > 100000 or (isinstance(value, float) and not math.isfinite(value)):
            invalid_response()
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    if not VALIDATORS[plan["template"]].is_valid(payload):
        invalid_response()
    total = numeric_total(payload.get("total_count"))
    # Protobuf JSON omits empty repeated fields, including the final window of
    # a nonempty result set. A positive total alone is not an empty first page.
    if (
        "reports" not in payload
        and total != 0
        and not (total is not None and plan["params"].get("page_token"))
    ):
        invalid_response()
    reports = payload.get("reports", [])
    if not reports and total is None and not payload.get("next_page_token"):
        invalid_response()
    if any("error" in message for message in payload.get("messages", [])):
        invalid_response()
    limit = plan["params"]["page_size"]
    if len(reports) > limit or (total is not None and total < len(reports)):
        invalid_response()
    token = payload.get("next_page_token") or None
    if token is not None and (len(token) > 8192 or token == plan["params"].get("page_token")):
        invalid_response()
    if (
        not plan.get("taxonomy")
        and "page_token" not in plan["params"]
        and total is not None
        and total > len(reports)
        and token is None
    ):
        invalid_response()
    qualified, identities = [], set()
    for report in reports:
        if "error" in report or ("errors" in report and report["errors"] != []):
            invalid_response()
        if plan.get("taxonomy"):
            node = report.get("taxonomy", {})
            identity = node.get("tax_id")
            if plan.get("names"):
                if not isinstance(identity, str) or not identity.isdigit():
                    invalid_response()
                identity = int(identity)
            if (
                type(identity) is not int
                or identity < 1
                or identity in identities
                or (plan.get("tax_id") is not None and identity != plan["tax_id"])
            ):
                invalid_response()
            identities.add(identity)
            if not node.get("current_scientific_name", {}).get("name"):
                invalid_response()
            parents = node.get("parents", [])
            if any(type(parent) is not int or parent < 1 or parent == identity for parent in parents) or len(
                set(parents)
            ) != len(parents):
                invalid_response()
            for rank in node.get("classification", {}).values():
                if type(rank.get("id")) is not int or rank["id"] < 1 or not rank.get("name"):
                    invalid_response()
                if "parents" in node and rank["id"] not in {*parents, identity}:
                    invalid_response()
        elif plan.get("sequence"):
            if (
                report.get("assembly_accession") != plan["accession"]
                or not any(report.get(field) for field in ("refseq_accession", "genbank_accession"))
                or type(report.get("length")) is not int
                or report["length"] < 1
            ):
                invalid_response()
            identity = report.get("refseq_accession") or report["genbank_accession"]
            if identity in identities or not re.fullmatch(r"[A-Z][A-Z0-9_]*[0-9]+\.[0-9]+", identity):
                invalid_response()
            identities.add(identity)
            if "gc_percent" in report and not 0 <= report["gc_percent"] <= 100:
                invalid_response()
        elif plan.get("annotation"):
            record = report.get("annotation")
            if not isinstance(record, dict) or not any(
                record.get(field) for field in ("gene_id", "symbol", "locus_tag")
            ):
                invalid_response()
            if "gene_id" in record and (not str(record["gene_id"]).isdigit() or int(record["gene_id"]) < 1):
                invalid_response()
            if plan["params"].get("symbols") and record.get("symbol") not in plan["params"]["symbols"].split(
                ","
            ):
                invalid_response()
            if plan["params"].get("gene_types") and record.get("gene_type") not in plan["params"][
                "gene_types"
            ].split(","):
                invalid_response()
            annotations = record.get("annotations", [])
            if annotations and not any(
                item.get("assembly_accession") == plan["accession"] for item in annotations
            ):
                invalid_response()
        else:
            accession = report.get("accession")
            if (
                not isinstance(accession, str)
                or not re.fullmatch(ACCESSION, accession)
                or accession in identities
            ):
                invalid_response()
            identities.add(accession)
            if plan.get("accession") and accession != plan["accession"]:
                invalid_response()
            organism = report.get("organism", {})
            if type(organism.get("tax_id")) is not int or organism["tax_id"] < 1:
                invalid_response()
            validate_assembly_measures(report)
            if plan.get("association_kind"):
                info = report.get("assembly_info", {})
                requested = plan["association_accession"]
                if plan["association_kind"] == "biosample":
                    matched = info.get("biosample", {}).get("accession") == requested
                else:
                    matched = info.get(
                        "bioproject_accession"
                    ) == requested or requested in project_accessions(info.get("bioproject_lineage", []))
                if not matched:
                    invalid_response()
        visible = dict(report)
        if not include_annotation and not plan.get("annotation"):
            visible.pop("annotation_info", None)
        if summary:
            visible = {
                key: value
                for key, value in visible.items()
                if key
                in {
                    "accession",
                    "current_accession",
                    "paired_accession",
                    "organism",
                    "assembly_info",
                    "assembly_stats",
                    "annotation_info",
                }
            }
        qualified.append(visible)
    result = page_payload(
        qualified,
        raw_count=len(reports),
        total=None if plan.get("taxonomy") else total,
        continuation=token,
        exhausted=token is None,
    )
    from biomedmcp.pagination import ProviderPage

    result["pagination"] = ProviderPage.model_validate(result["_provider_page"]).public_metadata()
    messages = [
        *payload.get("messages", []),
        *({"warning": report["warning"]} for report in reports if report.get("warning")),
    ]
    result["provider_messages"] = messages
    if plan.get("taxonomy"):
        result["provider_reported_total"] = total
        result["count_note"] = (
            "NCBI taxonomy total_count is deprecated for paginated results; continuation determines exhaustion."
        )
    if any(message.get("warning") for message in messages):
        result["warnings"] = [
            "NCBI supplied provider warnings; inspect provider_messages before interpreting this page."
        ]
    result["request"] = {
        "endpoint": plan["endpoint"],
        "parameters": {key: value for key, value in plan["params"].items() if key != "page_token"},
    }
    if plan.get("accession"):
        result["assembly_accession"] = plan["accession"]
    if plan.get("query_role"):
        result["query_role"] = plan["query_role"]
    if plan.get("annotation"):
        result["coordinate_system"] = (
            "Provider-native NCBI Datasets coordinates; no offset conversion is applied."
        )
    return result
