# Shared platform implementation status

Implementation authorized September 11, 2026. Work is in Linguar Hub;
the L OPS checkout is currently a reference and has not been changed.

## Completed foundation work

- Reconciled current remote job IDs against L OPS import provenance using the
  reusable read-only `convergence_audit.py` tool. Only aggregate results are
  recorded here; customer records and identifiers are not committed.
- Recovered the two missing Linguar migration files locally from their actual
  remote history statements. These remain outside this release pending a separate
  database review. No migration was applied or re-applied.
- Recorded both projects' remote migration versions and statement hashes in
  `migration-inventory.json`. This inventory is not a schema backup.
- Added `loss_contract.py` and `docs/contracts/loss-view.v1.schema.json`.
  The new contract requires organization and Loss identity, keeps multiple
  claims, and projects separate Division board cards. The existing workspace
  v1 remains supported. The new contract is not connected to production UI yet.
- Added tests for multi-claim/multi-Division identity, unknown facts, duplicate
  IDs, absent divisions, and reconciliation cutover blockers.

## Live reconciliation: September 11, 2026

| Check | Count |
|---|---:|
| Linguar source job IDs | 2,117 |
| L OPS imports from Linguar | 430 |
| Imported IDs matching current source | 429 |
| Source records absent from target | 1,688 |
| Missing IE records | 15 |
| Missing OC records | 16 |
| Missing records without franchise | 1,657 |
| Imports without a current source ID | 1 |
| Duplicate source/import IDs | 0 |
| Matched records with conflicting franchise | 0 |

Of the 1,657 unscoped source records, 547 are marked active and 1,094 closed;
16 have empty/unknown status. Do not assign these to IE by default. Resolve
ownership from authoritative source references before import. Retain the orphan
import until its source history is understood; a missing source ID does not
authorize deletion. Identity reconciliation is only one cutover gate, not proof
of complete data or permission parity.

## Still required before database cutover

1. Recover the full pre-history Linguar schema and the remote L OPS migration
   files absent from this PC. Validate a clean local database reconstruction.
   Matching the three recorded Linguar versions alone does not provide this.
2. Reconcile the L OPS local Job Profile migration with remote changes. It is
   not represented in the remote history and must not be blindly applied.
3. Reconcile unscoped/orphan identities and every linked card, folder, log,
   checklist, schedule row, claim and division. Produce a review queue.
4. Build canonical schema additions and compatibility adapters in staging.
5. Test both clients' memberships, restricted tools and fields, save conflicts,
   and background synchronization against that staging database.
6. Validate migration counts and restoration before production cutover.

## UI sequencing and preserved behavior

The next UI work consumes the canonical Loss contract after an adapter maps
real records. Keep existing working tools available throughout migration.
The first visual slice is the reusable card/list projection and Loss workspace.
The requested Loss spine is reviewed in context before rolling out all lanes.

Retain existing drag/drop while building its replacement and keyboard movement;
deferring new drag/drop is not permission to remove existing functionality.
Preserve ordinary comments separately from structured Job Log entries, retaining
provider IDs and provenance. Requirements and checklist progress remain distinct;
a checklist count cannot claim that all business Requirements are satisfied.
Snapshot remains an output generated from Job Log entries.

Production data, sign-in configuration, existing UI and L OPS source were not
changed during this foundation increment.
