"""Every declared retained route must exist without contacting a provider."""

import importlib

import pytest

from biomedmcp import adapters as adapter_module
from biomedmcp import transport
from biomedmcp.adapters import PROVIDERS, SourceAdapters
from biomedmcp.native.catalog import ADVANCED


@pytest.fixture
def configured_retained(monkeypatch):
    for provider in PROVIDERS.values():
        for name in provider.get("required_env", []):
            monkeypatch.setenv(name, "synthetic-credential-sentinel")
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "antibody-registry")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Inventory must not perform provider HTTP")

    monkeypatch.setattr(transport.AsyncClient, "request", forbidden)
    return SourceAdapters()


@pytest.mark.parametrize("source", sorted(PROVIDERS))
def test_each_retained_package_imports_offline(configured_retained, source):
    importlib.import_module(PROVIDERS[source]["module"])


@pytest.mark.parametrize("source", sorted(set(PROVIDERS) & set(ADVANCED)))
async def test_every_declared_retained_operation_exists_in_actual_catalog(
    configured_retained, source, monkeypatch
):
    discoveries = []
    original = adapter_module.Client

    class Client(original):
        async def list_tools(self, *args, **kwargs):
            discoveries.append(True)
            return await super().list_tools(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "Client", Client)
    assert configured_retained.availability(source)[0]
    first = await configured_retained.catalog(source)
    second = await configured_retained.catalog(source)
    assert first == second and first is not second and len(discoveries) == 1
    actual = {operation["name"] for operation in first}
    assert ADVANCED[source] <= actual, sorted(ADVANCED[source] - actual)
