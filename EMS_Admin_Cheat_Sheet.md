# EMS Admin Assistant — Workflow Cheat Sheet

Reorganized from handwritten training notes. Grouped by workflow area so each task has its steps, the tools/folders involved, and common gotchas.

---

## 1. Daily Workflow

### Morning
1. **Go through yesterday's run** — verify all photos uploaded for each tech on each job.
2. **Check Monitor jobs** — open each monitor, confirm photos are in place.
3. **Create today's Photo Folders** → launcher: **Photo Folders**. Auto-checks which already exist.
4. **Audit today's run** → launcher: **Run Audit**. Forms / Docusketch / photos checked per job.

### Throughout the day
- Watch the **Monitor channel** in Trello and keep up as techs post photos.
- If a tech mentions photos but none are posted, reach out for the missing Trello upload.
- If a job is missing photos, **DM the tech directly** in Teams — don't wait.
- Watch the **APA Monitor** all day; corporate runs ~2 hours ahead so updates land at ~10pm Pacific.

### End of day
- **Snapshot handoff** for each closing/closed job.
- Update Job/Snapshot summary in the spreadsheet.
- Open the **Hygiene** tab. It now has **three sub-tabs** — work the top one until empty, then move to the next:
  - **🔴 Action Needed**
    - 📆 Weekly check-ins due — Estimating-board cards 7+ days quiet. One-click sends the canonical note to clipboard + Trello + Teams.
    - 💰 Estimate Requests (48h SLA) — inbound asks from adjusters (email) or carriers (XA). "Send 48h ack" copies the canonical reply + DMs the estimator. Rows flip red when overdue.
    - 📨 Adjuster inquiries (approve to post) — inbox matches to Trello cards. **Nothing posts automatically anymore** — click ✓ Post per row to drop the receipt comment, ✕ Dismiss to suppress false positives (realtors, vendors, shared mailboxes). Dismissals stick across re-scans.
    - ⚖ Audit disputes (open + overdue) — open rows from the Dispute Tracker workbook. APA Monitor auto-imports each new dispute the first time it appears, and the launcher's hourly mini-scan also harvests dispute mentions from the EMS inbox. Per-row ✓ Mark sent + 📝 Edit; double-click opens the row in the Dispute Tracker tool. See §17a.
    - 🚨 Customer concerns — complaint / legal / refund language in Trello comments + inbox.
    - 📷 IPR requests — Trello @mentions asking for the Initial Photo Report. Auto-clears when you reply "uploaded" / "done" on the same card.
    - 🔔 Apology reminders (XA) — AR Board cards needing the weekly apology note posted in XactAnalysis.
    - 📐 Docusketch pending — jobs you've asked for a sketch on but the zip isn't back. Auto-clears on import.
    - 📝 Docusign pending — paperwork sent for e-sig or waiting for the office to call the insured. ✓ Received closes the entry.
    - ✍ Docusign physical-signature SLA — resends past 5 days without signature. 🔄 Resend on the original row restarts the clock.
    - 📋 Missing — items flagged at any stage (intake / audit / snapshot). Stage chip + age in days; ✓ Resolved when it arrives, 👁 Ignore for opt-outs.
  - **⚠ Trello quality**
    - ⚠ Hygiene violations — cards missing owner / follow-up date / recent activity.
    - 🔄 Lane moves missing handoff — moves in the last 24h with no handoff comment. One-word "ok" / "done" don't count.
    - 📸 Ready for Snapshot — SNAPSHOT-lane cards or cards explicitly tagged ready. ✓ Mark drafted clears the row + the card disappears the moment you actually generate the snapshot.
    - 📋 All open Trello jobs — full live view of every open card across the in-scope boards (stale-first). 🔄 Sync from Trello in Settings refreshes the cache.
  - **📝 Stale notes**
    - 📝 XA gaps — stale XA notes or open verbal commitments ("billing to follow", "drying underway") without a closing note. Pulled from the EMS@ inbox.

### Color codes (Trello / log)
- **Green** = Demo
- **Pink** = Contents / Cleaning
- **Yellow** = New loss

---

## 2. Sites / Apps Used

| Tool | Used for |
|---|---|
| **Xactimate** | Estimates (cloud + local). Initial shells, contents estimates, final estimates. |
| **Workcenter** | Source of truth for forms + photos. DBMx is where uploads land. |
| **Xactanalysis** | Insurance carrier portal — assignments, claim numbers, supplements. |
| **Job File Audit** | Self-audit after every Workcenter upload. ~10–15 min to populate. |
| **Trello** | Daily run + Monitor channel + per-job cards (paperwork status, dispatch notes). |
| **Teams** | DM techs, chat with leads (Sam / Zac / Eric / GL). |

---

## 3. Initial Uploads (per carrier)

**Tool path:** Workcenter → DBMx. Currently active for State Farm. Initial uploads happen the **same day of** the inspection — pay extra attention to NEW LOSSES.

### General initial-upload checklist
- Check photos uploaded in DBMx.
- **Claim info** → Insured info; date of loss at 12:00am.
- Cause of loss = `Other`; Deductible = `0`.
- **Parameters** → add company header in Report text.
- Opening + closing statements live in the diary notes.
- Update insurance/months and claim #.
- **Photos**: backstage → load all photos.
- **Reports** → Claim Reports → search photos / select photos. Export the Initial Photo Report.
- **Reports** → Attached docs tab → import Dry Report and Initial Photo Report → upload.
- Status should show **green** on Initial.
- Mark as complete and send.
- Uploads take ~15 min to clear out. **No yellow boxes = good.**

