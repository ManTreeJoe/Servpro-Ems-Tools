# Trello exit plan

Linguar Hub is the permanent system. Trello remains a temporary adapter while
the office changes over without interrupting active jobs.

## Ownership inventory

| Job feature | Linguar Hub status | Temporary Trello role | Cutover requirement |
|---|---|---|---|
| Clients, claims and jobs | Owned | Card name/reference | Continue identity reconciliation |
| Boards, lanes and cards | Mirrored and read first | Import and write-back | Native create/archive UI |
| Card movement | Saved locally first | Write-back to shared Trello board | Background retry queue |
| Full checklists and item states | Owned as of Trial 23 | Import and write-back | Template editor and native add/remove/reorder |
| Comments/activity | Owned and deduplicated | Import and write-back | Edit/delete permissions and retry queue |
| Structured Job Log | Owned | Trello comments can seed entries | Finish replacing comment parsing |
| Labels, due dates and card links | Mirrored | Import | Native editors |
| Attachments | Links currently read from Trello | Reference | Store attachment metadata; files remain on X:/OD |
| Members/assignments | Read from Trello | Reference | Linguar roles and job assignment UI |
| Automations/card close-out | Mixed | Trello automation | Linguar workflow rules and audit trail |

## Migration rules

1. Every user change is saved in Linguar Hub before Trello is contacted.
2. Trello failures never discard a successful local change; they create a sync warning.
3. Imports retain external IDs so repeated pulls update instead of duplicating data.
4. The database stores text, status and file references. Signed forms and media stay in the job folders.
5. New screens must work with a native Linguar card that has no Trello ID.

## Delivery order

1. Checklists: durable full checklist copy and local-first completion updates.
2. Sync outbox: retry pending card moves, checklist changes and comments.
3. Native checklist templates by EMS, Contents and Recon stage.
4. Native job assignment, due dates, labels and attachment metadata.
5. Replace Trello automations with workflow rules and notifications.
6. Run a read-only Trello period, compare both systems, then disable write-back.
7. Archive the final Trello export and remove the adapter after reconciliation.

## Target synchronization mechanics

Linguar Hub is the only canonical write model. Trello is represented by
provider links and external mirrors attached to permanent Client, Job, and
Division IDs; a card title is searchable display text, never identity.

Each user action follows one transaction boundary:

1. validate the user's franchise and role;
2. commit the Linguar Hub record and its audit event;
3. enqueue a uniquely keyed sync operation in the same database transaction;
4. update the screen immediately from the committed Hub value;
5. let a background worker publish the operation to Trello;
6. record the provider revision and acknowledge, retry, or surface a conflict.

Inbound Trello changes are normalized before they touch operational data.
Append-only activity such as a new comment can merge automatically. A lane,
description field, due date, checklist state, or other editable fact is applied
only when its Linguar value still equals the last synchronized base. If both
sides changed, preserve both values and create a conflict for review. Blank
external values never erase populated Hub values implicitly.

## Current implementation gaps

- `crm_pipeline_*` is a useful projection, but its board/lane/card keys and RLS
  are not franchise-scoped. Do not enable shared multi-franchise writes until
  every row and unique key carries the franchise boundary.
- `sync_status='pending'` is not a queue. A process or PC crash can strand the
  change because no durable operation owns its retry, attempt count, or error.
- Moves and checklist changes currently mix database writes with direct Trello
  calls. They need one shared outbox adapter so all changes follow one rule.
- Job Info already retains a `trello_base`, but the same three-way comparison is
  not consistently applied to lanes, labels, due dates, checklists, and cards.
- Trello comments and structured Job Log entries overlap. Job Log must remain
  canonical; a Trello comment is a mirror link or imported source event, not a
  second editable copy.
- The compatibility `canon_key` still participates in matching. New provider
  links must use permanent job/division IDs and require human review for an
  ambiguous title or claim match.

## Safe implementation slices

1. Add franchise-scoped integration connections and permanent external links.
2. Add a durable outbox, attempt history, idempotency keys, and a visible retry
   state without changing current Trello behavior.
3. Route card movement and comments through the outbox; keep current direct
   calls as a guarded fallback during device testing.
4. Add inbound checkpoints and three-way conflict detection for job fields,
   lanes, due dates, labels, and checklists.
5. Make Job Log-to-Trello projection explicit and stop parsing mirrored Hub
   comments back into duplicate Job Log entries.
6. Run a shadow comparison before allowing Linguar-owned records with no Trello
   card, then retire Trello feature by feature.
