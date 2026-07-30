# EMS Tools — Software Audit (what we use vs. don't)

*Compiled 2026-07-29 from the built-in usage tracker (`usage.db`) + code inventory.*

## Method & the one caveat
- **Hard data:** 1,610 recorded UI actions over **7 days (7/23–7/29)**. The tracker only
  instruments **Audit + Snapshot** — so click counts rank features *inside those two tools*
  reliably, but say nothing about the other panels. For those, the verdict is reasoned from
  redundancy/workflow, flagged **[reasoned]**.
- **7 days is short.** A zero-click item that's genuinely *situational* (multi-unit only, debug
  only) is judged on *why* it's unused, not just the count. Counts below are 7-day clicks.

---

## 1. Audit right-click menu — 30+ items, the main bloat

### KEEP — top-level, earn their place
| Item | Clicks | Why |
|---|---|---|
| 📁 Open OD folder | **81** | The single most-used action after import. Core. |
| Open Trello card | 58 | Core navigation. |
| 📂 Stage PICS for XA | 26 | Real daily estimating step. |
| 📋 Copy claim # | 41 | Daily. |
| 📋 Copy client name | 32 | Daily. |
| 📋 Copy path | 18 | Daily. |
| 📸 Open in Snapshot | 15 | Cross-tool jump, core. |
| Open CompanyCam | 8 | Used, and central to the photo workflow. |
| ↻ Re-audit this job | 8 | Core. |
| Open XactAnalysis | 7 | Core (once the link bug is behind us). |
| 🔀 Change / Find folder | 2 | Low count but **essential** when a folder's misfiled — keep. |
| 📎 Trello attachments | 1 | Low, but the only way to see card files — keep. |
| 🗂 Past claims | 1 | Low, situational (repeat customers) — keep. |

### CONTEXTUAL — keep the feature, but only show it on rows that need it
| Item | Clicks | Verdict |
|---|---|---|
| 🏠 Pick day-units | **0** | Multi-unit jobs only. Not useless — **wrong to show on every row.** Show only on multi-unit/umbrella rows. |
| 🏢 Property structure & settings | **0** | Same — multi-unit only. Make it contextual, not global. |

### CUT or DEMOTE — zero use + a better path already exists
| Item | Clicks | Why cut |
|---|---|---|
| 🔎 Match diagnostic | **0** | **Developer/debug tool**, not a daily action. Move behind a debug/settings flag, off the job menu. |
| 📌 Pin Trello card | **0** | Pinning is **automatic on audit** now — manual pin is redundant. |
| 💬 Post comment | **0** | Redundant with the 🗒 XA note + Docusketch/paperwork comment paths. Keep one comment path. |
| 📄 Show OD files/folders | **0** | Redundant with "Open OD folder" (81) — you just open the folder. |
| 📖 Job tracker (activity + who) | **0** | Unused; its value folds into the future CRM Job record. Demote. |
| 🧠 Client memory | **0** | Power-user memory editing. Collapse with the three memory items below into one **"Advanced ▸"** submenu. |
| 🏷 Edit search aliases | 0 | → Advanced submenu. |
| 🏢 Add to property | 0 | → Advanced submenu. |
| 🧹 Clear saved folder path | 0 | → Advanced submenu. |
| 📋 Copy issue list | 0 | Overlaps the snapshot missing-items comment. Demote/cut. |

**Net:** ~13 keep top-level, 2 become contextual, ~8 collapse into one "Advanced ▸" submenu or get
cut. The menu goes from a 30-item wall to a ~15-item list that matches how you actually work.

---

## 2. Audit top-bar buttons
| Button | Clicks | Verdict |
|---|---|---|
| 📥 Import / Extract / rescan (job-import flow) | 133 / 110 / 91 | **KEEP** — the busiest thing in the app. |
| Mode: Daily / Search / Starred | 46 / 11 / 4 | **KEEP** Daily + Search. Starred is barely used — consider folding into a filter. |
| ⋯ More actions | 14 | **KEEP** (now that low-use buttons live under it). |
| 🆕 New Loss | 7 | **KEEP** — real intake step (and the front door to the CRM). Paste box just enlarged. |
| 📥 **Incoming** | **1** | **CUT.** See §4 — redundant with Quick Import + per-job import + CompanyCam pull. |
| 🆕 New loss *filter* | 1 | Low; fine to keep (cheap). |

---

