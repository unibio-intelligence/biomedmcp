"""Run the actual CLI parser/application in separate offline Python processes."""

import json
import os
import sqlite3
import stat
import subprocess
import sys

import pytest
from synthetic_permissions import BOOTSTRAP as PERMISSION_BOOTSTRAP

BOOTSTRAP = """
import json, os
from biomedmcp.native.http import ProviderHTTP

async def get(self, url, **kwargs):
    params = kwargs.get("params", {})
    offset, size = int(params.get("cursorMark", "0").replace("*", "0")), params.get("pageSize", 2)
    with open(os.environ["FIXTURE_REQUEST_LOG"], "a") as stream:
        stream.write(json.dumps({"offset": offset, "query": params.get("query")}) + "\\n")
    rows = [{"id": str(n), "source": "MED", "title": "BRAF " + str(n)}
            for n in range(offset, min(offset + size, 5))]
    result = {"resultList": {"result": rows}, "hitCount": 5}
    if offset + size < 5:
        result["nextCursorMark"] = str(offset + size)
    return result

ProviderHTTP.get = get
from biomedmcp.cli import main
main()
"""


@pytest.fixture
def local_cli(tmp_path):
    script = tmp_path / "offline_cli.py"
    script.write_text(PERMISSION_BOOTSTRAP + BOOTSTRAP)
    directory = tmp_path / "state"
    log = tmp_path / "requests.jsonl"

    def run(cursor=None, *, query="BRAF", extra=None):
        arguments = {"query": query, "limit": 2, "filters": {"source": "europepmc"}}
        if cursor:
            arguments["cursor"] = cursor
        env = dict(
            os.environ, UBI_PROFILE="local", UBI_LOCAL_STATE_DIR=str(directory), FIXTURE_REQUEST_LOG=str(log)
        )
        env.pop("UBI_CURSOR_KEY", None)
        return subprocess.run(
            [sys.executable, str(script), "literature_search", json.dumps(arguments), *(extra or [])],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    return directory, log, run


def result(process):
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def error(process):
    assert process.returncode == 2 and not process.stdout
    return json.loads(process.stderr.strip().splitlines()[-1])["error"]


def test_separate_cli_processes_retrieve_consecutive_pages(local_cli):
    _, log, run = local_cli
    first = result(run())
    second = result(run(first["next_cursor"]))
    third = result(run(second["next_cursor"]))
    assert {r["pmid"] for r in first["records"]} == {"0", "1"}
    assert {r["pmid"] for r in second["records"]} == {"2", "3"}
    assert {r["pmid"] for r in third["records"]} == {"4"}
    assert third["next_cursor"] is None
    assert [json.loads(line)["offset"] for line in log.read_text().splitlines()] == [0, 2, 4]


@pytest.mark.parametrize("change", ["tamper", "query"])
def test_separate_process_rejects_tampered_or_query_mismatched_cursor(local_cli, change):
    _, log, run = local_cli
    cursor = result(run())["next_cursor"]
    if change == "tamper":
        cursor = ("a" if cursor[0] != "a" else "b") + cursor[1:]
    failure = run(cursor, query="TP53" if change == "query" else "BRAF")
    assert error(failure)["code"] == "invalid_cursor"
    assert len(log.read_text().splitlines()) == 1


def test_expired_page_state_returns_structured_restart_error(local_cli):
    directory, log, run = local_cli
    first = result(run())
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute("UPDATE cache SET expires=0 WHERE key LIKE 'page:%'")
    failure = run(first["next_cursor"])
    assert error(failure)["code"] == "expired_cursor"
    assert len(log.read_text().splitlines()) == 1


def test_reset_local_state_invalidates_old_cursors_without_silent_resume(local_cli):
    directory, log, run = local_cli
    cursor = result(run())["next_cursor"]
    (directory / "state.sqlite3").unlink()
    failure = run(cursor)
    assert error(failure)["code"] == "invalid_cursor"
    assert len(log.read_text().splitlines()) == 1


def test_cursor_signing_expiry_is_enforced_by_actual_cli(local_cli):
    directory, log, run = local_cli
    first = result(run())
    import base64
    import hashlib
    import hmac

    with sqlite3.connect(directory / "state.sqlite3") as connection:
        key = connection.execute("SELECT value FROM metadata WHERE key='signing_key'").fetchone()[0]
    raw = base64.urlsafe_b64decode(first["next_cursor"] + "=" * (-len(first["next_cursor"]) % 4))
    payload = json.loads(raw[32:])
    payload["e"] = 0
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    cursor = (
        base64.urlsafe_b64encode(hmac.new(key, encoded, hashlib.sha256).digest() + encoded)
        .decode()
        .rstrip("=")
    )
    assert error(run(cursor))["code"] == "invalid_cursor"
    assert len(log.read_text().splitlines()) == 1


def test_explicit_state_directory_flag_overrides_environment(local_cli, tmp_path):
    configured, _, run = local_cli
    chosen = tmp_path / "chosen"
    first = result(run(extra=["--state-dir", str(chosen)]))
    second = result(run(first["next_cursor"], extra=["--state-dir", str(chosen)]))
    assert {r["pmid"] for r in second["records"]} == {"2", "3"}
    assert chosen.is_dir() and not configured.exists()


def test_signing_material_and_database_are_private_and_not_printed(local_cli):
    directory, _, run = local_cli
    process = run()
    result(process)
    path = directory / "state.sqlite3"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as connection:
        key = connection.execute("SELECT value FROM metadata WHERE key='signing_key'").fetchone()[0]
    assert len(key) == 32
    assert key.hex() not in process.stdout + process.stderr


@pytest.mark.parametrize(
    "unsafe", ["directory", "database", "symlink", "database_symlink", "hardlink", "parent"]
)
def test_unsafe_local_state_fails_before_provider_io(local_cli, tmp_path, unsafe):
    directory, log, run = local_cli
    if unsafe == "directory":
        directory.mkdir(mode=0o755)
    elif unsafe == "parent":
        directory.mkdir(mode=0o700)
        directory.parent.chmod(0o777)
    elif unsafe == "symlink":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        directory.symlink_to(target, target_is_directory=True)
    elif unsafe == "database_symlink":
        directory.mkdir(mode=0o700)
        target = tmp_path / "database-target"
        target.touch(mode=0o600)
        (directory / "state.sqlite3").symlink_to(target)
    else:
        directory.mkdir(mode=0o700)
        path = directory / "state.sqlite3"
        path.touch(mode=0o600)
        if unsafe == "database":
            path.chmod(0o644)
        else:
            os.link(path, directory / "another-link")
    try:
        assert error(run())["code"] == "local_state_unsafe"
        assert not log.exists()
    finally:
        if unsafe == "parent":
            directory.parent.chmod(0o700)


def test_corrupt_local_database_fails_safely_without_path_disclosure(local_cli):
    directory, log, run = local_cli
    directory.mkdir(mode=0o700)
    path = directory / "state.sqlite3"
    path.touch(mode=0o600)
    path.write_bytes(b"synthetic-credential-sentinel-not-a-sqlite-database")
    failure = run()
    assert error(failure)["code"] == "local_state_unavailable"
    assert not log.exists()
    assert "sentinel" not in failure.stderr and str(directory) not in failure.stderr


def test_unknown_state_schema_is_preserved_and_rejected(local_cli):
    directory, log, run = local_cli
    result(run())
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        connection.execute("PRAGMA user_version=99")
    assert error(run())["code"] == "local_state_version"
    assert len(log.read_text().splitlines()) == 1
    with sqlite3.connect(directory / "state.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_repeated_cli_request_uses_persisted_provider_cache(local_cli):
    _, log, run = local_cli
    first = result(run())
    second = result(run())
    assert first["records"] == second["records"]
    assert len(log.read_text().splitlines()) == 1
    assert second["provenance"][0]["cached"]


def test_relative_state_path_is_rejected_by_actual_cli(local_cli):
    _, log, run = local_cli
    assert error(run(extra=["--state-dir", "relative-state"]))["code"] == "invalid_parameters"
    assert not log.exists()
