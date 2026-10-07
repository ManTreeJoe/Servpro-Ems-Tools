# L OPS platform / EMS Tools coordination

Status: October 7, 2026. This file is the canonical cross-chat handoff.

## October 7 — Operations analytics first working slice (DEV)

Chart motion follow-up: user requested loading animation. Panels enter in
160 ms; horizontal/vertical fills grow from their zero baseline in 260 ms.
Only first successful load or returning to the Operations tab triggers this;
search, selections and refreshes render without replay. Counts remain immediate,
controls are never disabled for animation, and both reduced-motion preferences
disable it. UI polish guidance kept motion short and limited to chart surfaces.
Both Analytics browser suites pass, including entrance names, reduced motion,
and absence of replay on filters/refresh. No backend or L OPS changes.

Chart follow-up: inspected the local L OPS checkout (`bac93c8`), especially
app/analytics-chart.tsx and app/operations-analytics.tsx. Adopted its accessible
clickable-bar/drill-down pattern without changing that repository or adding React.
OneLoss Operations now has board columns, sorted lane bars, and estimating-queue
bars. Board/search scope is explicit; clicks filter exact-card results. These
are placement counts, not time, performance, unique-job, or revenue charts.
Zero values render zero-length bars; numeric labels and keyboard buttons remain
available. Uses shared theme colors and no count-up/decorative chart animation.
UI-design guidance kept the comparison panels readable and mobile-stacked.
Both Analytics browser suites pass, including board totals/proportions,
drill-down, dark/light palette, narrow layout and existing weekly-review behavior.
No schema or L OPS consumer changes required.

Color follow-up: Analytics now imports shared theme.css and aliases its palette
to the Jobs tokens instead of defining a separate green-tinted dark theme.
Controls, lane accents and audit dialogs follow the same light/dark colors.
Preserved scrolling when importing shared chrome; both Analytics browser suites
pass, including exact dark/light background and lane-surface color assertions.
UI polish guidance limited this to theme consistency; no analytics logic changed.

Branch: `handoff/paperclip-source-20261003`. Analytics now starts at Operations
& lane timing instead of the weekly review. Existing weekly/audit views remain.
This read-only view uses existing scoped Jobs board sources independently of
the slow review graph, lists active WIP/Estimating/Contents lanes, supports board
and name filtering, and opens exact cards. Recon remains deferred. Counts are
card placements, NOT unique jobs; existing Jobs card-level exclusions still apply.

Inspect timing reads paginated Trello movement events (bounded at 10,000) for
one allowed card. It displays recorded entries/exits, actors, durations, and
cumulative recorded visits per lane. Missing entry evidence stays Unknown.
IE estimator cycles use verified lane IDs; arrival on the Logs BOARD stops the
cycle, independent of Billed lane. Shared estimator lanes retain their lane
identity; they are not assigned to guessed individuals. Other franchises need
explicit mappings. Closed cards do not retain a running current-lane clock.
Provider event IDs deduplicate this read; cross-board events with unknown target
lists end the prior lane without fabricating the next list. This does not prove
full historical coverage or merge separate WIP/Estimating card copies.

UI guidance kept compact, labelled queue colors and a 140 ms timing-dialog
entrance with reduced-motion support. Read failures preserve previous queues;
30-second UI timeouts offer retry rather than an endless spinner. Underlying
reads are not canceled. CSV export is disabled for this new view (old exports
are preserved). No new collection tables, schema, backend deployments, or live
card writes. Uses the existing scoped cache/provider read paths only.

Verified: 14 Python model/API tests; Operations browser test (filtering, opening,
errors, narrow layout, reduced motion); existing Analytics workflow browser test.
Read-only live smoke: 55 lanes/192 cards and one actual card movement timeline.

Still pending: shared durable movement ingestion and L OPS contract/migration,
automatic dashboard age hydration, completed-job cohorts/estimator-wide rollups,
Snapshot-to-Logs summaries, historical backfill, edit-ready lane/person mapping,
approved/invoiced/collected financial sources and the user's definition of gain.
Do not present this on-demand inspector as continuous org-wide analytics.
OneLoss owns shared integration; coordinate schema on GitHub before implementing.

## October 7 — Lane timing requirements and live lane audit

User correction: show ALL open Trello lanes without name-based exclusions,
including spacers, templates and On Call Teams. Both direct and mirrored read
paths now retain them. Archived lanes remain outside the open-board view.
This supersedes the exclusion policy below. Existing card-level filtering is
unchanged; this change concerns lane visibility, not analytics eligibility.

Branch: `handoff/paperclip-source-20261003`. Live Trello read verified WIP,
Estimating and Contents open lists. MARKETING TEAM was incorrectly filtered as
noise by the desktop; removed that exclusion. Spacers/templates stay excluded.
This is a lane-visibility fix, NOT deployment of the analytics described below.

Approved timing requirements:
- Track each visit to WIP, TBS New Loss/Re-inspection, TBS Mitigation, TBS
  Contents, Test/Clearance, each Pending Approvals lane, and On Hold separately.
- Show current time in lane and cumulative time across returns; preserve every
  entry/exit and source event, scoped to exact board/card placement and franchise.
- Snapshot is on ESTIMATING (list `63a384193d3ec900984ab584`). Record arrival
  from WIP, time awaiting snapshot, and overall Snapshot-to-Logs turnaround.
- Estimator assignment lanes start assignment timing. Entering THE LOGS - EMS
  board (`67bcf63154947b17268a18bb`) stops the estimating clock, regardless of
  destination lane. Billed-month lanes are NOT the stop trigger.
- Preserve estimator transfers/reopened cycles. Shared lanes such as KIM+ESTEBAN
  cannot be attributed to one person without an explicit assignment.
- Approved/billed/collected dollars and supplements are separate from elapsed
  time; financial meaning/source and cost/profit integration remain unresolved.

Live WIP includes separate PENDING APPROVALS/INSURANCE/SELF PAY and PENDING
APPROVALS/PROPERTY MANAGEMENT/COMMERCIAL, plus MARKETING - ON HOLD. Estimating
currently includes JUANTES, JOHNNY, AARON, AMAYA, KIM+ESTEBAN, SAMANTHA / AL JR.,
NATHAN, PABLO, MARK, ZAC and unassigned/review/service-call queues. Use permanent
lane IDs for mappings; preserve historical names and do not guess person identity.

Implementation pending: coordinate a shared movement-history ingestion contract
with L OPS before schema changes. Deduplicate Trello and OneLoss echoes, preserve
provider timestamps, distinguish observed-first from actual lane-entry time,
handle out-of-order events, and expose unknown history instead of fabricated days.
The current board age chip uses last activity, not verified lane tenure; it must
not feed this report. No automatic moves or schema changes were made. Snapshot
auto-advance trigger/destination still require a user decision.

Remaining refresh investigation: compare the app's authorized mirror/cache with
these live lists. Reading Trello here does not refresh the running desktop cache.

## October 7 — Lightweight surface entrances (DEV)

Follow-up: Jobs now includes the main job-card panel and lane menus in the same
140 ms entrance. The incremental workspace browser test verifies exactly one
panel entrance across fast/full/background refreshes, with draft and tab intact.
Surface-motion/reduced-motion checks pass. No layout or persistence changes.