## 3. Whole panels (launcher) — **[reasoned]**, not in the click data
Only **Audit + Snapshot** saw any activity in 7 days. The rest are periodic or background —
so the question isn't "delete the panel," it's "is the *underlying automation* worth it even
when the panel is rarely opened."

| Panel | Verdict | Reasoning |
|---|---|---|
| **Audit** | KEEP | The cockpit. |
| **Snapshot** | KEEP | Second-most used; the handoff artifact. |
| **Hygiene** | KEEP (panel demoted) | You already toggle it hidden. The *panel* is rarely opened, but its trackers (estimate SLA, missing items, IPR, disputes) do real background work. Keep the automation, keep the panel available, don't feature it. |
| **KPI** | KEEP-LITE | Weekly/monthly glance, not daily. Fine hidden behind the toggle. |
| **Pipeline** | RE-EVALUATE | Newer; low evidence it's used. Watch it a month; cut if it stays cold. |
| **WC Audit** | KEEP-LITE | Monthly by design — hidden toggle is correct. |
| **Notifications** | RE-EVALUATE | Overlaps Trello's own notifications. Justify or cut. |
| **Multi-unit** | KEEP | Small but load-bearing for apartment jobs. |
| **Photo Folders** | KEEP-LITE | Daily-run helper; keep. |
| **Disputes / Spreadsheets** | KEEP-LITE | Reference viewers; hidden toggle is right. |
| **Sort Files / New EMS Job** | ALREADY HIDDEN | Correct — superseded by Quick Import + New Loss. |
| **Settings** | KEEP (pinned) | Correct as-is. |

**Theme:** you've already made the right call by adding hide-toggles. The next step isn't deleting
panels — it's making sure each *hidden* panel's background automation still runs and reports
(badges), so a rarely-opened panel isn't a dead panel.

---

## 4. The 📥 Incoming button — verdict: **CUT**
It scans Downloads for importable files (WC dumps / DocuSign paperwork) and lets you assign a job
without finding the row first. **1 click in 7 days.** Everything it does is now covered:
- Job-agnostic "find the job, then import" → **Quick Import** (the whole point of that tool).
- Per-job imports → the row's **Import from SharePoint / Stage for XA / WC import** buttons.
- CompanyCam → the new **API pull** (no Downloads round-trip at all).
The only sliver it uniquely handles is auto-detecting **DocuSign paperwork** in Downloads → DOCS.
That's worth preserving **as a Quick Import capability**, not a second button in the main audit.
**Recommendation:** remove `📥 Incoming` from the audit; port the DocuSign-paperwork detection into
Quick Import if it isn't already there.

---

## 5. CompanyCam as a DocuSign replacement — verdict: **partial**
- ✅ CompanyCam **Signatures is a real product feature** — request/track/collect e-signatures on
  documents (change orders, contracts), auto-populated from Project/Report templates, with
  automatic reminders. Fully usable **in the CompanyCam web/mobile app today** — so you *can* stop
  paying for DocuSign for the manual workflow.
- ❌ **There is no signature API.** The CompanyCam API exposes only *List Project Documents* and
  *Upload a Document* (plus checklist templates). No endpoint to create a signature request, send
  it, or read signed status.
- **Confirmed:** CompanyCam's signature system is powered by **Dropbox Sign** (formerly HelloSign)
  under the hood — there's no CompanyCam-native signature API to hook, so the flow stays **manual
  in the CompanyCam app**. That's fine per the decision on 2026-07-29.
- **What that means for us:** we can **API-push** the forms that need signing into the right
  CompanyCam project (automate delivery), but "send for signature + collect" is a **manual step in
  CompanyCam**, and signed-status won't flow back into the EMS trackers automatically. No
  signature-automation work to do on our side — just adopt the manual flow if/when we drop DocuSign.

---

## Recommended action batch (pending your OK — this deletes real features)
1. **Audit menu diet:** keep the 13 top-level, make Pick-day-units + Property-structure contextual,
   collapse the 4 memory items into "Advanced ▸", cut Match-diagnostic (→ debug), Pin-card,
   Post-comment, Show-OD-contents, Copy-issue-list.
2. **Remove 📥 Incoming**; move DocuSign-paperwork detection into Quick Import.
3. **Re-evaluate Pipeline + Notifications** over the next month; cut if still cold.
4. **CompanyCam signatures:** pilot the manual in-app flow for one job; ask CompanyCam re: a
   signatures API; if yes, wire status-back later.

*Already done this session: New Loss paste box enlarged. Nothing else deleted yet — awaiting your
go on the batch above.*
