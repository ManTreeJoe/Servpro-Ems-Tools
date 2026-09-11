# Linguar Hub product work map

This file is the landing page for product decisions and incoming changes. It keeps the replacement app focused on one operational model instead of accumulating unrelated card controls.

## Product spine

```text
Client
└── Job / claim / loss / work order
    ├── Shared job facts and contacts
    ├── EMS division
    ├── Contents division
    └── Recon division
        ├── Stage and requirements
        ├── Checklist and assignments
        ├── Comments and Job Log entries
        └── Work periods and timing
```

The Client is the permanent record. Jobs are the individual pieces of work. Divisions are coordinated workstreams inside a Job, not separate Clients and not a global app mode.

## Screen responsibilities

| Screen | Primary question | Belongs here | Does not belong here |
|---|---|---|---|
| Clients | What is the complete relationship and history? | Contacts, properties, all years, all jobs, aliases | Active lane management |
| Jobs | What active work needs attention? | Board, lanes, search, job cards, assignment and stage signals | Duplicate client records |
| Job Workspace | What do I need to know or do on this job? | Shared facts, division switch, requirements, checklists, Job Log, comments, integrations | App-wide setup |
| Dispatch | Who is going where and when? | Day/week schedule, arrival windows, crew, activity, live edits, history | Full claim administration |
| Reports | How are teams and jobs performing? | Cycle time, SLA metrics, exceptions, drill-down | Editing operational source records |
| Settings | How does this franchise/user work? | Roles, integrations, folders, templates, defaults | Job-specific exceptions |

## Editing and saving contract

- Job Info uses an explicit **Save job info** action.
- Division status, assignment, requirements, and checklist completion save immediately and display `Saving`, `Saved`, or `Not saved`.
- Job Log forms are drafts until **Save update** is pressed.
- Comments are drafts until **Add comment** is pressed.
- Closing a Job Workspace warns only about a real unsaved draft. It never warns for a change that already autosaved.
- Every failed save leaves the entered value visible and explains what was not saved.

## New Loss contract

Main's **New Loss** action provisions one complete operational Job. It creates the appropriate OD job-folder skeleton, clones and pins the selected live Trello template, creates or adopts and pins the CompanyCam project, then records all three locators against the same Job identity. CompanyCam must be connected before provisioning begins. A partial external failure is reported as `setup incomplete` with the failed step; it is never presented as a fully ready job.

## Source ownership

| Information | Owner | Temporary adapter |
|---|---|---|
| Client/job/division identity | Linguar Hub database | OD folder index and Trello matching |
| Operational stage and requirements | Linguar Hub database | Trello sync |
| Job Log and Snapshot source entries | Linguar Hub database | Trello comment import |
| Photos and photo reports | CompanyCam | Job folder export while required |
| Signed documents | Job document storage | DocuSign |
| Schedule | Linguar Hub Dispatch | Run Doc import/print |

Trello synchronization runs as a background adapter: queued Hub writes are pushed before inbound board changes are imported every two minutes, while an open job conversation checks for new activity every minute. Routine sync does not reload the board or Job Workspace; only the affected data section changes.

## Delivery order

### Now — make the daily workflow dependable

1. One Job Workspace renderer from Jobs, Clients, Dispatch, search, and reports.
2. Correct save states and conflict handling for every editable control.
3. Stable Client → Job → Division identity and linking.
4. Fast initial card shell followed by section-level loading.
5. Complete parity for Job Info, requirements, checklist tabs, Job Log, comments, folders, XA, Trello, and CompanyCam.

### Next — simplify the client/job experience

1. Client page with contacts first and jobs grouped by year.
2. One job header containing shared facts and a persistent EMS/Contents/Recon switch.
3. Create/link a sibling Division without leaving the Job Workspace.
4. Universal search that returns active, closed, archived, and external-only matches.
5. Review queue for ambiguous client, claim, folder, and Trello matches.

### Queued after the shared identity/workspace migration — XA assignment intake

Build the temporary XactAnalysis email importer described in
[`XA_TEMPORARY_AUTO_IMPORT.md`](XA_TEMPORARY_AUTO_IMPORT.md). This is an
internal Windows workflow until Verisk provisions an official integration.

1. Import approved `.eml` files into an **Import Draft** queue; importing never
   creates or changes a live Job.
2. Parse and normalize assignment facts behind one `AssignmentImportSource`
   interface while preserving the original source, parser version, unknown
   labels, SHA-256, Internet Message ID, and safe attachment metadata.
3. Match drafts to the shared Client → Claim → Division contract using exact
   source, XA ID, claim/property, property/date, and contact-only confidence
   levels. No candidate is merged automatically.
4. Give authorized Front Ops users a review screen with edit, approve as new
   Job, add related assignment, merge exact duplicate, and reject actions.
5. Make approval atomic and write post-commit outbox work for CompanyCam,
   profiles, requirements, tasks, and audit entries. External failures remain
   retryable and never roll back the approved Job.
6. After the local parser and review workflow pass acceptance tests, connect
   the same pipeline to an authorized Outlook `XA Intake` folder through
   Microsoft Graph. Replace the source adapter—not the matcher or approval
   workflow.

**Owner:** Job intake, with Client and Claim candidate matching.

**Screen:** Front Ops → XA Import Drafts.

**Save behavior:** explicit approval or rejection; risky merges require a
second confirmation.

**Source:** temporary email/Graph adapter; Linguar Hub owns the approved data.

**Done when:** the approved sample set imports without creating live Jobs,
duplicates and related assignments are distinguished, and approval is
idempotent, authorized, audited, and safe under integration failure.

### Later — remove temporary dependencies

1. Linguar Hub-native boards, checklists, comments, and automations replace Trello.
2. Digital Dispatch replaces the editable Run Doc; printing remains an output.
3. Storage adapters support CompanyCam and approved onsite/cloud document storage.
4. Mobile field notes, offline queueing, and assignment-based Dispatch.

## How to record a new request

Before implementation, write one line for each of these:

1. **Owner:** Client, Job, Division, Work Period, or franchise setting.
2. **Screen:** where the user expects to perform it.
3. **Action:** the exact verb the control performs.
4. **Save behavior:** automatic or explicit, including failure and undo behavior.
5. **Source:** Linguar Hub-owned or imported from an external adapter.
6. **Done when:** the observable result a user can verify.

If those six answers are unclear, the feature is not ready to place in the interface.

## Related references

- `CLIENT_JOB_OD_MODEL.md` — folder recognition and migration rules
- `UI_UX_GUIDELINES.md` — interface and interaction contract
- `docs/DEPARTMENT_TIMING_REQUIREMENTS.md` — ownership and timing model
- `docs/TRELLO_AUTOMATION_MIGRATION.md` — Trello replacement plan
- `docs/XA_TEMPORARY_AUTO_IMPORT.md` — temporary XA assignment intake backlog
- `DATA_STORAGE_POLICY.md` — structured data and file storage policy
