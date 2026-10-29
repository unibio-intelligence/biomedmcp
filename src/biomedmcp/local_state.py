"""Private, bounded local CLI cache and signing state shared across processes."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .errors import ResearchError

MAX_VALUE_BYTES = 1_000_000
MAX_CACHE_BYTES = 32_000_000
MAX_ENTRIES = 256
MAX_EVIDENCE_ENTRIES = 64
APPLICATION_ID = 0x55424950
SCHEMA_VERSION = 1
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ubi-local-state")
_admission = threading.BoundedSemaphore(32)


def state_directory(explicit=None):
    configured = explicit or os.getenv("UBI_LOCAL_STATE_DIR")
    if configured:
        path = Path(configured).expanduser()
    else:
        base = Path(os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state").expanduser()
        path = base / "biomedmcp"
    if not path.is_absolute():
        raise ResearchError("invalid_parameters", "Local state directory must be an absolute path.")
    return path


def _unsafe():
    return ResearchError(
        "local_state_unsafe",
        "Local state ownership or permissions are unsafe; use a private directory (0700) and database (0600).",
    )


def _check_directory(directory):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise _unsafe()
    # Other users must not be able to replace the private directory via a
    # writable ancestor. Sticky system temporary directories protect ownership.
    resolved_parent = directory.parent.resolve()
    for parent in (resolved_parent, *resolved_parent.parents):
        info = parent.stat()
        if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise _unsafe()


def _check_database(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise _unsafe()
    if info.st_size > 64_000_000:
        raise ResearchError("local_state_unavailable", "Local state exceeds its storage budget.")


async def _run(function, *args):
    if not _admission.acquire(blocking=False):
        raise ResearchError("cache_unavailable", "Local state workers are busy; retry later.", retryable=True)
    try:
        future = _workers.submit(function, *args)
    except BaseException:
        _admission.release()
        raise
    future.add_done_callback(lambda _: _admission.release())
    task = asyncio.wrap_future(future)
    # Cancellation retains admission until the actual filesystem work finishes.
    task.add_done_callback(lambda item: None if item.cancelled() else item.exception())
    return await asyncio.shield(task)


class _InitializationBusy(Exception):
    """Transient SQLite contention; never expose database error text."""


class LocalState:
    def __init__(self, directory, signing_key):
        self.directory = directory
        self.path = directory / "state.sqlite3"
        self.signing_key = signing_key
        self.scope = "local-user:" + str(os.getuid())

    @classmethod
    async def open(cls, directory=None):
        path = state_directory(directory)
        try:
            async with asyncio.timeout(5):
                while True:
                    try:
                        key = await _run(cls._initialize, path)
                        break
                    except _InitializationBusy:
                        await asyncio.sleep(0.02)
        except TimeoutError:
            raise ResearchError(
                "local_state_unavailable",
                "Local state initialization timed out; retry later.",
                retryable=True,
            ) from None
        return cls(path, key)

    @staticmethod
    def _connection(path):
        _check_directory(path.parent)
        _check_database(path)
        connection = sqlite3.connect(path, timeout=2, isolation_level=None)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
        except BaseException:
            connection.close()
            raise
        return connection

    @classmethod
    def _initialize(cls, directory):
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            _check_directory(directory)
            path = directory / "state.sqlite3"
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                try:
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
            connection = cls._connection(path)
            try:
                connection.execute("PRAGMA journal_mode=DELETE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version == 0:
                    connection.execute("PRAGMA auto_vacuum=FULL")
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                identifier = connection.execute("PRAGMA application_id").fetchone()[0]
                if (
                    version == 0
                    and identifier == 0
                    and not connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                ):
                    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
                    connection.execute(
                        "CREATE TABLE cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires REAL NOT NULL, accessed REAL NOT NULL, size INTEGER NOT NULL)"
                    )
                    connection.execute("INSERT INTO metadata VALUES (?, ?)", ("signing_key", os.urandom(32)))
                    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                elif version != SCHEMA_VERSION or identifier != APPLICATION_ID:
                    raise ResearchError(
                        "local_state_version",
                        "Local state format is unsupported; choose another private state directory.",
                    )
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key=?", ("signing_key",)
                ).fetchone()
                if not row or not isinstance(row[0], bytes) or len(row[0]) != 32:
                    raise ResearchError(
                        "local_state_unavailable",
                        "Local signing state is invalid; choose another private state directory.",
                    )
                connection.execute("COMMIT")
                return row[0]
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            if (isinstance(exc, sqlite3.OperationalError)
                    and getattr(exc, "sqlite_errorcode", 0) & 0xff in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}):
                raise _InitializationBusy() from None
            raise ResearchError(
                "local_state_unavailable",
                "Local cursor/cache state is unavailable; retry with a writable private state directory.",
                retryable=True,
            ) from None

    def _get(self, key):
        try:
            connection = self._connection(self.path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                now = time.time()
                connection.execute("DELETE FROM cache WHERE expires<=?", (now,))
                row = connection.execute(
                    "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload ELSE NULL END FROM cache WHERE key=?",
                    (MAX_VALUE_BYTES, key),
                ).fetchone()
                if row and row[0] is None:
                    raise ValueError("Oversized cached payload")
                value = json.loads(row[0]) if row else None
                if row:
                    connection.execute("UPDATE cache SET accessed=? WHERE key=?", (now, key))
                connection.execute("COMMIT")
                return value
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError):
            raise ResearchError(
                "cache_unavailable", "Local result cache is unavailable; retry later.", retryable=True
            ) from None

    async def get(self, key):
        return await _run(self._get, key)

    def _put(self, key, encoded, ttl):
        try:
            connection = self._connection(self.path)
            try:
                connection.execute("BEGIN IMMEDIATE")
                now = time.time()
                connection.execute("DELETE FROM cache WHERE expires<=?", (now,))
                connection.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)",
                    (key, encoded, now + ttl, now, len(encoded.encode())),
                )
                if key.startswith("{evidence}:"):
                    connection.execute(
                        "DELETE FROM cache WHERE key IN (SELECT key FROM cache WHERE key LIKE '{evidence}:%' ORDER BY accessed DESC, key DESC LIMIT -1 OFFSET ?)",
                        (MAX_EVIDENCE_ENTRIES,),
                    )
                entries, size = connection.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM cache"
                ).fetchone()
                while entries > MAX_ENTRIES or size > MAX_CACHE_BYTES:
                    oldest, amount = connection.execute(
                        "SELECT key, size FROM cache ORDER BY accessed, key LIMIT 1"
                    ).fetchone()
                    connection.execute("DELETE FROM cache WHERE key=?", (oldest,))
                    entries, size = entries - 1, size - amount
                stored = connection.execute("SELECT 1 FROM cache WHERE key=?", (key,)).fetchone() is not None
                connection.execute("COMMIT")
                return stored
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            raise ResearchError(
                "cache_unavailable", "Local result cache is unavailable; retry later.", retryable=True
            ) from None

    async def put(self, key, value, ttl):
        encoded = json.dumps(value, allow_nan=False, default=str)
        if len(encoded.encode()) > MAX_VALUE_BYTES:
            return False
        return await _run(self._put, key, encoded, ttl)
