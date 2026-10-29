"""Scoped, expiring snapshots for bounded reads of acquired public evidence.

Resources never acquire provider data or interpret source text as instructions.
The snapshot is a retained source window, not an exhaustive provider dataset.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import zlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, ConfigDict, Field, ValidationError, field_validator, model_validator
from redis.exceptions import RedisError

from .contracts import Provenance, StrictModel
from .errors import ResearchError
from .native import REVISION
from .runtime import digest, public_continuation_resource, remaining_budget
from .snapshot_codec import VALUE_BYTES, PackingError, pack, unpack, workers

PREFIX = "biomedmcp://evidence/"
TEMPLATE = PREFIX + "{handle}/{selector}/{start}/{count}"
SNAPSHOT_BYTES = 1_000_000
RESOURCE_BYTES = 65_536
PREFERRED_RESOURCE_BYTES = 16_384
TTL = 600
MAX_SNAPSHOTS = 64
MAX_OMISSIONS = 32
ITEM_RANGE = 100
POINTER_BYTES = 1024
HANDLE = r"(?:[a-f0-9]{32}|public_[a-f0-9]{32}_[a-f0-9]{64})"
URI = re.compile(
    rf"^biomedmcp://evidence/({HANDLE})/(root|p_[A-Za-z0-9_-]{{1,1366}})/(0|[1-9]\d{{0,6}})/([1-9]\d{{0,3}})$"
)


def invalid_resource():
    return ResearchError("invalid_resource", "Use an evidence resource URI supplied by this service.")


def pointer_child(pointer, key):
    return pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")


def select_pointer(value, pointer):
    """Navigate an RFC 6901 pointer without aliases or list-index coercion."""
    try:
        for part in pointer.split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9]\d*", part):
                    raise ValueError()
                value = value[int(part)]
            elif isinstance(value, dict):
                value = value[part]
            else:
                raise TypeError()
    except (KeyError, IndexError, ValueError, TypeError):
        raise invalid_resource() from None
    return value


def omission_links(recovery, value, handle):
    """Only promote a range that still exists in the sanitized snapshot."""
    kinds = {"characters": str, "items": list, "fields": dict}
    for omission in recovery.get("omissions", []):
        omission.pop("uri", None)
        if not omission["addressable"]:
            continue
        try:
            selected = select_pointer(value, omission["pointer"])
            kind = omission["kind"]
            if kind != "depth" and (
                not isinstance(selected, kinds[kind]) or len(selected) != omission["total"]
            ):
                raise invalid_resource()
        except ResearchError:
            omission["recovery_status"] = "source_data_redacted_or_link_disabled"
            continue
        omission["uri"] = resource_uri(
            handle,
            omission["pointer"],
            omission["delivered"] if kind != "depth" else 0,
            4000 if kind == "characters" else ITEM_RANGE if kind == "items" else 25,
        )


def resource_uri(handle, pointer="", start=0, count=25):
    if len(pointer.encode()) > POINTER_BYTES:
        return None
    selector = (
        "root" if not pointer else "p_" + base64.urlsafe_b64encode(pointer.encode()).decode().rstrip("=")
    )
    return f"{PREFIX}{handle}/{selector}/{start}/{count}"


def parse_uri(uri):
    match = URI.fullmatch(uri) if isinstance(uri, str) else None
    if not match:
        raise invalid_resource()
    handle, selector, start, count = match.groups()
    try:
        pointer = (
            ""
            if selector == "root"
            else base64.b64decode(
                selector[2:] + "=" * (-len(selector[2:]) % 4), altchars=b"-_", validate=True
            ).decode()
        )
    except (ValueError, UnicodeError):
        raise invalid_resource() from None
    if (pointer and not pointer.startswith("/")) or len(pointer.encode()) > POINTER_BYTES:
        raise invalid_resource()
    if re.search(r"~(?![01])", pointer) or int(start) > VALUE_BYTES or int(count) > 4000:
        raise invalid_resource()
    if resource_uri(handle, pointer, int(start), int(count)) != uri:
        raise invalid_resource()
    return handle, pointer, int(start), int(count)


class Omissions:
    def __init__(self):
        self.items = []
        self.count = 0
        self.redacted = False

    def add(self, pointer, kind, total, delivered):
        self.count += 1
        if len(self.items) >= MAX_OMISSIONS:
            return
        addressed = len(pointer.encode()) <= POINTER_BYTES
        self.items.append(
            {
                "pointer": pointer if addressed else None,
                "kind": kind,
                "total": total,
                "delivered": delivered,
                "omitted": total - delivered if total is not None else None,
                "addressable": addressed,
            }
        )

    def metadata(self):
        return {
            "omissions": self.items,
            "omissions_count": self.count,
            "omissions_truncated": self.count > len(self.items),
            "redacted": self.redacted,
        }


class Snapshot(StrictModel):
    schema_version: Literal["1.1"] = "1.1"
    implementation: str
    scope_sha256: str
    expires_at: float = Field(allow_inf_nan=False)
    provenance: list[Provenance] = Field(min_length=1, max_length=64)
    view: Literal["acquired_evidence_range", "composed_result_range"] = "acquired_evidence_range"
    value: Any
    encoding: Literal["json", "zlib-json"]
    encoded_value: str | None = Field(max_length=SNAPSHOT_BYTES)
    value_utf8_bytes: int = Field(ge=1, le=VALUE_BYTES)
    value_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_sha256: str
    redacted: bool = False

    @model_validator(mode="after")
    def encoding_shape(self):
        if self.encoding == "json" and self.encoded_value is not None:
            raise ValueError("Plain snapshot cannot contain an encoded value")
        if self.encoding == "zlib-json" and (self.value is not None or not self.encoded_value):
            raise ValueError("Compressed snapshot must contain only its encoded value")
        return self


class EvidenceRange(StrictModel):
    unit: Literal["fields", "items", "characters", "value"]
    start: int = Field(ge=0, le=VALUE_BYTES)
    end_exclusive: int = Field(ge=0, le=VALUE_BYTES)
    total: int = Field(ge=0, le=VALUE_BYTES)

    @model_validator(mode="after")
    def coherent(self):
        if not self.start <= self.end_exclusive <= self.total:
            raise ValueError("Evidence range exceeds its acquired value")
        return self


class RecoveryModel(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ResourceReference(RecoveryModel):
    uri: str | None = Field(pattern=URI.pattern)

    @field_validator("uri")
    @classmethod
    def executable_uri(cls, value):
        if value is not None:
            parse_uri(value)
        return value


class FieldReference(ResourceReference):
    field: str = Field(max_length=256)
    field_truncated: bool = False
    reason: Literal["pointer_byte_budget"] | None = None


class ItemReference(ResourceReference):
    index: int = Field(ge=0, le=VALUE_BYTES)


class Omission(RecoveryModel):
    pointer: str | None = Field(max_length=POINTER_BYTES)
    kind: Literal["fields", "items", "characters", "depth"]
    total: int | None = Field(ge=0, le=VALUE_BYTES)
    delivered: int | None = Field(ge=0, le=VALUE_BYTES)
    omitted: int | None = Field(ge=0, le=VALUE_BYTES)
    addressable: bool
    uri: str | None = Field(default=None, pattern=URI.pattern)
    recovery_status: Literal["source_data_redacted_or_link_disabled"] | None = None


class EvidenceResponse(RecoveryModel):
    schema_version: Literal["1.0"]
    content_policy: Literal["data_only"]
    view: Literal["acquired_evidence_range", "composed_result_range"]
    evidence_ids: list[str] = Field(min_length=1, max_length=64)
    provenance: list[Provenance] = Field(min_length=1, max_length=64)
    source_permissions: list[str] = Field(default_factory=list, max_length=4096)
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    value_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    value_utf8_bytes: int = Field(ge=1, le=VALUE_BYTES)
    result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    redacted: bool
    expires_at: AwareDatetime
    pointer: str = Field(max_length=POINTER_BYTES)
    range: EvidenceRange
    value: Any
    truncated: bool
    children: list[FieldReference | ItemReference] = Field(max_length=ITEM_RANGE)
    omissions: list[Omission] = Field(max_length=MAX_OMISSIONS)
    omissions_count: int = Field(ge=0)
    omissions_truncated: bool
    next_uri: str | None
    value_omitted: str | None = None


class EvidenceStore:
    # One cluster slot; all replicas share this bounded family. Expired index
    # members are removed before oldest-snapshot eviction. Redis payload is
    # <= 64 MB; its bounded index remains until entries are replaced or cleared.
    PUT = """
