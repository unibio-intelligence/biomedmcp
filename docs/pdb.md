# PDB archive retrieval

Discover current parameters with `get_capabilities(source="pdb")`, then use `query_source`. The distinct operations are `search_structures`, `get_structure_info`, `download_structure` and `get_structure_quality`. [Source permissions](source-licenses.md) cover PDB archive records and coordinates; computed models and non-PDB third-party model identifiers are outside this integration.

Search returns experimental archive entries, provider scores, stable record locators, acquired counts and provider totals. `coverage` states the offset, limit and content scope. Execute the supplied `next_actions` to continue; a displayed window is not the complete archive. An HTTP 204 from RCSB means no hits in that page; an empty later page does not mean the total is zero. Past the largest supported offset, results stay partial and no continuation is offered.

Use current RCSB method names such as `X-RAY DIFFRACTION` or `SOLUTION NMR`. Sort fields are `score`, `rcsb_accession_info.initial_release_date` and `rcsb_entry_info.resolution_combined`, with `sort_direction` set to `asc` or `desc`. Resolution filters and reported resolutions use angstroms.

Entry metadata is validated against a dated projection of RCSB's entry schema and must identify the requested entry consistently. The entry's major/minor revision is recorded in provenance; live results may change over time. Quality retrieval retains entry metadata and embedded wwPDB validation summaries. Missing resolutions, entity counts, experimental-data flags and validation summaries remain unknown; missing validation summaries make the result partial. A clean summary does not guarantee the structure has no issues, and it is not a quality ranking.

Coordinate formats are text `mmcif`, legacy `pdb` and `xml`. MMTF is retired. Biological assemblies support mmCIF and legacy PDB; XML assemblies are rejected before acquisition. Legacy PDB assemblies use the documented `.pdb<assembly_id>` route. Text downloads have a four-million-byte inline limit and strict UTF-8 decoding. Larger files return an error, which does not mean the data is absent. Coordinate checks verify entry container identity, required atom identity fields and finite XYZ values. Assembly transforms and structural geometry are not independently verified. Large returned text can require [evidence recovery](evidence-resources.md).

Never put API keys in tool arguments.
