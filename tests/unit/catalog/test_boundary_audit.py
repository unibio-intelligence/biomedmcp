"""Audit regressions at provider, scientific-evidence and permission boundaries."""

import io
import zipfile
from unittest.mock import patch

import httpx
import pytest

from biomedmcp import source_licensing, transport
from biomedmcp.adapters import SourceAdapters
from biomedmcp.errors import ResearchError
from biomedmcp.evidence import section_from


@pytest.mark.parametrize("status", ["partial", "degraded"])
@pytest.mark.parametrize("shape", ["text", "object"])
def test_partial_source_is_not_described_as_unavailable(status, shape):
    value = status if shape == "text" else {"outcome": status}
    section, provenance = section_from(
        "clinical-trials",
        {
            "payload": {"records": [{"nct_id": "NCT00000001"}], "section_outcomes": {"coverage": value}},
            "retrieved_at": 1792108800,
        },
        False,
    )
    assert section.outcome == "partial"
    assert "Partial source sections: coverage" in section.warnings
    assert all("Unavailable" not in w for w in section.warnings)
    assert section.data["records"] and provenance.source == "clinical-trials"


@pytest.mark.parametrize("status", ["error", "unavailable", "failed", "timeout"])
def test_partial_and_failed_source_warnings_remain_distinct(status):
    section, _ = section_from(
        "clinical-trials",
        {
            "payload": {
                "records": [{"id": "retained"}],
                "section_outcomes": {"coverage": {"outcome": "partial"}, "missing": status},
            },
            "retrieved_at": 1792108800,
        },
        False,
    )
    assert "Unavailable source sections: missing" in section.warnings
    assert "Partial source sections: coverage" in section.warnings


@pytest.mark.source_permissions
@pytest.mark.parametrize("mode", ["search", "details"])
async def test_antibody_uses_current_policy_without_legacy_environment(monkeypatch, mode):
    monkeypatch.delenv("UBI_LICENSED_SOURCES", raising=False)
    row = {"abId": 1, "abName": "Synthetic antibody", "epitope": None}
    payload = {"items": [row], "page": 1, "totalElements": 1} if mode == "search" else [row]
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
    )
    value = await SourceAdapters().call(
        "antibody-registry",
        "query_antibody",
        {"query_type": mode, "query": "TP53" if mode == "search" else "AB_1"},
    )
    assert value["items"] == [row]


@pytest.mark.source_permissions
async def test_antibody_current_hold_cannot_be_overridden_by_legacy_flag(monkeypatch):
    from antibody_registry.unified import UnifiedAntibodyTools
    from fastmcp.exceptions import ToolError

    monkeypatch.setenv("UBI_LICENSED_SOURCES", "antibody-registry")
    monkeypatch.setattr(source_licensing, "operation_allowed", lambda *args: False)
    with patch.object(transport, "AsyncClient") as wire:
        with pytest.raises(ToolError, match="source_license_unreleased"):
            await UnifiedAntibodyTools().query_antibody("details", "AB_1")
        wire.assert_not_called()


@pytest.mark.parametrize(
    "status,code",
    [
        (404, "source_not_found"),
        (403, "source_access_denied"),
        (429, "source_rate_limited"),
        (500, "source_unavailable"),
    ],
)
async def test_orange_book_provider_failures_are_typed_and_sanitized(monkeypatch, caplog, status, code):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="untrusted-private-provider-message")
            )
        ),
    )
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("orange-book", "search_products", {"ingredient": "private-search-term"})
    assert error.value.code == code
    assert "private-search-term" not in caplog.text
    assert "untrusted-private-provider-message" not in caplog.text


@pytest.mark.parametrize("contents", [b"<html>Provider maintenance</html>", b"PK-not-a-valid-archive"])
async def test_orange_book_bad_archive_is_sanitized_source_failure(monkeypatch, contents):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=contents))
        ),
    )
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("orange-book", "search_products", {"ingredient": "imatinib"})
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("member", ["missing.txt", "products.txt"])
async def test_orange_book_missing_archive_member_or_columns_is_source_failure(monkeypatch, member):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(member, "wrong~fields\nnot~products\n")
    original = httpx.AsyncClient
    monkeypatch.setattr(
        transport,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content.getvalue()))
        ),
    )
    with pytest.raises(ResearchError) as error:
        await SourceAdapters().call("orange-book", "search_products", {"ingredient": "imatinib"})
    assert error.value.code == "invalid_source_response"


