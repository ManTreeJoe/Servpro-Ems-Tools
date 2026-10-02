# L OPS platform / EMS Tools coordination

Status: October 2, 2026. This file is the canonical cross-chat handoff.

## Active handoff — October 2, 2026

Owner: OneLoss/shared-backend chat. Branch: `main-lops-style-pivot` in
`ManTreeJoe/Servpro-Ems-Tools`. Base revision: `a495016` (release 1.8.26).
This handoff is documentation only; it does not publish an app release.

### Responsibility and communication

- This chat owns OneLoss desktop and shared-backend integration.
- The other-computer chat owns L OPS web/mobile in `ManTreeJoe/l-ops-crm`.
- Read this file from the latest remote branch before shared work. Record each
  handoff here with branch/revision, changes, database decisions, validation,
  required changes in the other app, and next owner/action.
- Shared schema/API changes must be proposed in GitHub and agreed by both sides
  BEFORE implementation. Acknowledgement is not approval. Deployment remains
  a separate action, not implied by pushing a proposal.
- Use linked PRs/comments for discussion and consolidate accepted decisions
  here. GitHub does not automatically deliver messages into either AI chat.

### Database and file decisions

- Supabase Storage and CompanyCam hold files for now; our own server comes later.
- Do not merge databases or assume existing job IDs/auth/workspaces match.
  Agree canonical IDs and explicit mappings; never join on display names alone.
- Before a schedule migration, agree source-of-truth project, existing tables
  to reuse, tenant/RLS rules, site-local dates/timezone, revision conflicts,
  idempotent confirm/post actions, audit history, and rollback compatibility.
- Store stable provider/object references, not expiring signed URLs. Keep
  credentials and customer documents out of GitHub.
- No database changes were made for this handoff.

### Schedule scope awaiting shared contract

- Main view: seven-day weekly calendar, weekends, week navigation, Today, and
  scheduling directly onto future days.
- Legacy view: familiar Run layout with editing/reordering and direct print/PDF.
  Same saved records as calendar and job log. NO Word dependency. Existing
  documents may be imported as copies only; never edited as the source of truth.
- One upcoming visit per job, multiple activities and per-activity assignments.
- Draft -> Confirm day updates board placements -> separate explicit Post to
  comments/job info. Board moves do not rewrite visits; board-to-draft pull is
  explicit.
- TBS retains entry date; Pending retains start date and remains visible on
  subsequent days only while unresolved.
- Canceled visits retain placement and history, flag rescheduling, and remain
  linked to their replacements.
- Monitor can be a main lane/activity or an extra without moving the WIP card.
- Reconstruction scheduling is ON HOLD. Preserve current behavior.

### Actual implementation status (not a completion claim)

The current `run_doc_editor_web.py` still loads/saves Word-backed days and prints
the original document. The requested digital weekly calendar is not implemented.
Do not wire the new web/mobile schedule to that Word-backed persistence.

Existing local work outside this documentation commit includes Card Details
movement history, exact notification aliases, division detection, profile source
refresh, and a document-storage pilot. These are NOT included in this handoff
commit and must not be assumed available in this remote revision. The previously
reported document pilot is gated; its live migration/enablement state must be
reverified before another client uses it. No new shared schedule schema exists
from this handoff.

### What L OPS must update / reply with

1. Acknowledge ownership and provide current branch/revision and migration head.
2. Link the actual job, visit, job-log, workspace/auth, and file-reference models.
3. Propose canonical identity mapping and shared source-of-truth project first.
4. Review the schedule requirements above and identify compatibility gaps.
5. After agreement, implement web/mobile against the versioned shared contract
   and common fixtures; do not independently create competing schedule tables.

OneLoss will reconcile that response before implementing a shared migration.
UI-only work and isolated tests need not change live data while review is pending.

Validation: documentation-only diff/whitespace review. No runtime tests or
deployment are claimed. The older linked L OPS guide below was not present in
the local checkout during this handoff; L OPS should confirm current guide paths.

### Follow-up: weekly-calendar presentation slice

Owner: OneLoss. Branch: `main-lops-style-pivot`, following `a2195a2`.
Status: isolated UI implemented/tested; NOT connected to the live Schedule.

- Added `run_doc_editor_web_assets/weekly_calendar.js` and `.css`: seven-day
  calendar, week/Today navigation, selected day, add/edit callbacks, search,
  TBS/Pending lists, loading/error/retry states, and a basic Legacy day view.
- Both views render the same host-provided collection. No Word, network,
  persistence or schema calls. The module never mutates host records.
- The input shape is a presentation adapter, NOT an approved shared schema.
  The host must supply authorized records, resolve pending state for the
  selected range, fence stale loads, and implement edits/persistence.
- Remaining: live data adapter, editor, ordering, original Run-style print/PDF,
  draft/confirm/post flow and shared schedule/job-log persistence. This basic
  Legacy view is not yet the complete original-document layout.
- `tests/weekly_calendar.cjs` passes using headless Edge: seven days/weekends,
  callbacks, same-record updates across views, queues, search, loading/retry,
  date boundaries, text escaping, narrow layout and teardown. Desktop/narrow
  screenshots inspected; retains OneLoss theme tokens and compact controls.
- L OPS: review shared contract questions above; do not build tables from this
  renderer's input shape. No action required in mobile/web for this isolated UI.
- No shared schema changes, app cutover, Reconstruction changes or release.

## Prior reference notes — September 14, 2026

### Latest design selection — B without an hourly grid

