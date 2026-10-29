# Orange Book data contracts

## Orange Book download availability

The FDA media ZIP is the primary Orange Book route. If that route returns HTTP 404, the adapter uses the [official openFDA Orange Book JSON export](https://open.fda.gov/apis/drug/orangebook/download/). Other errors, including access denial and rate limits, remain errors. The JSON route is an independent FDA distribution and exposes its URL, format, last-updated date, product count and downloaded ZIP hash in `source_release`.

The fallback accepts only the fixed one-part export, validates its complete record count and unique application-type/application/product identities, and bounds ZIP expansion. Products, patents and exclusivity records retain their FDA relationships and original JSON fields. Missing strengths remain blank, with their absence preserved in the original record. Dates in this distribution use the provider's `YYYYMMDD` strings; pre-1982 approvals are explicitly marked. This export may update independently of the text ZIP. Failed or partial exports cannot establish that products, patents or exclusivity are absent.