### Carrier-specific rules
- **State Farm** — currently the only carrier with daily uploads in CR Requirements. Create the **Initial estimate** as a **Service Call at $0** before uploading. Just click *Acknowledge* on the prelim estimate.
  - **State Farm needs the Equipment line on the estimate.** On the Service Call, add the **`EQ` — Equipment setup, take down, and monitoring (hourly charge)** line item (cat `WTR`, sel `EQ`, unit `HR`, coverage Dwelling). State Farm requires this line for the estimate.
  - **Override the EQ quantity per State Farm's SLA → `1.5`.** The line defaults to `1.75 HR` (Calc 1.75) — for State Farm, change the **Quantity/Calc to `1.5`** on the Service Call. Only do this override for State Farm.
- **Farmers** — Service Call estimate at **$300**. Sketch is required even if empty — add a **random room** to the sketch so it isn't blank. All other normal initial-upload steps still apply.
- **Travelers / Lemonade** — extra forms required (ATP, ATR, warranty) on top of ATP / CIF / CER / COS.
- **AAA** — Contents work flows through Pablo. See §10 (AAA Contents).
- **Allstate** (program spec **B.8 — Uploads**) — **Initial upload due within 72 calendar hours of dispatch** (this is a Performance Weighted Distribution ranking category — it affects our ranking, so don't miss it). Required documents for the initial upload:
  - **ClaimXperience Pre-Mitigation Video** — also a Performance Weighted Distribution ranking category.
  - **Sketch**
  - **Photos**
  - **SERVPRO® DryBook Dry Report**
  - **Authorization to Perform (form 28000)**
  - **Preliminary Estimate** — due within **72 calendar hours of receiving the assignment**; must include **each affected room with dimensions and the type of equipment set**; generally **50–70% complete**; **zero-dollar estimates are not acceptable**.

### Dry Report — Edit Initial Inspection defaults

**Path:** Workcenter → **Drybook** → click **Unlock** → click **Edit Initial Inspection**.

Set the form to these defaults:

| Field | Default |
|---|---|
| Site Inspected | (auto-fills current date/time — leave it) |
| Number of Levels Affected | **1** |
| Is access to loss site restricted? | **No** |
| Are there Safety and / or Security Issues? | **No** |
| Did the Customer refuse service? | **No** |
| Has subrogation potential been identified? | **No** |
| Are there any questions about coverage? | **No** |
| Are you providing an estimate only? | **No** |
| Are any of these services needed: contents cleaning, pack-out, textile or dry cleaning? | **Yes** — Edit Note → `N/A` |
| Are there any specialty content items? (grand piano, antiques, artwork, etc.) | **Yes** — Edit Note → `N/A` |
| Will pack-out exceed 24 hours? | **Yes** — Edit Note → `N/A` |
| Is demolition needed? | **Yes** — Edit Note → `N/A` |
| Will demolition exceed 24 hours? | **Yes** — Edit Note → `N/A` |
| Will repairs delay drying? | **No** |
| Will asbestos testing be performed? | **No** |
| Were lead paint test results positive? | **No** |
| Is there mold present? | **No** |
| Is specialty drying equipment needed? | **No** |

**Rule of thumb:** every **Yes** answer needs an `EDIT NOTE` filled in. For all five `Yes` defaults above, the note body is just `N/A`.

**Edit Note dialog defaults:**
- Category: `Additional Emergency Response Service`
- Type: `Additional Emergency Response Service`
- Visibility: `Franchise and Client`
- Date: (auto)
- Subject: descriptive per question (e.g., `Drying Delay - Demolition`)
- Notes: `N/A`

When the form's complete, click **Save** (top-right green button). The Dry Report is then ready to export and import into the Initial Upload alongside the Initial Photo Report.

### When uploads stall
- Sometimes opening the job back up takes 30 min to show on APA.
- Corporate is 2 hrs ahead → final clear is ~10pm Pacific.

---

## 4. Daily Estimate Upload (close-out flow)

When a job closes and you need to push the final estimate:

1. **Xactimate** → File → Project → **Complete → Inspect** → Mark as Complete → Save and Exit.
2. Double-check **Workcenter is up to date** — every file in Client Required is uploaded and accurate. Drying Report has the most recent job notes.
3. **Workcenter → Project Snapshot** → set **Project Progress: Billing** → click the floppy-disk **Save** icon.
4. Back to **Client Requirements → Due Dates / Uploads** → refresh until **Final Upload** is clickable → press Upload.
5. Wait 10–15 min for it to land in **Job File Audit**, then run the self-audit.

### Photo Report (when needed)
- Reports → Inventory → Reports → select **Presentation** and rename title to `Photo Inventory Report`.
- **Uncheck** Room Photos.

### Total Loss Report (when applicable)
- Same as Photo Report but select **Tabular** and title it `Total Loss Report`.
- Scroll and select condition (ALL) and select **Questionable** + **Total Loss**.
- Hit *Create Report* once loaded.
- Make sure Job Details has Insured, Claim #, Insurance Company, and Adjuster filled before creating the report.

### Estimate request — holding response
When someone asks where their estimates are, paste this (📋 copy):

> Good morning, [Name],
>
> Our estimating team is diligently working on these estimates.
>
> We will send them to you as soon as they are finalized.
>
> Thank you for your patience.
>
> Kind regards,

---

## 5. APA Monitor

- **APA Monitor page** lives in `X:\IE_Public\APA Monitor\<Year>\<Month>\` as a `.docx`.
- **Save as today's date**, copy yesterday's content, then clear all items except the **categories**.
- Initial Uploads go in the **Xactimate shell** (only).
- **17y** = Corp Rejections.
- Disputes can read like 17y but **don't show on APA**. Check the **Audit page** for disputes.
- Disputes clear next day at midnight. Holidays and weekends don't count, but clear it just in case.
- **Recon** does its own initial; **Contents** does its own initial.
- For these two, message in channel and ask if we need to extend.
- If pending review where it is in Trello — if we need to extend, where it is, add to **Doc** of that section.
- If no section, add to whatever section it needs to be done (Final Upload).
- Ask Pablo for billing contents.
- Pay attention to the context of jobs to extend if we still have more left to go.
- **Initials** need a state reason also.
- When extending, simply select Repair → not completed on Notes and Reason.
- **Finals** extend by a **week**.
- **Initials** extend by **2 days** + weekends.
- Can check this in Workcenter → we can do Final and Initials and shows due date.
- Can upload initials before due date.

### 🔁 Extended-tracking badge
The APA Monitor now shows a **🔁 N×** badge next to any row that's been extended N+ times. The counter bumps automatically the moment a row transitions to an extended status — no manual marking. Use it to spot rows that keep slipping and need escalation (same idea as the audit panel's recurring-flag.)

---

## 6. Closing a Job

Checklist when a job is being closed:

- [ ] **Paperwork** collected from Workcenter → DBMx → `DOCS` folder
- [ ] **Initial** docs present: ATP, CIF, CER
- [ ] **Closeout COS** (Certificate of Satisfaction) signed
- [ ] **Photos** from Baca uploaded to Workcenter so the cloud checks pass
- [ ] **In Trello → Last page** add work/missing items column if attention needed; add a comment in card specifying what's missing
- [ ] **Reopen if cancelled / reopened** — Workcenter project → Project Snapshot → set Project Status to *Reinstate*
- [ ] If forms are not signed and returned, **call or email** the insured and leave note in card of what we did
- [ ] **Reusable: sketch, forms, photos**
  - Docusketch folder lives in project + DOCS
  - In Docusketch, unzip and add the contents into the folder
- [ ] Any **written measurements** — copy and add to the Word doc in DOCS, label it **scope**
- [ ] **For photos**, add name of lead and when they went out

### DocuSign — close-out request

Use this exact subject + message when sending close-out paperwork through DocuSign. Replace the `<...>` placeholders before sending.

**Subject:** `<LASTNAME> - Final Paperwork`

**Message:**
> Hello, as Servpro has completed mitigation services at your property in `<CITYOFPROPERTY>`, we will need the following form(s) to be signed in order to close out this part of your claim with us. Please sign at your earliest convenience and if you have any questions, please contact our office at 951-398-3240. Thank you.

### Known hiccups
- Sometimes OneDrive doesn't update — check **SharePoint** directly.
- If photos missing, **message Teams** in Leads / conversation Trello.
- Anything is fine in Snapshot — ATP can be uploaded even without all paperwork.
- Handwritten scopes — scan with phone.
- **Double-check** I have access to SharePoint.
- **Double-check** spelling of job name.

---

## 7. Snapshot Handoff — Daily Breakdown

**Tool:** launcher → **EMS Snapshot**.

1. Look through Trello to add what was dispatched / next steps.
2. **In Trello**, check if **subs** also attended (note if billed or insurance).
3. **On snapshot, in dock**, add what we did (note if billed or insurance).
4. **Abatement** — take the sig and references (use it as a gap reference if needed).
5. Add if typed or not, even if **included or not**.
6. Mark it as **additional**.
7. If adding another dose, add it before.
8. Pay attention to the **Monitor channel** all day; check if monitors uploaded photos.

**File location:**
- Snapshot file → `X:\IE_Public\Front Operation\Snapshots\` (filled off template).
- All snapshot docs land in **Trello**.
- Move from snapshot column to **TO BE ARCHIVED** column (oldest to latest).

### Per plan
- Check every monitor to get photos.
- If a monitor job is missing paperwork (Forms, Scope, etc.) — flag it.
- Commercial already has its own paperwork set.
- **Extra Run Folder** for dispatches crossed out.
- **Let Run Folder know** if Laura helps speaking Spanish.
- Check photos both day-of and day-after.
- **Result** — create **Photo Folders** in SharePoint for that day's photos.
- Questions about others' policies → ask them.
- **Move all photos to Project Folder** (once Archive folder is created).

### Canonical activity language — Adjuster walk-through
When an adjuster visits the property, log it as **one activity line** on the snapshot (the daily activity log, not a separate visit row). Use this template so every walk-through reads the same and the snapshot PDF is self-explanatory to anyone reviewing later:

> **Adjuster walk-through — `<Adjuster name>` (`<Carrier>`) walked the property with `<our tech / lead>` for ~`<minutes>` min. Scope reviewed: `<rooms / areas>`. Outcome: `<approved / pending review / additional scope requested / re-inspect scheduled>`. Photos: `<PICS\Reinspect>` or `<PICS\Initial>`.**

Concrete examples (drop straight into the snapshot activity field):
- *Adjuster walk-through — Jane Doe (State Farm) walked the property with Cesar for ~30 min. Scope reviewed: kitchen + master bath. Outcome: approved as scoped. Photos: PICS\Reinspect.*
- *Adjuster walk-through — Mark Smith (Farmers) walked the property with George for ~45 min. Scope reviewed: garage + hallway. Outcome: additional scope requested (subfloor below tile). Re-inspect scheduled `<date>`. Photos: PICS\Reinspect.*
- *Adjuster walk-through — Lisa Tran (USAA) virtual via FaceTime with Mark L for ~20 min. Scope reviewed: laundry room. Outcome: pending review — adjuster sending supplement decision by EOW. Photos: PICS\Reinspect.*

### Why this matters
The snapshot PDF is what closes out the file for billing review. An adjuster walk-through is the single biggest scope-decision moment of the job — if the snapshot activity log just says *"adjuster came out today"*, you (or whoever audits the file later) can't tell whether the scope was approved, whether a supplement is owed, or whether a re-inspect is on the calendar. Fill the template; everything downstream is faster.

### Where to file the related artifacts
- **Photos from the walk-through** → `EMS\PICS\Reinspect\` (or `Initial\` if this was the first visit).
- **Adjuster notes / annotated scope** (if they hand you anything) → `EMS\DOCS\` labeled `<date> - adjuster walkthrough notes`.
- **Any signed acknowledgement** → DOCS, labeled per the form type.
- **Trello card** — drop a one-liner mirroring the snapshot activity so the card history matches.

---

## 8. Scope Verification

Scope is its own paperwork item — it's not interchangeable with the work log. **Always verify the scope matches the work that was actually done.**

### Red flags to check before signing off a scope
- **Multi-day demo with a short scope** — if demo ran across multiple days but the scope is only a few items, request **more info** from the tech or split it into **multiple scopes** (one per visit / room).
- **Scope mentions rooms not in the photos** — likely wrong job number or copied from a template.
- **Scope materials don't match photos** — e.g., scope says drywall removed, photos show only baseboards.
- **Handwritten scope** — scan with phone, then transcribe into the Word doc in DOCS so the audit picks it up. Label it **`scope`**.

### Why this matters
The Run Audit's scope check only verifies a scope file *exists*. Whether that scope actually reflects the work is on you — the audit can't tell.

---

## 9. Folder Structure

### File layout per job
```
X:\IE_Public\<YEAR>\<Client Name>\
├── EMS\
│   ├── DOCS\
│   ├── PICS\          (Initial, Reinspect, Demo, Mold Prep, Mold After, Post)
│   └── FIELD DOCS\
├── CONTENTS\
│   ├── DOCS\
│   ├── PICS\
│   └── FIELD DOCS\
└── RECON\
    ├── DOCS\
    ├── PICS\
    └── FIELD DOCS\
```

### Commercial properties
Main folder with sub-folders per **unit / apt**.

### Multi-year jobs
The audit tool **automatically searches the current year first, then the previous year** — a 2025 job audited in 2026 displays as `Smith, John (2025)`.

### Multi-claim jobs (`Second Claim` subfolder)
Some properties have a second separate claim (e.g., a roof leak followed months later by a water-heater leak). The convention is to drop a sub-folder named **`Second Claim`** / `2nd Claim` / `Claim 2` / `Third Claim` inside the existing job folder — that subfolder becomes the active claim's paperwork; the parent retains first-claim files.

The audit auto-descends into the highest-numbered claim subfolder when one exists. The audit row label shows `Carnero Corina \ 2nd Claim` so you can see which claim is being audited. EMS / DOCS / PICS lookups inside the audit target the active claim's files, not the parent's.

### Folder name convention
Job folders follow `Lastname Firstname` (no comma, mixed case). Spouses joined with `&`: `Smith John & Jane`. Run `_folder_rename.py` (devs only) to clean up any reversed / comma-form folders that accumulate. Trello card names are typically `Lastname, Firstname - Carrier` — both formats coexist.

### Special notes
- Folder of photos should use **stock** / pay extra attention to **New Losses**.
- **Daily uploads** — pay attention to initial uploads the **same day**.
- **Docusketch request** — request sketches and include them.
- If no photos, check what was written for updates.
- Sometimes a job's main name doesn't have a folder → go and **make it**.
- Docusketch is also used to send out docs.
- **Workcenter:** use the right shell with the X logo / download Forms if assigned + add to folder.

---

## 10. Contents — canonical Trello comments

When something contents-related happens on a job, drop the matching comment on the Trello card so the file's paper trail is self-explanatory at audit time. The audit and snapshot tools both surface comments matching these prefixes.

### Items being moved (pack-out / off-site / packed back in)
- **Items packed out today:** `Pack-out completed today by <tech list>. <N> boxes / <N> wardrobes routed to off-site storage. Pictures uploaded to Workcenter + OD/PICS/Pack Out.`
- **Items packed back in:** `Pack-in completed today. Items returned to <room/area>. Customer signed COS for contents.`
- **Items still off-site:** `Contents remain in off-site storage as of <date>. Awaiting <repair-complete / customer ready / structural sign-off>. Storage line on invoice continues to accrue.`

### Customer-facing contents issues
- **Damaged item flagged:** `Customer flagged damage to <item> during pack-out review. Photo + statement uploaded to DOCS\Contents Damage. Notified <adjuster>.`
- **Missing item dispute:** `Customer reports <item> missing from inventory list. Verified against pack-out photos — <found / not in pre-pack-out photos / open with Pablo>.`
- **Customer refused pack-out:** `Customer declined pack-out for <items / room>. Items left in place per customer request; refusal note signed and uploaded.`

### Coordination handoffs
- **Routed to Pablo:** `Contents portion of this claim is now with Pablo (contents lead). Estimating side staying with <estimator>.`
- **Routed to Victoria:** `Contents estimate handed off to Victoria for finalization.`
- **AAA contents:** `AAA contents xlsx + photo inventory uploaded to <AAA portal / Workcenter>. Final calculator saved as <Lastname Final Calculator.xlsx>.`

These match the contents-related conventions used in §10 (AAA Contents) below. Keep the comment short and factual — one line + one fact-cluster — so a future audit reads the card top-to-bottom in 10 seconds.

---

## 10a. AAA Contents (special workflow)

AAA contents jobs have a separate spreadsheet-driven flow:

1. Download the contents `xlsx` sheet from the AAA website + photo inventory report.
2. Add all items in the xlsx sheet (input + label boxes — picture boxes added to mirror box).
3. Wardrobe boxes always large; paper blankets and blue blankets added to AAA.
4. All beds + mattress bags add cost to xlsx.
5. **Labor key** should match the blue estimate on xlsx.
6. We tweak the xlsx to adjust if it's an item-by-item charge (just `# of the item`).
7. If `#` items, can be a **total loss** if actually a total loss in photos. Check photos to make sure.
8. **Total loss criteria**:
   - If they have their own box (clear box / plastic tote) → it's an item.
   - If no box (packed by ourselves) → total loss that's questionable.
   - If furniture or non-itemizing that's a total loss — verify with crew.
- Once done going through items in box, it'll be updated on `# Day`.
- Item to add to xlsx → **Sync app on available website**.
- Save xlsx as → **Last name Final Calculator**.
- Do it again as **xlsx workbook**.

### Xactimate (AAA contents)
- **Local → New Project**
  - Last → First → Contents
  - Carrier (if not from ins directly)
  - Find date for price (year + zip)
  - Tax = 8.75% (Riverside)
  - Add claim info (insured info)
  - Date of loss; date contracted (sometime is the same)
  - If no adj, add new
  - Update coverage + loss
  - Update statement (with client name + claim #)
- **Estimate** → **Estimate items**
  - New group: `Contents`
  - In new, click `notes` and create as a header (`Contents A`)
  - cat: `CPS`
  - sel:
    - Small Box = `BX <`
    - Medium Box = `BX`
    - Large Box = `BX >`
  - All others: search up in `sel` + Tab
  - Pad = paper blankets
  - Pad+ = blue blankets
  - BW wrap = bubble wrap 2ft (24in)
  - calc: `25ft`
  - Wrap = shrink wrap (no labor)
  - cat: `CPS`, sel: `Lab` (Labor) — calc: `(3*8)+(2*3)`
    - Add note: 3 techs for 8 hrs each = 24, plus 2 techs for 3 hrs each = 6, total 30 hrs
    - Add info for what was done if off-site too
- **Pack-out / Storage line items**
  - cat: `CPS`, sel: `Stor`
  - calc: `250 * 1` (250 sq ft @ $1/month for storage)
  - Note: `Tr = Box truck`
- **Pack-in (return)**
  - sel: `Lab`
  - calc: `2*4` (2 techs × 4 hrs each to pick up contents from insured's home and bring back to off-site storage facility — total 8 hrs)
  - Note: can use for justifying box truck.
- **Claim info** → reprices if copied items over.
- **Risk #s, resequence in `Doc → Reports`** to change coverage type.
- **Documents → Reports → Estimate Report**
  - Report: Final Draft → Marker on Contents Estimate.
  - New: download Photo Log Report and Total Loss Photo Report.

---

## 11. Forms Required per Job

Every job should have:

| Form | Keyword match |
|---|---|
| Auth to Perform | ATP / "auth perform" |
| Customer Info Form | CIF / "customer info" |
| Customer Equip Resp | CER / "customer equip" |
| Cert of Satisfaction | COS / "cert satisf" |
| Scope | "scope" |

**Carrier-specific extras:** Farmers, Travelers, Lemonade need 3+ additional forms (ATR, warranty, etc.).

**Commercial jobs** have their own paperwork set — the residential forms (ATP / CIF / CER / COS) are **not required**. Use the Run Audit's Commercial toggle on those rows.

The **Run Audit** tool checks all of these automatically.

---

## 12. Photos & Sketches

### Photos
- **Initial** — always required.
- **Reinspect** — if reinspect is in the log.
- **Demo** — if demo is in the log.
- **Mold Prep** + **Mold After** — if mold prep is in the log. "Mold After" covers the post-mold-prep visit; folder names `Post Mold Prep` / `Post Mold` / `Mold After` all satisfy it.
- **Mold** — if mold (any) is in the log without prep.
- **Abatement** — if abatement is in the log.
- **Post** — only when the run-doc explicitly says "Post" (e.g. "Post Demo" visit). Demo alone does **not** imply Post — post-demo photos come on a separate visit.
- For **Inspection-only** jobs, only initial pics are required + the photo report in DOCS.

### Photo folder naming
SharePoint root path is set in **Settings → Photos root folder** (defaults to `Servpro-10100 Photos - Photos` under your OneDrive).

Format: **`<TECH> <DATE> <CLIENT>`**
Example: `ML 4.24.26 Sanchez, Jacqueline`

The **Photo Folders** tool creates these for you per tech × job × date and won't duplicate ones that already exist.

### Fernando's photos
- Fernando uploads **directly to Workcenter**, not the SharePoint photo share.
- The Run Audit and Photo Folders panels show a purple **`WC (Fernando)`** badge on his rows so you don't go hunting in OneDrive.

### Docusketch
- `Tour_*_Order_*_all_sketches*.zip` downloaded from [app.docusketch.com](https://app.docusketch.com/portal-cc/projects).
- Extract into `DOCS\Docusketch\`.
- Must contain an `.esx` file to pass the audit.
- The Run Audit / Snapshot / Daily Photos panels each have a **📥 Import** button that does this automatically from Downloads.
- **After you've requested a Docusketch but it's not back yet**, click **📐 Mark Requested** in the import dialog — logs `📐 Docusketch was requested` on the matching Trello card (audit trail) and adds the job to the Hygiene tab's **Docusketch pending** section as a daily reminder. Auto-clears the moment you import the zip.

### Extra images added after the fact
- **Before the initial upload has gone out** → upload extras to **Xactimate only**.
- **After the initial upload has gone out** → upload extras to **BOTH Xactimate AND XactAnalysis**, then leave a quick XA note for the adjuster ("Additional photos uploaded to XactAnalysis for your review.").
- The Initial Upload state is the deciding factor — check the `INITIAL UPLOAD` box in the ADMIN checklist on the Trello card, or look for the canonical `Initial Upload submitted To WC.` comment to confirm whether it's been sent.

---

## 13. Escalation Rules

**Escalations go via Microsoft Teams DM** to the right person. Don't email — adjusters' inboxes are loud and Sam/Zac/George read Teams faster.

Escalate **to Sam (Claims) or Zac (Estimating)** when any of these fire:
- Job pending missing items **3+ business days**
- 3+ failed contacts with the insured
- Customer complaint
- High exposure / financial threshold approaching

Escalate **to George** (Sam/Zac only) when:
- Financial threshold exceeded
- Legal risk (lawyer / lawsuit / BBB language in correspondence)
- 10+ business days with no movement
- Unresolvable customer issue

Every Teams DM must include:
- **Current status** — where the job is right now
- **Last contact** — when, by whom, what was said
- **What we're waiting on** — specifically
- **Recommended next step**

The Hygiene tab's **🚨 Customer concerns** auto-flags Trello/inbox comments containing complaint, legal, BBB, refund, escalation language.
The Hygiene tab's **⚠ Hygiene violations** flags cards aged 3+ business days without a comment (the "pending 3+ days" rule above).

---

## 14. Accountability Standard

Every Trello card MUST have:
- **Assigned owner** (a Trello member, or `Owner: <name>` in the description)
- **Next action** — clear in the latest comment
- **Follow-up date** (Trello due date)
- A recent comment / note showing current state

When a card moves lanes, the **lane move = ownership transfer** — the moving party leaves a handoff note explaining what's been done and what the receiver needs to do next. One-word comments ("ok", "done") don't count.

The Hygiene tab's **⚠ Hygiene violations** + **🔄 Lane moves missing handoff** sections enforce this automatically. Cards missing any of the four (owner / next action / follow-up / activity) surface in the next scan.

---

## 15. Weekly Apology Note (Estimating Board)

Every open Estimating Board job that has gone quiet needs the standard apology comment posted **in XactAnalysis** (manually):

> *"Our apologies for the delay. Please note our estimating team is diligently working on the file."*

The Hygiene tab's **🔔 Apology reminders (XA)** lists AR Board cards that need this. Workflow:
1. Click **↗ Open** on the row → opens the Trello card so you can grab claim # / carrier / adjuster.
2. Click **📋 Copy note** → puts the apology text on your clipboard.
3. Paste into XA, post.
4. Click **✓ Done in XA** on the row → clears it from the worklist for ~a week.

---

## 16. Adjuster Inquiries (billing / status replies)

Adjusters email the EMS@ inbox or reply on existing threads. Standing rule: **respond same business day** with status / next step.

The local Outlook integration pulls inbound mail and matches each message to a Trello card by claim number / carrier domain / adjuster name. Matches are **queued for approval** in the Hygiene tab's **📨 Adjuster inquiries (approve to post)** section — nothing posts automatically.

### Why the approval gate exists
Realtors, contractors, environmental/mold vendors, and shared-mailbox handles (`clientservices@`, `operations@`, etc.) routinely reply to threads that carry a claim # in the body. Each false positive used to drop a bogus "📨 Email received from..." comment on a customer-visible card. The approval gate turns each new pattern into one ✕ Dismiss click instead of one ugly comment.

### Per-row actions
- **✓ Post** — drops the canonical receipt comment on the matched Trello card and records the post for idempotency (same email won't re-queue).
- **✕ Dismiss** — drops the entry AND remembers the message ID so re-scans don't re-queue the same false positive.
- The row shows the matched card, sender name + email, subject, body preview, and the **exact comment text** that ✓ Post would drop on the card. No surprises.

If a real inbound never lands in the queue, the matcher couldn't tie the email to a card — drop a manual comment with the gist.

---

## 17. Audits (AR / billing)

When auditing aged AR:
- **AR Aged** → Trello "Dropbox" → pull the job + read notes + check.
- **George's** for Greg's questions.
- **Storm CR** — separate flag.
- **Service Calls** — billed just for inspection.
- **Self pay** — separate flow.
- **Recoveries**.
- **Collection letters** start the notice process and gets resigned.
- **Pool collectors**.
- Everything is added to a spreadsheet & QuickBooks.
- Check estimates are the **same** as how much we'll bill.
- **Invoice, QuickBooks, Excel, and Trello must all align.**

### Xactanalysis
- Search via claim #.
- If insurance only shows estimate → it has a separate contents.
- Duplicate to local and make the profile carrier.
- If a profile in Xactimate has anything → it has a shell folder in Xactanalysis.
- An Xactimate "open" status means already completed → can't make changes (check only).

### Xactimate
- Cloud → search via claim #.
- If nothing pops up → search the name instead.
- If under Pablo or Victoria → most likely contents.
- Download files / grab from local.

### OneDrive (estimates)
- Mostly has the contents folder.
- File should be: **`Lastname — what was done (Contents Estimate)`**.
- Invoices help see the exact $.

---

## 17a. Dispute Tracker

Disputes are corporate (or carrier) pushbacks on a submitted audit that have to be responded to before the next-day midnight cutoff. The shared workbook is the source of truth; the **Dispute Tracker** launcher tool is the editable view.

### Where the data lives
- **Workbook:** `X:\IE_Public\Disputes\Dispute Tracker.xlsx` (or whatever path is set under **Settings → Dispute Tracker path**).
- The workbook itself often lives in a SharePoint / Teams Files chat — copy it locally for write access; the tool writes the canonical row, then a sidecar queue file when the xlsx is locked by Excel so changes aren't lost.

### How rows get in
1. **APA Monitor sync** — every reload of the APA doc scans for dispute-flagged rows and upserts any new ones into the workbook the first time they appear. The same row never gets re-inserted; subsequent changes only happen through the tool or the workbook itself.
2. **Email scan** — the Hygiene panel's hourly mini-scan calls `dispute_email_scan` against the EMS inbox and pulls in dispute-language messages (carrier replies, corporate notes containing *dispute*, *disputing*, *contests*, etc.). Already-seen message IDs are remembered so re-scans are idempotent.
3. **Manual add** — Dispute Tracker tool → **➕ Add** for anything the auto-imports miss.

### Working a dispute
1. Hygiene's ⚖ section flags the row with an aging chip. Double-click → opens the row in the tool.
2. Edit the cells the carrier replied to (resolution / sent / notes). Save.
3. Per-row ✓ **Mark sent** flips the Sent column to *Yes* and drops the row out of the open list.
4. If the dispute is overdue (next-day midnight passed), the Hygiene row turns red. Escalate via Teams per §13.

### Common dispute language to recognize in email
- *"This portion of the file is being disputed."*
- *"The auditor contests the labor line for…"*
- *"Please provide additional support for…"*
- *"Audit dispute"* / *"audit response required"* in the subject line.

---

## 18. Tech Initials

| Initials | Full Name |
|---|---|
| FB | Fernando (Baca) |
| ML | Mark L |
| ME | Mark E (Escobar) |
| GL | George |
| PG | Pablo |
| JL | Jose |
| AP | Aaron Perret |
| PCB | PCB *(used on New Loss lines)* |

**Adding a new tech:** Settings (gear icon) → **Manage Tech Roster…**. Type the name (and initials if dispatch lines use them) and Save. Every tool — snapshot, run audit, job notes — picks up the new name immediately, no restart needed.

The full built-in roster also includes the first names recognized in dispatch lines: Cesar, Nestor, Sam, Marco, Danny, Vince, Wendy, Robert, Pablo, Rudy, Sergio, Priscilla, Maria, Brenda, Elena, Vicente, Fernando, George, Jose, Aaron, Mark E, Mark L, Melvin.

---

## 19. Launcher Tools (in order of daily use)

| Tool | Purpose |
|---|---|
| **Run Audit** | First thing in the morning. Audits every job on today's run doc — forms, Docusketch, photos, SharePoint cross-check. Also has 🔍 Audit One Job, 📁 Photo Folders shortcut, 📌 Flag missing per row, 📨 Requested Nd ago chip per missing item, and 📋 Missing items list per row. Right-click any row for Change Folder / Open XactAnalysis / Add to property / Pin OD folder. Auto-descends into `2nd Claim` / `Third Claim` subfolders. **↺ Run Audit** in the toolstrip and any "card refresh hiccup" fallback re-runs **whatever audit you're in** — single-job mode stays in single-job mode instead of jumping back to the daily run. |
| **Initial Upload Queue** 📋 | Today's Initial Upload work. Pulls cards from the four canonical Trello lanes (WORK IN PROGRESS / Initial Uploads / On Hold / Daily Run) AND merges in any APA Monitor "Initial Uploads" rows that aren't on Trello yet. Time-slot pill from the run-doc. ➕ Add manually for off-Trello tracking. 📌 Flag missing + 📨 Trello comment buttons per row mirror Run Audit. |
| **Photo Folders** | Creates the SharePoint photo folder for each tech × job × date. Auto-detects which already exist. Also has Cleanup Empty Photo Folders. Shows 📤 WC (Fernando) badge on his jobs. Run-doc-driven (daily) — not tied to job creation. |
| **APA Monitor** | Tracks APA jobs by section. Daily docs in `X:\IE_Public\APA Monitor\<Year>\<Month>\<M-D-Weekday>.docx`. Send reminders to estimators via Teams (msteams: URL scheme). Auto-rolls over at midnight (with confirm prompt). 🔁 N× extended badge per row tracks repeat slips. Sections are user-reorderable. |
| **EMS Snapshot** | Build snapshot PDF from Trello comments. Audit Only button hands off to Run Audit. ✓ Mark drafted auto-fires on generate; the row drops out of Hygiene's Ready for Snapshot section. PDFs auto-attach to the Trello card with a consolidated "missing items" comment. Overflow past 8 subs / 53 logs renders ReportLab continuation pages. |
| **Hygiene** ⚠ | End-of-day check, three sub-tabs. **🔴 Action Needed**: weekly / estimates / 📨 adjuster pending / ⚖ disputes / concerns / IPR / XA apology / Docusketch / Docusign / Docusign resends / Missing. **⚠ Trello quality**: hygiene rules / handoff / closeout / all open Trello jobs. **📝 Stale notes**: XA gaps. Pulls from Trello + local Outlook (Classic Outlook desktop must be running). Sections collapse past 5 rows. Most automatic-clear flows are wired (IPR via "uploaded"/"done" reply, Docusketch via zip import, closeout via snapshot generate). Hourly mini-scan refreshes XA gaps + estimates + adjuster-pending + ⚖ disputes without a full Trello rescan. |
| **Dispute Tracker** ⚖ | Editable view of `Dispute Tracker.xlsx`. Treeview with filter dropdowns by sheet / status / sent. ➕ Add for off-board disputes; 📝 Edit on any row opens the cell-by-cell dialog. Pending-write sidecar queue handles Excel-locked-file saves so nothing's lost while the workbook is open. See §17a. |
| **Spreadsheets** | Workbook registry — Snapshots, Initial Photo Reports, Estimate Requests, Dispute Tracker, plus any workbook the user adds via the in-UI **➕ Add** button (no code change required — pick the xlsx, pick the header row, save). 🧹 Dedupe rows surfaces case/whitespace/comma-swap dupes with dry-run preview before deleting. ✕ Remove on user-added entries; built-ins are fixed. |
| **Multi-Unit** 🏢 | Commercial properties with multiple unit subfolders (e.g. `Avila Apartments 2026/Unit 1017/`, `Unit 1416/`, …). Auto-discovers any year-folder child with ≥1 `Unit …` subfolder; per-unit forms/photos audit chips at a glance. Secondary "Linked properties" section shows manually-grouped folders (right-click any audit row → **Add to property…**). 🏢 chip on audit/IUQ/Hygiene marks multi-unit rows. |
| **KPI** 📈 | Weekly metrics + repeat offenders + right-now hygiene snapshot + ⏱ Cycle time (median / p90 days open + longest-open jobs). Read-only aggregate view. |
| **Audit Backlog** | History of all audits, organized by week. Stale-flagged-jobs banner has a 🔍 Audit these button to re-audit forgotten jobs. Audit count bumps once per calendar day per job (not per re-run). |
| **Job Notes** | Free-form Trello-style notes per client. Auto-parses stages (Initial / Demo / Mold Prep / Reinspection) and shows them in the audit timeline. |
| **New EMS Job** | Folder structure for a new claim. Hidden from the launcher strip by default — opt in via Settings. |
| **Sort Files** | Move Downloads into the correct job folder on `X:\`. Hidden from the launcher strip by default — opt in via Settings. |
| **Cheat Sheet** | This document, searchable in-app. |
| **Settings** *(gear icon)* | Configure folder paths, Workcenter URL, Tech Roster, preferred browser, dark mode, hidden-tool checkboxes, 🔄 Sync from Trello (refreshes the ems_db job index). |

### Right-click everywhere
Every audit / IUQ / snapshot / APA / SP-recent / Hygiene row has the **same right-click menu**: Change Folder, Pin OD folder, Open XactAnalysis link, Add to property, Open card. Inline override buttons (the legacy ⇄ on audit rows) are deprecated — use the right-click menu so workflows stay identical across panels.

### SP Recent pinning (when a SharePoint photo doesn't pair with a job)
SP Recent surfaces newly-added SharePoint files that didn't auto-match an existing job. **📌 Pin → <client>** does two things now:
1. Writes an SP-match override so this SP folder always lands on this client in the future (no more re-matching the same `Wuetcher post pics`).
2. Also writes the OD folder path for the client (with an OD-picker fallback if it can't infer one), so the next audit row uses the pinned folder.

If a job stays in SP Recent after you've pinned it, the override didn't take — re-run the pin and confirm the OD folder picker shows the right path.

---

## Notes on This Document

Transcribed and consolidated from handwritten training notes. As the workflow evolves, **update this doc directly** rather than re-writing in the notebook. The Cheat Sheet panel re-reads this file on launch.
