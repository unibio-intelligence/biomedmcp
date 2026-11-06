"""Aggregate admission, leases, eviction and concurrent initialization outcomes."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from biomedmcp.errors import ResearchError
from biomedmcp.native.study_storage import MIB, PARSER_RESERVATION, StudyCache, payload_bytes


def test_active_reservations_share_one_aggregate_budget():
    cache = StudyCache(budget=100)
    with cache.reserve(60):
        with pytest.raises(ResearchError) as caught, cache.reserve(41):
            pytest.fail("Aggregate reservation was admitted past its limit")
        assert caught.value.code == "study_budget_exceeded"
        with cache.reserve(40):
            assert cache.snapshot()["accounted_bytes"] == 100
    assert cache.snapshot()["accounted_bytes"] == 0


def test_incremental_builder_cannot_grow_past_aggregate_limit():
    cache = StudyCache(budget=PARSER_RESERVATION + 10)

    def build(ticket):
        ticket.grow(11)
        pytest.fail("Builder was admitted past its limit")

    with pytest.raises(ResearchError), cache.lease("oversize", build):
        pass
    assert cache.snapshot()["accounted_bytes"] == cache.snapshot()["building"] == 0


def test_cache_pressure_evicts_idle_payload_but_preserves_leased_data():
    cache = StudyCache(budget=64 * MIB)
    value = "x" * 1000
    with cache.lease("old", lambda ticket: value):
        with pytest.raises(ResearchError), cache.reserve(cache.budget):
            pass
        assert cache.snapshot()["pinned_entries"] == 1
    with cache.reserve(cache.budget):
        assert cache.snapshot()["retained_bytes"] == 0
    rebuilt = []
    with cache.lease("old", lambda ticket: rebuilt.append(True) or value) as result:
        assert result == value
    assert rebuilt == [True]


def test_concurrent_initialization_is_shared_without_double_allocation():
    cache = StudyCache(budget=64 * MIB)
    entered, release = threading.Event(), threading.Event()
    builds = []

    def build(ticket):
        builds.append(True)
        entered.set()
        assert release.wait(3)
        return ("shared",)

    def read():
        with cache.lease("same", build) as value:
            return value

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(read)
        try:
            assert entered.wait(1)
            second = pool.submit(read)
        finally:
            release.set()
        assert first.result() == second.result() == ("shared",)
    assert builds == [True]
    assert cache.snapshot()["accounted_bytes"] == payload_bytes(("shared",))


def test_entry_limit_never_evicts_a_leased_entry():
    cache = StudyCache(budget=64 * MIB, max_entries=1)
    with (
        cache.lease("first", lambda ticket: "first"),
        pytest.raises(ResearchError),
        cache.lease("second", lambda ticket: "second"),
    ):
        pass
    with cache.lease("second", lambda ticket: "second") as value:
        assert value == "second"
    assert cache.snapshot()["entries"] == 1


def test_exception_after_pin_releases_pin_without_discarding_valid_payload():
    cache = StudyCache(budget=64 * MIB)
    with pytest.raises(ValueError), cache.lease("valid", lambda ticket: "valid"):
        raise ValueError("analysis failure")
    assert cache.snapshot()["pinned_entries"] == 0
    with cache.lease("valid", lambda ticket: pytest.fail("Valid payload was lost")) as value:
        assert value == "valid"


def test_failed_builder_never_publishes_partial_data_and_can_be_retried():
    cache = StudyCache(budget=64 * MIB)

    def failure(ticket):
        ticket.grow(1000)
        raise ValueError("failed input")

    with pytest.raises(ValueError), cache.lease("retry", failure):
        pass
    assert cache.snapshot()["accounted_bytes"] == 0
    with cache.lease("retry", lambda ticket: "complete") as value:
        assert value == "complete"
