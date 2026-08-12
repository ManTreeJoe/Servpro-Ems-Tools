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

## 6. Open questions

1. **Offline.** The Supabase offline queue is still pending. If the internet
   drops at 9am, does the run doc keep working? If yes, the local SQLite
   mirror becomes primary and Realtime is an overlay — a bigger build.
   *Needs an answer before coding starts.*
2. **OC is `.msg`, not `.docx`.** OC's run doc arrives as an Outlook email.
   Does OC move to the live table too (typing instead of receiving an
   email), or stay file-based?
3. **Does anyone open the run doc in Word directly?** If yes, the DB cannot
   be the only source of truth and we need file→DB import on change
   detection, not just DB→file export. This one decides whether the design
   is one-way or two-way.
4. Who may edit — everyone, or a named set?

---

## 7. Phasing

| phase | scope | rough |
|---|---|---|
| 0 | Round-trip harness: parse → rows → write → parse, on real docs | 1 day |
| 1 | Schema + backfill + audit reads rows (no editing yet) | 2–3 days |
| 2 | Editing UI, single user, `.docx` export on save | 2–3 days |
| 3 | Realtime subscribe + presence + soft locks | 2–3 days |
| 4 | Offline behaviour, per Q1 | ? |

Phase 0 first: if the round-trip is not exact on real documents, everything
above needs rethinking, and that is a day well spent finding out.

**Do not start phase 1 while the two-machine trial is still settling** —
changing the audit's input format and the deployment at the same time makes
any failure ambiguous.
