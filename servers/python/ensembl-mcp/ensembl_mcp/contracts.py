"""Minimum genome-info shapes from Ensembl REST 45d2746 (2026-10-12).

Validate acquisition before composition. Empty karyotype lists are explicit
provider metadata, not evidence that an organism has no chromosomes.
"""

import math
import re

from biomedmcp.errors import invalid_parameters
from biomedmcp.native.shapes import collection, invalid_shape


def species_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value):
        raise invalid_parameters()
    return {"human": "homo_sapiens", "mouse": "mus_musculus", "rat": "rattus_norvegicus"}.get(value, value)


def preflight(operation, params):
    species_name(params.get("species", "homo_sapiens"))
    if params.get("target_species") is not None:
        species_name(params["target_species"])
    if (
        operation == "analyze_evolution"
        and params.get("analysis_type") == "gene_tree"
        and params.get("target_species")
    ):
        raise invalid_parameters()
    for key in ("gene_id",):
        if key in params:
            identifier(params[key])
    if operation == "query_genes":
        if params.get("query_type", "symbol") == "id":
            identifier(params.get("query"))
        else:
            token(params.get("query"))
    if operation == "batch_gene_lookup":
        ids = params.get("gene_ids")
        if (
            not isinstance(ids, list)
            or not 1 <= len(ids) <= 1000
            or any(not isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids)
        ):
            raise invalid_parameters()
        for value in ids:
            identifier(value)
    for key in ("source_assembly", "target_assembly", "external_db"):
        if params.get(key) is not None:
            token(params[key])
    if "region" in params:
        region(params["region"])
    if operation == "analyze_variants":
        if params.get("analysis_type", "variants") == "variants":
            region(params.get("region_or_id"))
        else:
            token(params.get("region_or_id"))


def token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise invalid_parameters()
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"ENS[A-Z]*[GTP][0-9]+(?:\.[1-9][0-9]*)?", value):
        raise invalid_parameters()
    return value


def region(value):
    if not isinstance(value, str):
        raise invalid_parameters()
    match = re.fullmatch(
        r"([A-Za-z0-9][A-Za-z0-9_.-]{0,127}):([1-9][0-9]*)(?:-|\.\.)([1-9][0-9]*)(?::(-?1))?", value or ""
    )
    if not match:
        raise invalid_parameters()
    name, start, end, strand = match.groups()
    start, end = int(start), int(end)
    if end < start or end - start + 1 > 5_000_000:
        raise invalid_parameters()
    return name, start, end, int(strand or 1)


def _text(value):
    if not isinstance(value, str) or not value.strip():
        invalid_shape()
    return value


def _object(value):
    if not isinstance(value, dict) or not value or value.get("error") or value.get("errors"):
        invalid_shape()
    return value


def _number(value, minimum=0, maximum=None):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        invalid_shape()
    return value


def _positive(value):
    if type(value) is not int or value < 1:
        invalid_shape()
    return value


def lookup(value, species, expected=None, gene_only=False, expanded=False):
    value = _object(value)
    reported = _text(value.get("id"))
    found = reported.split(".")[0]
    kind = value.get("object_type")
    if kind not in ({"Gene"} if gene_only else {"Gene", "Transcript", "Translation"}):
        invalid_shape()
    if value.get("species") != species or not re.fullmatch(r"ENS[A-Z]*[GTP][0-9]+", found):
        invalid_shape()
    if not re.fullmatch(
        r"ENS[A-Z]*" + {"Gene": "G", "Transcript": "T", "Translation": "P"}[kind] + r"[0-9]+", found
    ):
        invalid_shape()
    if kind != "Translation" or "assembly_name" in value:
        _text(value.get("assembly_name"))
    _positive(value.get("version"))
    if "." in reported and reported != f"{found}.{value['version']}":
        invalid_shape()
    if expected:
        parts = expected.split(".")
        if found != parts[0] or (len(parts) == 2 and value["version"] != int(parts[1])):
            invalid_shape()
    if expanded:
        for transcript in collection(value, ("Transcript",)):
            lookup(transcript, species, gene_only=False)
            if transcript["object_type"] != "Transcript" or transcript.get("Parent") != found:
                invalid_shape()
    return value


