"""Reviewed source permissions are independent of credentials and live health."""

import json
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from urllib.parse import urlsplit

from .errors import ResearchError

ACCEPTED_DATA_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "ODbL-1.0"}

SCOPED_LICENSES = {
    "MIT": {"eve"},  # Publisher explicitly licenses all EVE site data under MIT.
    "LicenseRef-GTEx-Portal": {"gtex"},
    "LicenseRef-Ensembl-Project": {"ensembl"},
    "LicenseRef-EBI-GWAS": {"gwas"},
    "LicenseRef-NCBI-PublicData": {"ncbi", "ncbi-records"},
    "LicenseRef-MyGene-Identity": {"mygene"},
    "per_release": {"study"},
}


@lru_cache(maxsize=1)
def inventory():
    # Read the installed policy, not an operator environment override. A key or
    # legacy access attestation cannot promote a held integration.
    try:
        value = json.loads(files("biomedmcp").joinpath("source_licenses.json").read_text())
    except (OSError, UnicodeError, ValueError):
        raise ResearchError(
            "source_license_unavailable", "Source permission inventory is unavailable."
        ) from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("sources"), list)
        or not value["sources"]
        or len(value["sources"]) > 64
    ):
        raise ResearchError("source_license_unavailable", "Source permission inventory is unavailable.")
    names = [row.get("source") for row in value["sources"] if isinstance(row, dict)]
    if (
        len(names) != len(value["sources"])
        or any(not isinstance(name, str) for name in names)
        or len(set(names)) != len(names)
    ):
        raise ResearchError("source_license_unavailable", "Source permission inventory is invalid.")
    for row in value["sources"]:
        if (
            not isinstance(row.get("source"), str)
            or not 1 <= len(row["source"]) <= 64
            or not isinstance(row.get("review_status"), str)
            or row.get("review_status")
            not in {"permissive", "restricted", "content_review_required", "unresolved"}
            or not isinstance(row.get("release_status"), str)
            or row.get("release_status") not in {"eligible", "unreleased"}
            or not isinstance(row.get("license"), str)
            or not isinstance(row.get("reason"), str)
            or not row["reason"]
            or not isinstance(row.get("scope"), str)
            or not row["scope"]
            or not isinstance(row.get("byok"), str)
            or row.get("byok")
            not in {
                "not_applicable",
                "optional_local_environment",
                "required_local_environment",
                "optional_local_environment_unreleased",
                "required_local_environment_unreleased",
            }
            or not isinstance(row.get("evidence"), list)
            or not row["evidence"]
            or len(row["evidence"]) > 8
        ):
            raise ResearchError("source_license_unavailable", "Source permission inventory is invalid.")
        reviewed_grant = row["review_status"] == "permissive" and (
            row["license"] in ACCEPTED_DATA_LICENSES
            or row["source"] in SCOPED_LICENSES.get(row["license"], set())
        )
        owner_default = (
            value.get("policy_owner_confirmation") == "confirmed_2026-10-13_default_enable"
            and row.get("activation_basis") == "owner_default_allow"
            and row["review_status"] in {"unresolved", "content_review_required"}
        )
        if row["release_status"] == "eligible" and not (reviewed_grant or owner_default):
            raise ResearchError("source_license_unavailable", "Source permission eligibility is invalid.")
        for url in row["evidence"]:
            if not isinstance(url, str) or not 1 <= len(url) <= 2048:
                raise ResearchError("source_license_unavailable", "Source permission evidence is invalid.")
            try:
                parsed = urlsplit(url)
            except ValueError:
                raise ResearchError(
                    "source_license_unavailable", "Source permission evidence is invalid."
                ) from None
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ResearchError("source_license_unavailable", "Source permission evidence is invalid.")
    return value


def review(source):
    row = next((row for row in inventory()["sources"] if row["source"] == source), None)
    return (
        deepcopy(row)
        if row is not None
        else {
            "source": source,
            "review_status": "unresolved",
            "release_status": "unreleased",
            "license": "not_established",
            "evidence": [],
            "reason": "No reviewed source permission is available; keep unreleased.",
            "byok": "not_applicable",
        }
    )


def availability(source):
    row = review(source)
    ready = row["release_status"] == "eligible"
    return ready, None if ready else "Source integration is unreleased under the source license policy."