Branch: `handoff/paperclip-source-20261003`. Shared dialogs, pipeline modal
shells, the schedule editor and crew picker now use 120–140 ms CSS entrances.
Closing remains immediate; no save or click is delayed. Job content replacement
does not animate the audit-card panel again. Existing thread/menu motion remains
unchanged. Reduced-motion settings disable the new effects. Add update is retained
until the later job-card cleanup requested by the user.

Browser checks: surface animation, focus containment/restoration, immediate Escape,
reduced motion, job-panel animation exclusion; existing strict-backdrop, schedule
crew and comment-thread suites pass. This is a scoped motion pass, not a claim
that all app performance or interaction work is complete. UI-design guidance kept
the existing layouts and short entrance-only effects.

No database/schema, API or L OPS changes required. Main is not released by this
handoff; remaining immediate-feedback work is listed below.

## October 7 — Immediate feedback rollout, first pass (DEV)

Branch: `handoff/paperclip-source-20261003`. User requests app-wide immediate
visual response for reversible edits, background persistence, and rollback/error
on rejection. This rollout is NOT complete app-wide.

Implemented and delay-tested:
- Calendar and Legacy moves paint the new record/position before the save; crew
  and scroll are retained. Rejection restores the snapshot before reconciliation.
  Pre-mutation reads are discarded by the schedule adapter; acknowledgement
  revision is retained. Moves remain serialized while saving (not an offline queue).
- Schedule refresh keeps the loaded board instead of replacing it with a loader.
- Personal inbox read/unread (including opening) paints first, blocks duplicate
  same-item writes and restores on failure. In-flight old inbox reads are ignored;
  manual refresh is deferred while a read write is pending.
- Pins with an existing shared snapshot paint first, block repeat writes and
  roll back on rejection. New unsnapshotted pins still await verified server data.
- Trello reactions paint the intended count/state immediately and restore on
  failure; ambiguous failures still require provider refresh before retrying.

Audit findings / remaining work:
- Jobs board drops already have pending previews and rollback; preserve them.
- APA already paints edits before its serialized saves. Its failure path retains
  unsaved edits: needs a deliberate unsaved/retry experience, not whole-document
  rollback that could discard later edits.
- Checklist clicks already paint checks/progress first and revert on failure.
- Scheduling crew/activities are local draft edits until Save; already immediate.
- Still to implement/verify: label edits, Trello notification read/mark-all,
  personal notification mute, requirement saves that recreate the job modal,
  and pending comment/reply feed entries with stable retry IDs and echo dedupe.
- Do not make archive/delete, document generation or external delivery appear
  successful before acknowledgement. Lost responses can mean a write succeeded;
  reconcile and preserve operation identity rather than blind retries.

No schema changes or L OPS deployment required. L OPS should adopt this behavior
without interpreting a visual pending state as a confirmed database write.
Browser suites: schedule_optimistic, schedule_live, schedule_return_waiting,
personal_notifications, comment_threads, comment_reactions pass. Main unchanged.

## October 7 — Return calendar visits to waiting work (DEV)

Waiting groups lacked drop-target metadata, so calendar-to-waiting drops were
ignored. All seven waiting sections now accept drops (including empty sections)
using the existing queue/group save path and highlighted drop slot. Returning
clears the scheduled date while preserving activities/crew and the same record;
it does not create a second visit. Existing queue-entry timestamps follow the
current backend contract. No schema change. Browser regression covers the
waiting/day/waiting round trip, correct group, preserved people, no accidental
editor opening, and empty On Hold destination.

## October 7 — Schedule editor crew pills (DEV)

Replaced calendar's repeated single-select dropdown with a searchable native
popover: toggle multiple name pills without closing, search names/aliases,
remove selected chips, and optionally copy this activity's crew to all activities.
Each activity remains independently editable; manual names and offline fallback
remain under Edit names manually. Two Joses remain distinct. Save contract is
unchanged (`activities[].people` strings); no shared schema/Auth changes.
Editor uses lighter section dividers and compact activity rows, preserving
scrolling and sticky Save/Cancel. UI skills guided reuse of current tokens and
native controls rather than a redesign. Main unchanged.

## October 7 — APA cleanup and shared contacts follow-up

DEV removes the plain Paste toolbar button and Open in Word overflow action
from APA; Paste & reconcile, Print, Contacts, and Show in Explorer remain.
Removed the corresponding boot listeners and the print error's obsolete Word
suggestion. No document or backend data changes.

Next backend task requested by Nathan: APA contacts must be organization-wide,
not per-PC. Before schema implementation, coordinate the organization boundary,
authorized read/edit roles, contact identity and duplicate review, migration of
existing local lists, change history, and the L OPS read/write contract here.
Contacts are separate from scheduling people and authentication accounts.
No shared contact schema or migration has been implemented in this cleanup.

## October 7 — Approved IE scheduling roster (DEV)

Branch: `handoff/paperclip-source-20261003`. `scheduling_roster.py` records
Nathan's approved 33 scheduling people and aliases. The Schedule crew picker
uses this list in IE, retaining local custom additions. Jose/Jose Diaz and
Jose M/Jose Manuel are TWO people; Juan/Juan M, Maricruz/M.Cruz/Cruz,
Mario Nevarez/Mario N/Nevarez, and Vince/Vicente each resolve to one choice.
Aaron/AP maps to Aaron P; JL to Johnny. Rafa and Mike are included.

This is a bundled scheduling picker roster, NOT shared database staff records
or Auth accounts. No permissions, emails, passwords or invitations are created.
No schema changes, historical visit rewrites, or photo-folder alias changes.
Existing schedule payloads still store activity people as strings. Main's
installed release is unchanged; updated desktop source supplies the new list.

L OPS follow-up: use these approved canonical names/aliases when presenting
scheduling people. Before implementing shared editable staff profiles, coordinate
stable person IDs, office scoping, admin edits/deactivation, nullable verified
Auth linkage, and backward-compatible activity assignment IDs here in GitHub.
Do not auto-link accounts by first name or convert these records into logins.
The bundled roster is an interim picker source, not an account-linking contract.

Calendar activities now have an Add crew member selector backed by the same
API, with manual names preserved. Selecting an alias's canonical person removes
only that person's duplicate aliases; Jose Diaz and Jose Manuel remain separate.
Roster loading/error/empty states never block manual entry or erase assignments.
Validation: 18 Python roster/dispatch tests and three browser suites (Daily Run
crew controls, calendar regression, and scheduling crew) pass. Narrow editor
render inspected. No new visual system: existing labeled native controls and
scrolling editor are retained.

## October 7 — Floating comment thread (DEV)

Follow-up motion pass: refine existing Job Log height transition to 180ms;
140ms fade/short-slide entrance for its editor, activity picker, and job action
menus. All respect reduced motion, with no delay to saves/click handling.
Notifications default to showing read and unread items. Both sources label the
optional checkbox Only show unread. Personal inbox filters the loaded inbox
locally without discarding read rows, so turning it off restores messages
immediately; refresh obtains the latest bounded inbox page. Trello retains its
existing server-filtered refresh behavior. Read status and badge counts remain
separate from visibility. Five browser regression suites pass, including read
retention/filter toggling in both sources and reduced-motion menu behavior.
Main is unchanged. Broader card-opening, sync-change highlights, and schedule
motion remain future passes; no new notification-dismiss animation in this pass.