def sequences(value, identity, sequence_type):
    rows = collection(value, ())
    if not rows:
        # The source emits an HTTP not-found response when no sequences exist.
        invalid_shape()
    molecule = "protein" if sequence_type == "protein" else "dna"
    pattern = r"[A-Z*]+" if molecule == "protein" else r"[ACGTRYSWKMBDHVNU]+"
    prefix = re.fullmatch(r"(ENS[A-Z]*)[GTP][0-9]+", identity["id"])[1]
    for row in rows:
        if row.get("query") != identity["id"] or row.get("molecule") != molecule:
            invalid_shape()
        _positive(row.get("version"))
        found = _text(row.get("id"))
        if not re.fullmatch(r"ENS[A-Z]*[GTP][0-9]+", found):
            invalid_shape()
        kind = (
            "P"
            if molecule == "protein"
            else ("T" if sequence_type != "genomic" else identity["id"][len(prefix)])
        )
        if not re.fullmatch(re.escape(prefix) + kind + r"[0-9]+", found):
            invalid_shape()
        seq = _text(row.get("seq"))
        if not re.fullmatch(pattern, seq) or len(seq) > 10_000_000:
            invalid_shape()
        if sequence_type == "genomic" and (found != identity["id"] or row["version"] != identity["version"]):
            invalid_shape()
    return rows


def homology(value, identity, analysis_type, target_species=None):
    entries = collection(value, ("data",))
    if len(entries) > 1:
        invalid_shape()
    for entry in entries:
        if entry.get("id") != identity["id"]:
            invalid_shape()
        for row in collection(entry, ("homologies",)):
            relation = _text(row.get("type"))
            if analysis_type == "orthologs" and "ortholog" not in relation:
                invalid_shape()
            if analysis_type == "paralogs" and "paralog" not in relation:
                invalid_shape()
            _text(row.get("method_link_type"))
            partners = [_object(row.get(key)) for key in ("source", "target")]
            for partner in partners:
                _text(partner.get("id"))
                _text(partner.get("species"))
                _text(partner.get("protein_id"))
                _number(partner.get("perc_id"), maximum=100)
                _number(partner.get("perc_pos"), maximum=100)
                if not any(
                    isinstance(partner.get(key), str) and partner[key] for key in ("seq", "align_seq")
                ):
                    invalid_shape()
            # Source/target ordering comes from Compara; do not assume the
            # submitted member must be the first partner.
            indices = [
                i
                for i, p in enumerate(partners)
                if p["id"] == identity["id"] and p["species"] == identity["species"]
            ]
            if not indices or (
                target_species and not any(partners[1 - i]["species"] == target_species for i in indices)
            ):
                invalid_shape()
            if row.get("dn_ds") is not None:
                _number(row["dn_ds"])
    return value


def gene_tree(value, identity):
    value = _object(value)
    if value.get("type") != "gene tree" or value.get("rooted") not in (1, True):
        invalid_shape()
    if not re.fullmatch(r"ENSGT[0-9]+", _text(value.get("id"))):
        invalid_shape()
    stack, count, matched = [(value.get("tree"), 0)], 0, False
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 10_000 or depth > 128:
            invalid_shape()
        node = _object(node)
        _number(node.get("branch_length"), minimum=None)
        if "confidence" in node:
            confidence = node["confidence"]
            if not isinstance(confidence, dict):
                invalid_shape()
            for score in confidence.values():
                _number(score)
        if "children" in node:
            children = collection(node, ("children",))
            if not children:
                invalid_shape()
            stack.extend((child, depth + 1) for child in children)
        else:
            accession = _object(node.get("id"))
            sequence = _object(node.get("sequence"))
            if accession.get("source") != "EnsEMBL":
                invalid_shape()
            _text(accession.get("accession"))
            sequence_ids = collection(sequence, ("id",))
            if not sequence_ids:
                invalid_shape()
            for seq_id in sequence_ids:
                if seq_id.get("source") != "EnsEMBL":
                    invalid_shape()
                _text(seq_id.get("accession"))
            mol = _object(sequence.get("mol_seq"))
            _text(mol.get("seq"))
            if type(mol.get("is_aligned")) not in (bool, int) or mol["is_aligned"] not in (0, 1):
                invalid_shape()
            taxon = _object(node.get("taxonomy"))
            _positive(taxon.get("id"))
            scientific = _text(taxon.get("scientific_name"))
            if accession["accession"] == identity["id"]:
                if scientific.lower().replace(" ", "_") != identity["species"]:
                    invalid_shape()
                matched = True
    if not matched:
        invalid_shape()
    return value


