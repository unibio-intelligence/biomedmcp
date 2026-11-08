# Release notes

## Unreleased

- Link to the BioMed MCP overview on the UniBio Intelligence docs site from the
  package metadata and README.

## 0.2.6

- Update the container zlib package to 1.4.

- Require exact BioPortal class identities, valid mapping attribution and consistent
  provider page metadata before returning ontology records.
- Reject malformed ontology inventory rows and mappings unrelated to the requested class.
- Report missing public documentation links as failures on hosts with automated
  access restrictions; observed HTTP 403 refusals and the reviewed FDA
  abuse-detection redirect remain explicitly unverified.
- Report the installed package version during MCP initialization.
- Clarify source evidence limits and installation guidance.

## 0.2.5

- Remove the `build_dossier` workflows `literature_review`,
  `patent_landscape` and `study_summary`; use `search_literature` or
  `search_records` instead.
- Remove the unused `python-Levenshtein`, `thefuzz`, `aiohttp`, `requests` and
  `python-dotenv` dependencies.
- The adapter packages ship only inside the `biomedmcp` wheel, under its
  Apache-2.0 license.
- Reimplement the MyGene, MyChem, MyDisease, Open Targets and BioPortal
  adapters from the public API contracts. Each now exposes only the
  operations the research service and `query_source` use; adapter tool
  descriptions and schemas changed accordingly.

## 0.2.4

- Rename all 13 MCP tools and CLI operations to verb-object names, such as
  `get` to `get_record`, `capabilities` to `get_capabilities`, `batch` to
  `run_batch` and `quota` to `get_quota`. Old names are rejected; update
  client prompts and scripts. Source IDs and `query_source` operations are
  unchanged.
- The adverse-event entity is now `adverse_event`.
- Add tool titles and shorter routing descriptions. `build_dossier` sections
  are listed in its schema, and an unknown section fails validation.
- Follow-up actions returned in results use the new tool names.

## 0.2.3

- Add Python package, container and MCP Registry installation routes.
- Start a local MCP server with `biomedmcp mcp --transport stdio`.
- Use linked LDLR and PCSK9 evidence-notebook examples.
- Limit Python source distributions to build, runtime and license inputs.
- Require patched Authlib and dnspython dependencies.

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
