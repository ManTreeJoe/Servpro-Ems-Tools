# Division pin repair — 2026-10-07

Approved: repair Laura Juarez only; scan other jobs without automatic changes.
Root cause reproduced with mocked writes: persistence.set_trello_card_ids wrote
any selected card as unsuffixed trello_card (EMS), with no division check.
The reader treated unmarked links as primary and chose the oldest.

Pre-repair recovery record (no Trello cards are deleted):

- Job key: `juarez, laura`.
- Incorrect EMS link: type `trello_card`, value `6aab21c79872566b541cf39d`,
  added_at `2026-10-05T18:49:19`, added_by `persistence.set_trello_card_ids`,
  metadata_json null.
- Correct EMS link: `6aa9c45d56c42082e3037dcc`, added_at
  `2026-10-07T21:09:06`, added_by `companycam`, metadata_json null.
- Correct Contents link: type `trello_card_contents`, value
  `6aab21c79872566b541cf39d`; preserve unchanged.

Recovery, only if explicitly requested: recreate the exact removed link with
the recorded values and restore the correct EMS metadata to null. This would
restore the known bad association, so do not run automatically.

Code: verify all legacy inputs as EMS before local/shared writes, preserve
explicit secondary placements, write explicit primary metadata, refuse to
guess among multiple primary candidates, and guard legacy pin backfill too.
Modern division-specific pin validation remains in place. Main is not released.
Other direct import/identity writers and old installed clients still warrant
separate hardening; this is not a database-wide constraint on every writer.

Repair completed in the shared database using a transaction with exact-value
guards and expected-row-count assertions. Local legacy pin was corrected too.
Read-only reconciliation after repair reports EMS linked, Contents linked,
Recon missing, and `has_conflict: false`. No provider cards were changed.

Validation: 56 targeted tests pass (legacy guard, division boundaries, graph
wiring, identity preservation and divisions). The duplicate-type scan found
12 other candidate jobs; none were changed. Sources include sync_from_trello,
crm_workspace and pin_card_name. Verify board ownership before repairing these;
cross-type duplication alone is not proof of the correct replacement.