Branch: `handoff/paperclip-source-20261003`. The thread projection now uses a
native modal dialog anchored over the comments side, leaving the job in context.
Saved original is separate from newest-first replies. Its own reply composer
does not replace the regular feed draft; thread drafts survive closing/reopening
the panel while this job window remains open (not persisted across job closure).
Escape, close button and backdrop dismiss only the thread, restore focus, and
do not reflow the main feed. Narrow screens use the available viewport; reduced
motion is respected. Failed sends retain text and the same retry operation ID.

Uses the existing reply RPC and notification/provider pipeline; no schema or
L OPS backend changes. L OPS can adopt the same presentation independently.
Main 1.8.27 is unchanged. Browser regressions cover newest-first ordering,
separate drafts, failed-send retry, feed echo deduplication, backdrop/Escape,
layout/scroll preservation, narrow bounds and reduced motion. Desktop and narrow
renders inspected. Durable thread-composer drafts and rich-text controls in this
new composer remain follow-up work; the regular composer still supports both.

## October 6 — Main 1.8.27 promotion

User approved promoting the tested desktop before building the floating thread
view. Release source is `handoff/paperclip-source-20261003`, incorporating Main's
public update-feed and CI changes; promotion targets `main` and tag `v1.8.27`.
See `docs/release-1.8.27.md` for scope, verification and known limitations.
Installers and the Main channel feed use `ManTreeJoe/linguar-hub-releases`.

Published and locally installed successfully: release tag `v1.8.27` points to
desktop source `d208cdd`. Post-publication verification caught the temporary
GitHub draft URL in the feed; adopted Paperclip's existing publisher fix
`4632d24` as `329802c`, tested its 31 publisher/updater cases, and repaired the
Main feed using the published asset metadata. The public download returned HTTP
200 and matched the uploaded size/SHA-256. This tooling-only follow-up does not
change the installer or move the release tag. Automatic launch after local
installation was blocked; the user can open their normal OneLoss shortcut.

No new schema or L OPS change is introduced by packaging. L OPS still needs to
adopt the shared comment/pin/reply contract documented below. Existing shared
reply/member-notification migrations and the verified-parent endpoint are live;
do not infer a verified app identity from a Trello display name or username.

Next desktop UI: floating in-app thread panel over comments, not a separate
window. Keep the regular feed and thread replies newest-first; show the original
message as context, preserve the main feed's scroll and draft on close. All
replies remain in the regular feed. This new panel is not part of 1.8.27.
Direct-Trello activity ingestion, exact-card membership and verified provider
user mapping remain unfinished; current notifications must not be described as
complete all-activity coverage. Calendar, Reconstruction and L OPS follow-ups
remain separate work.

## October 6 — Approved duplicate identity repair

### Daily Run audit-list header: Open job card

Corrected surface: the user meant the Daily Run audit list, not just the Run
editor. Its selected-job header now offers Open job card through the existing
shell workspace message, retaining the mounted Daily Run. Uses the row's exact
Trello card ID when present; otherwise the existing name resolver. Shared detail
renderer exposes the button only when its host supplies the openJob callback.
`tests/daily_run_open_card.cjs` verifies the real rendered button, exact payload,
and retained selection/detail DOM. No schema/L OPS changes; DEV reload needed.

### Job window visual simplification

Branch `handoff/paperclip-source-20261003`: scope fields now appear after app
location with full-width, multiline copy targets; Client page has quieter
styling; inactive division owner/link controls are available under Manage
division while status remains visible; empty composer is compact and expands
on focus (rich toolbar also reveals on focus). Nonempty drafts remain expanded.
UI design simplification guidance used; no new animation, schema or L OPS work.
Popup layout/interaction, incremental hydration and rich-editor browser tests
pass. Rendered fixture visually checked. Not a Main release; DEV reload needed.

### Loading regression tests aligned with current behavior

Branch `handoff/paperclip-source-20261003`. Resolved the two previously reported
test failures: incremental hydration now checks the shared division tabs (not
the removed comments-only switcher); log preservation explicitly exercises
background protection, successful explicit refresh, and failed explicit refresh.
Also updated the division test's obsolete manual file-check expectation to the
automatic-check UI. No production code changed in this pass.

Seven browser tests passed: `job_workspace_loading_state`,
`job_workspace_incremental`, `job_workspace_slow_placement`,
`comment_initial_cache`, `linked_workspace_preload`, `job_division_tabs`, and
`job_popup_height` (all under `tests/*.cjs`). These use controlled backend
fixtures, not live multi-user performance measurements. No database or L OPS
changes required. Shared thread work stays deferred.

### L OPS TODO — shared comments/threads (deferred by user)

User parked this work on October 6. Do not implement or deploy it until the
user resumes it. Existing local saved-comment loading remains in place.

- [ ] L OPS: review the linked proposal when the user resumes this work.
- [ ] Agree source database and explicit user/job/placement identity mappings.
- [ ] Agree shared comment/thread API, access rules, delivery and notification ownership.
- [ ] Record agreement or counterproposal in this handoff before schema work.
- [ ] OneLoss: implement the accepted backend and desktop Reply/thread UI afterward.
- [ ] L OPS: wire web/mobile to the accepted contract and verify cross-app replies.

Required behavior: all replies appear in the regular feed and can open their
linked thread. This TODO does not authorize deployment or replace coordination.

See [comment-threads-contract-proposal.md](comment-threads-contract-proposal.md).
Branch: `handoff/paperclip-source-20261003`. Live read-only inspection confirms
the optional `crm_pipeline_activity`/`crm_pipeline_cards` tables are absent;
the current posting path can fall back to Trello. Proposed dedicated comments,
conversation identities, provider mappings and transactional delivery must be
agreed with L OPS before schema implementation. No live schema/data changes.
Next owner: L OPS reviews identity/API/access mapping and records agreement or
counterproposal here; OneLoss then implements the accepted contract. All replies
remain in the main feed with a separate thread view. This proposal is not a
working Reply feature, and acknowledgment alone is not contract approval.

### Initial conversation saved-first loading

Branch `handoff/paperclip-source-20261003`: the initially mounted comment pane
now reads the existing account/franchise/card-scoped SQLite projection without
waiting for full workspace hydration or starting another remote fetch. Cached
comments never overwrite a completed live response, a locally edited conversation,
or a closed pane. Verified with initial-cache and linked-preload browser tests
and 11 Python cache tests. No Supabase/schema changes; this is not shared
cross-device comment persistence. That storage contract and full reply threads
remain pending coordination before implementation.

### Daily Run: visible Open job action

Branch `handoff/paperclip-source-20261003`: document-based Daily Run rows now
expose Open job alongside the existing edit controls. Uses the existing shell
job resolver (exact card ID when available, name lookup otherwise); no new links
are created. Right-click/keyboard access stays available and unsaved Run edits
stay mounted. Browser test passes for all three entry points. No schema or
L OPS updates. Calendar/legacy-calendar enhancements remain deferred.

