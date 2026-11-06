"""MyGene.info MCP server: gene search, batch identifier mapping and comparison."""

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from biomedmcp.errors import ResearchError, provider_tool_boundary
from biomedmcp.native.identity import gene_matches, qualify_gene

from .client import MyGeneClient

try:
    from mcp.types import ToolAnnotations

    READ_ONLY_ANNOTATIONS = ToolAnnotations(title="Query MyGene", read_only_hint=True, open_world_hint=True)
except ImportError:  # pragma: no cover - annotations are optional metadata
    READ_ONLY_ANNOTATIONS = None

mcp = FastMCP("mygene", version="0.1.0")
client = MyGeneClient(cache_enabled=False)

IDENTITY_FIELDS = "symbol,name,taxid,entrezgene,ensembl.gene,HGNC"
Namespace = Literal["symbol", "entrezgene", "ensembl.gene"]
GeneId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[^\s,+]+$")]
GeneIds = Annotated[
    list[GeneId],
    Field(
        min_length=1, max_length=25, description="Literal identifiers in one namespace; no batch separators."
    ),
]
Species = Annotated[int, Field(gt=0, description="NCBI taxonomy ID, e.g. 9606 for human.")]


def _grouped_batch(rows, inputs):
    """One explicit outcome per input; contradictory or foreign rows are rejected."""
    grouped = {identifier: [] for identifier in inputs}
    for row in rows:
        if row["query"] not in grouped:
            raise ResearchError("invalid_source_response", "MyGene returned a row for an unrequested query.")
        grouped[row["query"]].append(row)
    for candidates in grouped.values():
        if not candidates or (len(candidates) > 1 and any(r.get("notfound") is True for r in candidates)):
            raise ResearchError("invalid_source_response", "MyGene omitted or contradicted a batch outcome.")
    return grouped


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mygene")
async def query_genes(
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            description="MyGene query string (symbol, name, alias or fielded query).",
        ),
    ],
    fields: Annotated[
        str, Field(min_length=1, max_length=512, description="Comma-separated MyGene fields to return.")
    ] = "symbol,name,taxid,entrezgene",
    species: Annotated[
        str, Field(min_length=1, max_length=64, description="Taxonomy ID or common name filter, e.g. '9606'.")
    ] = "9606",
    limit: Annotated[int, Field(ge=1, le=100, description="Hits per page.")] = 10,
    from_: Annotated[int, Field(ge=0, le=10000, description="Zero-based offset of the first hit.")] = 0,
) -> dict:
    """Search MyGene.info (GET /v3/query) and return its hits/total envelope unchanged."""
    return await client.get(
        "query", {"q": query, "fields": fields, "species": species, "size": limit, "from": from_}
    )


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mygene")
async def map_gene_ids(
    gene_ids: GeneIds,
    input_namespace: Annotated[Namespace, Field(description="Namespace every input belongs to.")] = "symbol",
    species: Species = 9606,
) -> dict:
    """Map up to 25 gene identifiers in one namespace to species-qualified Entrez/Ensembl/HGNC identities via one POST /v3/query batch."""
    inputs = list(dict.fromkeys(gene_ids))
    rows = await client.post(
        "query",
        {"q": inputs, "scopes": input_namespace, "species": str(species), "fields": IDENTITY_FIELDS},
    )
    mappings, missing = [], []
    for identifier, candidates in _grouped_batch(rows, inputs).items():
        if candidates[0].get("notfound") is True:
            missing.append(identifier)
            mappings.append({"query": identifier, "status": "not_found", "candidates": []})
            continue
        identities = []
        for row in candidates:
            if not gene_matches(row, identifier, species):
                raise ResearchError(
                    "invalid_source_response", "MyGene candidate does not carry the requested identity."
                )
            identities.append(qualify_gene(row, species))
        mappings.append(
            {
                "query": identifier,
                "status": "resolved" if len(identities) == 1 else "ambiguous",
                "candidates": identities,
            }
        )
    return {
        "success": True,
        "status": "complete" if all(m["status"] == "resolved" for m in mappings) else "partial",
        "input_namespace": input_namespace,
        "species": species,
        "total_input": len(gene_ids),
        "unique_inputs": len(inputs),
        "mappings": mappings,
        "unmapped_ids": missing,
        "limitations": ["Identities are MyGene annotations for the declared namespace and species only."],
    }


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
@provider_tool_boundary("mygene")
async def compare_genes(
    gene_ids: Annotated[
        list[GeneId],
        Field(min_length=2, max_length=25, description="Two to 25 symbols, Entrez or Ensembl gene IDs."),
    ],
    species: Species = 9606,
    fields: Annotated[
        str,
        Field(min_length=1, max_length=512, description="Comma-separated MyGene fields placed side by side."),
    ] = "symbol,name,taxid,entrezgene,ensembl.gene,type_of_gene,summary",
) -> dict:
    """Fetch several genes in one POST /v3/query batch (symbol, Entrez or Ensembl scopes) and tabulate the requested fields per input."""
    inputs = list(dict.fromkeys(gene_ids))
    rows = await client.post(
        "query",
        {"q": inputs, "scopes": "symbol,entrezgene,ensembl.gene", "species": str(species), "fields": fields},
    )
    grouped = _grouped_batch(rows, inputs)
    found = {k: [r for r in v if r.get("notfound") is not True] for k, v in grouped.items()}
    names = [name for name in fields.split(",") if name]
    return {
        "species": species,
        "inputs": inputs,
        "records": found,
        "not_found": [k for k, v in found.items() if not v],
        "ambiguous": [k for k, v in found.items() if len(v) > 1],
        "comparison": {
            name: {k: [_pluck(r, name) for r in v] for k, v in found.items() if v} for name in names
        },
    }


def _pluck(row, path):
    node = row
    for part in path.split("."):
        if isinstance(node, list):
            node = [item.get(part) for item in node if isinstance(item, dict)]
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node
