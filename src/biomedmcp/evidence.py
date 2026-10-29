"""Identity-preserving evidence normalization and output bounds."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .contracts import Provenance, ResearchResult, Section
from .runtime import digest


async def retain_composed_recovery(result: ResearchResult, *, store, scope, operation):
    """Store exact omitted rows before nesting or serializing a public view."""
    import json

    pending = result._omitted_evidence
    if pending is None and len(json.dumps(result.model_dump(mode="json")).encode()) <= 100000:
        return
    pending = pending or {
        "records": list(result.records),
        "sections": {name: section.data for name, section in result.sections.items()},
    }
    recovery = (
        await store.publish(
            {"operation": operation, **pending},
            result.provenance,
            {},
            scope=scope,
            view="composed_result_range",
        )
        if store is not None
        else {"snapshot_status": "unavailable", "reason": "snapshot_storage_unavailable"}
    )
    result.query.setdefault("output_omissions", {})["composed_recovery"] = recovery


async def compose_evidence(result: ResearchResult, *, store, scope, operation) -> Section:
    """Retain the constituent operation's evidence and recovery context."""
    from .public_catalog import validated_action

    await retain_composed_recovery(result, store=store, scope=scope, operation=operation)
    continuation = None
    if result.next_cursor and result.entity and result.query.get("query"):
        filters = result.query.get("execution", {}).get("requested_filters", {})
        continuation = validated_action(
            {
                "tool": "search",
                "arguments": {
                    "entity": result.entity.value,
                    "query": result.query["query"],
                    "limit": result.query.get("limit", 10),
                    "filters": filters,
                    "cursor": result.next_cursor,
                },
            }
        )
    return Section(
        outcome=result.outcome,
        data={
            "records": result.records,
            "provider_status": {
                name: section.model_dump(mode="json") for name, section in result.sections.items()
            },
            "query": result.query,
            "next_cursor": result.next_cursor,
            "continuation": continuation,
            "next_actions": [validated_action(action) for action in result.next_actions],
        },
        evidence_ids=[proof.evidence_id for proof in result.provenance],
        warnings=result.warnings,
        truncated=result.truncated,
    )


def bound(
    value: Any, *, rows: int = 25, string_limit: int = 4000, depth: int = 0, omissions=None, pointer="",
    _redact=None,
) -> tuple[Any, bool]:
    from .content_boundary import SECRET_FIELD
    from .logging_safety import redactor
    from .recovery import pointer_child

    redact = _redact if _redact is not None else redactor()
    if depth > 12:
        if omissions is not None:
            omissions.add(pointer, "depth", None, None)
        return {"truncated": True}, True
    if isinstance(value, str):
        safe = redact(value)
        if omissions is not None:
            omissions.redacted |= safe != value
        value = safe
        if omissions is not None and len(value) > string_limit:
            omissions.add(pointer, "characters", len(value), string_limit)
        return value[:string_limit], len(value) > string_limit
    if isinstance(value, list):
        if omissions is not None and len(value) > rows:
            omissions.add(pointer, "items", len(value), rows)
        values = [
            bound(
                v,
                rows=rows,
                string_limit=string_limit,
                depth=depth + 1,
                omissions=omissions,
                pointer=pointer_child(pointer, i),
                _redact=redact,
            )
            for i, v in enumerate(value[:rows])
        ]
        return [v for v, _ in values], len(value) > rows or any(t for _, t in values)
    if isinstance(value, dict):
        if omissions is not None and len(value) > 100:
            omissions.add(pointer, "fields", len(value), 100)
        output = {}
        truncated = False
        for key, item in list(value.items())[:100]:
            safe_key = redact(str(key))
            secret_field = bool(SECRET_FIELD.fullmatch(str(key)))
            if omissions is not None:
                omissions.redacted |= safe_key != str(key) or secret_field
            if secret_field:
                output[safe_key] = "[REDACTED]"
                continue
            output[safe_key], cut = bound(
                item,
                rows=rows,
                string_limit=string_limit,
                depth=depth + 1,
                omissions=omissions,
                pointer=pointer_child(pointer, safe_key),
                _redact=redact,
            )
            truncated |= cut
        return output, truncated or len(value) > 100
    return value, False


