# Plan of Attack — CompanyCam Reorg + Company-Wide CRM

*Grilled & locked 2026-07-29. Two parts: **Part A** ships on today's stack with no new
access; **Part B** is the dream CRM — marked at each step as **[Now]** (buildable today),
**[Access]** (needs a key/approval we don't have yet), or **[Dream]** (needs the cloud
green-light IT won't give today).*

---

## Part A — CompanyCam, organized like the real import

### The problem
Today "📷 Pull CompanyCam" is one press: it forces **one tech onto every photo** and dumps
the whole batch into **one stage folder** — even when 3 techs shot photos across 3 days and
2 stages. That's the "one-press-all" we're killing.

### Locked decisions
| Decision | Answer |
|---|---|
| Split axis | **All of it** — by uploader (tech) **and** day **and** stage |
| Confirm before download | **Yes** — grouped review screen first (like the multi-stage import) |
| Stage source | **CompanyCam photo tags** (a `demo` tag → Demo stage) |
| Untagged photos | **"Unsorted" group, blank stage** — you assign it in the review |
| Group key | **date + stage + tech** — two techs' Demo photos on 7/16 = two groups, each auto-credited |
| Rules engine | **Reuse `import_grouping.py`** — do not reinvent |

### Design — reuse what already exists
`import_grouping.py` is already the shared rule engine the WC/SP import uses:
- `detect_stage(name)` → `_STAGE_PATTERNS` (Post Mold Prep → Mold Prep → Demo → Monitor → Initial…)
- `detect_date(name)` → already parses CompanyCam's own `Jul 23 2026` / ISO / numeric formats
- `detect_groups(filenames)` → buckets by **(date, stage)**, drops no-stage files into an
  **"Unassigned"** group — which *is* our "Unsorted → blank" answer.

The only adaptation: API photos have no descriptive filename, so we feed each CompanyCam
photo in as a **synthetic record**:
- **stage** = `detect_stage(joined tag names)` — a `demo` tag hits the same `\bdemo\b` pattern
- **date** = `captured_at`
- **tech** = `creator_name`

Then the *same* grouping + *same* review panel takes over. Zero new stage logic.

### Work items
1. **`companycam_api.py`**
   - `_shape_photo`: add `tags` (fetch photo tags — `GET /v2/photos/{id}/tags` or the embedded
     `tags` array; cache per pull to respect the 240/min GET budget).
   - New `plan_pull(project_id, since="auto")` → returns **grouped** records:
     for each new photo build `{stage: detect_stage(tagtext), date: captured_at, tech: creator_name}`,
     group by `(date, stage, tech)`, return the same shape `detect_groups` emits
     (`groups[]`, `stages`, `dates`, `unassigned`, `multi`).
   - Keep `pull_new_photos(..., tech=)` but call it **per group** with that group's tech +
     stage subfolder (it already dedups by filename and stamps capture time).
2. **`import_grouping.py`** — add a thin `group_records(records)` sibling to `detect_groups`
   so structured records (not just filenames) share the identical bucketing/sort code.
3. **Settings** — a **tag→stage map** (`companycam_tag_map`): fuzzy default = run the tag text
   through `_STAGE_PATTERNS`; let the user pin exceptions (e.g. CompanyCam tag `"walkthrough"` → Initial).
4. **`audit_web.py` / `snapshot_web.py`** — replace `companycam_pull_one`'s single stage+tech
   call with: `plan_pull` → hand the groups to the review panel → on confirm, loop groups and
   pull each into `PICS/<stage>/` with its tech.
5. **Review panel** — reuse the import's multi-stage review UI (folder-per-stage, tech-per-group);
   pre-fill tech from `creator_name`, both editable; "Unsorted" group forces a stage before pull.
6. **Tests** — `test_companycam_grouping`: multi-tech/multi-day/multi-tag batch → correct groups;
   untagged → Unsorted/blank; tag→stage mapping + fuzzy fallback.

### Effort: ~1 focused session. No new access needed — the CompanyCam token already works.

---

## Part A½ — New-job provisioning (one action → CompanyCam + Trello + folder)

When a new job comes in, one action should stand it up **everywhere** so the three systems are
linked from birth — no manual triple-entry, no mismatched spellings.

### What it creates
1. **CompanyCam project** — `POST /v2/projects` (name + address from the assignment email).
2. **Trello card** — already built: `new_loss_intake.py` clones the WIP template (water/fire/property)
   into the dept's NEW LOSS list, bottom.
3. **OD / job folder** — `create_job_folder` / `child_folder_ops` scaffold `EMS/PICS` + `EMS/DOCS`
   under the dept's year folder (X: / OneDrive per dept).

### Design
- Extend **`new_loss_intake.create_new_loss`** into a single `provision_job(assignment)`:
  parse the email (already done) → create folder → create Trello card → create CompanyCam project →
  **`ems_db.resolve_and_link`** ties all three ids to ONE job identity (folder + `trello_card` +
  `companycam_project`), so every tool resolves the same job from any spelling.
- **Idempotent + partial-failure safe:** if the CompanyCam project (or card/folder) already exists,
  link it instead of duplicating; report per-system success/fail in the toast (mirrors the
  bug-#6 "count only real successes" rule). Order: folder → card → CompanyCam → link.
- Surfaced on the existing **🆕 New Loss** button; the confirm dialog shows the three things it will
  create (editable name/address) before it fires.

### Access note
CompanyCam project **creation is a write** — the current token is described as read+download.
Confirm the token has write scope (or mint one that does) in CompanyCam → Integrations → Developer.
Trello + folder creation already work today.

### Why it matters for Part B
This is where a **Job record is born** in the CRM. `provision_job` becomes the CRM's
"New Job" entry point — the moment Contacts, the Job, and its external ids all get created and
linked in one transaction. Build it now; it graduates straight into the CRM foundation.

### Effort: ~1 session (once CompanyCam write scope is confirmed).

---

## Part B — The Company-Wide CRM (the dream)

### Locked vision
| Area | Decision |
|---|---|
| Platform | **Cloud web app** — any device, office + field. *(Today IT won't bless cloud — see Two-Track below.)* |
| Primary job | **Job single-source-of-truth** — every photo, doc, note, email, estimate, status, $ in one record |
| Integrations | **Xactimate/XactAnalysis + QuickBooks + Outlook/MS Graph**, plus Trello & CompanyCam deepened, DocuSign |
| External portal | **None** — internal staff tool |
| AI | **Heavy — an AI copilot** (auto-draft, auto-file emails, next-actions, at-risk flags, ask-in-plain-English) |
| Access | **Role-based** (office/admin full · techs = their jobs · estimators = estimating · managers = reports) |
| Scope | **L&P Group departments** — IE + OC + future depts. Multi-department, not multi-tenant SaaS |

### Target architecture (dream)
```
                    ┌─────────────────────────────────────────┐
   Office browsers  │           CRM Web App (cloud)            │
   Field phones ────┤  React/Next front-end · REST/GraphQL API │
   Desktop "power   │  Auth + RBAC · Postgres · object storage │
   tools" (current) │  Background workers (sync, AI, reminders)│
                    └───────────────┬─────────────────────────┘
                                    │ connectors (workers)
     ┌────────────┬───────────┬─────┴──────┬────────────┬──────────────┐
   Trello     CompanyCam   Xactimate/     QuickBooks   MS Graph      DocuSign
   (have)     (have)       XactAnalysis   (Access)     (Outlook,     (have)
                           (Access:Verisk)             Access:IT)
```
- **DB:** Postgres (real relational DB — replaces SQLite-on-a-share, which is the current risk).
- **Storage:** photos/docs in object storage (S3/Azure Blob), *referencing* the X: job folders
  during transition so nothing moves until we're ready.
- **Desktop app kept** as the office power-tools front-end (audit/snapshot/hygiene) — it just
  talks to the same cloud API instead of local JSON/SQLite. Nothing already built is thrown away.

### Data model (foundation — same as `project_crm_vision`, expanded)
```
Contacts   (customer · adjuster · agent · carrier-rep · vendor · tech)
Companies  (carriers · property-mgmt · vendors)  ── Contacts belong to Companies
Jobs/Claims (link existing X: folder + Trello card + CompanyCam project + XA claim)
   ├─ Activities  (calls · emails · notes · XA notes · status changes)  ← 🗒 XA note is activity #1
   ├─ Photos      (CompanyCam + imports, tagged by stage/tech/day)
   ├─ Documents   (signed forms, estimates, COs — the DOCS folder)
   ├─ Estimates   (Xactimate/XA — line items, totals, revisions)
   ├─ Invoices    (QuickBooks — amount, AR aging, payments)  ← "did they pay the CO?" answered
   └─ Tasks       (hygiene/SLA/reminders — the trackers, unified)
```
Migrate from: `ems_db` (job index + identity graph) · Trello cards · job folders · the trackers.

### Integrations — what each unlocks
- **Xactimate / XactAnalysis** **[Access — via your Xactware rep, NOT a self-serve API]**: replace
  email-scraping (`xa_notes_parser`, `xa_notification_emails`) with a real assignment/estimate/claim
  data feed. **Researched 2026-07-29:** Verisk does *not* issue developer API keys. Access is the
  **XactAnalysis integration** (two-way pipe: assignments, contacts, notes, photos, docs, milestones,
  estimate data), enabled by your **Xactware account manager** — and oriented toward *approved
  software partners* (Vendor Alliances), not a franchise's in-house tool. Three paths: (1) **call
  your Xactware rep** and ask for an XactAnalysis assignment/estimate data feed to an internal
  endpoint — shortest route, costs a call; (2) **piggyback** an already-integrated CRM (DASH,
  Restoration Manager, JobNimbus, PSA, ClientRunner) if the company adopts one; (3) **keep the
  email-scrape bridge** until a feed opens. Treat as account-rep enablement, not a key. The
  estimating backbone. (Sources: Verisk Vendor Alliances; XactAnalysis Integrations help.)
- **QuickBooks** **[Access — Intuit API]**: invoices, AR aging, payments post back to the job.
  Ties production to money; auto-answers "did they pay the change order."
- **Outlook / MS Graph** **[Access — IT must approve Azure app]**: every adjuster email auto-filed
  to its job; calendar/scheduling from the CRM. *This is the one IT has blocked — `outlook_local.py`
  COM is the current bridge.* The AI email-filing copilot rides on this.
- **Trello** **[Now]**: already the backbone — becomes a *view* over CRM jobs, not the source.
- **CompanyCam** **[Now]**: Part A makes photos first-class; CRM stores them per job.
- **DocuSign** **[Now]**: signed-status back into the Documents model.
- **CompanyCam Signatures** **[Manual — no API]**: CompanyCam's e-sign is powered by **Dropbox
  Sign** under the hood; there's no CompanyCam signature API. It *can* replace DocuSign for the
  **manual in-app** flow (decided 2026-07-29: manual is fine). The API only exposes *List/Upload
  Project Documents*, so we can API-push forms into a project but the sign step stays manual and
  status won't flow back. No signature-automation work on our side. (See `SOFTWARE_AUDIT.md` §5.)

### AI copilot layer (heavy)
- **Auto-file** incoming adjuster emails to the right job (identity graph + AI classification).
- **Auto-draft** job notes, status updates, customer/adjuster replies — you approve before send
  (mirrors the existing no-auto-post gate on adjuster receipts).
- **Next-best-action** per job; **at-risk flags** (stalled, missing docs, SLA breach) — the
  hygiene/KPI engines become AI-summarized.
- **Ask in plain English:** "what's the status of Martinez Kim / who hasn't paid / which jobs
  are missing initial photos" → answered from the CRM.
- Cloud LLM (e.g. Claude API) — the earlier on-device idea is the offline fallback if cloud stalls.

### Phased roadmap
- **Phase 0 — Shared data spine** **[Now, no cloud]**: promote `ems_db` to the shared **X: SQLite**
  with WAL + single-writer discipline; land the **Contacts / Companies** tables + the **Activities**
  log (XA note = activity #1). Every existing tool reads/writes it. *This is real progress toward
  the dream that needs zero new access — do it first.*
- **Phase 1 — Contacts foundation UI**: a Contacts panel (customer/adjuster/carrier/vendor),
  each tied to jobs; back-fill from `ems_db` + Trello + folders.
- **Phase 2 — Job record = single source of truth**: unify photos/docs/notes/estimates/tasks
  under one Job view (folds audit + snapshot + hygiene + trackers into one record).
- **Phase 3 — Money & estimating** **[Access]**: QuickBooks + real Xactimate/XA data on the job.
- **Phase 4 — Email + AI copilot** **[Access: Graph]**: auto-file, auto-draft, at-risk, ask-anything.
- **Phase 5 — Cloud + field** **[Dream]**: lift the spine to Postgres in the cloud; web app on
  phones for techs; the desktop app becomes one client of the same API.

### Two-track reality
The dream is cloud; **today IT won't approve Azure/cloud.** So we run two tracks in parallel and
they converge:
- **Track 1 (build now, on-prem):** Phases 0–2 on shared X: SQLite + the current desktop app.
  Delivers the single-source-of-truth hub with no new permissions. Everything here is
  cloud-portable (clean data model + an API boundary, not UI-coupled logic).
- **Track 2 (unlock in parallel):** pursue the three keys — **Verisk (Xactimate/XA)**,
  **Intuit (QuickBooks)**, and the **Azure app approval for Graph**. Each arriving key lights up
  its phase. The Azure approval is also the gate to Phase 5's cloud lift.

### Risks & unknowns
- **SQLite on a network share** (Phase 0) — locking/corruption is the #1 near-term technical risk;
  WAL + a single-writer/queue pattern, or an on-prem Postgres/SQL-Server box if IT allows a server
  (cheaper than cloud, may pass where Azure won't).
- **Verisk API access** — Xactimate/XA APIs are gated/partner-only; may stay email-scraping longer.
- **Graph/Azure approval** — historically blocked; without it, email stays `outlook_local` COM
  (single-machine, no field).
- **Data migration fidelity** — dedup/identity across Trello + folders + `ems_db` (the identity
  graph already does much of this; reconciliation ran 473→326 jobs).
- **Adoption** — role-based access + keeping Trello as a familiar view lowers the change cost.

### What we can start THIS week (no new access)
1. **Ship Part A** (CompanyCam reorg) — immediate daily win.
2. **Ship Part A½** (`provision_job` — new job builds CompanyCam + Trello + folder in one action,
   all linked in `ems_db`). *Only external need: confirm the CompanyCam token has write scope.*
3. **Phase 0 spine** — shared `ems_db` on X: with WAL; add Contacts/Companies/Activities tables;
   route the 🗒 XA note through Activities as proof-of-concept. `provision_job` becomes its
   "New Job" write path.
4. **Draft the three access requests** (Verisk, Intuit, Azure/Graph) so Track 2 can start.

---

## Appendix — Draft ask to the Xactware account rep
> Subject: XactAnalysis assignment/estimate data feed for an internal tool
>
> Hi [rep name],
>
> We're a SERVPRO franchise (L&P Group — SERVPRO of Woodcrest/El Cerrito/Lake Mathews) and an
> active XactAnalysis customer. We're building an **internal** job-management tool for our own
> admin team and want to stop re-keying assignment data by hand.
>
> Can you enable an **XactAnalysis integration / data feed** to our account so our new-loss
> assignments and estimate data flow into our internal system automatically? Specifically:
> - New-loss **assignments** (insured, carrier, claim #, loss type, address, adjuster) as they land
> - **Estimate** totals / status and key **milestones** per claim
> - If there's an XML feed, webhook, or partner endpoint we can receive on, what are the steps
>   and requirements? If this requires the **Vendor Alliances / partner** path, what does that take
>   for an in-house tool (vs. a commercial product)?
>
> We already receive the assignment emails — a structured feed would just remove the manual step.
> What are our options and any cost?
>
> Thanks, [name] · [office] · 951-398-3240

*Related memory: `project_crm_vision`, `project_ems_db`, `project_multi_department`,
`project_update_check`, `project_main_trial_channels`. This doc is the living plan — update as
keys land and phases ship.*