### Loading reliability: independent placement lookup

Branch: `handoff/paperclip-source-20261003`. Job opening previously awaited
both saved facts and board/lane lookup before painting either or starting the
full refresh. A deterministic browser test held only placement unresolved and
reproduced missing saved facts. Placement now updates independently, with the
existing request identity/closed-window guards. Draft and loading status survive
the late update. Slow-placement, linked-preload, and popup-height browser tests
pass. No schema changes or L OPS updates required.

Remaining audit: the older loading-state test expects an unrelated refresh to
add a Job Log row, contrary to current explicit-refresh protection; investigate
its expectation separately rather than relaxing that protection. The broader
incremental test did not complete in this pass. Database-backed comment cache,
threading, and whole-app performance work are not delivered by this slice.

### Workspace close control

Toolbar follow-up: Initial notes now lives in More (same handler and availability),
and the loaded-comment count sits next to the Comments heading. Add update and
Import files remain visible. The browser test checks menu visibility and count
placement. Other visual cleanup ideas remain unimplemented; no backend changes.

Branch: `handoff/paperclip-source-20261003`. The job workspace close button now
anchors to the whole dialog's top-right corner, above comments on desktop,
instead of beside the job title. Comment count spacing is preserved. The
production popup browser test verifies placement, no count overlap, and closing
at three window heights. No database/schema or L OPS changes required. Broader
toolbar/comment visual simplification and database-first comment loading remain
proposals, not implemented by this change.

### First-load editor follow-up

The editor now previews facts from an explicitly resolved Trello card only when
the linked record has no populated settings and no recorded setting/baseline
keys. Existing values and intentionally cleared fields stay database-first.
An unavailable provider fails that initial load instead of opening a successful
blank form. Opening the editor performs no import/write. On the first edited
save, the displayed preview initializes saved settings, while only touched fields
are mirrored to Trello. Subsequent opens retain untouched preview fields.
Child inheritance is unchanged; ambiguous links remain blocked. No bulk backfill,
schema change, or automatic reconciliation is included.

Branch: `handoff/paperclip-source-20261003`. User approved consolidating Gary's
empty internal placeholder into the populated workspace job. A guarded database
transaction rechecked the empty row and its dependencies, preserved both job
snapshots and their links/events in a `job_reconciled` event on the survivor,
moved the original creation event, removed the redundant placeholder/link,
and added the alternate spelling as an alias. No Trello card or description
was changed. Recovery payload stays in the database, not this repository.

The actual editor API now resolves the populated record and returns 20 filled
fields. Both database adapters now reject multiple link owners instead of
choosing the oldest. No schema or L OPS migration is required; L OPS should
likewise treat ambiguous external references as an identity conflict, never
choose a record by age or by which one has more fields. Packaged Main is not
updated by this source change. This does not globally reconcile other duplicates
or remove old rows from every machine's offline cache.

## October 5 — Stability pass, first slice (source only)

Branch: `handoff/paperclip-source-20261003`. No release, schema migration,
profile activation, or live card mutation is included in this slice.

- Job Facts import and save-back now share multiline scope boundaries. Room
  labels belong to Initial/Additional scope; replacing or clearing a scope
  removes its old body without consuming the next scope/section or separator.
- `Initial Docusketch Link` is an explicit read/write alias for `Docusketch
  Link`. Existing label spelling survives edits. If both labels exist, an
  explicitly blank canonical label wins on read; edits update both labels so
  stale alias data cannot reappear. Scope headings with/without `:` are equal.
- APA status menus keep the clicked row's object identity and opening text.
  Identical row names no longer falsely conflict if that exact row survives,
  including reordering. After document replacement, only an originally unique,
  still-unique unchanged name is eligible. Ambiguous duplicates, changed text,
  and changed dates still block; durable row IDs remain future work.
- Verified 74 focused Python tests and three APA browser suites. Read-only
  checks against all 29 live template descriptions preserve no-edit text;
  Gary Newberry's actual Initial scope now imports nonempty. This does not
  prove every template label is mapped or measure general UI latency.

L OPS follow-up: use equivalent multiline/alias/explicit-clear behavior if
parsing Trello descriptions. No database/client migration is required here.
Profile snapshots on existing jobs must remain immutable.

### Remaining work / coordination proposal (not implemented)

1. Shared division-card resolution: ScheduleStore and `confirm_schedule_day`
   currently accept only `trello_card`, excluding `trello_card_contents` even
   when the pin is valid. Update the reader and server validation together,
   retaining office access, exact card identity, unambiguous distinct job
   ownership, active WIP/Contents limits and Recon exclusion. Multiple link
   types for the same job/card must not count as multiple owners. Coordinate
   the RPC change with L OPS before a migration; do not loosen validation in
   the UI alone or silently choose between multiple eligible cards.
2. Profile activation review: the 29 bundled source checklist name/item sets
   match live Trello, but the shared IE library currently has 13 inactive
   baseline profiles; Gary has no applied snapshot. Review/import the intended
   starter profiles through admin controls rather than enabling old generic
   profiles or mass-applying requirements. State Farm remains its own variant;
   conditional services must not become universal obligations.
3. Cross-computer acceptance: read/edit/save/refresh with Nathan and Sam,
   explicit deletions, division pins and conflicts; no such two-user live
   acceptance is claimed by the synthetic tests above.
4. Measure perceived slowness separately with timings around Trello fetches,
   database reads and UI refresh. Do not infer a performance fix from these
   correctness regressions passing.

## October 5 — Confirm day implemented in DEV

Branch: `handoff/paperclip-source-20261003`. Applied migration
`20261005215806_schedule_day_confirmation.sql` to OneLoss project
`oqwwapqnzzhefqxobadl`; L OPS database untouched. No confirmation or card move
was executed against customer data during testing. Active visits remain 133;
the new confirmation table and markers were empty after deployment.

Schedule → select day → Confirm day opens a complete-day review (independent of
calendar search/filters). Each entry shows linked card, current lane, and proposed
lane. Correct the dropdown or choose Keep current placement. Multiple eligible
cards default to no selection. Only existing active WIP/Contents card lanes are
offered, never estimating masters, archived cards or Recon. No copy is created.
Monitor as a side activity keeps placement; Monitor as the Run group may suggest
the Monitor lane. Suggestions require exact lane names; duplicates stay put.
Today's read-only check found 32 scheduled entries, 11 with eligible cards; the
remaining entries are explicitly kept in place rather than guessed or omitted.

Shared contract for L OPS:

- `confirm_schedule_day(p_command jsonb)` accepts version 1, department, ISO date,
  stable operation UUID, and the complete day's `entries` (`id`, `revision`,
  `action: keep|move`). Moves additionally specify exact `card_id`, `board_id`,
  `from_list`, placement `version` and target `list_id` on that same board.
- Server checks office/job access, exact unambiguous job links, board/origin
  permissions, current card state and revisions. It shares the draft save's
  office transaction lock. A missing/new/changed visit or stale move fails the
  whole transaction; no partial confirmation or partial board movement remains.
- Immutable office-RLS `schedule_confirmations` stores actor, timestamp, command,
  reviewed visit snapshots and result. Provider card descriptions are not copied
  into receipts. Identical operation retries return the original result.
