# Release notes

## 0.2.2

- Add Python package, container and MCP Registry installation routes.
- Start a local MCP server with `biomedmcp mcp --transport stdio`.
- Use linked LDLR and PCSK9 evidence-notebook examples.
- Limit Python source distributions to build, runtime and license inputs.

## 0.2.1

- Install one wheel with all biomedical adapters included.

- Read accessible PMC full text more reliably, including tables, captions and footnotes. Requests can fall back to NCBI PMC when Europe PMC is unavailable.
- Retrieve ClinVar assertions directly from NCBI, with separate germline, clinical-impact and oncogenicity results.
- Search OpenAlex authors and their works, and retrieve article citations and references.
- Read manufacturer-submitted FDA drug-label text and official label links.
- Retrieve AlphaMissense and optional EVE variant scores. Predictor coverage and dataset requirements vary by source.
- Continue public searches and recover public results across requests without signing in, where anonymous access is enabled.
- Improve gene, disease, pathway, pharmacogenomics and Orange Book lookups, local startup reliability and dependency security.
- Remove Semantic Scholar and its TLDR routes. Use PubMed, Europe PMC or OpenAlex for literature discovery.

## 0.2.0

- Introduce `biomedmcp`: biomedical retrieval, literature and trial search, variant evidence and public-study analysis through MCP, Python and the JSON CLI.
- Add local and hosted connection options, search continuation and recoverable results.
