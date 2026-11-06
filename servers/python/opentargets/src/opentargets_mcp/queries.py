"""Validated GraphQL access to the Open Targets Platform API."""

from biomedmcp import transport as httpx
from biomedmcp.native.opentargets import plan, response

ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"


class OpenTargetsClient:
    """POST one reviewed read-only query and return its shape-checked ``data``."""

    def __init__(self, endpoint=ENDPOINT, timeout=30.0):
        self.endpoint, self.timeout = endpoint, timeout

    async def _query(self, query, variables=None):
        # plan() validates the document against the reviewed contract before any
        # network use; response() checks the payload against the same selection.
        wire, _, _ = plan(query)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            reply = await client.post(self.endpoint, json={"query": wire, "variables": variables or {}})
            reply.raise_for_status()
            payload = reply.json()
        return response(payload, query, variables)


def relation(data, root, field):
    """One selected relation of a verified root entity (None when unavailable)."""
    return (data.get(root) or {}).get(field)
