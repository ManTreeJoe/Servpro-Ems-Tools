# Live run doc — plan

**Goal:** 2–3 people edit the day's run doc at the same time inside Linguar
Hub and see each other's changes live. The `.docx` is still produced, so it
can be printed exactly as it is today.

Chosen over full Google-Docs-style rich-text collaboration (CRDT + editor +
websocket server, weeks–months) because the run doc is not prose. It is a
list of job lines in two sections. Concurrent editors touch different
*lines*, never the same sentence, which is an ordinary shared-table problem.

---

## 1. The constraint that shapes everything

`run_doc._parse_run_doc_entries` is **lossy**. From a line like

```
3. Keystone-Highland Village (Anibal Humberto) (Unit 168): 168 W. Main St,
   Temecula 92591 951-555-1212 (water) JD/FB
```

it keeps `client`, `unit`, `tenant`, `claim_hint`, `new_loss`, techs — and
throws away the numbering, the `(...)` groups, the exact spacing, and every
line it does not recognise (struck lines, `warehouse` lines, section
headers, anything unparseable).

**Therefore: the row stores the raw line as authored.** Parsed fields are a
derived read-time view, never the source. Regenerating a `.docx` from
parsed fields would silently reformat the document and drop content nobody
noticed was being dropped — the same mistake `render_desc` already had to
learn in `job_settings` (rewrite line by line; an untouched line goes back
byte-identical).

This single decision is what makes the print requirement safe.

---

## 2. Schema

```sql
create table run_days (
  id            uuid primary key default gen_random_uuid(),
  department    text not null,              -- 'IE' | 'OC'
  run_date      date not null,
  docx_path     text,                       -- where the printable file lands
  created_at    timestamptz default now(),
  updated_at    timestamptz default now(),
  unique (department, run_date)             -- one run doc per dept per day
);

create table run_entries (
  id            uuid primary key default gen_random_uuid(),
  run_day_id    uuid not null references run_days(id) on delete cascade,
  section       text not null,              -- 'work' | 'monitor' | 'other'
  pos           double precision not null,  -- Trello-style gap ordering
  raw_text      text not null,              -- AS AUTHORED. source of truth.
  struck        boolean not null default false,
  canon_key     text,                       -- resolved job, when known
  updated_at    timestamptz default now(),
  updated_by    text
);
create index on run_entries (run_day_id, section, pos);
```

`pos` uses gaps (1024, 2048, …) so inserting between two lines is one write
and never renumbers the rest — the same trick Trello uses, and we already
sort by it in `trello_client.order_checklists`.

`struck` stays a real column: strikethrough is *meaning* in this document
(the parser skips struck lines), not styling.

---

## 3. Concurrency

Row-level, which is all this needs:

- **Realtime subscription** on `run_entries` filtered by `run_day_id`.
  Postgres change → websocket → the other panels patch that one row.
- **Per-row last-write-wins**, but only ever on the row being edited. Two
  people on different lines never conflict at all.
- **Soft lock / presence**: while someone has a line focused, others see it
  greyed with their name. Not enforced — advisory, like Excel's shared mode.
  Enough for 3 people who can also talk to each other.
- **Optimistic UI**: apply locally, then reconcile from the realtime echo.

No CRDT, no OT, no custom server. Supabase Realtime is already sitting on
the Postgres we migrated to (5,075 rows, 16/16 conformance) — we have simply
never subscribed to it.

---

## 4. The `.docx` (the print requirement)

Rows are the source of truth; the file is a **rendered artifact**, like the
snapshot PDF.

`run_doc.write_run_doc(path, run_day, entries)` — new, mirrors
`apa.write_doc`:

1. Date header line, current format.
2. `WORK TO BE PERFORMED` heading, then its entries by `pos`, numbered on
   the way out.
3. `MONITOR` heading, then its entries.
4. Each entry writes `raw_text` verbatim, with `strike=True` when `struck`.

Round-trip test, and it is the one that matters: parse today's real `.docx`
→ rows → write → parse again → **identical `(jobs, run_date)`**. Anything
less and printing silently drifts from what people typed.

**When it writes:** debounced ~2s after the last edit, plus an explicit
🖨 Print/Export. Not on every keystroke — it is a file on a synced folder,
and OneDrive does not need 400 versions of it.

**Keep `_preserve_mtime`.** OD-on-demand stamps today's mtime when it
materializes a file; that logic already exists in `parse_run_doc` and the
writer must not undo it.

---

## 5. Migration

1. Backfill: for each existing `.docx` in `runs_dir`, create a `run_days`
   row and one `run_entries` row per paragraph (raw text + struck), keeping
   section and order. Dry-run first, like `backfill_carriers.py`.
2. The audit reads rows when a `run_day` exists for that date, else falls
   back to parsing the file. Both paths live side by side until trusted.
3. `parse_run_doc` stays regardless — it is how a file becomes rows, and it
   is still the OC `.msg` intake.

---

## 6. Answered (2026-08-12)

