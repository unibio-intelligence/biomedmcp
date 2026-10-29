"""Native exact-variant resolution and evidence. No clinical classification is inferred."""

import re

from ..errors import ResearchError
from ..pagination import page_payload
from .http import ProviderHTTP, segment
from .myvariant import direct_response, query_response
from .shapes import invalid_shape

MYVARIANT = "https://myvariant.info/v1"
AA = dict(
    zip(
        "ACDEFGHIKLMNPQRSTVWY*",
        [
            "Ala",
            "Cys",
            "Asp",
            "Glu",
            "Phe",
            "Gly",
            "His",
            "Ile",
            "Lys",
            "Leu",
            "Met",
            "Asn",
            "Pro",
            "Gln",
            "Arg",
            "Ser",
            "Thr",
            "Val",
            "Trp",
            "Tyr",
            "Ter",
        ],
    )
)
AA_REVERSE = {v: k for k, v in AA.items()}


def protein_change(value):
    if not isinstance(value, str):
        return None
    value = value.rsplit(":", 1)[-1].removeprefix("p.")
    match = re.fullmatch(r"([A-Z]|[A-Z][a-z]{2})([1-9]\d*)([A-Z*]|[A-Z][a-z]{2})", value)
    if not match:
        return None
    ref, pos, alt = match.groups()
    ref = AA_REVERSE.get(ref, ref)
    alt = AA_REVERSE.get(alt, alt)
    if ref not in AA or alt not in AA:
        return None
    return f"{ref}{pos}{alt}"


