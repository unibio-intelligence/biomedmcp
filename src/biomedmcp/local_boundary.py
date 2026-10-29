"""Explicit anonymous local mode when the hosting integration is absent.

No authentication or quota implementation is duplicated here. Hosted startup
requires the shared Ubi package; it can never fall back to these local helpers.
"""

import os
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class AuthSettings:
    profile: str
    base_url: str
    redis_url: str = ""

    @property
    def resource(self):
        return self.base_url.rstrip("/") + "/mcp"

    @classmethod
    def from_env(cls, *, default_url):
        if os.getenv("UBI_PROFILE") != "local":
            raise ValueError("Hosted mode requires the a configured hosting integration")
        return cls("local", os.getenv("UBI_MCP_BASE_URL", default_url))


def build_auth(settings):
    if settings.profile != "local" or os.getenv("UBI_PROFILE") != "local":
        raise ValueError("The hosting integration is required for authenticated service")


def current_context(resource):
    if os.getenv("UBI_PROFILE") != "local":
        raise ValueError("Anonymous mode must be explicitly enabled locally")
    return SimpleNamespace(cache_scope="local", account_id="local")


class LocalLedger:
    async def snapshot(self, account):
        return {"enabled": False, "profile": "local"}


def build_ledger(profile):
    if profile != "local":
        raise ValueError("Hosted accounting requires the shared Ubi package")
    return LocalLedger()


async def accounted(ledger, context, name, params, operation, **kwargs):
    return await operation()


async def dependencies_ready(settings, ledger):
    build_auth(settings)


async def close_auth(auth):
    pass


class ServiceError(Exception):
    pass
