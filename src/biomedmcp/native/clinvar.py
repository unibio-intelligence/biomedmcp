"""Direct public ClinVar assertions, with exact allele checks before projection."""

import re

from ..errors import ResearchError
from .shapes import invalid_shape
from .variants import AA, protein_change

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def records(value, ids):
    result = value.get("result") if isinstance(value, dict) else None
    if not isinstance(result, dict) or result.get("uids") != ids or result.get("error") or result.get("errors"):
        invalid_shape()
    rows = []
    for uid in ids:
        row = result.get(uid)
        if (not isinstance(row, dict) or row.get("uid") != uid or row.get("error")
                or not isinstance(row.get("variation_set"), list) or not row["variation_set"]
                or not all(isinstance(v, dict) and v for v in row["variation_set"])):
            invalid_shape()
        rows.append(row)
    return rows


def exact(row, kind, identity, variants):
    if len(row["variation_set"]) != 1:
        return False
    allele = row["variation_set"][0]
    name = allele.get("variation_name")
    if not isinstance(name, str) or not name:
        invalid_shape()
    if kind == "protein":
        match = re.fullmatch(r"[^()]+\(([^()]+)\):[^ ]+ \(p\.([^()]+)\)", name)
        return bool(match and match[1] == identity["gene"] and protein_change(match[2]) == identity["change"])
    if kind == "rsid":
        xrefs = allele.get("variation_xrefs")
        if not isinstance(xrefs, list) or not all(isinstance(x, dict) for x in xrefs):
            invalid_shape()
        return any(x.get("db_source") == "dbSNP" and x.get("db_id") == identity.removeprefix("rs") for x in xrefs)
    if kind == "hgvs":
        qualified = re.sub(r"\([^()]+\)(?=:)", "", name)
        return identity == qualified.split(" ", 1)[0]
    # Coordinates alone are insufficient: preserve assembly, chromosome,
    # reference and alternate, using one allele's SPDI and assembly locations.
    locations = allele.get("variation_loc")
    spdi = allele.get("canonical_spdi")
    if not isinstance(locations, list) or not all(isinstance(v, dict) for v in locations) or not isinstance(spdi, str):
        invalid_shape()
    if any(not isinstance(v.get(key), str) for v in locations
           for key in ("assembly_name", "chr", "start", "stop")):
        invalid_shape()
    match = re.fullmatch(r"(NC_\d+\.\d+):(\d+):([ACGT]):([ACGT])", spdi)
    if not match:
        return False
    try:
        observed_kind, observed = variants.validate(
            f"{match[1]}:g.{int(match[2]) + 1}{match[3]}>{match[4]}")
    except ResearchError:
        return False
    return (observed_kind == "genomic" and observed == identity and any(
                v.get("assembly_name", "").lower() == identity["assembly"]
                and v.get("chr") == identity["chromosome"]
                and v.get("start") == str(identity["position"])
                and v.get("stop") == str(identity["position"]) for v in locations))


def project(row):
    accession = row.get("accession_version")
    if not isinstance(accession, str) or not re.fullmatch(r"VCV\d+\.\d+", accession):
        invalid_shape()
    allele = row["variation_set"][0]
    classifications = {}
    for key in ("germline_classification", "clinical_impact_classification", "oncogenicity_classification"):
        supplied = row.get(key)
        if supplied is None:
            classifications[key] = None
            continue
        if not isinstance(supplied, dict):
            invalid_shape()
        selected = {}
        for field in ("description", "review_status", "last_evaluated"):
            value = supplied.get(field)
            if value is not None and not isinstance(value, str):
                invalid_shape()
            selected[field] = value or None
        classifications[key] = selected
    return {"id": accession, "clinvar_variation_id": row["uid"], "title": allele["variation_name"],
            "canonical_spdi": allele.get("canonical_spdi"), "classifications": classifications,
            "url": f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{row['uid']}/",
            "source": "ClinVar", "source_release": accession}


async def assertions(variants, identifier, assembly):
    kind, identity = variants.validate(identifier, assembly)
    if kind == "protein":
        change = identity["change"]
        term = f'{identity["gene"]}[gene] AND {AA[change[0]]}{change[1:-1]}{AA[change[-1]]}'
    elif kind == "genomic":
        if len(identity["reference"]) != 1 or len(identity["alternate"]) != 1:
            raise ResearchError("normalization_required", "Use a transcript-qualified HGVS for indels.")
        field = "chrpos38" if identity["assembly"] == "grch38" else "chrpos37"
        term = f'{identity["chromosome"]}[chr] AND {identity["position"]}[{field}]'
    else:
        if kind == "hgvs" and not re.fullmatch(r"N[MCGP]_\d+\.\d+:[cgp]\.[A-Za-z0-9_>*=+.-]+", identity):
            raise ResearchError("unsupported_identifier", "ClinVar requires accession-qualified HGVS, rsID, gene/protein change, or explicit coordinates with assembly.")
        term = identity
    data = await variants.http.get(f"{EUTILS}/esearch.fcgi", params={
        "db": "clinvar", "term": term, "retmode": "json", "retmax": 25,
    })
    search = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(search, dict) or search.get("ERROR") or search.get("error") or search.get("errors"):
        invalid_shape()
    errors = search.get("errorlist", {})
    if not isinstance(errors, dict) or errors.get("fieldsnotfound"):
        invalid_shape()
    count, ids = search.get("count"), search.get("idlist")
    if (not isinstance(count, str) or not count.isascii() or not count.isdigit()
            or not isinstance(ids, list) or any(not isinstance(x, str) or not re.fullmatch(r"\d+", x) for x in ids)
            or len(ids) != min(25, int(count)) or len(ids) != len(set(ids))):
        invalid_shape()
    if int(count) > 25:
        raise ResearchError("ambiguous_identifier", "ClinVar discovery exceeds the exact-identity bound; use a more specific allele identifier.")
    matches = []
    if ids:
        rows = records(await variants.http.get(f"{EUTILS}/esummary.fcgi", params={
            "db": "clinvar", "id": ",".join(ids), "retmode": "json",
        }), ids)
        matches = [row for row in rows if exact(row, kind, identity, variants)]
        if not matches:
            raise ResearchError("unresolved_identity", "ClinVar candidates do not prove the requested exact allele; no absence can be inferred.")
        if len(matches) > 1:
            raise ResearchError("ambiguous_identifier", "ClinVar resolves to multiple alleles; choose a transcript-qualified HGVS or explicit coordinates.")
    rows = [project(row) for row in matches]
    return {"record_type": "clinvar_assertions", "records": rows,
            "source_release": rows[0]["source_release"] if rows else None,
            "coverage": {"scope": "ClinVar indexed public variant assertions", "candidates_checked": len(ids)},
            "interpretation": "Source-submitted germline, clinical-impact and oncogenicity classifications are distinct assertions. "
                              "Missing classifications are unknown; these records are not medical advice or independent validation."}
