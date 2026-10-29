"""Licensed AlphaMissense scores with exact protein/allele context and no aggregator."""

import csv
import hashlib
import io
import math
import re

from ..errors import ResearchError
from .http import segment
from .shapes import invalid_shape
from .variants import Variants

CLASSES = {"LBen": "likely_benign", "Amb": "ambiguous", "LPath": "likely_pathogenic"}
INTERPRETATION = (
    "AlphaMissense computational missense-effect prediction, not a clinical classification, "
    "patient risk, or evidence of disease causation. No other predictor is substituted."
)
ATTRIBUTION = (
    "AlphaMissense predictions © 2023 DeepMind Technologies Limited, CC BY 4.0; "
    "Cheng et al., Science (2023), https://doi.org/10.1126/science.adg7492. "
    "Extracted and normalized from the named provider; no endorsement is implied."
)


def score(value, classification):
    if (
        type(value) not in {int, float}
        or not math.isfinite(value)
        or not 0 <= value <= 1
        or not isinstance(classification, str)
        or classification not in set(CLASSES.values())
    ):
        invalid_shape()
    # Providers publish rounded scores; permit half a four-decimal unit at the
    # documented boundaries, without deriving or replacing their class.
    rounding = 0.00005
    if (
        classification == "likely_benign"
        and value > 0.34 + rounding
        or classification == "ambiguous"
        and not 0.34 - rounding <= value <= 0.564 + rounding
        or classification == "likely_pathogenic"
        and value < 0.564 - rounding
    ):
        invalid_shape()
    return {"predictor": "AlphaMissense", "score": value, "classification": classification}


def plan(identifier, assembly=None):
    kind, identity = Variants().validate(identifier, assembly)
    if kind == "protein":
        change = identity["change"]
        if change[-1] == "*" or change[0] == change[-1]:
            raise ResearchError(
                "unsupported_variant", "AlphaMissense supports amino-acid substitutions only."
            )
    if kind == "genomic" and (len(identity["reference"]) != 1 or len(identity["alternate"]) != 1):
        raise ResearchError(
            "unsupported_variant", "AlphaMissense genomic scores require a single-nucleotide substitution."
        )
    return kind, identity


async def acquire(http, identifier, assembly=None):
    kind, identity = plan(identifier, assembly)
    payload = (
        await protein(http, identity) if kind == "protein" else await vep(http, identifier, kind, identity)
    )
    return {
        "record_type": "alphamissense_predictions",
        "query": identifier,
        **payload,
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": ATTRIBUTION,
        "interpretation": INTERPRETATION,
    }


