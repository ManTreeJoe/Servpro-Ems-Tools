# OneLoss / L OPS — mission and execution handoff

Updated October 3, 2026. Start here when onboarding an agent or Paperclip project.
This is an execution brief, not a Paperclip configuration or a production release.

## Source publication update — use this branch

**Team source branch: `handoff/paperclip-source-20261003`.** It includes all prior
calendar commits plus the previously local desktop/backend implementation:
Card Details, profiles/template sources, notification navigation, division handling,
document import/store, CompanyCam gateway changes, Trello sync functions, existing
migration/ops/test SQL, Python/browser regression tests and DEV helper tools.
The local-only implementation inventory below is now historical for those files.

This is a WIP source snapshot for inspection and continued development, NOT a
release or a statement that every migration should be run. No migration/function
deployment was performed. Supabase credential-pattern checks found only synthetic
test fixtures among flagged candidates; this was not a full security audit.

Validation for the snapshot: 60 targeted Python tests passed (card activity,
document import/store, profile starters, notification navigation and division
detection). CompanyCam gateway reliability and saved Run activity Node tests passed.
`tests/document_storage_sql.cjs` was not runnable here because
`@electric-sql/pglite` was missing; its header records tested dependency 0.5.8.
No full clean-machine app build or live integration verification is claimed.

Excluded and preserved locally: build/install output, customer-specific diagnostic
notes and one-off repair scripts, scratch prototypes and generated artifacts.
These are not required to inspect the published application/backend source.
Private runtime credentials and customer documents are intentionally not supplied.

Checkout for the team:

```sh
git clone --branch handoff/paperclip-source-20261003 https://github.com/ManTreeJoe/Servpro-Ems-Tools.git
```

Use this branch in the agent kickoff below instead of `main-lops-style-pivot`.
The first task is now validating a clean checkout and reviewing the WIP snapshot,
not recovering the published core files from this computer.

## Mission

Build one integrated restoration-operations system: OneLoss desktop for the office,
L OPS web/mobile for connected staff, shared authorized job data and durable history.
Preserve the workflows staff depend on while replacing Trello and Word gradually.
OneLoss should become the primary system, but Trello remains business-critical
during the overlap. Do not cut it off until Nathan explicitly approves and users
have transitioned. The long-term photo app is intended to replace CompanyCam with
an overlap period; the previously stated six-month target is a planning goal,
not a delivery commitment.

## Repositories and ownership

- Desktop/shared-backend: `ManTreeJoe/Servpro-Ems-Tools`, branch
  `main-lops-style-pivot`. Latest feature checkpoint before this brief: `3413dd0`.
- L OPS web/mobile: `ManTreeJoe/l-ops-crm`; another chat owns that implementation.
  Obtain its actual branch, revision and migration head before assigning shared work.
- Canonical cross-app coordination: [l-ops-platform.md](l-ops-platform.md).
- Nathan is the product decision-maker. Managers/admins control shared views and
  profile management; normal users may create personal saved views.
- This brief does not grant agents additional deployment, data-editing, account,
  purchasing, messaging or migration authority.

## Current reality

| Area | Evidence / current state | Remaining work |
|---|---|---|
| Schedule UI | Committed DEV-only sample calendar, default 3 Days, Week, Month, weekend support, waiting sidebar | Real authorized data and persistence |
| Waiting work | TBS three groups, Pending three groups, On Hold; entry dates and independent scroll | Resolve lifecycle against shared model |
| Editor | Job/contact/insurance facts, optional arrival, activities with independent crews, equipment/access/notes | Bind canonical job facts; avoid divergent copies |
| Search | Top name/address search selects sample jobs; existing visits are edited without duplicates | Authorized live job lookup |
| Drag/drop | Calendar and Legacy pointer-following row/card, landing gap, animation, Escape cleanup | Broader edge/scroll/touch testing; persistence |
| Legacy Run | Paper-style sample layout, reorder and cross-section moves, shared in-memory records | Exact approved Run layout and direct print/PDF; no Word |
| Confirm/post | Requirements captured | Not implemented in the new digital calendar |
| Storage pilot | Local October 2 notes report an applied, gated foundation, not connected to Files | Verify live state; review/publish local implementation; approved pilot |
| Other desktop work | Extensive established source and local WIP across jobs, comments, profiles, notifications, files and snapshots | Audit checkout/release parity before claiming complete |

DEV schedule edits currently reset on close. They do not change live jobs, Trello,
Word, or the database. Apply/Cancel still reviews drag moves. Pushing this branch
does not publish a desktop update. Installed Main and DEV are distinct.

The historical handoff contains chronological notes; older statements that the
calendar was absent are superseded by this UI status, not by a claim of live integration.

## Product decisions to preserve

### Jobs, boards, and identity