@pytest.mark.parametrize("params", [{}, {"ingredient": ""}, {"brand_name": " "}])
async def test_orange_book_generic_lookup_requires_a_nonempty_identity(monkeypatch, params):
    with patch.object(transport, "AsyncClient") as wire:
        with pytest.raises(ResearchError) as error:
            await SourceAdapters().call("orange-book", "search_generic_equivalents", params)
        assert error.value.code == "invalid_parameters"
        wire.assert_not_called()


@pytest.mark.parametrize("brand", ["[", "DRUG."])
async def test_orange_book_brand_names_are_literal_not_regular_expressions(monkeypatch, brand):
    from unittest.mock import AsyncMock

    import pandas as pd
    from orange_book_mcp import server

    frame = pd.DataFrame(
        [
            {"Ingredient": "wrong", "Trade_Name": "DRUGX", "RLD": "Yes", "TE_Code": "AB"},
            {"Ingredient": "correct", "Trade_Name": brand, "RLD": "Yes", "TE_Code": "AB"},
        ]
    )
    for name in ["Appl_No", "Applicant", "Dosage_Form", "Strength", "Approval_Date"]:
        frame[name] = "synthetic"
    monkeypatch.setattr(server, "_fetch_orange_book_file", AsyncMock(return_value=frame))
    result = await SourceAdapters().call("orange-book", "search_generic_equivalents", {"brand_name": brand})
    assert result["ingredient"] == "correct" and result["generic_count"] == 1


@pytest.mark.source_permissions
def test_antibody_wire_gate_uses_shipped_policy_without_legacy_flag(monkeypatch):
    monkeypatch.delenv("UBI_LICENSED_SOURCES", raising=False)
    assert (
        transport.validate_url("https://www.antibodyregistry.org/api/antibodies/1")
        == "www.antibodyregistry.org"
    )


@pytest.mark.source_permissions
def test_antibody_wire_gate_rejects_current_hold_even_with_legacy_flag(monkeypatch):
    monkeypatch.setenv("UBI_LICENSED_SOURCES", "antibody-registry")
    monkeypatch.setattr(source_licensing, "operation_allowed", lambda *args: False)
    with pytest.raises(ResearchError, match="reviewed data projection"):
        transport.validate_url("https://www.antibodyregistry.org/api/antibodies/1")


async def test_old_orange_book_cache_cannot_restore_regex_based_results():
    from unittest.mock import AsyncMock

    from biomedmcp.domain import ResearchService
    from biomedmcp.native import REVISION
    from biomedmcp.runtime import ProviderRuntime

    runtime = ProviderRuntime()
    params = {"brand_name": "DRUG."}

    async def legacy_payload():
        return {"ingredient": "wrong-regex-match", "generics": [{"Ingredient": "wrong"}]}

    await runtime.invoke(
        "orange-book",
        {
            "operation": "search_generic_equivalents",
            "params": params,
            "version": None,
            "implementation": REVISION,
        },
        legacy_payload,
        scope="audit",
    )
    adapters = SourceAdapters()
    adapters.call = AsyncMock(return_value={"ingredient": "correct", "generics": [{"Ingredient": "correct"}]})
    service = ResearchService(runtime=runtime, adapters=adapters)
    result = await service.source("orange-book", "search_generic_equivalents", params, scope="audit")
    assert adapters.call.await_count == 1
    assert result.sections["orange-book"].data["ingredient"] == "correct"
    assert result.provenance[0].cached is False
    repeated = await service.source("orange-book", "search_generic_equivalents", params, scope="audit")
    assert adapters.call.await_count == 1 and repeated.provenance[0].cached is True
