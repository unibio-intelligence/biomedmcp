"""Local state must remain private, bounded and consistent across workers."""

import asyncio
import hashlib
import sqlite3
import threading

import pytest

from biomedmcp import local_state
from biomedmcp.errors import ResearchError
from biomedmcp.local_state import LocalState, state_directory


async def test_concurrent_initialization_shares_one_persistent_signing_identity(tmp_path):
    states = await asyncio.gather(*(LocalState.open(tmp_path / "state") for _ in range(8)))
    assert len({hashlib.sha256(state.signing_key).hexdigest() for state in states}) == 1
    assert len({state.scope for state in states}) == 1
    with sqlite3.connect(states[0].path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM metadata").fetchone()[0] == 1


async def test_cache_reopens_with_expiry_and_private_json_views(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(local_state.time, "time", lambda: now[0])
    a = await LocalState.open(tmp_path / "state")
    assert await a.put("fixture", {"rows": [{"id": "sentinel"}]}, 2)
    b = await LocalState.open(tmp_path / "state")
    view = await b.get("fixture")
    view["rows"][0]["id"] = "changed"
    assert (await a.get("fixture"))["rows"][0]["id"] == "sentinel"
    now[0] = 102
    assert await b.get("fixture") is None
    with sqlite3.connect(a.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


async def test_cache_bounds_value_count_and_total_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(local_state, "MAX_ENTRIES", 3)
    monkeypatch.setattr(local_state, "MAX_CACHE_BYTES", 50)
    state = await LocalState.open(tmp_path / "state")
    for n in range(8):
        assert await state.put(str(n), {"id": n}, 60)
    with sqlite3.connect(state.path) as connection:
        count, size = connection.execute("SELECT COUNT(*), SUM(size) FROM cache").fetchone()
        assert count == 3 and size <= 50
    assert await state.get("0") is None
    assert await state.get("7") == {"id": 7}
    monkeypatch.setattr(local_state, "MAX_CACHE_BYTES", 25)
    assert await state.put("new", {"id": "new"}, 60)
    with sqlite3.connect(state.path) as connection:
        assert connection.execute("SELECT SUM(size) FROM cache").fetchone()[0] <= 25
    assert not await state.put("oversized", "X" * 1_000_001, 60)
    assert await state.get("oversized") is None


async def test_eviction_reclaims_database_file_growth(tmp_path, monkeypatch):
    monkeypatch.setattr(local_state, "MAX_CACHE_BYTES", 150_000)
    state = await LocalState.open(tmp_path / "state")
    for n in range(16):
        assert await state.put(str(n), "X" * 100_000, 60)
    with sqlite3.connect(state.path) as connection:
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 1
    assert state.path.stat().st_size < 150_000 + 65_536


async def test_corrupt_cached_json_fails_safely(tmp_path):
    state = await LocalState.open(tmp_path / "state")
    await state.put("fixture", {}, 60)
    with sqlite3.connect(state.path) as connection:
        connection.execute("UPDATE cache SET payload='synthetic-secret-broken-json'")
    with pytest.raises(ResearchError) as caught:
        await state.get("fixture")
    assert caught.value.code == "cache_unavailable"
    assert "synthetic-secret" not in str(caught.value)


async def test_permission_changes_after_open_fail_before_cache_access(tmp_path):
    state = await LocalState.open(tmp_path / "state")
    state.path.chmod(0o644)
    with pytest.raises(ResearchError) as caught:
        await state.get("fixture")
    assert caught.value.code == "local_state_unsafe"


async def test_cancelled_filesystem_job_retains_worker_admission(monkeypatch):
    gate, started = threading.Event(), threading.Event()
    captured = []
    submit = local_state._workers.submit

    def record(*args):
        future = submit(*args)
        captured.append(future)
        return future

    monkeypatch.setattr(local_state._workers, "submit", record)
    monkeypatch.setattr(local_state, "_admission", threading.BoundedSemaphore(1))

    def slow():
        started.set()
        gate.wait(2)
        return True

    task = asyncio.create_task(local_state._run(slow))
    await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        with pytest.raises(ResearchError) as caught:
            await local_state._run(lambda: True)
        assert caught.value.code == "cache_unavailable"
    finally:
        gate.set()
        await asyncio.wrap_future(captured[0])
    assert await local_state._run(lambda: True)


async def test_slow_filesystem_work_does_not_block_event_loop(tmp_path, monkeypatch):
    import time

    initialize = LocalState._initialize

    def slow(directory):
        time.sleep(0.08)
        return initialize(directory)

    monkeypatch.setattr(LocalState, "_initialize", slow)
    opening = asyncio.create_task(LocalState.open(tmp_path / "state"))
    await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.05)
    assert not opening.done()
    await opening


def test_local_state_path_precedence_and_absolute_requirement(monkeypatch, tmp_path):
    monkeypatch.setenv("UBI_LOCAL_STATE_DIR", str(tmp_path / "configured"))
    assert state_directory(tmp_path / "explicit") == tmp_path / "explicit"
    assert state_directory() == tmp_path / "configured"
    monkeypatch.delenv("UBI_LOCAL_STATE_DIR")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert state_directory() == tmp_path / "xdg" / "biomedmcp"
    monkeypatch.setenv("UBI_LOCAL_STATE_DIR", "relative-state")
    with pytest.raises(ResearchError):
        state_directory()


async def test_remote_cli_does_not_open_local_state(monkeypatch):
    from biomedmcp import cli

    def forbidden(*args, **kwargs):
        raise AssertionError("Local state must not be opened")

    monkeypatch.setattr(LocalState, "open", forbidden)
    with pytest.raises(ResearchError) as caught:
        await cli.execute("literature_search", {}, url="https://example.org/mcp", state_dir="/unused")
    assert caught.value.code == "invalid_parameters"


async def test_local_state_initialization_is_inside_cli_request_deadline(monkeypatch):
    import time

    from biomedmcp import cli
    from biomedmcp.runtime import operation_deadline

    async def slow(*args):
        await asyncio.sleep(0.1)
        raise AssertionError("Initialization outlived caller deadline")

    monkeypatch.setattr(LocalState, "open", slow)
    deadline = time.monotonic() + 0.02
    token = operation_deadline.set(deadline)
    try:
        with pytest.raises(ResearchError) as caught:
            await cli.execute("literature_search", {"query": "BRAF"})
        assert caught.value.code == "operation_timeout"
        assert operation_deadline.get() == deadline
    finally:
        operation_deadline.reset(token)


async def test_initialization_retries_transient_sqlite_lock_without_changing_signing_identity(
    tmp_path, monkeypatch
):
    state = await LocalState.open(tmp_path / "state")
    owner = sqlite3.connect(state.path, isolation_level=None)
    owner.execute("BEGIN IMMEDIATE")
    original = LocalState._connection
    attempts = []

    def immediate_busy(path):
        connection = original(path)
        connection.execute("PRAGMA busy_timeout=0")
        attempts.append(1)
        return connection

    monkeypatch.setattr(LocalState, "_connection", staticmethod(immediate_busy))
    task = asyncio.create_task(LocalState.open(tmp_path / "state"))
    try:
        for _ in range(50):
            await asyncio.sleep(0.01)
            if task.done() or len(attempts) >= 2:
                break
        assert not task.done() and len(attempts) >= 2
    finally:
        owner.execute("COMMIT")
        owner.close()
    reopened = await task
    assert reopened.signing_key == state.signing_key and reopened.scope == state.scope


async def test_initialization_does_not_retry_noncontention_database_errors(tmp_path, monkeypatch):
    calls = []

    def broken(path):
        calls.append(1)
        raise sqlite3.OperationalError("synthetic-private-database-error")

    monkeypatch.setattr(LocalState, "_connection", staticmethod(broken))
    with pytest.raises(ResearchError) as e:
        await LocalState.open(tmp_path / "state")
    assert e.value.code == "local_state_unavailable" and calls == [1]
    assert "synthetic-private" not in str(e.value)