- One canonical job; familiar permanent boards become saved views/filters rather
  than separate job copies. Keep the familiar UI; no unrelated side-panel redesign.
- All Jobs is a full-width information list. Shared views are admin-managed;
  personal saved views are user-owned. Tags and profiles are different concepts.
- Placement changes must stay consistent between lane dragging and job controls.
- The temporary execution card is in WIP; Estimating retains the main card.
  A manual pull-back retires the WIP temporary card and retains its information
  on the main estimating job. Preserve links/history; do not infer destructive merges.
- Work done means field work completed; closeout means estimating completed.
- Folder presence alone is not proof of a real active division/card. Preserve
  archived-card evidence and the ability to open it; verify exact identities.
- Reconstruction scheduling is deferred. Preserve existing behavior.

### Scheduling and job records

- Most visits have no specific time. Do not force an hourly grid or fake arrival times.
- One upcoming visit per job, with multiple activities and per-activity people.
  Retain historical/canceled visits rather than erasing them or duplicating active work.
- Draft -> Confirm day -> separate explicit Post to comments/job information.
  Confirm day is intended to update board placement. Ordinary board movement must
  not silently rewrite the schedule. Pull board work into a draft explicitly.
- TBS is undated work needing scheduling and retains its entry date. Pending
  retains its start date and carries forward only while unresolved. Hold is distinct.
- Canceled work keeps its placement/history, is marked canceled and needs
  rescheduling; preserve the original and replacement relationship.
- Monitor can be a primary lane/activity or an additional WIP activity without
  changing placement merely because monitoring was added.
- Display dates MM/DD/YY, use validated date-only values internally, and agree
  office timezone behavior before persistence.
- Job Log is the structured work record used directly by Snapshot. Multiple
  activities and crew assignments must survive editing and exports.
- Snapshot/Job Log exports should show activity, crew and equipment details,
  hide full comments, place subcontractor work at the top and omit redundant
  '- completed' wording. Verify actual export behavior before closing this work.
- Card Details is permanent app-owned audit history: who changed what, including
  moves across boards and checklist changes. Do not make it an editable Trello log.

### Operational features and reliability

- Membership and mentions drive personal notifications; unread counter beside
  the label, background refresh, mark-read on open and reliable mark-all.
- Open the exact authorized job/comment, including popouts. Ambiguous mappings
  must be resolved by verified identifiers, never display-name-only joins.
- Comments should share mentions, formatting, emoji/reactions and consistent UI
  across jobs, schedule and snapshots. Reactions must survive refresh.
- Profiles originate from approved Trello templates; managers can customize them.
  State Farm is a residential variant. Do not conflate labels/tags with profiles
  or change/delete template fields without the relevant approval.
- Files should use simple galleries/folders, auto-check availability quietly,
  permit correcting CompanyCam project links, and preserve existing source files.
- Stage selection maps to approved CompanyCam tags, not arbitrary new tags.
- Avoid duplicate loaders. Keep compact controls, scrollable panels and visible
  drag feedback. Provide equivalent click/edit controls and reduced-motion behavior.
- Historical EMS logs are import-only copies for now, not edits to the original
  documents. Preserve source provenance and deduplicate by verified identity.

## Integration guardrails

- Supabase Storage and CompanyCam hold files now; an office server accessible
  outside the office comes later. Preserve provider-independent IDs/references.
- Coordinate schema/API changes in GitHub with both app owners BEFORE implementing.
  Do not create competing visit/job-log tables or silently merge databases.
- Agree canonical job/workspace/user IDs, identity mappings, authorization,
  revision/conflict rules, audit semantics, retry/idempotency and rollback.
- During overlap, support two-way Trello synchronization with explicit conflict
  handling and loop prevention. 'Overwrite perfectly' is a user outcome, not a
  safe technical conflict policy; specify and test it rather than guessing.
- No credentials, tokens, customer documents, exports, database dumps or build
  directories in commits. Do not run historical repair scripts automatically.
- Migration files in a local checkout do not prove migration deployment state.
  Reconcile remote migration history read-only before any approved migration.
- Production enablement, live repairs and Trello retirement require explicit approval.

## Proposed Paperclip work queue

These are proposed tasks, not claims that Paperclip issues have been created.

1. **P0 — Establish a reproducible source checkpoint.** Inventory local WIP listed
   below; review for secrets/customer data and dependencies; publish coherent
   source/test slices to review branches. Compare with the installed app. Done:
   another machine can check out and run documented tests with no hidden files.
2. **P0 — Shared contract handshake.** L OPS supplies current branch/models/migration
   head; OneLoss proposes identity, visit, activity/assignment, queue/history and
   confirm/post contracts. Done: both owners acknowledge the same versioned contract
   with authorization/conflict fixtures. No implementation before agreement.
