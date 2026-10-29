"""Bounded, namespace- and species-qualified batch gene identity mapping."""

import re

from biomedmcp.errors import ResearchError, provider_boundary
from biomedmcp.native.identity import qualify_gene


async def map_gene_ids(client, gene_ids, namespace, species):
    with provider_boundary("mygene"):
        patterns = {
            "symbol": r"[A-Za-z0-9_.-]{1,100}",
            "entrezgene": r"[0-9]{1,20}",
            "ensembl.gene": r"ENS[A-Z]*G[0-9]+(?:\.[0-9]+)?",
        }
        if (
            namespace not in patterns
            or type(species) is not int
            or species <= 0
            or not 1 <= len(gene_ids) <= 25
            or any(
                not isinstance(term, str) or not re.fullmatch(patterns[namespace], term) for term in gene_ids
            )
        ):
            raise ResearchError("invalid_parameters", "Provide bounded identifiers in one gene namespace.")
        terms = list(dict.fromkeys(gene_ids))
        rows = await client.query_batch(
            {
                "q": ",".join(terms),
                "scopes": namespace,
                "species": species,
                "fields": "_id,symbol,name,taxid,entrezgene,ensembl.gene,HGNC",
                "dotfield": "false",
            }
        )
        if not isinstance(rows, list) or len(rows) > 625 or any(not isinstance(row, dict) for row in rows):
            raise ResearchError("invalid_source_response", "Invalid batch gene response.")
        groups = {term: [] for term in terms}
        for row in rows:
            query = row.get("query")
            if not isinstance(query, str) or query not in groups:
                raise ResearchError("invalid_source_response", "Unrequested gene mapping response.")
            groups[query].append(row)
        mappings = []
        for term, hits in groups.items():
            if not hits or len(hits) > 25:
                raise ResearchError(
                    "invalid_source_response", "Missing or excessive gene mapping candidates."
                )
            if any(hit.get("notfound") is True for hit in hits):
                if len(hits) != 1 or any(
                    key in hits[0] for key in ("_id", "symbol", "entrezgene", "ensembl")
                ):
                    raise ResearchError("invalid_source_response", "Contradictory gene mapping response.")
                candidates = []
            else:
                candidates = []
                for hit in hits:
                    if "notfound" in hit and hit["notfound"] is not False:
                        raise ResearchError("invalid_source_response", "Invalid missingness marker.")
                    identity = qualify_gene(hit, species)
                    values = {
                        "symbol": [identity["symbol"]],
                        "entrezgene": [identity["entrez_id"]],
                        "ensembl.gene": identity["ensembl_ids"],
                    }[namespace]
                    if term.casefold() not in {
                        str(value).casefold() for value in values if value is not None
                    }:
                        raise ResearchError(
                            "invalid_source_response", "Gene mapping did not match the requested namespace."
                        )
                    if identity not in candidates:
                        candidates.append(identity)
            mappings.append(
                {
                    "query": term,
                    "input_namespace": namespace,
                    "species": species,
                    "status": "not_found"
                    if not candidates
                    else "resolved"
                    if len(candidates) == 1
                    else "ambiguous",
                    "candidates": candidates,
                }
            )
        return {
            "mappings": mappings,
            "source": "mygene",
            "species": species,
            "missingness": "not_found applies only to this source, namespace and species",
        }
