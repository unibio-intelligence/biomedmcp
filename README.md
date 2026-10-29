# biomedmcp

Search biomedical literature, read accessible full-text papers, inspect variant evidence and explore genes, drugs and clinical trials through one MCP interface. The same tools are available through Python and a JSON CLI.

## Get started

**Connect an MCP client:** use `https://biomedmcp.unibiointelligence.com/mcp` as a Streamable HTTP endpoint. Availability and sign-in depend on the hosted service. See the [connection guide](docs/connect.md) for local setup and troubleshooting.

**Run locally:** install Python 3.13+ and [uv](https://docs.astral.sh/uv/), then run from this repository:

```sh
uv sync --frozen
UBI_PROFILE=local uv run --frozen biomedmcp literature_search '{"query":"BRAF V600E melanoma","filters":{"source":"pubmed"}}'
```

The release also includes a single Python wheel with all adapters bundled. Install it in a Python 3.13+ environment with `uv pip install ./biomedmcp-0.2.1-py3-none-any.whl`; third-party dependencies are resolved automatically.

To start a local MCP server:

```sh
UBI_PROFILE=local uv run --frozen biomedmcp-server --transport http --host 127.0.0.1 --port 8000
```

Connect your client to `http://127.0.0.1:8000/mcp`.

## What you can do

| Goal | Tool |
| --- | --- |
| Find papers, with optional source, date and ranking controls | `literature_search` |
| Read accessible article text and tables in pages of up to 100 lines | `get` with `entity: "article"` and `sections: ["fulltext"]` |
| Look up ClinVar or CIViC assertions for a variant | `variant_evidence` |
| Search clinical trials | `trial_search` |
| Explore genes, proteins, drugs, diseases and pathways | `search`, `get`, `resolve`, `relate` |
| Build a focused research dossier | `research` |
| Analyze an installed public study | `study_analysis` |

Try asking your agent to “find recent BRAF V600E melanoma papers,” “compare ClinVar evidence for BRAF V600E and V600K,” or “retrieve the tables from this PMC article.” Use the [call examples](docs/examples.md) for exact arguments and [investigations](docs/investigations.md) for longer workflows.

<details>
<summary>CLI examples</summary>

<!-- public-call-examples:start -->
```sh
UBI_PROFILE=local uv run biomedmcp get '{"entity":"gene","id":"ERBB2","species":9606,"sections":["expression"]}'
UBI_PROFILE=local uv run biomedmcp literature_search '{"query":"BRAF","filters":{"source":"pubmed","date_from":"2024-01-01"}}'
UBI_PROFILE=local uv run biomedmcp variant_evidence '{"id":"BRAF V600E"}'
```
<!-- public-call-examples:end -->

</details>

## Available data and results

Some sources require a key or an installed dataset. Check [source access](docs/source-access.md), or run `uv run --frozen biomedmcp diagnose` when setup is uncertain. Keep keys in environment variables or client secret storage.

Follow `next_cursor` and returned continuation links to read more. An unavailable source does not mean no evidence exists; results may be partial. Full-text access depends on the article. See [result handling](docs/output-contracts.md) for details.

Integration code is licensed under [Apache-2.0](LICENSE). Provider data has its own [terms](docs/source-licenses.md). See [release notes](CHANGELOG.md) and [contributing](CONTRIBUTING.md).