- `schedule_visits.confirmed_revision == revision` means currently confirmed;
  `confirmed_at` is server time. Ordinary draft edits advance revision, making
  them drafts again. Confirmation does NOT mean work completed.
- Moves use `app_placement_change` and its existing durable Trello sync state.
  Desktop wakes the existing worker after the successful transaction. Confirmation
  means saved in OneLoss, not proof that Trello delivery has finished. No comments
  or Job Log posts occur. No automatic lane-mapping administration is added.

Verification: 61 focused Python tests, isolated PostgreSQL tests using the real
placement lifecycle (rollback, retries, stale review, RLS, disallowed board/lane,
link checks and re-draft), plus live/sample/weekly browser suites. New browser
coverage includes selected date, ambiguous/missing cards, corrected lane, safe
retry, cancellation and narrow layout. Desktop/narrow renders inspected. Supabase
security advisors report no findings on these new objects; previously documented
admin function/password-protection findings remain outside this change.

Still next: complete/cancel/reschedule with retained original and replacement
links; separate idempotent Post to comments/Job Log; explicit Pull board into
draft; Legacy print/PDF without Word; Nathan/Sam two-PC acceptance test. None of
these is implied complete by the new Confirm day button. Main installer unchanged.

### Original approved coordination proposal

Branch: `handoff/paperclip-source-20261003`. Nathan approved a review of each
job's current and proposed lane, with corrections before Confirm day. Preserve
the calendar layout; posting comments is a separate later action. This slice
confirms scheduled active visits for the selected day, not all waiting queues.

Planned additive contract: office-scoped immutable `schedule_confirmations`
receipts, plus `confirmed_revision`/`confirmed_at` on visits. One transaction
checks the complete reviewed day's visit revisions and exact saved job/card
links, applies reviewed moves through the existing placement lifecycle/outbox,
and records the confirmation. Stable operation IDs make retries safe. Editing
a confirmed visit makes that revision a draft again; board changes never edit
the schedule. Concurrent changes require a fresh review, never partial moves.

Initial lane choices stay within the selected linked WIP or Contents card's
current board. An estimating master must not move instead of its WIP copy.
Ambiguous cards require explicit selection; unlinked/unsupported cards may be
confirmed with Keep placement, visibly identified. Recon boards/lanes are not
eligible. Extra Monitor activity does not propose a move to Monitor; the Run
group, not an incidental activity, controls that suggestion. Cancellation and
replacement linking remain a separate follow-up, with no placement change.

L OPS must consume confirmation revisions separately from completion and must
not treat a confirmation as permission to post comments. No live card moves
will be used for development tests. This proposal is pushed before schema work.

## October 5 — explicit Job Info field clearing

Reproduced carrier/claim returning after add → clear → reopen even when Trello
successfully cleared its description. Both database adapters' partial-upsert
rules skipped empty text, leaving stale columns which beat the blank settings.
Added optional `clear_fields` to SQLite/Supabase `upsert_job`; Job Info persistence
passes only explicitly empty mapped columns. Default import semantics still
preserve existing values on blank input. Offline calls retain the argument through
the existing kwargs/outbox path. No schema change and no live customer repair.
Tests cover reopening, refresh with successful/failed Trello pushes, remote PATCH
shape and ordinary blank imports. L OPS must likewise distinguish explicit clears
from omitted fields; do not globally change imports to overwrite with blanks.

## October 5 — follow-up drag/click protection

The user still saw an editor after dropping. A browser regression reproduced a
delayed compatibility click opening the live editor after the old 500 ms guard
expired. The pointer helper now suppresses post-drag pointer clicks until a fresh
pointerdown (keyboard activation remains available), including canceled drags and
calendar rerenders. Native fallback dragging also enables suppression and passes
queue/group information. Sample preview now moves directly too; it no longer
deliberately opens the editor on drop. Live/sample/renderer browser tests pass,
including delayed click suppression and ordinary click-to-edit. No backend changes.

## October 5 — historical Run backfill deployed; DEV viewer implemented

Nathan approved read-only Calendar/Legacy history with correctable job links.
Branch: `handoff/paperclip-source-20261003`. Migration
`20261005171816_run_document_history.sql` applied to OneLoss project
`oqwwapqnzzhefqxobadl`; no L OPS database changes. Imported 81 source documents,
July 1–October 3, 2026 (searched through October 4; no document for that day),
5,290 source lines, 3,303 automatically linked lines, 57 struck lines. Unlinked
lines include headers/notes as well as unmatched jobs. Active visits stayed at
133 before/after; original files are read-only and were not uploaded or rewritten.

API contract for L OPS adoption:

- `run_history_documents`: immutable department/date/digest/filename and parsed
  snapshot (paragraphs/tables/source review flags). Same department/date/digest
  deduplicates; different file revisions remain separate.
- `run_history_rows`: immutable source index, text, section and strike flag;
  only `job_id`/`revision` may change through the link RPC.
- `run_history_link_changes`: append-only actor/old/new job/revision audit.
- `import_run_history(p_department,p_document)` atomically imports one document;
  `link_run_history(p_row,p_job,p_revision)` corrects a link, checks office/job
  access and revision. No direct table writes granted. Read access uses office RLS.
- These records are observations of a dated Run, NOT active visits or evidence
  of completion. Do not feed old TBS/pending/hold rows into current waiting queues.

Desktop: Schedule → History → select Run (3 Days/Week/Month calendar or Legacy
selector) → original sectioned text, with Correct link beside source lines.
History cannot be dragged or edited. Dates display MM/DD/YY. This is a sectioned
text rendering, not a byte-identical Word layout. Search on the history calendar
finds document names; link search finds existing jobs. Source snapshots may
contain table/tracked-change review flags and are retained for future richer rendering.

Verification: 53 Python tests; PGlite revision/retry/RLS/atomic rollback and source
immutability tests; browser tests include waiting/struck lines, link correction,
non-draggable archive and unchanged live save calls. Security advisors returned
no findings on these new objects; existing unrelated auth/admin findings remain.
Backfill CLI: `tools/import_run_history.py --start 2026-07-01 --end 2026-10-04`
previews; `--apply` performs office-bound authenticated imports, safe to repeat.

### Original coordination proposal (approved)

Nathan requested several months of Run history. Source library located at the
configured EMS Daily Run OneDrive directory; proposed initial window July 1 through
October 4, 2026. Do not use active schedule bulk import for historical documents.
It would turn historical waiting rows into current work and cannot faithfully
represent repeated daily observations of the same job.

Shared-backend coordination proposal: separate office-scoped historical Run documents
and their dated source rows from active visits. Preserve all source sections,
raw text, source digest, original row identity, cancellation markings and reviewed
job links. Scheduled work is not evidence of completion. Repeated pending/TBS/hold
rows belong to each historical day, not today's waiting queue. Exact file retries
must deduplicate; changed versions must be retained for review, not overwrite history.
Calendar/Legacy history should be read-only initially, with unresolved links visible.
L OPS should consume this history separately from active schedule visits. This
proposal was pushed before implementation and approved by Nathan; deployment
details above supersede its earlier proposed status.

