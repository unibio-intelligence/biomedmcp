"""Public source access requirements, derived from the implemented catalog."""

from .adapters import PROVIDERS
from .extensions import MODELS
from .native.catalog import ADVANCED, SEARCH_SOURCES, SECTION_ALTERNATIVES, SECTIONS


def source_names():
    return sorted(
        (
            set(PROVIDERS)
            | set(MODELS)
            | set(ADVANCED)
            | {source for values in SEARCH_SOURCES.values() for source in values}
            | {source for values in SECTIONS.values() for source in values.values()}
            | {
                source
                for sections in SECTION_ALTERNATIVES.values()
                for sources in sections.values()
                for source in sources
            }
        )
        - {"article-content"}
    )


def policy(source):
    from .source_licensing import review

    required = PROVIDERS.get(source, {}).get("required_env", [])
    required = {
        "nci": ["NCI_API_KEY"],
        "oncokb": ["ONCOKB_TOKEN"],
        "disgenet": ["DISGENET_API_KEY"],
        "patents": ["EPO_OPS_CONSUMER_KEY", "EPO_OPS_CONSUMER_SECRET"],
        "study": ["UBI_PUBLIC_STUDY_DIR", "UBI_PUBLIC_STUDY_MANIFEST"],
    }.get(source, required)
    optional = {
        "ncbi": ["NCBI_API_KEY"],
        "ncbi-records": ["NCBI_API_KEY"],
        "pubmed": ["NCBI_API_KEY"],
        "pmc": ["NCBI_API_KEY"],
        "gtr": ["NCBI_API_KEY"],
        "openfda": ["OPENFDA_API_KEY"],
        "openalex": ["OPENALEX_API_KEY"],
    }.get(source, [])
    gated = source in {"oncokb", "disgenet"}
    return {
        "source": source,
        "license_review": review(source),
        "required_environment": required,
        "optional_environment": optional,
        "access_attestation": source if gated else None,
        "access_policy": "Explicitly qualified licensed/access mode required"
        if gated
        else "Account terms require operator review"
        if source == "patents"
        else "Checksummed public release required"
        if source == "study"
        else "Provider credentials required; review account/access terms"
        if required
        else "No access credential required by this implementation; review source terms",
        "module": PROVIDERS.get(source, {}).get(
            "module", "biomedmcp.extensions" if source in MODELS else "biomedmcp.native.providers"
        ),
    }


def recovery(source, *, configured, importable):
    from .source_licensing import availability

    if not availability(source)[0]:
        return "This source integration is unreleased. Inspect docs/source-licenses.md and choose an eligible source; credentials and access attestations cannot override the hold."
    if not importable:
        return "Install the locked public distribution and restart the process; report adapter_import_failed without exception text."
    if source == "study":
        return "Install a reviewed checksummed public study release and inspect its assay coverage; see docs/studies.md."
    if source == "depmap":
        return "This retained route is unavailable. Discover a released platform data capability or choose another qualified source."
    if not configured:
        return "Configure the named environment settings and required access attestation outside tool arguments, then restart the process."
    return "Configuration and importability do not establish live health. Run separate authorized live canaries when needed."
