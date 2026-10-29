"""Synthetic versioned GenCC assertions; no live or clinical qualification."""
import csv
import io
from biomedmcp.native.gencc import HEADERS


def assertion(index=1, gene='BRAF', **changes):
    row = dict.fromkeys(HEADERS, '')
    row.update(sgc_id=f'SGC-{index}', version_number='1', gene_curie='HGNC:1097',
               gene_symbol=gene, disease_curie='MONDO:9000001', disease_title='Synthetic phenotype',
               classification_curie='GENCC:100003', classification_title='Moderate',
               moi_curie='HP:0000006', moi_title='Autosomal dominant',
               submitter_curie='GENCC:000101', submitter_title='Synthetic submitter',
               submitted_as_date='2026-01-01', submitted_as_notes='Synthetic assertion only.')
    row.update(changes)
    return row


def export(rows=(), headers=HEADERS):
    text = io.StringIO(newline=''); writer = csv.DictWriter(text, fieldnames=headers)
    writer.writeheader(); writer.writerows(rows)
    return text.getvalue()