def as_list(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def exact_annotations(hit, gene, change):
    """Accept conjunctive annotation records, never independent parallel arrays."""
    annotations = as_list((hit.get("snpeff") or {}).get("ann"))
    matched = [
        a
        for a in annotations
        if isinstance(a, dict) and a.get("genename") == gene and protein_change(a.get("hgvs_p", "")) == change
    ]
    if matched:
        return matched
    # A single-gene/single-change annotation is safe; a cartesian join is not.
    db = hit.get("dbnsfp") or {}
    genes = as_list(db.get("genename"))
    changes = as_list(db.get("hgvsp"))
    if len(genes) == len(changes) == 1 and genes[0] == gene and protein_change(changes[0]) == change:
        return [{"genename": gene, "hgvs_p": changes[0]}]
    return []


def require_identity_evidence(hit, kind, identity):
    """A candidate without the requested identity fields cannot prove no match."""
    annotations = as_list(hit.get("snpeff", {}).get("ann"))
    if kind == "rsid":
        if not as_list(hit.get("dbsnp", {}).get("rsid")):
            invalid_shape()
    elif kind == "protein":
        db = hit.get("dbnsfp", {})
        genes, changes = as_list(db.get("genename")), as_list(db.get("hgvsp"))
        if (len(genes) > 1 or len(changes) > 1) and not exact_annotations(
            hit, identity["gene"], identity["change"]
        ):
            raise ResearchError(
                "ambiguous_identifier",
                "Parallel protein annotations do not establish a conjunctive gene/change identity.",
            )
        qualified = any(a.get("genename") and protein_change(a.get("hgvs_p")) for a in annotations)
        if not qualified and not (genes and changes and any(protein_change(c) for c in changes)):
            invalid_shape()
    elif kind == "hgvs" and hit["_id"] != identity:
        field = "hgvs_p" if ":p." in identity else "hgvs_c"
        if not any(a.get("feature_id") and a.get(field) for a in annotations):
            invalid_shape()


def genomic_identity(value, assembly="grch38"):
    match = re.fullmatch(r"(?i)chr([1-9]|1\d|2[0-2]|X|Y|M):([1-9]\d*):([ACGT]+):([ACGT]+)", value)
    if not match:
        return None
    chrom, pos, ref, alt = match.groups()
    if ref.upper() == alt.upper():
        raise ResearchError("invalid_identifier", "Reference and alternate allele must differ.")
    return {
        "chromosome": chrom.upper(),
        "position": int(pos),
        "reference": ref.upper(),
        "alternate": alt.upper(),
        "assembly": assembly,
    }


def search_filters(query, filters):
    """Reconcile explicit filters with a conjunctive protein shorthand."""
    shorthand = re.fullmatch(r"([A-Za-z0-9_.-]+) (?:p\.)?([A-Z][1-9]\d*[A-Z*])", query)
    if not shorthand:
        return query, filters
    gene, change = shorthand.groups()
    gene = gene.upper()
    if (
        filters.get("gene")
        and filters["gene"].upper() != gene
        or filters.get("hgvsp")
        and protein_change(filters["hgvsp"]) != change
    ):
        raise ResearchError(
            "invalid_parameters", "Variant shorthand and explicit gene/protein filters must agree."
        )
    return "*", {**filters, "gene": gene, "hgvsp": change}


class Variants:
    def __init__(self, http=None):
        self.http = http or ProviderHTTP()

    def validate(self, identifier, assembly=None):
        genomic = genomic_identity(identifier, assembly or "grch38")
        if assembly and not genomic:
            raise ResearchError(
                "invalid_assembly", "Assembly applies to explicit chromosome coordinates only."
            )
        if genomic:
            return "genomic", genomic
        accession = re.fullmatch(
            r"NC_0000(0[1-9]|1[0-9]|2[0-4])\.(\d+):g\.([1-9]\d*)([ACGT])>([ACGT])", identifier
        )
        if accession:
            chromosome, version, position, ref, alt = accession.groups()
            number = int(chromosome)
            # Human RefSeq chromosome accessions carry their assembly version.
            grch37 = [10, 11, 11, 11, 9, 11, 13, 10, 11, 10, 9, 11, 10, 8, 9, 9, 10, 9, 9, 10, 8, 10, 10, 9]
            grch38 = [
                11,
                12,
                12,
                12,
                10,
                12,
                14,
                11,
                12,
                11,
                10,
                12,
                11,
                9,
                10,
                10,
                11,
                10,
                10,
                11,
                9,
                11,
                11,
                10,
            ]
            build = (
                "grch37"
                if int(version) == grch37[number - 1]
                else "grch38"
                if int(version) == grch38[number - 1]
                else None
            )
            if not build:
                raise ResearchError(
                    "unsupported_assembly",
                    "RefSeq accession version is not a supported human chromosome assembly.",
                )
            chrom = "X" if number == 23 else "Y" if number == 24 else str(number)
            return "genomic", genomic_identity(f"chr{chrom}:{position}:{ref}:{alt}", build)
        match = re.fullmatch(r"([A-Za-z0-9_.-]{1,40})\s+(?:p\.)?(.+)", identifier)
        if match and protein_change(match[2]):
            return "protein", {"gene": match[1].upper(), "change": protein_change(match[2])}
        if re.fullmatch(r"rs\d+", identifier, re.IGNORECASE):
            return "rsid", identifier.lower()
        if re.fullmatch(r"(?:chr[0-9XYM]+:g\.|N[MCGP]_\d+(?:\.\d+)?:[cgp]\.).+", identifier, re.IGNORECASE):
            return "hgvs", identifier
        raise ResearchError(
            "invalid_identifier",
            "Use a qualified HGVS identifier, rsID, gene plus exact protein change, or chr:position:ref:alt with assembly.",
        )

    async def resolve(self, identifier, assembly=None):
        kind, identity = self.validate(identifier, assembly)
        complete = True
        if kind == "protein":
            change = identity["change"]
            long = f"p.{AA[change[0]]}{change[1:-1]}{AA[change[-1]]}"
            query = f'(dbnsfp.genename:"{identity["gene"]}" OR snpeff.ann.genename:"{identity["gene"]}") AND (dbnsfp.hgvsp:*{long} OR snpeff.ann.hgvs_p:{long} OR snpeff.ann.hgvs_p:p.{change})'
        elif kind == "genomic":
            if len(identity["reference"]) != 1 or len(identity["alternate"]) != 1:
                raise ResearchError(
                    "normalization_required",
                    "Use an accession-qualified HGVS for indels, or ClinGen normalization before lookup.",
                )
            query = f"chr{identity['chromosome']}:g.{identity['position']}{identity['reference']}>{identity['alternate']}"
        else:
            query = f"dbsnp.rsid:{identity}" if kind == "rsid" else f'_id:"{identity}"'
        if kind == "genomic" or (kind == "hgvs" and identity.startswith("chr")):
            lookup = query if kind == "genomic" else identity
            params = {
                "fields": "all",
                "assembly": {"grch37": "hg19", "grch38": "hg38"}[
                    identity["assembly"] if kind == "genomic" else "grch37"
                ],
            }
            data = await self.http.get(f"{MYVARIANT}/variant/{segment(lookup)}", params=params)
            hits = direct_response(data)
        else:
            if kind == "hgvs":
                accession, change = identity.split(":", 1)
                field = "hgvs_p" if change.startswith("p.") else "hgvs_c"
                query = f'snpeff.ann.feature_id:"{accession}" AND snpeff.ann.{field}:"{change}"'
            params = {"q": query, "size": 25, "fields": "all"}
            data = await self.http.get(f"{MYVARIANT}/query", params=params)
            hits, total = query_response(data)
            complete = len(hits) == total
        raw_count = len(hits)
        for hit in hits:
            require_identity_evidence(hit, kind, identity)
        if kind == "protein":
            hits = [
                {**h, "matched_annotations": exact_annotations(h, identity["gene"], identity["change"])}
                for h in hits
                if exact_annotations(h, identity["gene"], identity["change"])
            ]
        if kind == "rsid":
            hits = [h for h in hits if identity in as_list((h.get("dbsnp") or {}).get("rsid"))]
        elif kind in {"hgvs", "genomic"}:
            expected = query if kind == "genomic" else identity

            # Transcript HGVS needs a matching conjunctive annotation, not an
            # unrelated consequence elsewhere in the returned allele record.
            def exact_hgvs(hit):
                if hit.get("_id") == expected:
                    return True
                return any(
                    expected
                    == str(a.get("feature_id", ""))
                    + ":"
                    + str(a.get("hgvs_p" if ":p." in expected else "hgvs_c", ""))
                    for a in as_list((hit.get("snpeff") or {}).get("ann"))
                    if isinstance(a, dict)
                )

            hits = [h for h in hits if exact_hgvs(h)]
            if kind == "genomic" and not hits:
                raise ResearchError(
                    "identity_mismatch", "MyVariant direct lookup returned a different allele."
                )
        if len(hits) > 1 or not complete:
            return {
                "resolution": "ambiguous",
                "query": identifier,
                "candidates": hits,
                "warning": "Select an exact allele/transcript before joining downstream evidence; a bounded candidate window cannot establish uniqueness or absence.",
                "candidate_window": {
                    "complete": complete,
                    "returned": raw_count,
                    "total": total if not complete else raw_count,
                    "limit": 25,
                },
            }
        if not hits:
            return {"resolution": "empty", "query": identifier, "candidates": []}
        return {
            "resolution": "exact",
            "query": identifier,
            "identity": identity,
            "annotation": hits[0],
            "assembly": identity.get("assembly", "grch37") if isinstance(identity, dict) else "grch37",
            "id": hits[0].get("_id"),
            "source": "myvariant",
        }

    async def search(self, query, filters, limit, offset=0):
        # Protein shorthand is a conjunctive scientific identity, not free text.
        query, filters = search_filters(query, filters)
        clauses = [query]
        mapping = {
            "gene": "dbnsfp.genename",
            "significance": "clinvar.rcv.clinical_significance",
            "consequence": "cadd.consequence",
            "review_status": "clinvar.rcv.review_status",
        }
        for key, field in mapping.items():
            if filters.get(key):
                clauses.append(f'{field}:"{filters[key]}"')
        if filters.get("hgvsp"):
            normalized = protein_change(filters["hgvsp"])
            if not normalized:
                raise ResearchError("invalid_parameters", "Invalid protein change filter.")
            clauses.append(f"dbnsfp.hgvsp:*p.{AA[normalized[0]]}{normalized[1:-1]}{AA[normalized[-1]]}")
        if filters.get("max_frequency") is not None:
            clauses.append(f"gnomad_exome.af.af:[0 TO {filters['max_frequency']}]")
        if filters.get("revel_min") is not None:
            clauses.append(f"dbnsfp.revel.score:[{filters['revel_min']} TO 1]")
        result = await self.http.get(
            f"{MYVARIANT}/query",
            params={
                "q": " AND ".join(f"({c})" for c in clauses),
                "size": limit,
                "from": offset,
                "fields": "_id,dbnsfp,snpeff,clinvar,dbsnp,gnomad_exome",
            },
        )
        raw, total = query_response(result, offset=offset)
        if filters.get("gene") and filters.get("hgvsp"):
            identity = {"gene": filters["gene"], "change": protein_change(filters["hgvsp"])}
            for hit in raw:
                require_identity_evidence(hit, "protein", identity)
            result["hits"] = [
                h for h in raw if exact_annotations(h, filters["gene"], protein_change(filters["hgvsp"]))
            ]
        exhausted = offset + len(raw) >= total if total is not None else len(raw) < limit
        result["_provider_page"] = page_payload(
            result["hits"],
            raw_count=len(raw),
            total=total,
            exhausted=exhausted,
            next_offset=None if exhausted else offset + len(raw),
            filtered_count=len(raw) - len(result["hits"]),
            filtering={"exact_annotation": len(raw) - len(result["hits"])}
            if filters.get("gene") and filters.get("hgvsp")
            else {},
            exhaustion_basis="total" if total is not None else "short_window",
        )["_provider_page"]
        return result

    async def population(self, record):
        from .gnomad import population

        return await population(self.http, record)

    async def civic(
        self, focus, entity="variant", limit=10, *, collection=None, after=None, entrez_id=None, assembly=None
    ):
        from .civic import evidence

        if entity == "variant":
            kind, identity = self.validate(focus, assembly)
            if kind != "protein":
                resolved = await self.resolve(focus, assembly)
                if resolved["resolution"] != "exact":
                    raise ResearchError(
                        "ambiguous_identifier"
                        if resolved["resolution"] == "ambiguous"
                        else "unresolved_identity",
                        "CIViC requires one exact allele with a qualified gene/protein annotation.",
                    )
                annotation = resolved["annotation"]
                changes = {
                    (a["genename"], protein_change(a.get("hgvs_p")))
                    for a in as_list((annotation.get("snpeff") or {}).get("ann"))
                    if isinstance(a, dict) and a.get("genename") and protein_change(a.get("hgvs_p"))
                }
                if not changes:
                    db = annotation.get("dbnsfp") or {}
                    genes, proteins = as_list(db.get("genename")), as_list(db.get("hgvsp"))
                    if len(genes) == len(proteins) == 1 and protein_change(proteins[0]):
                        changes.add((genes[0], protein_change(proteins[0])))
                if len(changes) != 1:
                    raise ResearchError(
                        "ambiguous_identifier" if changes else "unresolved_identity",
                        "Allele annotations do not identify one conjunctive gene/protein change for CIViC.",
                    )
                gene, change = changes.pop()
                identity = {"gene": gene, "change": change}
            focus = f"{identity['gene']} {identity['change']}"
        return await evidence(
            self.http, focus, entity, limit=limit, collection=collection, after=after, entrez_id=entrez_id
        )

    async def normalize(self, hgvs):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+:[cgp]\.\S{1,300}", hgvs):
            raise ResearchError(
                "invalid_identifier", "ClinGen normalization requires accession-qualified HGVS."
            )
        from .clingen import normalization

        payload = await self.http.get("https://reg.genome.network/allele", params={"hgvs": hgvs})
        return normalization(payload, hgvs)

    async def assertions(self, caid):
        if not re.fullmatch(r"CA\d+", caid):
            raise ResearchError("invalid_identifier", "Use a ClinGen CA identifier.")
        from .clingen import assertions

        payload = await self.http.get(
            "https://erepo.clinicalgenome.org/evrepo/api/summary/classifications",
            params={"columns": "caId", "values": caid, "matchTypes": "exact", "pgSize": 25, "pg": 1},
        )
        return assertions(payload, caid)

    async def specifications(self, gene):
        if not re.fullmatch(r"[A-Z0-9_.-]{1,40}", gene):
            raise ResearchError("invalid_identifier", "Use an exact gene symbol.")
        from .clingen import specifications

        payload = await self.http.get(
            f"https://cspec.clinicalgenome.org/cspec/Gene/id/{segment(gene)}/SequenceVariantInterpretation/version",
            params={"detail": "low"},
        )
        return specifications(payload, gene)

    async def linked_data(self, caid):
        if not re.fullmatch(r"CA\d+", caid):
            raise ResearchError("invalid_identifier", "Use a ClinGen CA identifier.")
        from .clingen import linked_data

        payload = await self.http.get(
            f"https://ldh.genome.network/ldh/Variant/id/{segment(caid)}/ld", params={"detail": "med"}
        )
        return linked_data(payload, caid)