3. **P1 — Finish schedule interaction QA.** Validate drag order across groups/dates,
   canceled and empty states, long-list edge scrolling, touch/keyboard paths,
   month/Legacy parity, and explicit Upcoming date selection. Fix shortcomings
   before connecting live data. Done: approved DEV walkthrough plus automated tests.
4. **P1 — Digital persistence and draft lifecycle.** After #2, implement authorized
   adapter, revisions, durable ordering and canceled/replacement history. Build
   Confirm day and separately idempotent Post. Done: retries and concurrency do
   not duplicate visits, board changes or comments; live pilot approved separately.
5. **P1 — Legacy print/PDF.** Match the user-approved Run reference using the same
   saved records, long-page breaks and section formatting. No Word round trip.
   Done: approved rendered PDF and calendar/Legacy data parity.
6. **P1 — Identity and Trello reliability.** Audit notifications, popouts, archived
   divisions, temporary WIP/Estimating links, background refresh and two-way sync.
   Done: exact links, no lost updates/loops, user-attributed history and tested recovery.
7. **P1 — Documents pilot.** Reverify the reported foundation and exact allowed
   users/jobs; connect preview/confirm/progress/history/download and safe retries.
   Done: approved sample upload, read-back verification, nonpilot denial and both
   computers tested. Metadata backup is not an object-bytes backup.
8. **P2 — Profiles, logs and analytics.** Verify approved template parity, customizable
   profiles, historical import provenance and analytics definitions (including missing
   data). Keep data-quality gaps visible; no invented completion/progress numbers.
9. **P2 — Photo-app overlap and server portability.** Plan provider adapters, object
   manifests/checksums, permissions and reversible migration; no early cutover.

## Local-only work requiring review/publication

As inspected October 3 in the working checkout, these were NOT part of the pushed
calendar commits. This brief inventories them; it does not publish their contents.

- Tracked changes: `CONTEXT.md`, `_ems_root_index.html`, architecture/overhaul docs,
  `job_profile_sources.json`, `job_profile_starters.py`, `notification_navigation.py`,
  `pipeline_web.py`, `pipeline_web_assets/{app.js,job_workspace_tabs.js,run_activity.js}`,
  `supabase/config.toml`, CompanyCam gateway and associated regression tests.
- Untracked implementation: `card_activity.py`, `document_import.py`,
  `document_store.py`, Trello sync function, storage/card-activity tests.
- Untracked SQL/ops: RLS baseline, Trello mirrors/scheduler/projection,
  capabilities, profiles/note templates, job-log scoping, placement/drop-position,
  document-storage pilot, database tests and operations scripts. Determine which
  are historical/applied versus proposals; do not run them as a batch.
- Many untracked design/audit/repair notes and tools, some customer-specific;
  sanitize before publication. `docs/document-storage-pilot-20261002.md` records
  historical live-verification claims that need current re-verification.
- Excluded build/dist folders, prototypes and generated artifacts are not a
  reproducible substitute for reviewed source. Preserve locally; do not delete.

Do not use `git add .` or reset this checkout. A clean-clone check must distinguish
committed behavior from local dependencies. A remote-only Paperclip agent cannot
inspect these unpublished implementations until their source slices are reviewed.

## Verification and entry points

- `run_doc_editor_web_assets/calendar_preview.html`: sample host, editor, search,
  Legacy rendering and in-memory records.
- `weekly_calendar.js`, `weekly_calendar.css`, `calendar_drag.js` in that directory:
  reusable renderer, layout and pointer feedback.
- `tests/calendar_preview.cjs`, `tests/weekly_calendar.cjs`: Playwright/Edge suites;
  last feature run passed. Requires Node, Playwright and Edge installed.
- `tools/dev_schedule_check.py`: opens Schedule in actual DEV shell and reports
  iframe/theme/day count. DEV uses safe localhost ports; do not disable browser security.
- `dev_http_port.py`: safe-port selection. Python tests should use a fresh
  `--basetemp`; this machine has problematic old pytest temporary directories.
- Windows environment paths in prior chats are machine-specific, not portable
  installation instructions. Discover runtimes and dependencies on the new host.

## Agent kickoff text

> Read docs/paperclip-handoff.md and docs/l-ops-platform.md on branch
> main-lops-style-pivot in ManTreeJoe/Servpro-Ems-Tools. Start with the reproducible
> source checkpoint and shared-contract handshake, not a live migration. Coordinate
> L OPS web/mobile through GitHub. Report verified facts separately from proposals
> and local-only claims. Preserve live operations, unrelated changes and user data.
> Do not deploy, enable pilots, repair live records or retire Trello without approval.

Every completed task should publish its branch/commit, scope, tests and remaining
gaps; shared decisions must also be consolidated into docs/l-ops-platform.md.
