# biomedmcp

biomedmcp is a Model Context Protocol (MCP) server that retrieves records from
biomedical sources, including PubMed, UniProt, ClinicalTrials.gov, ChEMBL, Open
Targets and the Genotype-Tissue Expression (GTEx) project. Each result identifies
its source records, so an AI agent's answers can be checked against them.

<!-- mcp-name: io.github.unibio-intelligence/biomedmcp -->

See the [BioMed MCP overview](https://docs.unibiointelligence.com/ubi-mcp-servers/servers)
for supported tools and access options.

## Start with a research question

The following request can be sent from an MCP client:

> Build an evidence notebook on LDL-receptor biology and cholesterol lowering.
> Start with a human LDLR target dossier, inspect tissue expression, then find
> PCSK9 genetic studies. Separate observations, intervention results and open
> questions. Cite the records you read and identify any unavailable sources.

Connect to `https://biomedmcp.unibiointelligence.com/mcp` using Streamable HTTP
and sign in when prompted. For a local server, install the
Python distribution, run the Docker image below, or build from this checkout; see [connection options](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/connect.md).

## Run the same investigation locally

Use Python 3.13+ in an activated virtual environment:

```sh
python -m pip install biomedmcp==0.2.7
UBI_PROFILE=local biomedmcp build_dossier '{"workflow":"target_dossier","focus":"LDLR","species":9606}'
```

The single Python distribution includes all source adapters. From a source
checkout, `uv sync --frozen` installs the locked environment; prefix commands
with `uv run --frozen` when using it.

The following narrower calls can fill gaps in the notebook:

<!-- public-call-examples:start -->
```sh
UBI_PROFILE=local biomedmcp get_record '{"entity":"gene","id":"LDLR","species":9606,"sections":["expression"]}'
UBI_PROFILE=local biomedmcp search_literature '{"query":"PCSK9","filters":{"source":"pubmed","date_from":"2024-01-01"}}'
UBI_PROFILE=local biomedmcp get_variant_evidence '{"id":"PCSK9 R46L"}'
```
<!-- public-call-examples:end -->

Check each response's source, species and identifiers before combining records;
a partial or unavailable section is a gap, not a negative result. Follow the
continuation and recovery links in a response to retrieve more than the preview.

## Choose the next question

| Research task | Where to start |
| --- | --- |
| Separate target observations from causal claims | [Evidence investigations](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/investigations.md) |
| Inspect an allele without conflating transcript or genome build | [Typed call examples](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/examples.md) |
| Read a paper's accessible text and tables | `get_record` with `entity: "article"` and `sections: ["fulltext"]` |
| Examine registered studies | `search_trials`; inspect each study's submitted record |
| Reproduce a local analysis | [Synthetic study walkthrough](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/studies.md) |

## Connect a local agent

```sh
UBI_PROFILE=local biomedmcp-server --transport http --host 127.0.0.1 --port 8000
```

### Run with Docker

The versioned image is published to GitHub Container Registry for Linux AMD64.
Start a local HTTP server with Docker:

```sh
docker run --rm --platform linux/amd64 -p 127.0.0.1:8000:8000 ghcr.io/unibio-intelligence/biomedmcp:0.2.7
```

For an MCP client that starts its server over stdio:

```sh
docker run --rm -i --platform linux/amd64 --no-healthcheck ghcr.io/unibio-intelligence/biomedmcp:0.2.7 biomedmcp-server --transport stdio
```

Use `http://127.0.0.1:8000/mcp`, or configure a stdio client using the
[connection guide](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/connect.md). The [call reference](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/examples.md) covers
exact JSON arguments; [result handling](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/output-contracts.md) explains partial
results and evidence boundaries.

Some sources need a key or installed dataset. Run `biomedmcp diagnose` and consult
[source access](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/source-access.md). Keep credentials in environment variables
or client secret storage. A failed source does not mean that there is no evidence.

The integration code is licensed under [Apache-2.0](https://github.com/unibio-intelligence/biomedmcp/blob/main/LICENSE). Retrieved data retains its
[source terms](https://github.com/unibio-intelligence/biomedmcp/blob/main/docs/source-licenses.md). See [notices](https://github.com/unibio-intelligence/biomedmcp/blob/main/NOTICE.md),
[release notes](https://github.com/unibio-intelligence/biomedmcp/blob/main/CHANGELOG.md) and [contributing](https://github.com/unibio-intelligence/biomedmcp/blob/main/CONTRIBUTING.md).

## Acknowledgements

We gratefully acknowledge support from Anthropic's AI for Science rare disease
research grants.
