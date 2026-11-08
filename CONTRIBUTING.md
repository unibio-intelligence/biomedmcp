# Contributing

We accept bug reports, fixes, documentation, new data sources and improved tool descriptions.

## How to contribute

1. **Open an issue first.** For a bug, give your biomedmcp version, the tool or command, a minimal example, and the expected and observed behavior. To propose a data source or feature, describe what it answers, the provider and its terms of use. Except for typo fixes, wait for a maintainer to agree on the approach before you open a pull request.
2. **Open a focused pull request.** Make one change per pull request, link its issue (`Closes #123`) and run the tests below first.
3. **Review and release.** Accepted changes are reviewed, tested and credited in a later public release. The hosted service and public releases may update at different times.

Contributions are licensed under the repository's [Apache-2.0 license](LICENSE). Keep credentials, patient data and sensitive research out of issues. Report security issues privately to [helpdesk@unibiointelligence.com](mailto:helpdesk@unibiointelligence.com), not in public issues.

## Development

Install Python 3.13+ and uv, then run:

```sh
uv sync --frozen
uv run --frozen pytest tests -q
./scripts/test-local.sh
```

Docker is required for the last command, which checks the container build and Redis integration. Use synthetic fixtures for repeatable tests; keep live provider checks separate.

For further detail, see [CI checks](docs/development/ci-governance.md), [live checks](docs/operations.md#qualification-and-live-observations), [runtime observations](docs/development/runtime-observations.md), [request limits](docs/operations.md#http-request-budgets), [retries](docs/operations.md#public-provider-retry-and-infrastructure-policy) and [release recovery](docs/development/release-recovery.md).

State for the local command-line interface (CLI) is stored under `$XDG_STATE_HOME/biomedmcp` (default `~/.local/state/biomedmcp`). Choose another private directory with `UBI_LOCAL_STATE_DIR` or `--state-dir`; use directory mode `0700` and file mode `0600`. Restart a query after cursor expiry or a state reset.

HTTP clients use localhost by default. For proxies or browser clients, set explicit `UBI_HTTP_ALLOWED_HOSTS` and `UBI_HTTP_ALLOWED_ORIGINS` values. Wildcards are not accepted, forwarded headers are not trusted, and these settings do not configure CORS. Provider keys belong in environment variables or secret storage.
