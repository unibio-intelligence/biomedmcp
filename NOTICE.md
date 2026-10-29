# Notices

biomedmcp
Copyright 2026 UniBio Intelligence

All code in this repository, including the adapter packages under `servers/python/`, is written by UniBio Intelligence and licensed under [Apache-2.0](LICENSE). Each distribution carries the same license file and `Apache-2.0` metadata.

## Third-party software

Third-party Python packages are installed as separate dependencies, not bundled, and keep their own licenses. Locked versions and license metadata are in [docs/python-dependency-inventory.json](docs/python-dependency-inventory.json).

- `mmcif-pdbx==2.1.0`, used by the PDB adapter, is distributed under CC0-1.0. Its software permission is separate from permissions on structure data.

## Third-party material in tests

These test fixtures are copied from their publishers and keep their own licenses and attribution:

- `tests/fixtures/uniprot-P02751-projected-2026-10-12.json`: UniProt Consortium data under CC-BY-4.0. The adjacent [provenance file](tests/fixtures/uniprot-P02751-projected-2026-10-12-provenance.json) records the projection, observed release and content hash.
- `tests/fixtures/gnomad-schema-2026-10-09.json`: gnomAD browser schema and resolver excerpts, Copyright 2017 Broad Institute and gnomAD Browser contributors, under MIT. The fixture embeds the upstream license text.
- `tests/fixtures/civic-schema-2026-10-09.json`: CIViC generated GraphQL schema from `griffithlab/civic-v2`, under MIT.

## Provider data

The Apache-2.0 license covers code only. It grants no rights over provider data, papers, supplements or studies retrieved at runtime; those keep their own terms. The [source license inventory](docs/source-licenses.md) records each source's terms and which integrations are enabled. EVE score responses carry the publisher's MIT notice.