def article_identifiers(record: dict[str, Any]) -> set[str]:
    identifiers = set()
    external = record.get("externalIds") or record.get("external_ids") or {}
    for key, prefix in (
        ("pmid", "pmid"),
        ("pmcid", "pmcid"),
        ("doi", "doi"),
        ("paperId", "s2"),
    ):
        value = (
            record.get(key)
            or external.get(key.upper())
            or external.get({"pmid": "PubMed", "pmcid": "PubMedCentral", "doi": "DOI"}.get(key, ""))
        )
        if value:
            normalized = str(value).strip()
            if prefix == "doi":
                normalized = (
                    normalized.lower()
                    .removeprefix("https://doi.org/")
                    .removeprefix("http://dx.doi.org/")
                    .removeprefix("doi:")
                )
            identifiers.add(f"{prefix}:{normalized}")
    return identifiers


def deduplicate_articles(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[tuple[set[str], dict[str, Any]]] = []
    for record in records:
        ids = article_identifiers(record)
        matches = [i for i, (keys, _) in enumerate(groups) if ids and keys & ids]
        merged = dict(record)
        contributors = set(
            [record["sources"]] if isinstance(record.get("sources"), str) else record.get("sources") or []
        )
        for i in reversed(matches):
            old_ids, old = groups.pop(i)
            ids |= old_ids
            contributors.update(
                [old["sources"]] if isinstance(old.get("sources"), str) else old.get("sources") or []
            )
            ranks = {**merged.get("_provider_ranks", {})}
            for source, rank in old.get("_provider_ranks", {}).items():
                ranks[source] = min(rank, ranks.get(source, rank))
            retracted = (
                True
                if True in (merged.get("is_retracted"), old.get("is_retracted"))
                else False
                if False in (merged.get("is_retracted"), old.get("is_retracted"))
                else None
            )
            assertions = [*merged.get("source_assertions", []), *old.get("source_assertions", [])]
            if assertions:
                # Different sources/windows remain separate assertions. An
                # aggregate flag never discards a reported disagreement.
                assertions = list({digest(assertion): assertion for assertion in assertions}.values())
            identities = [*merged.get("identities", []), *old.get("identities", [])]
            if identities:
                identities = list({digest(identity): identity for identity in identities}.values())
            # Keep higher-ranked first occurrence's scientific values.
            merged = {
                **merged,
                **{k: v for k, v in old.items() if v is not None},
                "_provider_ranks": ranks,
                "is_retracted": retracted,
                **({"source_assertions": assertions} if assertions else {}),
                **({"identities": identities} if identities else {}),
                "evidence_ids": sorted(
                    set(merged.get("evidence_ids", [])) | set(old.get("evidence_ids", []))
                ),
            }
        if contributors:
            merged["sources"] = sorted(contributors)
        entry = (ids, merged)
        if matches:
            groups.insert(min(matches), entry)
        else:
            groups.append(entry)
    return [record for _, record in groups]


def records_from(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r if isinstance(r, dict) else {"value": r} for r in payload]
    if isinstance(payload, dict):
        for key in (
            "articles",
            "concepts",
            "results",
            "hits",
            "studies",
            "genes",
            "drugs",
            "variants",
            "items",
            "records",
            "data",
        ):
            if isinstance(payload.get(key), list):
                return records_from(payload[key])
        return [payload] if payload else []
    return [{"value": payload}] if payload is not None else []


def scientific_outcome(payload: Any) -> str:
    """Shared section/observation semantics; failed evidence is never success."""
    outcome = "data" if records_from(payload) else "empty"
    if isinstance(payload, dict):
        if isinstance(payload.get("resolution"), str) and payload["resolution"] in {"empty", "ambiguous"}:
            outcome = payload["resolution"]
        if "variant" in payload and payload["variant"] is None:
            outcome = "empty"
        if any(
            (value.get("outcome") if isinstance(value, dict) else value)
            in {"error", "unavailable", "failed", "timeout", "degraded", "partial"}
            for value in payload.get("section_outcomes", {}).values()
        ):
            outcome = "partial"
    return outcome


def visible_payload(payload):
    visible = (
        {
            k: v
            for k, v in payload.items()
            if k
            not in {"_provider_page", "_provider_pages", "_interpro_continuation", "_complexportal_state"}
        }
        if isinstance(payload, dict)
        else payload
    )
    if isinstance(payload, dict) and "_meta" in payload:
        visible = {
            **visible,
            "_meta": {
                k: v
                for k, v in payload["_meta"].items()
                if k in {"evidence_urls", "section_sources", "source_status", "search_plan", "ranking"}
            },
        }
    return visible


def section_from(
    source: str,
    record: dict[str, Any],
    cached: bool,
    *,
    record_id: str | None = None,
    version: str | None = None,
    origin_hint: str | None = None,
    row_limit: int = 25,
) -> tuple[Section, Provenance]:
    payload = record["payload"]
    evidence_id = (
        "ev_" + digest({"source": source, "id": record_id, "version": version, "data": payload})[:24]
    )
    from .recovery import Omissions

    visible = visible_payload(payload)
    omissions = Omissions()
    data, truncated = bound(visible, rows=row_limit, omissions=omissions)
    outcome = scientific_outcome(payload)
    warnings = []
    if isinstance(payload, dict):
        statuses = payload.get("section_outcomes", {})
        failures = [
            name
            for name, value in statuses.items()
            if (value.get("outcome") if isinstance(value, dict) else value)
            in {"error", "unavailable", "failed", "timeout"}
        ]
        partial = [
            name
            for name, value in statuses.items()
            if (value.get("outcome") if isinstance(value, dict) else value) in {"degraded", "partial"}
        ]
        if failures:
            outcome = "partial"
            warnings.append("Unavailable source sections: " + ", ".join(failures))
        if partial:
            warnings.append("Partial source sections: " + ", ".join(partial))
        if payload.get("warnings"):
            warnings.extend(str(w)[:500] for w in payload["warnings"][:8])
    url = payload.get("url") if isinstance(payload, dict) else None
    if not isinstance(url, str) or urlparse(url).scheme not in {"https", "http"}:
        url = None
    actual_sources = set()
    if isinstance(payload, dict):
        statuses = list(payload.get("section_outcomes", {}).values()) + payload.get("_meta", {}).get(
            "section_sources", []
        )
        for status in statuses:
            if isinstance(status, dict) and status.get("outcome") in {"data", "empty", "degraded"}:
                actual_sources.update(status.get("sources", []))
        for provider in payload.get("sources", []) if isinstance(payload.get("sources"), list) else []:
            if isinstance(provider, str):
                actual_sources.add(provider)
    for row in records_from(payload):
        provider = row.get("source")
        if isinstance(provider, str) and provider.strip():
            actual_sources.add(provider)
    if not actual_sources and origin_hint:
        actual_sources.add(origin_hint)
    actual_sources.add(source)
    origin = source
    # This release is observed in the validated source entry, not a replay pin.
    if (
        source == "protein-atlas"
        and isinstance(payload, dict)
        and payload.get("record_type") == "hpa_source_xml"
    ):
        from .hpa_records import HPASourceRecord

        acquired = HPASourceRecord.model_validate(
            {key: payload[key] for key in HPASourceRecord.model_fields if key in payload}
        )
        version = acquired.source_release
    if source in {"interpro", "alphamissense", "eve"} and isinstance(payload, dict):
        version = payload.get("source_release")
    if source in {"pdb", "uniprot"} and isinstance(payload, dict):
        version = payload.get("source_release")
    if source == "ncbi" and isinstance(payload, dict) and payload.get("record_type") == "clinvar_assertions":
        version = payload.get("source_release")
    provenance = Provenance(
        evidence_id=evidence_id,
        source=origin,
        sources=sorted(actual_sources),
        processor="Ubi Python",
        record_id=record_id,
        url=url,
        source_version=version,
        content_hash=digest(payload),
        cached=cached,
        retrieved_at=datetime.fromtimestamp(record["retrieved_at"], UTC).isoformat(),
    )
    return Section(
        outcome=outcome,
        data=data,
        evidence_ids=[evidence_id],
        warnings=warnings,
        truncated=truncated,
        recovery=omissions.metadata(),
    ), provenance