def require(source):
    ready, reason = availability(source)
    if not ready:
        raise ResearchError("source_license_unreleased", reason)


def operation_allowed(source, operation):
    """A scoped source grant cannot unlock other operations or old cache rows."""
    scopes = {
        "openfda": {
            "search_recalls",
            "search",
            "get:record",
            "get:safety",
            "get:regulatory",
            "get:label",
            "get:reactions",
            "get:outcomes",
            "get:concomitant",
            "get:guidance",
            "endpoint:drug/enforcement",
            "endpoint:drug/event",
            "endpoint:drug/drugsfda",
            "endpoint:drug/label",
            "endpoint:device/510k",
        },
        "mygene": {
            "query_genes",
            "gene_identity",
            "search",
            "resolve",
            "get:record",
            "get:go",
            "get:aliases",
        },
    }
    return source not in scopes or operation in scopes[source]


def require_operation(source, operation):
    require(source)
    if not operation_allowed(source, operation):
        raise ResearchError(
            "source_license_unreleased", "This source operation is outside the reviewed data projection."
        )


def notice(source, *, version=None, retrieved_at=None):
    """Carry permission and attribution context with acquired evidence."""
    row = review(source)
    if row["release_status"] != "eligible":
        return None
    message = f"Source: {source}; data/API license: {row['license']}; terms: {row['evidence'][0]}."
    if row.get("activation_basis") == "owner_default_allow":
        message += " Enabled by owner policy; exact content rights remain unresolved or conditional. Preserve upstream use limitations."
    if row["license"] in {"CC-BY-SA-3.0", "CC-BY-SA-4.0", "ODbL-1.0"}:
        message += " Preserve attribution and this upstream data license; share-alike obligations apply to qualifying adaptations/databases, separately from Apache-2.0 code."
    if source in {"orcid", "who", "who-ivd", "ols", "mychem", "mydisease"}:
        message += " " + row["reason"]
    if retrieved_at:
        message += f" Retrieved: {retrieved_at}."
    if version:
        message += f" Source release: {version}."
    if source == "gtex":
        message += " Release currency is not verified; compare this release with the GTEx portal before reuse. No provider endorsement is implied."
    return message


def check_inventory(names):
    manifest = inventory()
    actual = {row["source"] for row in manifest["sources"]}
    if actual != set(names):
        raise ResearchError(
            "source_license_unavailable", "Source permission inventory differs from the implemented catalog."
        )
    return manifest


def matrix_markdown():
    manifest = inventory()
    lines = [
        "# Source license and release inventory",
        "",
        manifest["policy"],
        "",
        "Reviewed on "
        + manifest["reviewed_on"]
        + ". Eligibility concerns source permissions only; implementation, scientific qualification and the integration-code license remain separate release gates. Unresolved entries are not completed license reviews. Software licenses and licenses on papers describing a database do not establish permission for its API/data.",
        "",
        "| Source | Data / API terms | Release | Evidence and reason |",
        "| --- | --- | --- | --- |",
    ]
    for row in manifest["sources"]:
        links = ", ".join(f"[source {n}]({url})" for n, url in enumerate(row["evidence"], 1))
        lines.append(
            f"| `{row['source']}` | {row['license']} | {row['release_status']} | {row['reason']} {links} |"
        )
    lines += ["", "## Embedded content", ""]
    for row in manifest["embedded_sources"]:
        links = ", ".join(f"[source {n}]({url})" for n, url in enumerate(row["evidence"], 1))
        lines.append(f"- **{row['source']} — {row['release_status']}:** {row['reason']} {links}")
    lines += [
        "",
        "## Bring your own API key",
        "",
        "Local single-user installations accept supported provider keys through their process environment or client secret storage. Scientific tool arguments never accept credentials. A configured key changes access, not release eligibility. See [the source access matrix](source-access.md) for exact supported variable names.",
        "",
        "A shared hosted server must not mutate process-wide environment variables to switch users' keys. Hosted per-user keys require platform-owned secret storage, authenticated user binding, request-scoped retrieval, revocation, and isolated cache/coalescing/rate-limit scopes. That integration is not implemented or released in this checkout; local environment support is not hosted multi-user BYOK qualification.",
        "",
    ]
    return "\n".join(lines)
