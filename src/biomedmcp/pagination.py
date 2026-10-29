"""Provider windows retain raw coverage independently of client-side filtering."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ResearchError
from .evidence import records_from

MAX_PROVIDER_PAGE = 100000
PAGE_LIMIT_WARNING = (
    "Further source records exceed the supported page range; acquired evidence is retained as partial."
)


def page_continuation(next_page):
    """Keep source exhaustion distinct from an unavailable service action."""
    if next_page is None:
        return None, {}
    if type(next_page) is not int or next_page < 0:
        raise ResearchError("invalid_source_response", "Provider continuation page is invalid.")
    if next_page > MAX_PROVIDER_PAGE:
        return None, {
            "continuation_status": "unavailable",
            "continuation_reason": "supported_page_range_exceeded",
            "maximum_page": MAX_PROVIDER_PAGE,
            "next_provider_page": next_page,
        }
    return next_page, {}


class ProviderPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    raw_count: int = Field(ge=0, le=1000)
    next_offset: int | None = Field(default=None, ge=0)
    continuation: str | None = Field(default=None, min_length=1, max_length=8192)
    exhausted: bool
    total: int | None = Field(default=None, ge=0)
    exhaustion_basis: Literal["provider", "total", "short_window", "bounded_snapshot"] = "provider"
    filtered_count: int = Field(default=0, ge=0, le=1000)
    filtering: dict[str, int] = Field(default_factory=dict)
    sort_scope: Literal["provider", "window", "bounded_snapshot"] = "provider"

    @model_validator(mode="after")
    def consistent(self):
        if self.filtered_count > self.raw_count:
            raise ValueError("Filtered count exceeds acquired count")
        if self.exhausted and (self.continuation is not None or self.next_offset is not None):
            raise ValueError("Exhausted page has continuation")
        if not self.exhausted and self.continuation is None and self.next_offset is None:
            raise ValueError("Non-exhausted page requires continuation")
        if any(type(n) is not int or not 0 <= n <= self.raw_count for n in self.filtering.values()):
            raise ValueError("Invalid filtering counts")
        return self

    def public_metadata(self):
        value = self.model_dump(exclude={"continuation", "next_offset", "exhausted"})
        value["accessible_window_exhausted"] = self.exhausted
        return value


def page_payload(rows, **metadata):
    """Serialize metadata for the cache; opaque tokens stay out of public evidence."""
    try:
        page = ProviderPage(**metadata)
        if len(rows) > page.raw_count or page.filtered_count > page.raw_count:
            raise ValueError("counts")
        return {"records": rows, "_provider_page": page.model_dump()}
    except (ValidationError, ValueError):
        raise ResearchError("invalid_source_response", "Provider pagination metadata is invalid.") from None


def numeric_total(value):
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if value is not None and (type(value) is not int or value < 0):
        raise ResearchError("invalid_source_response", "Provider total count is invalid.")
    return value


def page_from(payload, *, offset, limit, bounded=False):
    if isinstance(payload, dict) and "_provider_page" in payload:
        try:
            page = ProviderPage.model_validate(payload["_provider_page"])
            if len(records_from(payload)) > page.raw_count:
                raise ValueError("Rows exceed raw acquisition count")
            return page
        except (ValidationError, ValueError):
            raise ResearchError(
                "invalid_source_response", "Provider pagination metadata is invalid."
            ) from None
    rows = records_from(payload)
    total = None
    if isinstance(payload, dict):
        for key in ("total", "totalCount", "hitCount", "count"):
            if key in payload:
                total = numeric_total(payload[key])
                break
    exhausted = bounded or (offset + len(rows) >= total if total is not None else len(rows) < limit)
    return ProviderPage(
        raw_count=len(rows),
        total=total,
        exhausted=exhausted,
        next_offset=None if exhausted else offset + len(rows),
        exhaustion_basis="bounded_snapshot" if bounded else "total" if total is not None else "short_window",
        sort_scope="bounded_snapshot" if bounded else "provider",
    )
