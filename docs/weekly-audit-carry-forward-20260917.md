# Weekly audit incremental review

Implemented in Linguar Hub's existing Logs audit, without a database cutover.

- Saved findings and source snapshots remain in local audit state. Previous period versions remain available to the weekly Excel exporter.
- A new period carries findings, not approval. Changed Logs or linked AR evidence clears review confirmations on inspection.
- New, edited and removed comments are reported. Current suggestions that disagree with saved findings are marked; they do not overwrite those findings.
- EMS Days uses physical work start through billed date. Contents Days uses the original Contents card start through billed date. Ready for Billing remains separate. Missing starts produce unknown days, never a ready-date fallback.
- The 15-column Excel template is preserved. Typed start dates in Audit detail feed the day formulas.
- Explicit start-date labels can suggest values with sources. General natural-language readiness inference and original Contents-card discovery still require review; they are not treated as confirmed facts.
- Preview and explicit confirmation remain required for Trello comments and moves. No production records were changed during implementation/testing.

Not yet implemented: shared cross-PC audit persistence or structured Job Log event ingestion. Do not describe this local state as shared database storage. Existing historical exports are not rewritten, and previously generated draft workbook findings are not imported as confirmed reviews.

Verification: 46 Python audit/evidence/suggestion/export tests; browser workflow test covering save, preview, confirmation, source escaping, narrow layout and start-to-billed calculation. Native Excel recalculation and live desktop acceptance remain to be tested.
