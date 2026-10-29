"""Original MIT-licensed EVE data; canonical protein identity, no clinical bundle."""

import csv
import hashlib
import io
import math
import re
import zipfile
import zlib

from ..errors import ResearchError
from .alphamissense import canonical_protein
from .shapes import invalid_shape
from .variants import Variants

BASE = "https://evemodel.org"
NOTICE = """MIT License
Copyright (c) 2022 Joseph Min
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
AA = "ACDEFGHIKLMNPQRSTVWY"
FIELDS = {
    "wt_aa",
    "position",
    "mt_aa",
    "EVE_scores_ASM",
    "uncertainty_ASM",
    "EVE_classes_75_pct_retained_ASM",
}


def plan(identifier, assembly=None):
    kind, identity = Variants().validate(identifier, assembly)
    if (
        kind != "protein"
        or identity["change"][-1] not in AA
        or identity["change"][0] == identity["change"][-1]
    ):
        raise ResearchError(
            "unsupported_variant",
            "EVE requires a gene plus protein substitution; no genomic or transcript mapping is inferred.",
        )
    return identity


def parse_archive(raw, entry, resolved):
    if not isinstance(raw, bytes) or len(raw) > 8_000_000:
        raise ResearchError("response_too_large", "EVE protein archive exceeds its bounded read.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if (
                len(files) != 1
                or files[0].filename != entry + ".csv"
                or files[0].file_size > 16_000_000
                or files[0].flag_bits & 1
                or files[0].compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                invalid_shape()
            with archive.open(files[0]) as source:
                text = source.read(16_000_001)
            if len(text) > 16_000_000 or len(text) != files[0].file_size:
                invalid_shape()
        reader = csv.DictReader(io.StringIO(text.decode("utf-8")))
        if (
            not reader.fieldnames
            or len(set(reader.fieldnames)) != len(reader.fieldnames)
            or not FIELDS <= set(reader.fieldnames)
        ):
            invalid_shape()
        records, seen = [], set()
        sequence = resolved["sequence"]
        for row in reader:
            if None in row or not all(isinstance(row.get(k), str) for k in FIELDS):
                invalid_shape()
            ref, alt, pos = (row[k] for k in ("wt_aa", "mt_aa", "position"))
            if (
                ref not in AA
                or len(ref) != 1
                or alt not in AA
                or len(alt) != 1
                or not re.fullmatch(r"[1-9]\d{0,4}", pos)
                or int(pos) > len(sequence)
                or sequence[int(pos) - 1] != ref
                or (pos, alt) in seen
                or len(seen) >= 100000
            ):
                raise ResearchError(
                    "identity_mismatch", "EVE score rows do not match one canonical protein sequence."
                )
            seen.add((pos, alt))
            supplied = row["EVE_scores_ASM"]
            if not supplied:
                continue
            value = float(supplied)
            uncertainty = float(row["uncertainty_ASM"])
            label = row["EVE_classes_75_pct_retained_ASM"]
            if (
                not math.isfinite(value)
                or not 0 <= value <= 1
                or not math.isfinite(uncertainty)
                or uncertainty < 0
                or label not in {"Benign", "Pathogenic", "Uncertain"}
            ):
                invalid_shape()
            if ref + pos + alt == resolved["change"]:
                records.append(
                    {
                        "predictor": "EVE",
                        "model": "ASM",
                        "score": value,
                        "uncertainty": uncertainty,
                        "classification_75_pct_retained": label,
                        "protein_variant": resolved["change"],
                        "uniprot_id": resolved["accession"],
                        "gene": resolved["gene"],
                        "sequence_version": resolved["sequence_version"],
                    }
                )
        if not seen:
            invalid_shape()
        return records
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        csv.Error,
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        EOFError,
        NotImplementedError,
    ):
        invalid_shape()


async def acquire(http, identifier, assembly=None):
    identity = plan(identifier, assembly)
    resolved = await canonical_protein(http, identity)
    entry = resolved["entry"]
    if not isinstance(entry, str) or not re.fullmatch(r"[A-Z0-9_]+_HUMAN", entry):
        invalid_shape()
    protein_id = await http.get(BASE + "/api/proteins/web_pid/" + entry + "/id/")
    if protein_id is None:
        raise ResearchError(
            "source_unavailable", "EVE does not supply this protein; no effect can be inferred."
        )
    if type(protein_id) is not int or protein_id < 1 or protein_id > 1000000:
        invalid_shape()
    stats = await http.get(BASE + f"/api/proteins/id/{protein_id}/protein_stats/")
    if (
        not isinstance(stats, dict)
        or stats.get("protein_id") != protein_id
        or type(stats.get("id")) is not int
        or type(stats.get("protein_id")) is not int
        or stats.get("id") != protein_id
        or stats.get("pid") != entry
        or stats.get("pid_for_website") != entry
        or stats.get("uniprot_id") != resolved["accession"]
        or stats.get("gene_id") != resolved["gene"]
    ):
        raise ResearchError("identity_mismatch", "EVE and UniProt protein identities do not match.")
    url = BASE + "/api/proteins/web_pid/" + entry + "/download/"
    raw = await http.get(url, params={"variants": "True"}, binary=True)
    records = parse_archive(raw, entry, resolved)
    sha = hashlib.sha256(raw).hexdigest()
    return {
        "record_type": "eve_predictions",
        "query": identifier,
        "records": records,
        "source_release": "EVE ASM protein archive sha256:" + sha,
        "score_artifact_sha256": sha,
        "source_url": url,
        "license": "MIT",
        "license_url": BASE + "/LICENSE.txt",
        "license_notice": NOTICE,
        "attribution": "EVE: Frazer et al., Nature (2021), https://doi.org/10.1038/s41586-021-04043-8; original evemodel.org data extracted and normalized.",
        "interpretation": "EVE computational prediction, not clinical classification or patient risk. Source 75%-retained class and uncertainty are preserved; scores from different predictors are not combined.",
        "protein_identity": {
            "gene": resolved["gene"],
            "uniprot_id": resolved["accession"],
            "sequence_version": resolved["sequence_version"],
            "sequence_sha256": hashlib.sha256(resolved["sequence"].encode()).hexdigest(),
        },
        "coverage": {
            "scope": "Exact canonical human protein substitution; no genomic allele inferred.",
            "returned": len(records),
            "score_status": "supplied" if records else "no_score_supplied",
            "exact_dataset_release_reported": False,
        },
    }
