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
