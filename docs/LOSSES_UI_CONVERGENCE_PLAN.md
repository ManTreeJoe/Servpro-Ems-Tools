# Losses UI convergence plan

**Status:** Implementation authorized September 11, 2026; foundation in progress

**Target:** Linguar Hub Windows office software first

**Design reference:** L OPS
**Dependency:** Canonical shared database identity and access contract

## Product decision

Linguar Hub and L OPS will share the same core Losses experience and data contract:

- **Board view** moves a Division through its workflow stages.
- **List view** supports fast search, sorting, scanning, closed work, and management.
- **Loss workspace** contains the complete record after a row or card is opened.

Cards are summaries and navigation objects, not miniature databases. The Windows
application may expose additional authorized office actions, but those actions
must remain contextual to the Loss or inside an **Office tools** area. They must
not alter the shared navigation or create a second job model.

## Shared visual contract

Use the existing L OPS visual language in both clients:

- dark forest navigation rail;
- light gray-green workspace and white working panels;
- restrained forest, gold, blue, and orange states;
- Segoe UI Variable/Aptos for operational copy;
- Georgia only for selected page and customer headings;
- quiet borders, shallow shadows, compact controls, and minimal motion;
- the same Phosphor icon mapping, tabs, dialogs, card anatomy, and interaction
  states;
- light and dark modes derived from shared design tokens.

Reference tokens:

```text
Ink             #152821
Muted text      #68766F
Workspace       #F5F7F4
Panel           #FFFFFF
Border          #DFE5E0
Primary forest  #164F3D
Soft mint       #DBEAE4
Attention       #D96E3B
Due soon        #BF8A29
Informational   #3D668F
```

Do not add arbitrary Trello colors, gradients on ordinary cards, or unrelated
bright status colors.

## Signature element: Loss spine

Each Loss card has a narrow left **Loss spine**, resembling the edge of a
restoration job folder.

- One segment represents each active Division: EMS, Contents, and Reconstruction.
- The current Division is emphasized on a Division board.
- Orange is used only for a genuine attention condition.
- Hover and keyboard focus explain the active Divisions and attention reasons.
- The same information remains understandable without color.

## Navigation and page structure

```text
L OPS-style navigation
├── Operations inbox
├── Losses
│   ├── All losses
│   ├── EMS
│   ├── Contents
│   ├── Reconstruction
│   └── Closed
├── Schedule
├── Billing & AR
├── Analytics
└── Admin / Settings
```

The Losses command area contains one search field, essential filters, sort, and
the List/Board toggle. Windows-only tools do not become additional primary
navigation destinations.

## View behavior

### All Losses list

Render one row per master Loss:

```text
Loss | Customer/property | Divisions | Current position | Next action | Owner | Alerts
```

- A multi-Division Loss appears once.
- Current position summarizes the most urgent active Division while preserving
  each Division's individual stage.
- Opening a row opens the same Loss workspace used by every other entry point.
- Closed and archived Losses remain searchable and auditable.

### Division boards

- EMS, Contents, and Reconstruction each use their approved stages.
- A Loss appears once on every applicable Division board.
- Moving a card changes only that Division's stage.
- Protected milestones enforce Requirements; drag/drop cannot bypass them.
- Accessible Move Back and Move Forward actions must work before drag/drop is
  considered complete.
- Cards never shrink to fit a lane; lanes own vertical scrolling and the board
  owns horizontal scrolling.

## Card contract

Required visible information, in priority order:

1. Loss number.
2. Customer/insured.
3. Property address and unit.
4. Current Division badge.
5. Next action and owner.
6. Due state: overdue, today, due soon, or no due date.
7. Up to two actionable exception chips, followed by `+N` when needed.
8. Requirement/checklist progress.

Optional compact indicators include Job Log count, attachment count, CompanyCam
state, XA assignment state, and quick-link availability.

Visual attention priority is:

1. safety, customer, or production blocker;
2. overdue next action;
3. missing mandatory paperwork;
4. estimate or approval blockage;
5. storage renewal or billing deadline;
6. external-system verification issue;
7. informational status.

An incomplete checklist by itself does not make a card orange.

## Loss workspace

Opening a row or card displays a wide right-side workspace without losing the
board's scroll position, filters, or selected Division.

The persistent header contains Loss number, customer, property/unit,
carrier/payer, claims, active Divisions, primary attention state, and an obvious
close control.

The Quick Links bar may include CompanyCam, Xactimate/XactAnalysis, WorkCenter,
email/thread, Maps, folder, Trello, and approved custom links. Authorized users
may manage custom links. Opening a link never runs a hidden action.

Workspace tabs:

1. **Overview** — stages, next actions, blockers, readiness, and important dates.
2. **Job Log** — shared dated activity with Division filters.
3. **People** — customers, tenants, adjusters, staff, crews, and subcontractors.
4. **Requirements** — forms, signatures, approvals, and checklists.
5. **Files & Integrations** — documents and provider synchronization health.
6. **Schedule** — visits, arrival windows, crews, equipment, and unscheduled work.
7. **Estimating & Billing** — estimate and billing milestones with permission
   enforcement.
