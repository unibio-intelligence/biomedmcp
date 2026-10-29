"""EVE never merges clinical/aggregator fields or substitutes protein identities."""

import copy
import csv
import io
import zipfile

import pytest
from native_helpers import HTTP
from test_alphamissense import protein_inputs

from biomedmcp.dispatch import execute
from biomedmcp.domain import ResearchService
from biomedmcp.errors import ResearchError
from biomedmcp.native.eve import FIELDS, acquire, parse_archive, plan

pytestmark = pytest.mark.source_permissions


def fixture():
    up = protein_inputs()[0]
    up["results"][0]["uniProtkbId"] = "BRAF_HUMAN"
    stats = {
        "protein_id": 512,
        "id": 512,
        "pid": "BRAF_HUMAN",
        "pid_for_website": "BRAF_HUMAN",
        "gene_id": "BRAF",
        "uniprot_id": "P15056",
    }
    row = {
        "wt_aa": "V",
        "position": "2",
        "mt_aa": "E",
        "EVE_scores_ASM": "0.64",
        "uncertainty_ASM": "0.65",
        "EVE_classes_75_pct_retained_ASM": "Pathogenic",
        "ClinVar_ClinicalSignificance": "UNREVIEWED_SENTINEL",
        "EVE_scores_BPU": "0.61",
    }
    return up, stats, row


def archive(row, *, filename="BRAF_HUMAN.csv", duplicate=False):
    text = io.StringIO()
    w = csv.DictWriter(text, fieldnames=list(row))
    w.writeheader()
    w.writerow(row)
    if duplicate:
        w.writerow(row)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename, text.getvalue())
    return out.getvalue()


def http():
    up, stats, row = fixture()
    return HTTP(up, 512, stats, archive(row))


async def test_exact_source_score_uncertainty_class_and_mit_notice_are_preserved():
    h = http()
    v = await acquire(h, "BRAF V2E")
    assert v["records"][0]["score"] == 0.64 and v["records"][0]["uncertainty"] == 0.65
    assert v["records"][0]["classification_75_pct_retained"] == "Pathogenic"
    assert v["records"][0]["model"] == "ASM" and v["license"] == "MIT"
    assert "Copyright (c) 2022 Joseph Min" in v["license_notice"]
    assert len(v["score_artifact_sha256"]) == 64 and v["score_artifact_sha256"] in v["source_release"]
    assert "UNREVIEWED_SENTINEL" not in str(v) and "BPU" not in str(v)
    assert h.calls[-1][2] == {"params": {"variants": "True"}, "binary": True}
    assert v["protein_identity"]["sequence_version"] == 4


@pytest.mark.parametrize(
    "key,value",
    [
        ("protein_id", 42),
        ("id", True),
        ("pid", "OTHER_HUMAN"),
        ("pid_for_website", "OTHER_HUMAN"),
        ("uniprot_id", "P99999"),
        ("gene_id", "OTHER"),
    ],
)
async def test_profile_identity_mismatch_stops_before_archive(key, value):
    up, stats, row = fixture()
    stats[key] = value
    h = HTTP(up, 512, stats)
    with pytest.raises(ResearchError, match="identities"):
        await acquire(h, "BRAF V2E")
    assert len(h.calls) == 3


@pytest.mark.parametrize("identifier", ["rs123", "chr7:10:A:T", "BRAF V2V", "BRAF V2*"])
def test_unqualified_or_non_substitution_input_fails_before_network(identifier):
    with pytest.raises(ResearchError) as e:
        plan(identifier)
    assert e.value.code == "unsupported_variant"


@pytest.mark.parametrize(
    "key,value",
    [
        ("wt_aa", "A"),
        ("position", "3"),
        ("position", "0"),
        ("mt_aa", "*"),
        ("EVE_scores_ASM", "NaN"),
        ("EVE_scores_ASM", "1.1"),
        ("uncertainty_ASM", "inf"),
        ("uncertainty_ASM", "-1"),
        ("EVE_classes_75_pct_retained_ASM", "likely_pathogenic"),
    ],
)
async def test_malformed_or_mismatched_score_rows_are_not_evidence(key, value):
    up, stats, row = fixture()
    row[key] = value
    with pytest.raises(ResearchError):
        await acquire(HTTP(up, 512, stats, archive(row)), "BRAF V2E")


@pytest.mark.parametrize("filename", ["../BRAF_HUMAN.csv", "OTHER_HUMAN.csv", "BRAF_HUMAN.csv/"])
async def test_archive_member_identity_is_checked_without_extracting_paths(filename):
    up, stats, row = fixture()
    with pytest.raises(ResearchError):
        await acquire(HTTP(up, 512, stats, archive(row, filename=filename)), "BRAF V2E")


async def test_duplicate_contexts_cannot_be_averaged_or_selected():
    up, stats, row = fixture()
    with pytest.raises(ResearchError):
        await acquire(HTTP(up, 512, stats, archive(row, duplicate=True)), "BRAF V2E")


async def test_missing_score_is_explicit_not_zero_or_benign():
    up, stats, row = fixture()
    row["EVE_scores_ASM"] = ""
    v = await acquire(HTTP(up, 512, stats, archive(row)), "BRAF V2E")
    assert v["records"] == [] and v["coverage"]["score_status"] == "no_score_supplied"


async def test_missing_protein_is_unavailable_not_absent_effect():
    up, _, _ = fixture()
    h = HTTP(up, None)
    with pytest.raises(ResearchError) as e:
        await acquire(h, "BRAF V2E")
    assert e.value.code == "source_unavailable" and len(h.calls) == 2


@pytest.mark.parametrize("raw", [b"not a zip", b"x" * 8_000_001])
def test_archive_bounds_and_format_are_checked(raw):
    with pytest.raises(ResearchError):
        parse_archive(raw, "BRAF_HUMAN", {})


async def test_real_mcp_dispatch_owns_optional_eve_section_without_held_provider():
    from biomedmcp.receipts import verify_receipt
    from biomedmcp.output_contracts import validate_output

    service = ResearchService(http=http())
    v = (
        await execute(service, "variant_evidence", {"id": "BRAF V2E", "sections": ["eve"]}, scope="test")
    ).model_dump(mode="json")
    validate_output("variant_evidence", v)
    assert v["outcome"] == "data" and verify_receipt(v)
    assert v["provenance"][0]["source"] == "eve" and v["provenance"][0]["sources"] == ["eve", "uniprot"]
    assert v["provenance"][0]["source_version"].startswith("EVE ASM")


async def test_binary_archive_boundary_preserves_bytes_and_rejects_http_errors(monkeypatch):
    import httpx
    from biomedmcp.native import http as boundary

    raw = archive(fixture()[2])
    status = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return httpx.Response(
                status, content=raw, request=httpx.Request("GET", "https://evemodel.org/fixture")
            )

    monkeypatch.setattr(boundary.httpx, "AsyncClient", Client)
    assert await boundary.ProviderHTTP().get("https://evemodel.org/fixture", binary=True) == raw
    status = 502
    with pytest.raises(ResearchError) as error:
        await boundary.ProviderHTTP().get("https://evemodel.org/fixture", binary=True)
    assert error.value.code == "source_unavailable"
