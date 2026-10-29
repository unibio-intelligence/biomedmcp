#!/usr/bin/env python3
"""Extract used factual response schemas from a locally saved official GTEx OpenAPI file."""

import argparse
import hashlib
import json
from pathlib import Path

ENDPOINTS = (
    "/",
    "/expression/medianGeneExpression",
    "/expression/geneExpression",
    "/expression/topExpressedGene",
    "/association/egene",
    "/association/sgene",
    "/association/singleTissueEqtl",
    "/association/singleTissueSqtl",
    "/association/metasoft",
    "/association/dyneqtl",
    "/association/dynsqtl",
    "/reference/gene",
    "/reference/transcript",
    "/reference/exon",
    "/dataset/variant",
    "/dataset/tissueSiteDetail",
    "/metadata/dataset",
    "/dataset/sample",
)


def extract(raw, retrieved_on):
    source = json.loads(raw)
    schemas = source["components"]["schemas"]
    selected = {}

    def clean(value):
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key == "properties":
                # Property names are data fields, even when they coincide
                # with schema annotation keywords such as "description".
                result[key] = {name: clean(schema) for name, schema in item.items()}
                continue
            if key in {"description", "title", "examples", "example", "externalDocs"}:
                continue
            if key == "$ref":
                name = item.removeprefix("#/components/schemas/")
                if name not in selected:
                    selected[name] = None
                    selected[name] = clean(schemas[name])
            result[key] = clean(item)
        return result

    endpoints = {
        path: clean(
            source["paths"]["/api/v2" + path]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
        )
        for path in ENDPOINTS
    }
    requests = {}
    for path in ENDPOINTS:
        parameters = source["paths"]["/api/v2" + path]["get"].get("parameters", [])
        query = [parameter for parameter in parameters if parameter["in"] == "query"]
        requests[path] = {
            "type": "object",
            "properties": {parameter["name"]: clean(parameter["schema"]) for parameter in query},
            "required": [parameter["name"] for parameter in query if parameter.get("required")],
            "additionalProperties": False,
        }
    return {
        "source_url": "https://gtexportal.org/api/v2/openapi.json",
        "retrieved_on": retrieved_on,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "api_version": source["info"]["version"],
        "openapi_version": source["openapi"],
        "endpoints": endpoints,
        "requests": requests,
        "components": {"schemas": selected},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--retrieved-on", required=True)
    args = parser.parse_args()
    destination = Path(__file__).parents[1] / "servers/python/gtex/src/gtex_mcp/contracts.json"
    destination.write_text(json.dumps(extract(args.source.read_bytes(), args.retrieved_on), indent=2) + "\n")