8. **Contents Storage** — conditional Contents inventory, POD/vault, renewal, and
   billing information.

Financial tabs, counts, badges, alerts, API responses, and cached data must all
obey the same authorization rules.

## Windows-only extension layer

Linguar Hub may add these capabilities without adding them to L OPS:

- Trello refresh, card selection/repinning, imports, comment search, and repair;
- CompanyCam project provisioning, import, repinning, and administrative repair;
- XA assignment import/export and temporary email intake;
- OD/job-folder open, repin, copy path, download import, and file dialogs;
- bulk office maintenance, APA, backup, updater, and system diagnostics;
- native context menus, clipboard commands, printing, and offline queue controls.

The UI exposes them through contextual menus, the relevant workspace tab, or a
permission-controlled Office tools area. The API and database enforce the
permission; hidden controls alone are not security.

## Search and filters

Search matches Loss number, customer, property/unit, claim number, XA ID, phone,
email, and external job identifiers across active, closed, archived, and imported
records.

Essential filters include Division, stage, attention, paperwork, owner/team,
estimator, field lead, carrier/payer, Job Profile, integration state, billing
readiness, Contents storage due, and date range. Saved views follow only after
the base query behavior is proven.

## Interaction and state rules

- Single click opens the Loss workspace; Enter and Space provide equivalent
  keyboard behavior.
- Protected transitions show unmet Requirements before offering a permitted,
  reasoned, audited override.
- Low-risk edits may be optimistic; a failed save restores the prior committed
  value and clearly identifies the failure.
- Loading skeletons preserve card dimensions.
- Partial provider failures remain local to the affected record or section.
- Offline mode identifies cached data and blocks unsafe bulk/conflicting actions.
- Production never substitutes demo records.
- Windows scaling must work at 100%, 125%, 150%, and 200%.

## Delivery slices

### Slice 0 — shared foundation and baseline

- Reconcile the two Supabase schemas and migration histories.
- Approve the canonical Organization → Location → Loss → Division identifiers.
- Capture current L OPS and Linguar screenshots and behavior.
- Run existing builds/tests without UI changes.

### Slice 1 — shared view model

- Define one typed view model for list rows, Division cards, and workspace header.
- Map existing Linguar/Trello information without making Trello the owner.
- Test a single Loss containing EMS, Contents, and Reconstruction.

### Slice 2 — static shared card

- Build the reusable, non-draggable card and Loss spine.
- Cover normal, overdue, paperwork, provider-warning, and multi-Division states.

### Slice 3 — All Losses list

- Implement list/search/filter behavior using the same view model.
- Open the shared workspace from every row.

### Slice 4 — Division boards

- Implement each board and accessible movement controls.
- Confirm moving EMS never moves Contents or Reconstruction.

### Slice 5 — workspace shell

- Implement the header, Quick Links, close behavior, tabs, and Overview.
- Connect existing capabilities one tab at a time.

### Slice 6 — real actions and safeguards

- Connect stages, ownership, next actions, Requirements, permissions, overrides,
  audit events, sync failure, and offline behavior.
- Add Windows-only office actions through the extension layer.

### Slice 7 — QA and finish gate

- Verify keyboard, touch, screen reader, reduced motion, scaling, responsive
  layouts, long content, realistic lane size, errors, loading, and offline state.
- Run both clients against the same staged database and permission matrix.

Analytics UI expansion follows this foundation so every metric drills into the
same Loss list/workspace rather than introducing another record renderer.

## Acceptance criteria

- A three-Division Loss appears once in All Losses and once on each applicable
  board, with three independent stages.
- Cards show recognized operational facts without displaying full descriptions.
- Opening from Jobs, Clients, Schedule, Analytics, or search produces the same
  workspace and committed data.
- Closing preserves board position and filters.
- Search finds active, closed, archived, and external-only candidates.
- Protected stages require completed Requirements or a permissioned audit entry.
- Unauthorized users cannot infer restricted data from tabs, counts, or alerts.
- Board zoom, horizontal scroll, per-lane vertical scroll, keyboard movement,
  opening, editing, saving, and restoring failed saves pass regression tests.
- Desktop-only actions remain available to authorized office users without
  appearing in the general L OPS experience.

## Explicitly deferred

- free-form card layout customization;
- arbitrary customer-specific card colors;
- drag/drop before accessible movement is stable;
- AI-generated card content as the primary status;
- free-form report/view designers;
- customer portal views.

## Definition of done

The Losses foundation is complete when both clients use one canonical record,
view model, and permission contract; Linguar visually matches L OPS for shared
work; employees retain the useful information and office actions they depend on;
multi-Division behavior is correct; failure and offline states are honest; and
Analytics can drill into the same Loss workspace without redesigning it.
