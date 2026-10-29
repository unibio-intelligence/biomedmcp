"""Pair evidence uses independent signed state, including nested assessment actions."""

from .opentargets_variant_evidence import VariantContinuation


def analysis(payload):
    nested = payload.get("association_analysis")
    return nested if isinstance(nested, dict) else payload


def partial(payload, reason):
    pair = analysis(payload)
    pair["section_outcomes"]["evidence"] = {"outcome": "partial"}
    pair["coverage"]["continuation_status"] = reason
    if pair is not payload:
        payload["section_outcomes"]["association_analysis"] = {"outcome": "partial"}


class PairContinuation(VariantContinuation):
    operation = "analyze_association"
    page_key = "pair_evidence"
    cache_prefix = "opentargets-pair-page:"
    label = "Target-disease evidence"

    @staticmethod
    def request(payload, params, operation):
        if operation == "analyze_association":
            return params
        # Constructed by the scientific primitive from validated service input;
        # provider content cannot supply executable request parameters.
        return payload["_provider_pages"]["pair_evidence"]["request"]