Nathan selected the three-day schedule with a persistent right-hand waiting
panel. Most visits have no set time: a date is sufficient to be scheduled.
Show an arrival-window label only when provided; do not show "Time not set".
TBS means no scheduled day, not a missing arrival time. Day lists retain Monitor
and Work To Be Performed; the right panel contains all seven Run waiting groups
and scrolls independently. On narrow windows it stacks below the dated work.
The layout comparison chooser is removed from the sample DEV page.

Compact toolbar follow-up: range (3 Days/Week/Month), queue selection and selected
date moved into a Filters disclosure. Selected range is a pill; queue pills can
be cleared. Date arrows, Today, search and Legacy remain visible. Escape and
outside-click dismiss the dropdown. Both browser suites pass, including filter
selection, clearing and keyboard dismissal. This remains sample-only DEV UI.

Visit editor follow-up: job/address/contact/phone/carrier/claim, explicit Run
group, optional arrival, activity multi-select pills with independent crew
assignments, equipment/access/work notes. Sample edits retain unknown record
fields and per-activity people; waiting items need no scheduled date. Browser
test verifies save/reopen retains details and distinct crews. No backend schema
or shared customer write behavior is implied; live job facts must use the agreed
canonical job model rather than independently copied visit fields at integration.

DEV presentation follow-up: displayed full dates and editor entry use MM/DD/YY;
stored values remain ISO. Activity pills/strips use blue Monitor, green Initial,
orange Demo, purple Contents, teal Equipment, with amber Pending, gray Hold and
red Canceled status strips. Labels remain visible independently of color. These
are local presentation choices, not schema changes. Browser suites passed and
the actual DEV shell confirmed three columns and loaded theme after restart.

Validated both calendar browser suites. No shared schema or live-data changes.
DEV now chooses an available port in 53100–53199: pywebview randomly selected
4045, which Edge rejected with ERR_UNSAFE_PORT. A socket regression test checks
the safe range and that occupied ports are skipped. Installed Main is unchanged.

### DEV testing handoff — calendar range and Run groups

OneLoss owner, branch `main-lops-style-pivot`: DEV-only Schedule route now opens
`calendar_preview.html` inside the normal shell. Main route is unchanged. This
remains sample/in-memory UI, not shared persistence or a deployment.

- Default 3 Days, plus Week and Month; month overflow opens the selected day.
- Day columns separate Monitor and Work To Be Performed and scroll independently.
- Page scroll exposes the three TBS groups, three Pending groups, and On Hold,
  each with its own scrollable list and entry dates. These are undated queues,
  not duplicate booked visits. They remain visible beneath calendar views.
- Populated synthetic examples and paper-style Legacy preview are available.
  Legacy is not yet an exact reproduction of the original Run or print-ready.
- Verified `tests/weekly_calendar.cjs` and `tests/calendar_preview.cjs`, including
  month navigation/drilldown, grouped queues and actual page/column scroll.
- `tools/dev_schedule_check.py` opens the real DEV Schedule and reports loaded
  theme tokens. The old standalone preview server rooted assets incorrectly;
  the main DEV shell serves shared CSS from the correct root.
- L OPS: no schema/API changes to adopt. Shared identity/source-of-truth review
  above is still required. Reconstruction remains deferred.

Read the [full L OPS agent guide](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/README.md) before transferring features. It covers web CRM, Expo phone/iPad app, architecture, shared data, roles, run/visit crew assignments, media, documents, forms/signing, build commands, tests and remaining work.

- [Product decisions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/product.md)
- [Architecture](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/architecture.md)
- [Builds and validation](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/builds.md)
- [Data and permissions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/data-and-access.md)
- [Current status](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/status.md)
- [Transfer protocol](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/cross-repo.md)
- [Local intake mapping](intake-parity.md)

## EMS Tools remains a business-workflow reference
`new_loss_intake.py` has mature carrier intake parsing and template/folder/CompanyCam workflows. The new web intake now has corresponding contact, loss, claim/policy, adjuster and property/notes fields. Its parser fills explicit recognized labels for review; external provisioning and fallback parsing are not fully ported.

The user wants useful features to move in both directions. Shared domain contracts and fixtures should stay compatible, while Python desktop and TypeScript web/native rendering remain platform-specific. Tech assignments belong to dated runs/visits; permanent job contacts and Lead Tech staff designation are separate.

## No automatic DB merger
The legacy DB and new platform DB are not yet one database. Do read-only comparisons, agree stable IDs and source-of-truth/conflict rules, and build a reversible migration before shared writes. Avoid destructive changes to the working legacy app.

## Publication caveat
### 2026-10-02 — Waiting work drag-to-schedule DEV handoff

Branch: `main-lops-style-pivot`. The sample calendar now accepts waiting-work drops onto three-day/week columns and month cells. A drop opens the visit editor with Scheduled and the target date selected; Apply replaces the same sample record, while Cancel leaves Waiting unchanged. Job details and activity assignments are retained. Click-to-edit remains available without dragging. Browser tests cover cancel/apply and duplicate prevention; the existing calendar suite also passes.

No database/schema, Trello, Word, or live scheduling writes were added. L OPS does not need a schema update for this UI-only change. Shared persistence remains subject to a coordinated contract before implementation.

This is a documentation snapshot. Some new-platform code is still local/uncommitted; the mobile repo has no remote yet. Verify the actual source revision and migration state before assuming a described feature is available from GitHub or deployed. No production release is implied by these notes.
