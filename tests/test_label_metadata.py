"""FDA label prose is enabled while attachments remain outside acquisition."""

import json

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.native.label_metadata import project
from biomedmcp.source_licensing import operation_allowed

pytestmark = pytest.mark.source_permissions


def label():
    return {
        "id": "12345678-1234-1234-1234-123456789abc",
        "set_id": "12345678-1234-1234-1234-123456789abd",
        "version": "2",
        "effective_time": "20261001",
        "openfda": {"generic_name": ["imatinib"], "route": ["ORAL"], "unexpected_text": ["held"]},
        "boxed_warning": ["held"],
        "indications_and_usage": ["held"],
        "description": ["held"],
        "attachments": ["held"],
    }


def test_label_prose_and_factual_metadata_leave_acquisition_boundary():
    row = project([label()])[0]
    assert row["product_metadata"] == {"generic_name": ["imatinib"], "route": ["ORAL"]}
    assert row["label_sections"]["boxed_warning"] == ["held"]
    assert row["label_sections"]["description"] == ["held"]
    assert "attachments" not in row["label_sections"]
    assert "unexpected_text" not in row["product_metadata"]
    assert row["version"] == "2" and row["effective_time"] == "20261001"
    assert row["label_url"].endswith(label()["set_id"])
    assert operation_allowed("openfda", "get:label")
    assert not operation_allowed("openfda", "endpoint:device/udi")


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "https://evil.example"),
        ("set_id", None),
        ("version", True),
        ("effective_time", "20260230"),
        ("openfda", []),
        ("openfda", {"generic_name": "bad"}),
    ],
)
def test_invalid_identity_date_or_fact_shape_fails_closed(field, value):
    row = label()
    row[field] = value
    with pytest.raises(ResearchError):
        project([row])


async def test_retained_fda_boundary_preserves_text_before_runtime_cache(monkeypatch):
    import httpx
    from openfda_mcp import server

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, params):
            return httpx.Response(200, json={"results": [label()]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kwargs: Client())
    result = await server.fda_api_request("drug/label", search="imatinib")
    assert result["results"][0]["label_sections"]["indications_and_usage"] == ["held"]
    assert "attachments" not in result["results"][0]["label_sections"]
    assert result["results"][0]["content_scope"] == "label_text_and_metadata"


@pytest.mark.parametrize("value", ["not a list", [None], [123]])
def test_malformed_prose_is_not_coerced(value):
    row = label()
    row["warnings"] = value
    with pytest.raises(ResearchError):
        project([row])


def test_unicode_and_multiline_label_sections_are_preserved():
    row = label()
    row["description"] = ["α—β\nDose text with <literal> symbols.  "]
    assert project([row])[0]["label_sections"]["description"] == row["description"]


async def test_live_sized_label_prose_stays_visible_and_full_text_is_recoverable():
    from biomedmcp.dispatch import execute
    from biomedmcp.domain import ResearchService
    from biomedmcp.recovery import parse_uri, resource_uri
    from biomedmcp.receipts import verify_receipt

    row = label()
    row["description"] = ["αβ text " * 2000]
    row["indications_and_usage"] = ["Manufacturer-submitted indications."]
    records = project([{**row, "id": "12345678-1234-1234-1234-" + f"{n:012d}"} for n in range(10)])
    requested = []
    service = ResearchService()

    async def fda(path, query, limit=10, **kwargs):
        requested.append(limit)
        return records[:limit]

    service.providers.fda = fda
    value = (
        await execute(
            service, "get", {"entity": "drug", "id": "imatinib", "sections": ["label"]}, scope="test"
        )
    ).model_dump(mode="json")
    assert verify_receipt(value) and value["outcome"] == "data"
    data = value["sections"]["label"]["data"]
    assert requested == [1] and len(data["records"]) == 1
    assert data["records"][0]["label_sections"]["description"][0] == row["description"][0][:4000]
    assert "One matching" in data["coverage"]["scope"]
    recovery = value["sections"]["label"]["recovery"]
    assert recovery["snapshot_status"] == "available"
    handle = parse_uri(recovery["uri"])[0]
    recovered = await service.read_evidence(
        resource_uri(handle, "/records/0/label_sections/description/0", 4000, 4000), scope="test"
    )
    assert recovered["value"] == row["description"][0][4000:8000]
