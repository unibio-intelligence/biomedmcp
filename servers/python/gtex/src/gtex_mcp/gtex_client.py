"""HTTP client for GTEx Portal API."""

import asyncio
from typing import Any

from biomedmcp import transport as httpx
from biomedmcp.errors import provider_boundary

from .config import (
    DEFAULT_DATASET_ID,
    ENDPOINTS,
    GTEX_API_BASE_URL,
    RATE_LIMIT_DELAY,
    REQUEST_TIMEOUT,
)
from .contracts import validate_request, validate_response
from .identity import release_parameters, variant_selector


class GTExClient:
    """Async HTTP client for interacting with GTEx Portal API v2."""

    def __init__(self):
        self.base_url = GTEX_API_BASE_URL
        self.endpoints = ENDPOINTS
        self.timeout = REQUEST_TIMEOUT
        self._last_request_time = 0.0
        self._rate_limit_delay = RATE_LIMIT_DELAY
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def _rate_limit(self):
        """Enforce rate limiting between requests."""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._rate_limit_delay:
            await asyncio.sleep(self._rate_limit_delay - time_since_last)
        self._last_request_time = asyncio.get_event_loop().time()

    async def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """
        Make an HTTP request to the GTEx API.

        Args:
            endpoint: API endpoint path
            method: HTTP method (GET or POST)
            params: Query parameters
            json_data: JSON body for POST requests

        Returns:
            Response JSON data

        Raises:
            httpx.HTTPError: If request fails
        """
        with provider_boundary("gtex"):
            validate_request(endpoint, params)
            await self._rate_limit()
            client = await self._get_client()
            url = f"{self.base_url}{endpoint}"
            if method == "GET":
                response = await client.get(url, params=params)
            elif method == "POST":
                response = await client.post(url, params=params, json=json_data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return validate_response(endpoint, response.json(), params)

    async def close(self):
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # Service Info
    async def get_service_info(self) -> dict[str, Any]:
        """Get GTEx API service information."""
        return await self._make_request(self.endpoints["service_info"])

    # Expression Data
    async def get_median_gene_expression(
        self,
        gene_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get median gene expression across tissues."""
        params = {"gencodeId": gene_id, "datasetId": dataset_id}
        return await self._make_request(
            self.endpoints["median_gene_expression"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_gene_expression(
        self,
        gene_id: str,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get gene expression for a specific tissue."""
        params = {
            "gencodeId": gene_id,
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["gene_expression"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_top_expressed_genes(
        self,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        limit: int = 50,
        *,
        page: int = 0,
    ) -> dict[str, Any]:
        """Get top expressed genes in a tissue."""
        params = {
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
            "itemsPerPage": limit,
            "page": page,
        }
        return await self._make_request(self.endpoints["top_expressed_genes"], params=params)

    # Association - Static
    async def get_eqtl_genes(
        self,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get eQTL genes for a tissue."""
        params: dict[str, Any] = {
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["eqtl_genes"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_single_tissue_eqtls(
        self,
        gene_id: str,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        variant_id: str | None = None,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get significant single-tissue eQTLs."""
        params: dict[str, Any] = {
            "gencodeId": gene_id,
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        if variant_id is not None:
            params["variantId"] = variant_id
        return await self._make_request(
            self.endpoints["single_tissue_eqtl"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_single_tissue_sqtls(
        self,
        gene_id,
        tissue_site_detail_id,
        dataset_id=DEFAULT_DATASET_ID,
        variant_id=None,
        page=0,
        limit=None,
    ):
        params = {
            "gencodeId": gene_id,
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
            "page": page,
        }
        if variant_id is not None:
            params["variantId"] = variant_id
        return await self._make_request(
            self.endpoints["single_tissue_sqtl"],
            params={**params, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_sqtl_genes(
        self,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get sQTL genes for a tissue."""
        params = {
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["sqtl_genes"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_metasoft_results(
        self,
        gene_id: str,
        variant_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get multi-tissue eQTL results using METASOFT."""
        params = {
            "gencodeId": gene_id,
            "variantId": variant_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["metasoft"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    # Association - Dynamic
    async def calculate_dynamic_eqtl(
        self,
        gene_id: str,
        variant_id: str,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
    ) -> dict[str, Any]:
        """Calculate dynamic eQTL on demand."""
        params = {
            "gencodeId": gene_id,
            "variantId": variant_id,
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(self.endpoints["dynamic_eqtl"], params=params)

    async def calculate_dynamic_sqtl(
        self,
        phenotype_id: str,
        variant_id: str,
        tissue_site_detail_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
    ) -> dict[str, Any]:
        """Calculate dynamic sQTL on demand."""
        params = {
            "phenotypeId": phenotype_id,
            "variantId": variant_id,
            "tissueSiteDetailId": tissue_site_detail_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(self.endpoints["dynamic_sqtl"], params=params)

    # Reference
    async def get_gene_info(
        self,
        gene_id: str | None = None,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get gene information by ID (symbol or GENCODE ID)."""
        params: dict[str, Any] = release_parameters(dataset_id)
        if gene_id is not None:
            params["geneId"] = gene_id
        return await self._make_request(
            self.endpoints["gene"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_transcript_info(
        self,
        gene_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get transcripts of one versioned gene under the dataset's annotation release."""
        params = {
            "gencodeId": gene_id,
            **release_parameters(dataset_id),
        }
        return await self._make_request(
            self.endpoints["transcript"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_exon_info(
        self,
        gene_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get transcript-associated exons of one versioned gene."""
        release_parameters(dataset_id)
        params = {
            "gencodeId": gene_id,
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["exon"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def get_variant_info(
        self,
        variant_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get variant information."""
        release_parameters(dataset_id)
        params = {
            **variant_selector(variant_id),
            "datasetId": dataset_id,
        }
        return await self._make_request(
            self.endpoints["variant"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    async def list_tissues(
        self,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List all available tissues."""
        params = {"datasetId": dataset_id}
        return await self._make_request(
            self.endpoints["tissue"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )

    # Dataset
    async def get_dataset_info(
        self,
        dataset_id: str = DEFAULT_DATASET_ID,
    ) -> list[dict[str, Any]]:
        """Get dataset information."""
        params = {"datasetId": dataset_id}
        return await self._make_request(self.endpoints["dataset_info"], params=params)

    # Biobank
    async def get_sample_info(
        self,
        sample_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        *,
        page: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Get sample information."""
        params = {"sampleId": sample_id, "datasetId": dataset_id}
        return await self._make_request(
            self.endpoints["sample"],
            params={**params, "page": page, **({"itemsPerPage": limit} if limit is not None else {})},
        )
