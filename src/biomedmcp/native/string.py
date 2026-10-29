"""Validate the classic STRING functional-network JSON contract before citation.

Contract: https://string-db.org/help/api/#getting-the-protein-network
The provider supplies protein identifiers and functional associations, not
gene-identity equivalences, physical binding measurements or causal effects.
"""

import math
import re

from .shapes import collection, invalid_shape

CHANNELS = ("nscore", "fscore", "pscore", "ascore", "escore", "dscore", "tscore")
ADDED_NODES = 10


def score(value):
    if type(value) not in {int, float} or not 0 <= value <= 1 or not math.isfinite(value):
        invalid_shape()


def network(payload, *, symbol, species):
    """Reject the whole response if any edge violates identity/score semantics."""
    rows = collection(payload, ())
    missing_channels = set()
    for row in rows:
        if "error" in row or "errors" in row:
            invalid_shape()
        taxon = row.get("ncbiTaxonId")
        if isinstance(taxon, str) and re.fullmatch(r"[1-9][0-9]{0,9}", taxon):
            taxon = int(taxon)
        if type(taxon) is not int or taxon != species:
            invalid_shape()
        for side in ("A", "B"):
            identifier = row.get(f"stringId_{side}")
            label = row.get(f"preferredName_{side}")
            if (
                not isinstance(identifier, str)
                or len(identifier) > 200
                or not re.fullmatch(rf"{species}\.[^\s]+", identifier)
                or not isinstance(label, str)
                or not label.strip()
                or len(label) > 1000
                or any(ord(character) < 32 for character in label)
            ):
                invalid_shape()
        score(row.get("score"))
        for channel in CHANNELS:
            if channel in row:
                score(row[channel])
            else:
                missing_channels.add(channel)
    warnings = [
        (
            "STRING functional associations do not establish physical binding or causality; "
            "scores are confidence scores, not effect sizes or experimental measurements."
        ),
        (
            "This query expands the network by up to ten neighbors and can include "
            "neighbor-to-neighbor edges. Returned protein identifiers are not gene-identity equivalences."
        ),
        "An empty network does not establish biological absence. The live source release is unpinned.",
    ]
    if missing_channels:
        warnings.append(
            "Some edges omit channel scores: "
            + ", ".join(sorted(missing_channels))
            + ". Missing scores are unreported, not measured zero."
        )
    return {
        "records": rows,
        "network_type": "functional",
        "added_nodes": ADDED_NODES,
        "requested_symbol": symbol,
        "requested_species": species,
        "warnings": warnings,
    }