**1. Word editing goes away — the sync is ONE-WAY.** ⚠ **SUPERSEDED 2026-08-24 — see 1a below.** The reasoning is kept because it still explains what one-way buys, and 1a gives up only part of it.

**1. (original)** People open the doc in
Word today, but the intent is that the run doc is authored in the software
and the `.docx` becomes an export for printing only.

This is the biggest simplification available. One-way means:
- no file→DB import, no change-watcher on `runs_dir`, no "the file and the
  DB disagree" state to resolve;
- the `.docx` can be regenerated from scratch at any time;
- the round-trip test in §4 stays a *migration* check (old docs import
  cleanly once), not a permanent correctness requirement.

⚠ It needs a transition, though. Until everyone has stopped, an edit made
in Word is silently discarded on the next export. Phase 2 should mark the
exported file **read-only on disk** and stamp a header line —
"Generated by Linguar Hub — edit in the app, not here" — so the failure is
loud instead of silent.

**1a. REVISED 2026-08-24 — Word stays, as a live *view* plus a recovery path.**

The ask changed: keep Word's familiar live-editing feel, but add the
drag-and-drop quick tools. Literal two-way co-authoring is still rejected —
Word Online and the Hub writing the same day at once is two live writers
with no shared lock, and §1's lossy parser makes a silent Word round-trip
unsafe. Instead:

- **The app stays the only editor.** Drag-drop rows, quick-edit chips,
  Realtime presence. Unchanged from phases 2–3.
- **Word becomes a live view.** The `.docx` is re-exported on save into the
  Run library; Word Online refreshes it in place, so anyone watching sees
  the day fill in. Keep the "Generated by Linguar Hub — edit in the app,
  not here" header stamp.
- **Drop the read-only-on-disk idea** from item 1. The file must stay
  openable, and a hard lock only pushes people into Save-As copies.
- **Word edits are recovered, not discarded.** Before each export, line-diff
  the file on disk against the stored `raw_text`. Changed, added, or removed
  lines surface in the panel as a *"Word edits detected — accept / discard"*
  review strip. Accepting writes the line into `raw_text` verbatim; nothing
  is auto-merged and nothing is parsed on the way in. Cheap, because rows
  are raw lines.

**Consequence for §4:** the round-trip test is **no longer just a migration
check** — it is a permanent correctness requirement. Every export is diffed
against a file real people may have touched, so parse → rows → write →
parse must stay exact for as long as Word is in the loop. Phase 0 matters
more under this decision, not less.

**In-Hub preview:** do not try to embed Word Online in the panel — Graph and
Azure are blocked ([[project_graph_blocked]]) and pywebview's webview will
not reliably carry the SSO session. Render the `.docx` to HTML for the
preview pane and put an "Open in Word" button beside it.

**2. OC moves to the same format.** OC stops parsing the emailed `.msg` and
types into the same table. `msg_reader` + the `.msg` branch of
`parse_run_doc` stay for backfilling historical docs and as a fallback.

**3. Offline — recommendation: online to EDIT, always available to READ.**

The ask was "it needs to still work, without things overlapping too much".
Those pull against each other, and the honest answer is to give up offline
*editing* rather than take on merge complexity:

- Keep a local SQLite mirror, refreshed on every sync. If the network
  drops, the run doc goes **read-only** with a clear banner, and viewing,
  printing and `.docx` export all keep working from the mirror.
- Editing resumes automatically on reconnect. Brief blips are invisible.
- **Do not queue offline edits.** Two people editing the same run doc
  offline and reconciling later is precisely the "overlap" problem — and
  it is rare, because a run doc is a morning-coordination document that
  gets written once and read all day.

The `.docx` export is itself the offline safety net: it already sits on a
synced folder and prints. If the internet is down at 8am, the exported
copy is what the office actually uses — which is what happens today.

If offline editing later proves genuinely necessary, the escape hatch is
single-writer: one machine claims the day's run doc, edits offline, and
pushes on reconnect. Still no merge. Not worth building until asked for.

**4. Still open:** who may edit — everyone, or a named set?

---

## 7. Phasing

| phase | scope | rough |
|---|---|---|
| 0 | Round-trip harness: parse → rows → write → parse, on real docs | 1 day |
| 1 | Schema + backfill + audit reads rows (no editing yet) | 2–3 days |
| 2 | Editing UI, single user, `.docx` export on save | 2–3 days |
| 3 | Realtime subscribe + presence + soft locks | 2–3 days |
| 4 | Read-only mirror + offline banner (no edit queue) | 1–2 days |
| 4a | Word-edit review strip: line-diff on disk vs `raw_text`, accept/discard | 1–2 days |
| 5 | OC onto the same table; retire the .msg intake | 1–2 days |

Phase 0 first: if the round-trip is not exact on real documents, everything
above needs rethinking, and that is a day well spent finding out.

**Do not start phase 1 while the two-machine trial is still settling** —
changing the audit's input format and the deployment at the same time makes
any failure ambiguous.