def _coordinates(value, insertion=False):
    value = _object(value)
    _text(value.get("seq_region_name"))
    start = _positive(value.get("start"))
    end = value.get("end")
    if type(end) is not int or end < start - int(insertion):
        invalid_shape()
    if type(value.get("strand")) is not int or value["strand"] not in {-1, 0, 1}:
        invalid_shape()
    return start, end


def overlap(value, requested_region, features):
    name, start, end, _ = region(requested_region)
    rows = collection(value, ())
    for row in rows:
        feature = row.get("feature_type")
        if feature not in features or row.get("seq_region_name") not in {name, name.removeprefix("chr")}:
            invalid_shape()
        left, right = _coordinates(row, insertion=feature == "variation")
        _text(row.get("id"))
        _text(row.get("assembly_name"))
        if left > end + int(feature == "variation") or right < start - int(feature == "variation"):
            invalid_shape()
    return rows


def mappings(value, requested_region, source_assembly, target_assembly):
    name, start, end, strand = region(requested_region)
    for row in collection(value, ("mappings",)):
        original, mapped = _object(row.get("original")), _object(row.get("mapped"))
        left, right = _coordinates(original)
        _coordinates(mapped)
        for coords, expected in ((original, source_assembly), (mapped, target_assembly)):
            _text(coords.get("coord_system"))
            if coords.get("assembly") != expected or coords["strand"] not in {-1, 1}:
                invalid_shape()
        if (
            original["seq_region_name"] not in {name, name.removeprefix("chr")}
            or left < start
            or right > end
            or original["strand"] != strand
        ):
            invalid_shape()
    return value


def consequences(value, identifier):
    rows = collection(value, ())
    for row in rows:
        if row.get("input") != identifier:
            invalid_shape()
        _coordinates(row, insertion=True)
        _text(row.get("assembly_name"))
        _text(row.get("most_severe_consequence"))
        selected = [
            key
            for key in (
                "transcript_consequences",
                "intergenic_consequences",
                "regulatory_feature_consequences",
                "motif_feature_consequences",
            )
            if key in row
        ]
        if not selected:
            invalid_shape()
        count = 0
        for key in selected:
            for consequence in collection(row, (key,)):
                count += 1
                terms = consequence.get("consequence_terms")
                if not isinstance(terms, list) or not terms:
                    invalid_shape()
                for term in terms:
                    _text(term)
        if not count:
            invalid_shape()
    return rows


def assembly(value):
    regions = collection(value, ("top_level_region",))
    _text(value.get("assembly_name"))
    karyotype = value.get("karyotype")
    if not isinstance(karyotype, list):
        invalid_shape()
    for name in karyotype:
        _text(name)
    for region in regions:
        _text(region.get("name"))
        _text(region.get("coord_system"))
        length = region.get("length")
        if type(length) is not int or length < 1:
            invalid_shape()
    return value


def species_catalog(value):
    for record in collection(value, ("species",)):
        _text(record.get("name"))
        _text(record.get("assembly"))
    return value


def project_assembly(value):
    """Fixed Ensembl inventory facts, excluding imported annotation payloads."""
    assembly(value)
    result = {key: value[key] for key in ("assembly_name", "karyotype")}
    result["top_level_region"] = [
        {key: region[key] for key in ("name", "coord_system", "length")}
        for region in value["top_level_region"]
    ]
    for key in ("assembly_accession", "assembly_date", "default_coord_system_version"):
        if key in value:
            result[key] = None if value[key] is None else _text(value[key])
    if "golden_path_length" in value:
        result["golden_path_length"] = _positive(value["golden_path_length"])
    return result


def project_species(value):
    species_catalog(value)
    rows = []
    for record in value["species"]:
        row = {key: record[key] for key in ("name", "assembly")}
        for key in ("taxon_id", "release"):
            if key in record:
                row[key] = _positive(record[key])
        if "division" in record:
            row["division"] = _text(record["division"])
        rows.append(row)
    return {"species": rows}
