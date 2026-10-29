# Connect to biomedmcp

## Hosted service

Add `https://biomedmcp.unibiointelligence.com/mcp` as a **Streamable HTTP** server in your MCP client. Use the same URL when signing in. Anonymous access and limits depend on the operator; clients that support OAuth can sign in when prompted.

The hosted service may run a different version from this source package. Ask your operator for a different endpoint if needed.

## Local setup

Install Python 3.13+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```sh
uv sync --frozen
UBI_PROFILE=local uv run --frozen biomedmcp literature_search '{"query":"PCSK9 familial hypercholesterolemia","filters":{"source":"pubmed"}}'
```

For a client that launches a **stdio** server, use this configuration, replacing the project path:

```json
{
  "mcpServers": {
    "biomedmcp": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/biomedmcp", "--frozen", "biomedmcp-server", "--transport", "stdio"],
      "env": {"UBI_PROFILE": "local"}
    }
  }
}
```

Client configuration formats vary. Set the command, arguments and environment above in the client's MCP settings.

For **local HTTP**, start:

```sh
UBI_PROFILE=local uv run --frozen biomedmcp-server --transport http --host 127.0.0.1 --port 8000
```

Connect to `http://127.0.0.1:8000/mcp`. This server is unauthenticated and listens on your machine only. Network-facing deployments need an operator-managed access configuration; see [contributing](../CONTRIBUTING.md).


## Installed Python package

In a Python 3.13+ virtual environment, run `python -m pip install biomedmcp==0.2.2`.
For a stdio client, the package command is:

```sh
UBI_PROFILE=local biomedmcp mcp --transport stdio
```

The `biomedmcp-server` command accepts the same server options. A client with uvx
can use `uvx --from biomedmcp==0.2.2 biomedmcp mcp --transport stdio`.

## Container

A stdio client can run the versioned container:

```sh
docker run --rm -i --no-healthcheck ghcr.io/unibio-intelligence/biomedmcp:0.2.2 biomedmcp-server --transport stdio
```

For local HTTP, publish port 8000 on loopback only:

```sh
docker run --rm -p 127.0.0.1:8000:8000 ghcr.io/unibio-intelligence/biomedmcp:0.2.2
```

## Use the CLI with a server

```sh
uv run --frozen biomedmcp tools --url https://biomedmcp.unibiointelligence.com/mcp
uv run --frozen biomedmcp literature_search '{"query":"PCSK9 familial hypercholesterolemia"}' --url https://biomedmcp.unibiointelligence.com/mcp
```

Add `--login` to sign in through OAuth. Repeat it for later commands, or provide `UBI_PUBLIC_TOKEN` through secret storage. Keep keys and tokens out of tool arguments and shared command transcripts.

## Troubleshooting

| Problem | Next step |
| --- | --- |
| Local setup or source access fails | Run `uv run --frozen biomedmcp diagnose`, then check [source access](source-access.md). |
| Login required or HTTP 401/403 | Sign in to the selected endpoint; check permissions and remove stale tokens. |
| Quota exceeded or HTTP 429 | Check `quota`, wait for reset or sign in for the operator's higher allowance. |
| Source rate-limited | Wait before retrying and reduce concurrent requests. |
| Expired or invalid cursor | Restart the original query without its cursor. |
| Ambiguous identifier | Use `resolve` and choose the intended species, assembly or record. |
| Partial result | Follow returned continuation links or `next_cursor`; see [result recovery](evidence-resources.md). |
| Public study missing | Install a supported dataset using the [study guide](studies.md). |

Keep query parameters unchanged when continuing a search. Restart a search after changing login identity. Anyone given a public recovery link can read that result until it expires; account results require the original login.

An unavailable source is not an empty scientific result. See [result handling](output-contracts.md) and [examples](examples.md) for details.