local now=redis.call('TIME'); local ms=tonumber(now[1])*1000+math.floor(tonumber(now[2])/1000)
local expired=redis.call('ZRANGEBYSCORE',KEYS[2],'-inf',ms-tonumber(ARGV[2])*1000)
for _,key in ipairs(expired) do if redis.call('EXISTS',key)==0 then redis.call('ZREM',KEYS[2],key) end end
redis.call('ZADD',KEYS[2],ms,KEYS[1])
local surplus=redis.call('ZCARD',KEYS[2])-tonumber(ARGV[3])
if surplus>0 then
  local old=redis.call('ZRANGE',KEYS[2],0,surplus-1)
  for _,key in ipairs(old) do redis.call('DEL',key); redis.call('ZREM',KEYS[2],key) end
end
if not redis.call('ZSCORE',KEYS[2],KEYS[1]) then return 0 end
redis.call('SET',KEYS[1],ARGV[1],'EX',ARGV[2])
return 1
"""

    def __init__(self, cache, signing_key=None):
        self.cache = cache
        self.signing_key = signing_key

    def public_scope(self, scope):
        resource = public_continuation_resource(scope)
        if resource is None or not self.signing_key:
            return None
        return "public-evidence:" + digest({"resource": resource, "implementation": REVISION})

    def signature(self, handle, scope):
        return hmac.new(self.signing_key, ("public-evidence-v1:" + scope + ":" + handle).encode(),
                        hashlib.sha256).hexdigest()

    @staticmethod
    def key(scope, handle):
        return "{evidence}:" + digest({"scope": scope, "implementation": REVISION}) + ":" + handle

    async def publish(self, value, proof, recovery, *, scope, view="acquired_evidence_range"):
        recovery = {"schema_version": "1.0", "redacted": False, **recovery, "snapshot_status": "unavailable"}
        proofs = proof if isinstance(proof, list) else [proof]
        if not proofs or len(proofs) > 64:
            return {**recovery, "reason": "snapshot_provenance_budget"}
        # Only the trusted anonymous host context can opt public acquisitions
        # into transferable recovery. Account and BYOK snapshots stay scoped.
        public_scope = self.public_scope(scope)
        if public_scope is not None:
            scope = public_scope
        try:
            async with asyncio.timeout(remaining_budget(2)):
                packed, safe, changed = await workers.run(pack, value)
        except PackingError as exc:
            return {**recovery, "reason": exc.reason}
        except (TimeoutError, ResearchError, RuntimeError):
            return {**recovery, "reason": "snapshot_worker_unavailable"}
        except (ValueError, TypeError, RecursionError, zlib.error):
            return {**recovery, "reason": "snapshot_invalid_data"}
        redacted = changed or recovery["redacted"]
        recovery["redacted"] = redacted
        if packed["encoded_value"] is not None and len(packed["encoded_value"]) > SNAPSHOT_BYTES:
            return {**recovery, "reason": "snapshot_byte_budget"}
        body = Snapshot(
            implementation=REVISION,
            scope_sha256=digest(scope),
            expires_at=time.time() + TTL,
            provenance=proofs,
            view=view,
            **packed,
            snapshot_sha256="0" * 64,
            redacted=redacted,
        ).model_dump(mode="json")
        body["snapshot_sha256"] = digest({k: v for k, v in body.items() if k != "snapshot_sha256"})
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False)
        recovery["redacted"] = redacted
        if len(encoded.encode()) > SNAPSHOT_BYTES:
            return {**recovery, "reason": "snapshot_byte_budget"}
        handle = secrets.token_hex(16)
        if public_scope is not None:
            handle = "public_" + handle + "_" + self.signature(handle, scope)
        key = self.key(scope, handle)
        try:
            async with asyncio.timeout(remaining_budget(2)):
                redis = getattr(self.cache, "redis", None)
                if redis is not None:
                    stored = await redis.eval(
                        self.PUT,
                        2,
                        "biomedmcp:result:" + key,
                        "biomedmcp:evidence:{evidence}:index",
                        encoded,
                        TTL,
                        MAX_SNAPSHOTS,
                    )
                else:
                    stored = await self.cache.put(key, body, TTL)
                    memory = getattr(self.cache, "values", None)
                    if memory is not None:
                        keys = [name for name in memory if name.startswith("{evidence}:")]
                        for old in keys[: max(0, len(keys) - MAX_SNAPSHOTS)]:
                            memory.pop(old, None)
                        stored = stored and key in memory
        except (RedisError, OSError, TimeoutError, ResearchError):
            return {**recovery, "reason": "snapshot_storage_unavailable"}
        if not stored:
            return {**recovery, "reason": "snapshot_storage_budget"}
        omission_links(recovery, safe, handle)
        metadata = {
            **recovery,
            "snapshot_status": "available",
            "uri": resource_uri(handle),
            "expires_at": datetime.fromtimestamp(body["expires_at"], UTC).isoformat(),
            "eviction": "May expire earlier under cache pressure.",
            "snapshot_sha256": body["snapshot_sha256"],
            "value_sha256": body["value_sha256"],
            "value_utf8_bytes": body["value_utf8_bytes"],
        }
        while len(json.dumps(metadata, ensure_ascii=False).encode()) > 8192 and metadata.get("omissions"):
            metadata["omissions"].pop()
            metadata["omissions_truncated"] = True
        return metadata

    async def read(self, uri, *, scope, availability=None):
        handle, pointer, start, count = parse_uri(uri)
        if handle.startswith("public_"):
            public_scope = self.public_scope(scope)
            _, nonce, signature = handle.split("_")
            if public_scope is None or not hmac.compare_digest(signature, self.signature(nonce, public_scope)):
                raise ResearchError("evidence_unavailable", "Public evidence recovery grant is unavailable for this resource.")
            scope = public_scope
        value = await self.cache.get(self.key(scope, handle))
        if value is None:
            raise ResearchError(
                "evidence_unavailable",
                "Evidence snapshot is unavailable, expired, or outside this account scope. Repeat the original public request if needed.",
            )
        try:
            snapshot = Snapshot.model_validate(value)
            expected = digest({k: v for k, v in value.items() if k != "snapshot_sha256"})
            if (
                snapshot.snapshot_sha256 != expected
                or snapshot.scope_sha256 != digest(scope)
                or snapshot.implementation != REVISION
                or snapshot.expires_at <= time.time()
            ):
                raise ValueError()
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > SNAPSHOT_BYTES:
                raise ValueError()
        except (ValidationError, ValueError, TypeError):
            raise ResearchError(
                "evidence_invalid_data",
                "Stored evidence snapshot failed integrity validation; repeat the original request.",
            ) from None
        if availability is not None and any(
            not availability(source)[0]
            for proof in snapshot.provenance
            for source in {proof.source, *proof.sources}
        ):
            raise ResearchError(
                "source_access_denied",
                "The snapshot source is no longer available under this service's access configuration.",
            )
        try:
            async with asyncio.timeout(remaining_budget(2)):
                decoded = await workers.run(unpack, snapshot)
        except (TimeoutError, ResearchError, RuntimeError):
            raise ResearchError(
                "evidence_unavailable", "Evidence decoding is busy; retry later.", retryable=True
            ) from None
        except (ValueError, TypeError, RecursionError, zlib.error):
            raise ResearchError(
                "evidence_invalid_data", "Stored evidence failed decoding validation."
            ) from None
        if snapshot.expires_at <= time.time():
            raise ResearchError(
                "evidence_unavailable", "Evidence expired during decoding; repeat the request."
            )
        selected = select_pointer(decoded, pointer)
        return bounded_read(snapshot, handle, pointer, selected, start, count, full_value=decoded)


def bounded_read(snapshot, handle, pointer, selected, start, count, *, full_value, requested_count=None):
    from .evidence import bound
    from .source_licensing import notice

    requested_count = count if requested_count is None else requested_count

    collection = isinstance(selected, (dict, list, str))
    total = len(selected) if collection else 1
    if start > total or (not collection and start != 0):
        raise invalid_resource()
    unit = (
        "fields"
        if isinstance(selected, dict)
        else "items"
        if isinstance(selected, list)
        else "characters"
        if isinstance(selected, str)
        else "value"
    )
    effective = min(
        count, 4000 if isinstance(selected, str) else ITEM_RANGE if isinstance(selected, list) else 25
    )
    end = min(total, start + effective)
    if isinstance(selected, dict):
        keys = list(selected)[start:end]
        window = {k: selected[k] for k in keys}
    elif isinstance(selected, (list, str)):
        window = selected[start:end]
    else:
        window = selected
    omissions = Omissions()
    if isinstance(window, list):
        parts = [
            bound(item, omissions=omissions, pointer=pointer_child(pointer, index))
            for index, item in enumerate(window, start)
        ]
        bounded, truncated = [item for item, _ in parts], any(cut for _, cut in parts)
    else:
        bounded, truncated = bound(window, omissions=omissions, pointer=pointer)
    children = []
    if isinstance(window, dict):
        for key, item in window.items():
            target = pointer_child(pointer, key)
            children.append(
                {
                    "field": key[:256],
                    **({"field_truncated": True} if len(key) > 256 else {}),
                    "uri": resource_uri(handle, target, count=4000 if isinstance(item, str) else 25),
                    **({"reason": "pointer_byte_budget"} if len(target.encode()) > POINTER_BYTES else {}),
                }
            )
    elif isinstance(window, list):
        for index, item in enumerate(window, start):
            children.append(
                {
                    "index": index,
                    "uri": resource_uri(
                        handle, pointer_child(pointer, index), count=4000 if isinstance(item, str) else 25
                    ),
                }
            )
    result = {
        "schema_version": "1.0",
        "content_policy": "data_only",
        "view": snapshot.view,
        "evidence_ids": list(dict.fromkeys(proof.evidence_id for proof in snapshot.provenance)),
        "provenance": [proof.model_dump(mode="json") for proof in snapshot.provenance],
        "source_permissions": list(
            dict.fromkeys(
                message
                for proof in snapshot.provenance
                for source in sorted({proof.source, *proof.sources})
                if (
                    message := notice(
                        source,
                        version=proof.source_version if source == proof.source else None,
                        retrieved_at=proof.retrieved_at,
                    )
                )
            )
        ),
        "snapshot_sha256": snapshot.snapshot_sha256,
        "value_sha256": snapshot.value_sha256,
        "value_utf8_bytes": snapshot.value_utf8_bytes,
        "expires_at": datetime.fromtimestamp(snapshot.expires_at, UTC).isoformat(),
        "pointer": pointer,
        "range": {"unit": unit, "start": start, "end_exclusive": end, "total": total},
        "value": bounded,
        "truncated": truncated or end < total,
        "children": children,
        **omissions.metadata(),
        "redacted": snapshot.redacted or omissions.redacted,
        "next_uri": resource_uri(handle, pointer, end, requested_count) if end < total else None,
        "result_sha256": "0" * 64,
    }
    omission_links(result, full_value, handle)
    if (
        isinstance(selected, list)
        and effective > 1
        and len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > PREFERRED_RESOURCE_BYTES
    ):
        # Clients can truncate large resource text in their responses,
        # making valid server JSON unparsable. Prefer smaller readable windows
        # while preserving the existing hard metadata/response byte ceiling.
        return bounded_read(
            snapshot,
            handle,
            pointer,
            selected,
            start,
            max(1, effective // 2),
            full_value=full_value,
            requested_count=requested_count,
        )
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESOURCE_BYTES:
        result["value"] = None
        result["truncated"] = True
        result["value_omitted"] = (
            "Select a child field or item resource; this window exceeds the resource byte budget."
        )
        if isinstance(window, list):
            result["children"] = [
                {
                    "index": index,
                    "uri": resource_uri(
                        handle, pointer_child(pointer, index), count=4000 if isinstance(item, str) else 25
                    ),
                }
                for index, item in enumerate(window, start)
            ]
    while (
        len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESOURCE_BYTES
        and result["omissions"]
    ):
        result["omissions"].pop()
        result["omissions_truncated"] = True
    if (
        len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESOURCE_BYTES
        and end - start > 1
    ):
        return bounded_read(
            snapshot,
            handle,
            pointer,
            selected,
            start,
            max(1, effective // 2),
            full_value=full_value,
            requested_count=requested_count,
        )
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESOURCE_BYTES:
        raise ResearchError(
            "evidence_resource_budget", "Resource metadata exceeds its byte budget; select a narrower field."
        )
    result = EvidenceResponse.model_validate(result).model_dump(mode="json", exclude_unset=True)
    result["result_sha256"] = digest({k: v for k, v in result.items() if k != "result_sha256"})
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > RESOURCE_BYTES:
        raise ResearchError("evidence_resource_budget", "Normalized resource exceeds its byte budget.")
    return result
