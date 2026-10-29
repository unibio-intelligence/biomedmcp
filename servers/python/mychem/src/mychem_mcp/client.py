"""Validated MyChem annotation acquisition; underlying source permissions remain separate."""

from biomedmcp.native.biothings import BioThingsClient, CacheEntry


class MyChemError(Exception):
    """Invalid local annotation arguments (never includes provider response bodies)."""


class MyChemClient(BioThingsClient):
    source = "mychem"

    def __init__(
        self,
        base_url="https://mychem.info/v1",
        timeout=30.0,
        cache_enabled=True,
        cache_ttl=3600,
        rate_limit=10,
    ):
        super().__init__(base_url, timeout, cache_enabled, cache_ttl, rate_limit)
