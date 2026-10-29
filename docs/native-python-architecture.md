# Public scientific architecture

The independently buildable public distribution serves biomedical evidence through 13 MCP tools and a JSON CLI. The canonical contract is `src/biomedmcp/public_catalog.py`; MCP and CLI use the same dispatch/preflight layer. Public source access, identity qualification, provider acquisition, bounded study analysis and evidence composition belong here. Private accounts, hosted authentication/accounting, projects, imports, jobs and modeling are injected by a separate hosting/platform integration.

Named tasks own literature discovery, trial discovery, variant evidence and study analysis. Ordinary `search`/`get` cover other records; `resolve`/`relate` preserve qualified identities; `research` composes declared dossiers; `query_source` exposes distinct advanced operations. Provider servers remain implementation details rather than mounted public tools. [Operation ownership](operation-ownership.json) and [executable examples](examples.md) document the current routes.

Scientific results retain species/assembly, source/version, attribution, per-section status, missingness and measured denominators. Provider failure is distinct from a healthy empty result. The [output contract](output-contracts.md) describes versioned schemas and machine-readable errors. Results from live data remain time-dependent when a provider cannot pin releases.

[STRING functional networks](string-network.md) retain protein-level edge identity, species and reported confidence channels. Their expanded neighborhoods can contain neighbor-to-neighbor edges; functional association does not establish physical binding or causality. Malformed collections fail before scientific evidence is issued, and omitted valid edges remain recoverable.

[ClinGen evidence](clingen-evidence.md) distinguishes HGNC identity matches, canonical nucleotide/protein alleles, expert-panel assertions, specification references and linked entities. Source envelopes and nested records are validated before caching; unavailable or malformed responses cannot become measured negative evidence.

[Open Targets evidence](opentargets-evidence.md) validates queried GraphQL types and exact entity identities, preserves nullable values and bounds association counts/scores. Gene composition keeps annotation semantics and provider-page coverage; malformed results cannot enter the healthy cache.

Connection pooling, bounded caching, request coalescing, provider pacing and scoped signed cursors control acquisition. Redis qualification exercises independent runtime objects and persisted state under synthetic provider conditions. Public studies require exact member inventories and checksums; verification and analysis run off the event loop in bounded workers. Current resource settings and their qualification boundaries are in the [README](../README.md).

The [readiness matrix](capability-readiness.json) and [qualification interpretation](live-qualification.md) identify limitations. Offline tests establish the specified fixtures and routes; configured sources and imported adapters do not prove live health, comprehensive scientific accuracy or model task success. Private deployment details are outside this distribution.
