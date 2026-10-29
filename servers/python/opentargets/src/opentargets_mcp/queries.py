"""Open Targets GraphQL over Ubi's shared bounded public transport."""

from biomedmcp import transport as httpx
from biomedmcp.errors import ResearchError
from biomedmcp.native.opentargets import plan
from biomedmcp.native.opentargets import response as validated_response


class OpenTargetsClient:
    def __init__(self, base_url="https://api.platform.opentargets.org/api/v4/graphql", cache_ttl=0):
        self.base_url = base_url

    async def _query(self, query, variables=None):
        wire, _, _ = plan(query)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.base_url, json={"query": wire, "variables": variables or {}})
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                raise ResearchError(
                    "invalid_source_response", "Open Targets did not return valid JSON."
                ) from None
            return validated_response(payload, query, variables)

    async def close(self):
        pass
