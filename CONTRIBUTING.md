# Contributing

Report an issue in this repository with your biomedmcp version, a minimal example, and expected versus observed behavior. Keep credentials, patient data and sensitive research out of reports.

Patches are welcome. Accepted changes are reviewed, tested and included in a selected public release with author credit. Hosted updates and public releases may arrive at different times; an issue is fixed publicly when its released version is available.

## Development

Install Python 3.13+ and uv, then run:

```sh
uv sync --frozen
uv run --frozen pytest tests -q
./scripts/test-local.sh
```

Docker is required for the last command, which checks the container build and Redis integration. Use synthetic fixtures for repeatable tests; keep live provider checks separate.

For deeper reference, see [CI checks](docs/ci-governance.md), [live checks](docs/live-qualification.md), [runtime settings](docs/runtime-observations.md), [request limits](docs/http-budgets.md), [retries](docs/retries.md) and [release recovery](docs/release-recovery.md).

Local CLI state is stored under `$XDG_STATE_HOME/biomedmcp` (default `~/.local/state/biomedmcp`). Choose another private directory with `UBI_LOCAL_STATE_DIR` or `--state-dir`; use directory mode `0700` and file mode `0600`. Restart a query after cursor expiry or a state reset.

HTTP clients use localhost by default. Operators can set explicit `UBI_HTTP_ALLOWED_HOSTS` and `UBI_HTTP_ALLOWED_ORIGINS` values for proxies or browser clients. Wildcards are not accepted; forwarded headers do not grant trust, and these settings do not configure CORS. Provider keys belong in environment variables or secret storage.