## October 5 — live schedule drop fix

Branch: `handoff/paperclip-source-20261003`. Live calendar and Legacy drops now
save the move directly through the existing revision-checked schedule API instead
of opening the preview editor. Ordinary clicks still edit. Saving has status
feedback; failures refresh the saved placement and display an error. No schema,
Trello, Word, or L OPS changes required. Sample-only preview's original edit-on-drop
flow was removed in the follow-up above. Browser regression tests cover direct drop, click editing, failed move, and
Legacy movement; calendar renderer and sample-preview tests also pass.

## October 5 — bulk import correction implemented in DEV

Nathan rejected mandatory per-line linking and approved importing the whole Run,
auto-linking strong job/Trello matches, retaining unmatched rows on the calendar,
and correcting links afterward. Planned shared contract change: permit a null
schedule visit job_id for an imported/unlinked entry, retain an explicit display
title and source identity, and provide an authorized revision-checked save/link
operation plus an atomic bulk import. Office membership remains mandatory even
without a job link. Link changes must validate both the old and new job's office.
Existing visits must not be silently overwritten or duplicated. No fake jobs,
Trello card creation or original-document writes. L OPS remains untouched; its
future consumer must support nullable job links and display needs-link states.
Branch: handoff/paperclip-source-20261003. Deployment and tests follow below once
verified; this section publishes the schema decision before implementation.

Implementation update: `20261005154121_schedule_bulk_import.sql` applied to
OneLoss/Linguar Hub. Added nullable job links, entry_title/source_key, v2
`save_schedule_entry` and atomic `import_schedule_entries`. Existing v1 save
remains available for linked visits. Direct writes stay denied; RLS allows only
office-authorized unlinked entries or authorized linked jobs. Link changes and
edits use revisions and append-only receipts. Source identity is immutable.

The .docx dialog now has one **Import all** action. Unique normalized full-name
and street-address evidence auto-matches existing jobs; ambiguous/conflicting
evidence stays unlinked. Existing saved `job_links` Trello pins follow the job—
this does not create/repin external cards or fuzzy-match directly against Trello.
Unmatched entries persist and show Needs link in calendar and Legacy. The visit
editor can search/change/remove its job link and edit an unlinked entry title.
Retries of the same source reuse rows, preserving subsequent edits. An already
active matched job is not overwritten; its new source line is retained unlinked
for reconciliation. Dates absent from Upcoming remain TBS with a review note;
unsupported sections are retained in On Hold with the original section in notes.
Crossed-out lines are counted/skipped. Tables remain explicit manual-review text.
Raw text is retained in notes; crew is not guessed from ambiguous abbreviations.

Validation: 51 Python tests passed; calendar/Legacy and live browser suites passed.
Isolated PostgreSQL tests cover unlinked saves, retries, duplicate handling,
link/unlink, stale edits, forbidden cross-office links and atomic batch rollback.
Signed-in read-only checks found 510 authorized jobs and confirmed saved Trello
links could be read. Live schedule load succeeded after migration; no real Run
entries were inserted by tests. Database changes and documentation are shared;
L OPS consumer adaptation remains future work. This is DEV, not an app release.

## October 5 — Schedule document import

Added **Import document** beside the live Schedule search. A native file picker
reads a .docx Run into a review dialog, with an explicit MM/DD/YY Run date.
Each recognized line can be linked to a real job and opened in the existing visit
editor. Save draft uses the same revision/idempotency/RLS path as manual visits.
This is reviewed line-by-line import, not unattended bulk matching.

Work/Monitor use the reviewed Run date. Upcoming requires its date to be entered;
TBS, Pending and Hold remain undated. Original line text and filename are retained
in notes. Crew and activities require review; only an explicit Monitor section
proposes Monitor. Crossed-out rows and unsupported sections such as Marketing are
flagged/skipped, not silently converted. Tables are displayed for manual review;
tracked changes/text boxes warn that original-document review is needed.

No Word edits, Trello posts, job-fact changes or database migrations. Existing
active visits cannot be overwritten through import. Stable source-row UUIDs plus
the database's one-active-visit constraint prevent blind duplicate creation.
Changed documents need fresh review. The source is read from one bounded byte
snapshot; compressed and expanded document sizes are limited. UI-design guidance
kept the existing dialog/editor workflow. Parser/picker tests verify unchanged
source bytes, repeatable IDs, waiting groups and cancellation. Browser tests cover
file review, skip state, linking, editor handoff, saving and Saved feedback.
Supported input in this first version: Word .docx, not legacy .doc or PDF.

## October 5 — approved OneLoss-owned schedule drafts

This section supersedes the readiness/coordination blockers below. Nathan approved
OneLoss as owner and explicitly allowed L OPS to be rewired later because nobody
uses it yet. L OPS and its database are untouched. Branch:
`handoff/paperclip-source-20261003`.

Implementation: `schedule_store.py`, dedicated `schedule_load/search/save` desktop
methods, and `schedule_live.js` wire the existing calendar/Legacy editor to real
job UUIDs. DEV uses `calendar_preview.html?live=1`; without that flag the original
sample UI remains available for isolated tests. Installed Main is unchanged.

Database contract: additive migration `20261005150008_oneloss_schedule_drafts.sql`
creates `schedule_visits`, append-only `schedule_changes`, and
`save_schedule_draft(p_command jsonb)`. Signed-in office membership plus the job's
department are checked server-side. Direct client writes are denied. Exactly one
active visit per job; revision conflicts reject stale edits. Identical retries use
the same operation UUID. Optional `before_id` applies ordering atomically with the
save; clients cannot supply numeric positions. Job facts are never updated here.

L OPS integration later: use this contract or an agreed adapter, preserve canonical
OneLoss job/visit IDs, resolve account/office mappings, and use user authorization.
Do not mirror these drafts into test-only daily-run rows. Keep Supabase Storage
and CompanyCam for files; this change does not move files or change media APIs.

Scope: persistent active drafts, all waiting groups, per-activity crews, calendar
and Legacy drag/reorder, real-job search, read-only job facts. Confirmation,
Trello/board movement, comment posting, printable Run output, history UI and
cancellation/rescheduling controls remain follow-up work. No Word writes. The
calendar starts empty until real visits are explicitly added; there is no automatic
Run import or synthetic data inserted into the live database.

Validation: isolated PostgreSQL tests cover saves, revisions, retries, duplicate
prevention, invalid payloads, history, cross-office reads/writes and direct-write
denials. Python tests cover payload validation and bound-account transport.
Browser tests cover existing layouts/dragging and live-mode save failure/retry.
Deployment: applied successfully to OneLoss/Linguar Hub (`oqwwapqnzzhefqxobadl`)
on October 5. Verified both tables have RLS enabled and authenticated users have
SELECT but no direct INSERT/UPDATE/DELETE grants. The signed-in desktop loaded
the empty live schedule and searched authorized jobs successfully. No real visits
were created by tests. DEV launched the live route with three day columns and
loaded theme assets. Source publication is not an installed-app release.

