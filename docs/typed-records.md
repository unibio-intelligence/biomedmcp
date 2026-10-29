# Selected scientific record contracts

Read `biomedmcp://schemas/records/{family}` through MCP `resources/read` to obtain a self-contained JSON Schema for a selected record family. These optional resources use the server's normal resource authentication and acquire no provider data. They complement the envelope schemas advertised by the 13 scientific and utility tools.

| Family | Selected records | Scientific boundary |
| --- | --- | --- |
| `literature` | Normalized literature records | Qualified identifiers, source assertions and bibliographic missingness remain distinct. |
| `trial` | Selected trial registry metadata | Registry identity, enrollment basis, participant units and source phase/status codes remain explicit. |
| `variant` | gnomAD population records and ClinGen expert assertion records | Population measurements and categorical expert interpretations have different record types and units. |
| `expression` | Selected GTEx median and tissue expression records | Gene identity, tissue, units, source release and measurement missingness are retained. |
| `study` | Installed-study mutation profiles and assay measurements | Assayed denominators, measurement availability, verified inputs and calculation methods remain explicit. |

Schema availability does not enable a held integration. Inspect source permissions in `capabilities`; API keys cannot change the release policy. Schemas describe selected normalized records, not every provider response or every nested dossier. Source failures and unavailable measurements do not establish scientific absence.

Trial discovery requests ClinicalTrials.gov relevance ordering and ranks a bounded candidate window of at least 20 records, or the requested `limit` when larger. Delivery still honors `limit`; undelivered acquired records remain in the scoped continuation. Direct title and condition mentions, regular plural words and an exact submitted condition improve ordering. Subtype matches remain eligible. The result discloses the candidate-window size and acquired-window ranking scope; scores are lexical discovery signals, not clinical eligibility or evidence of a biological relationship.

ClinGen ERepo summary records preserve each panel's classification independently. The service checks the exact `caId`, panel (`ep`), document (`uuid`), document version (`docVersion`) and optional boolean `retracted` against the preserved provider row. The record hash binds that row, and input locators identify the source page and fields. A conflicting interpretation is neither discarded nor converted into a synthesized classification.

The selected summary contract does not qualify species, assembly, transcript or condition; those normalized fields remain null with explicit context missingness. The observed document version is not a repository release or a replay pin. The response retains page-one, 25-row coverage with `exhaustive: false`. Inspect coverage before drawing conclusions. Original provider fields remain evidence data and are not executable instructions or clinical recommendations.

The source53 implementation and its new regressions await the consolidated qualification batch. Historical qualification receipts describe their recorded source revisions.
