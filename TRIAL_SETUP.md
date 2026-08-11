# Shared-database trial — two PCs, one job index

Goal: your PC and one coworker's PC read and write the **same** job index
(identities, folder/Trello/CompanyCam links, unit & claim hierarchy,
Trello stage history) instead of each keeping its own copy.

Run `python trial_preflight.py` on **both** machines at any point. It
checks every item below and tells you which one is the reason if
something isn't working.

---

## What is actually shared

| Table | Rows | What it holds |
|---|---|---|
| `jobs` | 418 | One row per **client**. Identity, department, and the v6 job record — address, phone, email, carrier, claim #, adjuster name/email/phone, agent, deductible, date of loss, date received, cause of loss, XA id, WorkCenter project id. |
| `job_aliases` | 452 | Every spelling that means the same client. |
| `job_links` | 709 | `folder_path` (352), `trello_card` (351), `companycam_project` (6). |
| `job_children` | 139 | Units (55), sub-jobs (76), claims (9) under a client. |
| `job_lifecycle` | 3175 | Trello cards + current stage. |
| `job_stage_transitions` | 229 | Stage moves with days-in-stage. |

**Not** shared: `state.json` and its sidecar caches (resolved issues,
closeout ledger, missing items, tracker state) are still per-machine.

Job facts are now IN the database rather than only on the Trello card —
`backfill_job_facts.py` filled 292 of the 301 carded jobs from their card
descriptions. Coverage: address 292, date of loss 276, phone 264, carrier
241, claim # 222, adjuster 210, adjuster email 190, deductible 104, XA id
77. `wc_project_id` is 0 — it isn't on any card yet, so it gets typed
into ⚙ Job info (or added to the card) as jobs come through.

Re-run `backfill_job_facts.py --dry` any time; it only ever fills blanks
and never overwrites a value someone corrected by hand.

---

## One-time, on the admin side

1. **Supabase → Authentication → Users → Add user**, with your
   coworker's email. Signup is disabled, so they can't self-register.
2. **SQL editor → run `supabase/002_grant_access.sql`.** Until they have
   a row in `app_user_departments` they sign in fine and see *nothing* —
   that's RLS working, not a bug.
3. Confirm: the last query in that file lists each email and department.
4. ⚠ **SQL editor → run `supabase/005_crm_columns.sql` BEFORE anyone
   switches to the shared backend.** It adds the v6 job-record columns.
   Until it runs, saving a job against the cloud fails with a PostgREST
   400 on the first missing column. `trial_preflight.py` blocks on this,
   so you'll see it before it bites. Then push the backfilled values up
   with `python migrate_to_supabase.py`.

## On each PC

1. Install the current build (see below). First run seeds
   `%APPDATA%\Linguar Hub\config.json` from the bundled config, which now
   carries the Supabase URL + publishable key, the Trello app key, both
   department profiles, and the franchise identity.
2. **Settings → Connect Trello.** Personal, per user — the shipped config
   deliberately has no token in it.
3. **Settings → ☁ Shared job database →** send code, enter the 6-digit
   code, then **Use shared**. (Or `python trial_preflight.py --cloud`.)
4. Re-run `trial_preflight.py`. You want `READY`.

## Verify the two PCs really are joined

On PC A, pin a folder or Trello card to any job. On PC B, hit re-audit —
the pin should already be there. If it isn't, `trial_preflight.py` on
PC B will say why (usually: still on the local backend, or no department
grant).

---

## Known issues to respect during the trial

- **Do not run the old "EMS Tools" build.** It still writes to
  `%APPDATA%\EMS Automation`, which is a *different* folder from
  `%APPDATA%\Linguar Hub`. That already cost one job (`norberto
  collins`). Uninstall it or leave it closed.
- **Offline is queued, not lost.** Dropping the network makes reads come
  from the local mirror and writes queue to `ems_db_queue.jsonl`.
  Settings shows the pending count with a 🔄 Sync button. Replay is FIFO
  and stops at the first failure, so a stuck item blocks the rest — check
  the count if something isn't propagating.
- **Bulk operations refuse offline** rather than queueing (`merge_jobs`,
  purges, backfills). Do those online.
- A coworker's local mirror starts empty. That only matters offline;
  online they read the cloud directly.

---

## Building the current version

Inno Setup is **not** installed on this machine, so there is no installer
right now. For two PCs the folder build is simpler anyway:

```
cd scripts
build.bat                       # -> dist\Linguar Hub\
```

Zip `dist\Linguar Hub\` and copy it to the other PC. The `.exe` needs the
`_internal\` folder beside it. To produce a real installer later, install
Inno Setup 6 and run the command in the header of `Linguar_Hub.iss`.

If you change any shared setting, regenerate what ships:

```
python _packaging/make_shipped_config.py
```

`tests/test_shipped_config.py` guards it both ways — a missing shared key
fails, and so does a personal token or a `C:\Users\...` path sneaking in.
