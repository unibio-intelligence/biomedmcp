# biomedmcp

Build a cited evidence notebook for a biomedical research question. BioMedMCP
retrieves source records, keeps their identities and limitations visible, and
lets an agent collect a bounded dossier before following individual leads.

<!-- mcp-name: io.github.unibio-intelligence/biomedmcp -->

## Start with a research question

Try this with your MCP client:

> Build an evidence notebook on LDL-receptor biology and cholesterol lowering.
> Start with a human LDLR target dossier, inspect tissue expression, then find
> PCSK9 genetic studies. Separate observations, intervention results and open
> questions. Cite the records you read and identify any unavailable sources.

Connect to `https://biomedmcp.unibiointelligence.com/mcp` using Streamable HTTP.
The hosted service controls sign-in and access. For a local server, install the
Python distribution or build from this checkout; see [connection options](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/connect.md).

## Run the same investigation locally

Use Python 3.13+ in an activated virtual environment:

```sh
python -m pip install biomedmcp==0.2.2
UBI_PROFILE=local biomedmcp research '{"workflow":"target_dossier","focus":"LDLR","species":9606}'
```

The single Python distribution includes all source adapters. From a source
checkout, `uv sync --frozen` installs the locked environment; prefix commands
with `uv run --frozen` when using it.

These focused calls can fill gaps in the notebook:

<!-- public-call-examples:start -->
```sh
UBI_PROFILE=local biomedmcp get '{"entity":"gene","id":"LDLR","species":9606,"sections":["expression"]}'
UBI_PROFILE=local biomedmcp literature_search '{"query":"PCSK9","filters":{"source":"pubmed","date_from":"2024-01-01"}}'
UBI_PROFILE=local biomedmcp variant_evidence '{"id":"PCSK9 R46L"}'
```
<!-- public-call-examples:end -->

Review each response's source, species, identifiers and outcome before combining
records. A partial or unavailable section remains a gap in the notebook. Follow
returned continuation and recovery actions to inspect material beyond the preview.

## Choose the next question

| Research task | Where to start |
| --- | --- |
| Separate target observations from causal claims | [Evidence investigations](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/investigations.md) |
| Inspect an allele without conflating transcript or genome build | [Typed call examples](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/examples.md) |
| Read a paper's accessible text and tables | `get` with `entity: "article"` and `sections: ["fulltext"]` |
| Examine registered studies | `trial_search`; inspect each study's submitted record |
| Reproduce a local analysis | [Synthetic study walkthrough](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/studies.md) |

## Connect a local agent

```sh
UBI_PROFILE=local biomedmcp-server --transport http --host 127.0.0.1 --port 8000
```

Use `http://127.0.0.1:8000/mcp`, or configure a stdio client using the
[connection guide](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/connect.md). The [call reference](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/examples.md) covers
exact JSON arguments; [result handling](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/output-contracts.md) explains partial
results and evidence boundaries.

Some sources need a key or installed dataset. Run `biomedmcp diagnose` and consult
[source access](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/source-access.md). Keep credentials in environment variables
or client secret storage. Source failures do not establish absence of evidence.

The integration code uses [Apache-2.0](https://github.com/unibio-intelligence/biomedmcp/blob/main/LICENSE). Retrieved data retains its
[source terms](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/source-licenses.md). See [notices](https://github.com/unibio-intelligence/biomedmcp/blob/main/NOTICE.md),
[release notes](https://github.com/unibio-intelligence/biomedmcp/blob/main/CHANGELOG.md) and [contributing](https://github.com/unibio-intelligence/biomedmcp/blob/main/CONTRIBUTING.md).