async def canonical_protein(http, identity):
    gene, change = identity["gene"], identity["change"]
    response = await http.get(
        "https://rest.uniprot.org/uniprotkb/search",
        params={
            "query": f"gene_exact:{gene} AND organism_id:9606 AND reviewed:true",
            "format": "json",
            "size": 2,
        },
    )
    rows = response.get("results") if isinstance(response, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        invalid_shape()
    if len(rows) > 2 or any(
        not isinstance(row.get("genes"), list)
        or any(not isinstance(g, dict) or not isinstance(g.get("geneName", {}), dict) for g in row["genes"])
        or any(not isinstance(row.get(k), dict) for k in ("sequence", "entryAudit", "organism"))
        for row in rows
    ):
        invalid_shape()
    matched = [
        row
        for row in rows
        if any(
            isinstance(g.get("geneName", {}).get("value"), str)
            and g["geneName"]["value"].casefold() == gene.casefold()
            for g in row["genes"]
        )
    ]
    if len(matched) != 1 or len(rows) > 1:
        raise ResearchError(
            "ambiguous_identifier" if rows else "unresolved_identity",
            "Select one exact reviewed human protein before requesting predictions.",
        )
    row = matched[0]
    gene = next(
        g["geneName"]["value"]
        for g in row["genes"]
        if isinstance(g.get("geneName", {}).get("value"), str)
        and g["geneName"]["value"].casefold() == gene.casefold()
    )
    accession = row.get("primaryAccession")
    sequence = row.get("sequence", {}).get("value")
    sequence_version = row.get("entryAudit", {}).get("sequenceVersion")
    if (
        not isinstance(accession, str)
        or not re.fullmatch(r"[A-Z0-9]{6,10}", accession)
        or row.get("organism", {}).get("taxonId") != 9606
        or row.get("entryType") != "UniProtKB reviewed (Swiss-Prot)"
        or not isinstance(sequence, str)
        or not re.fullmatch(r"[A-Z]+", sequence)
        or type(sequence_version) is not int
        or sequence_version < 1
    ):
        invalid_shape()
    if len(sequence) > 5000:
        raise ResearchError(
            "unsupported_variant",
            "This protein exceeds the bounded score-file window; use an exact genomic substitution through Ensembl.",
        )
    position = int(change[1:-1])
    if position > len(sequence) or sequence[position - 1] != change[0]:
        raise ResearchError(
            "identity_mismatch", "The reference amino acid does not match this canonical protein sequence."
        )
    return {
        "gene": gene,
        "change": change,
        "accession": accession,
        "sequence": sequence,
        "sequence_version": sequence_version,
        "entry": row.get("uniProtkbId"),
    }


async def protein(http, identity):
    resolved = await canonical_protein(http, identity)
    gene, change, accession, sequence, sequence_version = (
        resolved[k] for k in ("gene", "change", "accession", "sequence", "sequence_version")
    )
    metadata = await http.get("https://alphafold.ebi.ac.uk/api/prediction/" + accession)
    if not isinstance(metadata, list) or len(metadata) != 1 or not isinstance(metadata[0], dict):
        invalid_shape()
    meta = metadata[0]
    url = f"https://alphafold.ebi.ac.uk/files/AF-{accession}-F1-aa-substitutions.csv"
    if (
        meta.get("uniprotAccession") != accession
        or meta.get("uniprotSequence") != sequence
        or meta.get("uniprotStart") != 1
        or meta.get("uniprotEnd") != len(sequence)
    ):
        raise ResearchError(
            "identity_mismatch", "AlphaMissense and UniProt protein identity/sequence do not match."
        )
    if not meta.get("amAnnotationsUrl"):
        raise ResearchError("source_unavailable", "This protein has no supplied AlphaMissense score file.")
    if meta["amAnnotationsUrl"] != url:
        raise ResearchError(
            "identity_mismatch", "The supplied AlphaMissense score URL does not match this protein."
        )
    text = await http.get(url, text=True)
    if not isinstance(text, str) or len(text.encode()) > 4_000_000:
        raise ResearchError(
            "response_too_large", "AlphaMissense protein score file exceeds its bounded read."
        )
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["protein_variant", "am_pathogenicity", "am_class"]:
        invalid_shape()
    found, seen = [], set()
    try:
        for item in reader:
            variant = item.get("protein_variant", "")
            match = re.fullmatch(r"([ACDEFGHIKLMNPQRSTVWY])([1-9]\d*)([ACDEFGHIKLMNPQRSTVWY])", variant)
            if (
                set(item) != {"protein_variant", "am_pathogenicity", "am_class"}
                or not match
                or variant in seen
                or len(seen) >= 100000
                or int(match[2]) > len(sequence)
                or sequence[int(match[2]) - 1] != match[1]
                or match[1] == match[3]
                or item.get("am_class") not in CLASSES
            ):
                invalid_shape()
            seen.add(variant)
            prediction = score(float(item["am_pathogenicity"]), CLASSES[item["am_class"]])
            if variant == change:
                found.append(
                    {
                        **prediction,
                        "protein_variant": change,
                        "uniprot_id": accession,
                        "gene": gene,
                        "sequence_version": sequence_version,
                    }
                )
    except (ValueError, TypeError, KeyError, csv.Error):
        invalid_shape()
    if not seen or not found:
        raise ResearchError(
            "source_unavailable",
            "The score file did not supply the requested substitution; no effect can be inferred.",
        )
    sha = hashlib.sha256(text.encode()).hexdigest()
    return {
        "records": found,
        "source_release": "AlphaMissense score file sha256:" + sha,
        "source_url": url,
        "score_artifact_sha256": sha,
        "protein_identity": {
            "uniprot_id": accession,
            "gene": gene,
            "sequence_version": sequence_version,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
        },
        "coverage": {
            "scope": "Exact canonical human protein substitution; no genomic allele inferred.",
            "returned": len(found),
            "exact_dataset_release_reported": False,
        },
    }


async def vep(http, identifier, kind, identity):
    build = identity["assembly"] if kind == "genomic" else "grch38"
    base = "https://grch37.rest.ensembl.org" if build == "grch37" else "https://rest.ensembl.org"
    value = (
        f"{identity['chromosome']}:g.{identity['position']}{identity['reference']}>{identity['alternate']}"
        if kind == "genomic"
        else identity
    )
    route = "id" if kind == "rsid" else "hgvs"
    if kind == "genomic":
        # Coordinates already identify one forward-strand allele. Avoid the
        # expensive chromosome HGVS resolver; verify the returned reference too.
        route = "region"
        value = f"{identity['chromosome']}:{identity['position']}-{identity['position']}:1/{identity['alternate']}"
    expected_input = (
        f"{identity['chromosome']} {identity['position']} {identity['position']} "
        f"{identity['reference']}/{identity['alternate']} 1"
        if kind == "genomic"
        else value
    )
    wire_id = segment(value)
    if kind == "genomic":
        wire_id = segment(value.rsplit("/", 1)[0]) + "/" + segment(identity["alternate"])
    raw = await http.get(
        base + "/vep/human/" + route + "/" + wire_id,
        params={
            "AlphaMissense": 1,
            "protein": 1,
            "content-type": "application/json",
        },
    )
    if not isinstance(raw, list) or not raw or len(raw) > 10 or any(not isinstance(r, dict) for r in raw):
        invalid_shape()
    records, mappings, seen = [], [], set()
    for row in raw:
        chrom, start, end, alleles = (
            row.get(k) for k in ("seq_region_name", "start", "end", "allele_string")
        )
        if (
            row.get("input") != expected_input
            or row.get("assembly_name") != ("GRCh37" if build == "grch37" else "GRCh38")
            or not isinstance(chrom, str)
            or not re.fullmatch(r"(?:[1-9]|1\d|2[0-2]|X|Y|MT)", chrom)
            or type(start) is not int
            or type(end) is not int
            or start < 1
            or end < start
            or type(row.get("strand")) is not int
            or row["strand"] != 1
            or not isinstance(alleles, str)
        ):
            raise ResearchError(
                "identity_mismatch", "Ensembl did not prove the submitted variant and assembly."
            )
        variants = alleles.split("/")
        if kind == "rsid" and row.get("id") != identity:
            raise ResearchError("identity_mismatch", "Ensembl returned a different rsID.")
        if kind == "genomic" and (
            chrom != identity["chromosome"].replace("M", "MT")
            or start != identity["position"]
            or end != start
            or variants != [identity["reference"], identity["alternate"]]
        ):
            raise ResearchError("identity_mismatch", "Ensembl returned a different allele or reference base.")
        mappings.append(
            {
                "assembly": row["assembly_name"],
                "chromosome": chrom,
                "start": start,
                "end": end,
                "alleles": variants,
            }
        )
        consequences = row.get("transcript_consequences", [])
        if not isinstance(consequences, list) or len(consequences) > 2000:
            invalid_shape()
        for t in consequences:
            if not isinstance(t, dict):
                invalid_shape()
            if "alphamissense" not in t:
                continue
            am = t["alphamissense"]
            if (
                not isinstance(am, dict)
                or not isinstance(t.get("transcript_id"), str)
                or not re.fullmatch(r"ENST\d+", t["transcript_id"])
                or not isinstance(t.get("gene_id"), str)
                or not re.fullmatch(r"ENSG\d+", t["gene_id"])
                or t.get("variant_allele") not in variants[1:]
                or not isinstance(t.get("consequence_terms"), list)
                or any(not isinstance(term, str) for term in t["consequence_terms"])
                or "missense_variant" not in t["consequence_terms"]
                or (t.get("gene_symbol") is not None and not isinstance(t["gene_symbol"], str))
                or not isinstance(t.get("amino_acids"), str)
                or not re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]/[ACDEFGHIKLMNPQRSTVWY]", t["amino_acids"])
                or type(t.get("protein_start")) is not int
                or t["protein_start"] < 1
                or t.get("protein_end") != t["protein_start"]
            ):
                invalid_shape()
            prediction = score(am.get("am_pathogenicity"), am.get("am_class"))
            prediction.update(
                transcript_id=t["transcript_id"],
                gene_id=t["gene_id"],
                gene=t.get("gene_symbol"),
                variant_allele=t["variant_allele"],
                protein_variant=t["amino_acids"][0] + str(t["protein_start"]) + t["amino_acids"][-1],
                genomic_mapping=mappings[-1],
            )
            key = (t["transcript_id"], t["variant_allele"], chrom, start)
            if key in seen:
                raise ResearchError(
                    "invalid_source_response", "Duplicate transcript/allele prediction context."
                )
            seen.add(key)
            records.append(prediction)
    release = await http.get(base + "/info/software", params={"content-type": "application/json"})
    if not isinstance(release, dict) or type(release.get("release")) is not int or release["release"] < 1:
        invalid_shape()
    return {
        "records": records,
        "source_url": base + "/documentation/info/vep_" + route + "_get",
        "source_release": "Ensembl VEP "
        + str(release["release"])
        + "; AlphaMissense dataset release not reported",
        "genomic_mappings": mappings,
        "coverage": {
            "scope": "All supplied scored transcript/allele contexts; rsIDs may be multiallelic.",
            "returned": len(records),
            "exact_dataset_release_reported": False,
            "score_status": "supplied" if records else "no_missense_prediction_supplied",
        },
    }