Security advisor reported no schedule findings. Separate existing findings remain:
[admin security-definer RPC review](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)
and [leaked-password protection disabled](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
Those were not changed as part of scheduling.

### Same-day addition: near-real-time multiuser calendar

Nathan requested immediate cross-user updates. Additive migration
`20261005151551_oneloss_schedule_realtime.sql` enables `schedule_visits` in the
existing `supabase_realtime` publication. Applied successfully. Two independent
authenticated subscriptions reached PostgreSQL-subscription-ready status against
the live service without modifying records. The browser uses the documented
Phoenix v1 protocol with the user's short-lived JWT, table RLS and office filter;
no service credentials. Credentials refresh every minute, heartbeats detect dead
connections, and reconnects trigger a full read to recover missed events.

Events trigger a debounced authorized reload, not direct trust in event payloads.
There is a 15-second backup refresh and visibility/online catch-up. Healthy
connections should update shortly after a committed save; this is not an SLA or
simultaneous field-by-field co-editing. Unsaved editor content is preserved and
stale saves remain rejected. Incoming updates wait during dragging. A Live /
Reconnecting / Offline indicator shows connection state. Browser tests simulate
remote edits while an editor is open and verify local text is retained. A real
two-person save/observe test remains for Nathan and Sam in DEV.

## October 5 — live schedule readiness check (read-only)

Update: Nathan approved OneLoss/Linguar Hub as the canonical schedule backend.
`schedule_records.py` now defines a validation-only draft save envelope, covered
by 32 passing tests in `tests/test_schedule_records.py`. It performs no database
or external writes, is not wired to the sample UI, and is not a security boundary.
No migration has been created or applied. Server-side enforcement and the
adapter/UI connection remain pending cross-app contract review and implementation.
Reordering requires a separate atomic server operation; client position values
are deliberately not accepted by the visit save payload.
Implementation starts with a draft persistence contract; no automatic L OPS
writes, database merging, Word writes, board movement or comment posting.
Existing OneLoss job UUIDs and department access are authoritative. L OPS must
consume the agreed contract with verified identity mappings rather than write
its test-only daily-run rows as production data.

Draft v1 contract for cross-app review: persistent visit UUID + job UUID,
department, lifecycle (active/completed/canceled), queue (scheduled/tbs/pending/hold),
Run group, optional date/arrival label, activities with independent people,
equipment/access/notes, ordering, revision and actor-attributed change history.
Exactly one active visit per job; canceled/completed records remain history.
Save uses expected revision and a retry identity; requests never write job facts.
Authorization, allowed groups and payload limits must be enforced server-side.
Confirm day and posting require separate idempotent operations, not side effects
of a draft save. Deployment remains pending migration tests and cross-app review.

Nathan requested connecting the agreed calendar/Legacy layout to real persistent
schedule data. No layout redesign, Word write-back or Reconstruction expansion.

Verified against public information_schema metadata: OneLoss/Linguar Hub has no
public tables whose names contain schedule, visit or run. The L OPS database has
`workspace_job_visits` and `workspace_daily_run_rows`. The latter enforces
`CHECK (is_test)` and must not be repurposed for real scheduling by bypassing it.
Existing visits require an HH:MM time and use one crew string; they do not directly
represent the agreed optional arrival, undated waiting queues, and per-activity
assignments. The current L OPS main source at
`1fd31841bc2bf05320776536218482fd207058af` contains the older visit migration and
actions, but its migration tree lacks the live daily-run table and the additional
visit source-log/workstream fields. Source/deployment parity needs reconciliation.

Decision required before writing live data: which backend owns the canonical
schedule, and how the existing OneLoss job/account/workspace identities map to it.
No schema or data was changed during this inspection. Do not solve missing fields
by inventing arrival times, flattening independent crews, storing production work
as test rows, or connecting the new calendar to Word persistence.

Recommended decision to Nathan: start with the current OneLoss database as the
schedule owner for existing OneLoss jobs/users, publish the versioned contract,
and coordinate L OPS consumption/mapping before cross-app writes. This is a
proposal, not permission to create a competing schema or an accepted migration.
If L OPS instead owns persistence, require its current source/migration handoff
and explicit identity/auth mapping before implementation. Await Nathan's backend
direction and the previously required cross-app contract agreement.

## Code handoff — October 3

The team source snapshot is on `handoff/paperclip-source-20261003`, including the
previously unpublished desktop, storage, Trello sync and migration source plus
tests. Use that branch for Paperclip; see the publication update in
[paperclip-handoff.md](paperclip-handoff.md). This publishes existing WIP, not a
new shared-schema decision or live deployment. L OPS should inspect identity and
contract compatibility before using any SQL or enabling writes. Targeted Python:
60 passed; CompanyCam and Run activity Node checks passed. Storage SQL test blocked
by missing local PGlite dependency. No production release.

## Start here — Paperclip / new-agent onboarding

Read [paperclip-handoff.md](paperclip-handoff.md) for the mission, latest verified
DEV status, product decisions, ownership, next-task queue, and unpublished local
work inventory. Latest feature checkpoint: `3413dd0`, branch `main-lops-style-pivot`.
The calendar and Legacy drag UI exist as sample-only DEV functionality; digital
persistence, Confirm/Post and production print/PDF are still unfinished. Earlier
dated status notes below are historical. No release or schema deployment is
authorized by this documentation handoff.

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
### 2026-10-03 — Legacy Run drag-and-drop

Branch `main-lops-style-pivot`: Legacy sample Run rows now share calendar pointer feedback and support drops within/across Run sections, including empty groups. Destination queue/group/date populate the review editor; Upcoming proposes the following day for review. Apply retains identity/details and inserts at the chosen position; Cancel leaves the original row untouched. Browser tests verify Legacy Monitor-to-Work placement, cancellation and duplicate prevention alongside existing calendar regressions. Render inspected; UI-design guidance preserved the paper-style layout. No live writes, schema changes or L OPS database updates.

### 2026-10-02 — Visible calendar drag feedback

Branch `main-lops-style-pivot`: DEV sample cards now use pointer-following ghosts, insertion placeholders, destination highlights and a short landing/return animation, referencing the existing job-board interaction. Escape cancels; reduced-motion skips the animation. Apply/Cancel review still owns the actual sample move. Added browser checks for visible ghost/placeholder and Escape cleanup; full preview and calendar regression tests pass. No schema or live-write changes; no L OPS update required. UI-design guidance kept existing controls and click-to-edit access.

### 2026-10-02 — All calendar cards and job search

Branch: `main-lops-style-pivot`. Extended DEV calendar dragging to scheduled cards as well as waiting cards. Drops review the existing visit on the target day, preserving its identity and details. Added a compact top job-name/address search with existing-visit and not-yet-scheduled sample results. Selecting an existing visit edits it instead of inserting a duplicate. Browser tests cover scheduled moves, new sample additions, repeated selection, empty results, and existing calendar regressions. Render inspected at desktop size.

UI-design guidance kept the existing compact controls and click-to-edit fallback. This remains in-memory sample functionality only; no shared schema or live writes changed. L OPS has no required database changes from this handoff.

### 2026-10-02 — Waiting work drag-to-schedule DEV handoff

Branch: `main-lops-style-pivot`. The sample calendar now accepts waiting-work drops onto three-day/week columns and month cells. A drop opens the visit editor with Scheduled and the target date selected; Apply replaces the same sample record, while Cancel leaves Waiting unchanged. Job details and activity assignments are retained. Click-to-edit remains available without dragging. Browser tests cover cancel/apply and duplicate prevention; the existing calendar suite also passes.

No database/schema, Trello, Word, or live scheduling writes were added. L OPS does not need a schema update for this UI-only change. Shared persistence remains subject to a coordinated contract before implementation.

This is a documentation snapshot. Some new-platform code is still local/uncommitted; the mobile repo has no remote yet. Verify the actual source revision and migration state before assuming a described feature is available from GitHub or deployed. No production release is implied by these notes.

## 2026-10-06 — Shared pins and threaded replies resumed

Activity notification increment (user-approved default): card members should
receive all activity. Migration `20261006231958` adds transactional notifications
for native replies (members + native thread authors) and placement events.
Confirmed desktop Trello card edits now use the existing durable member queue;
comment/move paths already owned by another producer are excluded to avoid
double delivery. Recipient access, mutes and self-exclusion remain enforced.
No production event backfill is performed. The existing member model is job-level,
so exact card-specific membership and ingestion of changes made directly in
Trello are still open work, not claimed complete by this increment. Trello-only
thread authors cannot be mapped to OneLoss accounts by guessing usernames.

Trello reply payload is now only the reply body and deduplicated @mentions.
Thread IDs and operation IDs remain internal. Legacy marker reconciliation stays
available for previously posted replies; new uncertain clean-text deliveries
must not auto-repost or guess an action match. A confirmed Trello action ID is
still saved as the provider link. Existing posted comments are not rewritten.

Follow-up: authenticated `comment-parent` Edge Function verifies/imports recent
Trello parents on demand, removing the comment-snapshot delay. No table changes.
Live verification also revealed two PL/pgSQL alias/variable collisions in the
thread read/reconciliation branch. Migrations `20261006231105` and
`20261006231154` rename those internal aliases; public contract and permissions
are unchanged. Authenticated thread reads are now included in rollback tests.
The desktop prepares author/original-mention reply-all tags (deduplicated, no
self-tag) and uses that body in both OneLoss and Trello. L OPS should adopt this
same preparation contract; never upload client-supplied original-comment facts
as verified provider data. Existing authorization, thread IDs and outbox claims
are unchanged. Six Python tests and the gateway authorization/import tests pass.

Owner: OneLoss/shared backend. Branch: `handoff/paperclip-source-20261003`.
User approved implementing without waiting for L OPS; Main remains unchanged.
See `docs/comment-threads-contract-proposal.md` for the incremental RPC contract,
delivery limitations and L OPS adoption requirements. Schema is additive to
OneLoss project `oqwwapqnzzhefqxobadl`; do not assume L OPS user/job UUIDs match.
L OPS TODO: adopt shared pins, immutable reply links, paginated thread records,
normal-feed reply visibility and provider echo deduplication. Do not implement
local-only pins or infer threads from @mentions. Supabase Storage/CompanyCam
file ownership is unchanged. Schedule and Recon work remain deferred.

Deployment: additive migration applied to the shared backend; remote migration
version `20261006224700` (local CLI-generated source `20261006224224`). No Main
binary release. SQL rollback tests passed for actual authenticated-role RLS,
anonymous/unrelated-user denial, forged parents, retry identity, exclusive
delivery claims and deferred foreign keys. Browser tests passed for pins,
ordering, drafts, failed-send retry, thread access and provider echo deduplication.
Three Python delivery-boundary tests passed; existing rich-editor, initial-cache,
incremental workspace and popup-height tests also passed.

Security advisor reported no findings on the new table/RPC. Existing unrelated
warnings remain: [admin SECURITY DEFINER endpoints](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)
and [disabled leaked-password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
No auth settings were changed in this task. Still needs a two-device user test
and real Trello reply test; automated tests do not post production comments.
# Timing UI and all-job movement retention — 2026-10-07

## Retention contract: approved forward requirement, implementation underway

Deployment status: migration `20261007210858_retained_card_observations` applied
to Linguar Hub `oqwwapqnzzhefqxobadl` on 2026-10-07. Baseline: 3,943 saved card
placements across six boards. After deployment the existing server worker
retained 21 new changes and completed a poll with no error. Transactional
service-role tests passed: no-op polls do not duplicate, moves/details/removal
retain before/after records, clients cannot read, service role cannot delete.
No Main desktop release. No L OPS database changes.

Security advisor: intentional [RLS with no client policy](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)
for this service-only table; anonymous/authenticated grants are revoked. Existing
unrelated [admin definer warnings](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)
and [password protection warning](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)
remain unchanged. Append-only snapshots increase storage: add monitoring and
scope-safe read/projection before opening history to clients. These observations
do not yet feed Analytics. Exact event ingestion remains a required follow-up.

DEV timing UI: shared `web_shared/lane_timing_summary.js` renders Snapshot cycles,
waiting-lane totals (unknown intervals explicitly partial), every recorded Logs
arrival, and current Logs age. Analytics card timing and job Overview reuse this
renderer and `lane_timing_metrics.py`. Estimator timing remains Logs-entry based.
Other Analytics pages still require shared history integration; do not claim
their summary charts or weekly records contain these new metrics yet.

OneLoss owns retention across every configured board and all Analytics consumers.
First additive backend slice: service-only `hub_card_observations` stores changes
observed in the existing server mirror: card payload, details, comments and
presence, with board/card IDs, captured scope and observation time. No destructive
foreign-key cascade, no client writes, no use of observation time as move time.
Existing cached records will be baselined; later changes retain before/after
values. This does NOT capture intermediate changes between polls or prove exact
move times. Provider action ingestion/backfill and confirmed OneLoss move events
remain necessary. No public L OPS read API until historical scope guards exist.

L OPS: do not add a separate timing store. All Analytics pages (Weekly Review,
Jobs to Review, Corrections, Billing/AR, Trends, Data Quality and Operations),
plus job cards, must ultimately consume one verified movement projection. Current
legacy views are NOT yet rewired. Store observation time separately from event
time; show missing coverage, not an inferred age or zero. Recon data retention
is included, but Recon workflow/analytics design remains deferred.

Branch: `handoff/paperclip-source-20261003`. OneLoss owns shared-backend work.
Timing detail now separates current duration, estimator cycles, movement timeline
and lane totals using the shared theme. UI only; Main and database unchanged.
Next integration decision: [persistent movement ledger](movement-ledger-handoff.md).
This records the all-job/Logs requirement for L OPS coordination before schema
implementation. Existing on-demand Trello history is not guaranteed full history.

Job-card timing follow-up: Overview now includes a compact current-lane duration
and expandable movement/estimator history. It reads independently of workspace
loading via `job_card_timing`, checks scoped saved card membership and rejects
results after a workspace switch. Background card updates preserve the timing
section; failed timing refresh keeps prior values with an error. No database
changes or durable all-job tracking are introduced. L OPS can mirror this UI
after the shared movement-ledger contract is implemented; do not infer entry
times from last activity. Tests cover scoping, workspace changes, incremental
card rendering, history expansion and narrow layout. Main remains unchanged.
