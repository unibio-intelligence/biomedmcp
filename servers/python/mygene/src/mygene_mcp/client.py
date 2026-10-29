# src/mygene_mcp/client.py
from typing import Any

from biomedmcp import transport as httpx
from biomedmcp.errors import provider_boundary


class MyGeneError(Exception):
    """Custom error for MyGene API operations."""


class MyGeneClient:
    """Client for MyGene.info API."""

    def __init__(self, base_url: str = "https://mygene.info/v3", timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make GET request to MyGene API."""
        url = f"{self.base_url}/{endpoint}"
        with provider_boundary("mygene"):
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()

    async def close(self) -> None:
        """Close any persistent resources (placeholder for future enhancements)."""
        return

    async def query_batch(self, params: dict[str, Any]) -> Any:
        """Use the documented form-encoded batch query contract."""
        with provider_boundary("mygene"):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/query", data=params)
                response.raise_for_status()
                return response.json()

    async def post(self, endpoint: str, json_data: Any) -> Any:
        """Make POST request to MyGene API."""
        url = f"{self.base_url}/{endpoint}"
        headers = {"content-type": "application/json"}
        with provider_boundary("mygene"):
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=json_data, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
