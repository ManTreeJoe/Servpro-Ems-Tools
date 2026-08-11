"""Shared-database trial preflight — run this on EVERY machine.

    python trial_preflight.py            # check only
    python trial_preflight.py --cloud    # also switch this PC to the cloud DB

Answers one question: will this PC read and write the same job index as
the other PC? It checks config, credentials, sign-in, department access,
the backend switch, and the file paths the panels need — and says which
of those is the reason if the answer is no.

Read-only unless you pass --cloud. Nothing here writes to the shared
database.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

OK, WARN, FAIL = "  OK  ", " WARN ", " FAIL "
_results = []


def check(label, state, detail="", fix=""):
    _results.append((state, label, detail, fix))
    print(f"[{state}] {label}" + (f" — {detail}" if detail else ""))


def main():
    go_cloud = "--cloud" in sys.argv
    print("=" * 68)
    print("  Linguar Hub — shared database preflight")
    print("=" * 68)

    import paths
    print(f"\nversion {paths.VERSION} · channel {paths.CHANNEL}")
    print(f"data dir  {paths.DATA_DIR}")

    # ── 1. Data-directory split ───────────────────────────────────────
    legacy = os.path.join(os.environ.get("APPDATA", ""), "EMS Automation")
    if os.path.isdir(legacy) and os.path.abspath(legacy) != os.path.abspath(
            paths.DATA_DIR):
        newer = ""
        try:
            lg = os.path.getmtime(os.path.join(legacy, "state.json"))
            cur = os.path.getmtime(paths.data("state.json"))
            if lg > cur:
                newer = " and it is NEWER than the current one"
        except OSError:
            pass
        check("Old EMS Automation data folder", WARN,
              f"still present{newer}",
              "The old EMS Tools build writes there. Don't run it during "
              "the trial or your two PCs will disagree.")
    else:
        check("Single data folder", OK)

    # ── 2. Config ─────────────────────────────────────────────────────
    import config
    cfg = config.load()
    for key, why in (("supabase_url", "shared DB address"),
                     ("supabase_anon_key", "shared DB key"),
                     ("trello_api_key", "Trello app key")):
        if (cfg.get(key) or "").strip():
            check(f"config: {key}", OK)
        else:
            check(f"config: {key}", FAIL, f"missing ({why})",
                  "Reinstall from the current build, or paste it in "
                  "Settings.")

    tok = (cfg.get("trello_token") or "").strip()
    check("Trello signed in", OK if tok else WARN,
          "" if tok else "no per-user token",
          "" if tok else "Settings → Connect Trello (each person does "
                         "this once; it is personal, not shared).")

    dept = cfg.get("active_department") or "(none)"
    check("Active department", OK if dept != "(none)" else WARN, dept)

    # ── 3. Supabase reachability + identity ───────────────────────────
    import supabase_client as sb
    if not sb.is_configured():
        check("Shared DB configured", FAIL, "no url/key")
        return _summary()

    h = sb.health()
    if h.get("reachable"):
        check("Shared DB reachable", OK)
    else:
        err = str(h.get("error") or "")
        hint = ("Project looks PAUSED or down. Open the Supabase dashboard "
                "and resume it." if "521" in err or "503" in err
                else "Check the network / URL.")
        check("Shared DB reachable", FAIL, err.strip()[:80], hint)
        return _summary()

    user = sb.current_user()
    if user and sb.is_signed_in():
        check("Signed in", OK, user.get("email", ""))
    else:
        check("Signed in", FAIL, "not signed in",
              "Settings → ☁ Shared job database → send code, then enter it.")
        return _summary()

    # Department membership — RLS returns rows only for granted departments.
    try:
        rows = sb.rest("GET", "app_user_departments",
                       params={"select": "department"}) or []
        depts = sorted(r.get("department") for r in rows if r.get("department"))
        if depts:
            check("Department access", OK, ", ".join(depts))
            if dept not in depts:
                check("Active department is granted", FAIL,
                      f"signed-in user has {depts}, app is set to {dept}",
                      "Run supabase/002_grant_access.sql, or switch "
                      "department in Settings.")
        else:
            check("Department access", FAIL, "no rows",
                  "You can sign in but will see NOTHING until an admin runs "
                  "supabase/002_grant_access.sql for your user.")
    except Exception as ex:
        check("Department access", FAIL, f"{type(ex).__name__}: {ex}")

    # ── 4. Can we actually read the shared jobs? ──────────────────────
    try:
        rows = sb.rest("GET", "jobs",
                       params={"select": "canon_key", "limit": "5"}) or []
        check("Read shared jobs", OK if rows else WARN,
              f"{len(rows)} row(s) visible",
              "" if rows else "Signed in but no jobs visible — usually the "
                              "department grant above.")
    except Exception as ex:
        check("Read shared jobs", FAIL, f"{type(ex).__name__}: {ex}")

    # ── 4b. Cloud schema is up to date ────────────────────────────────
    # The v6 CRM columns are added by supabase/005_crm_columns.sql, which
    # only a human can run (DDL needs the SQL editor). If the app writes a
    # job before that runs, PostgREST rejects the whole row with a 400 on
    # the first unknown column — so catch it here rather than on a save.
    try:
        import ems_db_sqlite as _sq
        probe = ",".join(_sq.CRM_COLUMNS)
        sb.rest("GET", "jobs", params={"select": probe, "limit": "1"})
        check("Shared DB schema (v6)", OK, "CRM columns present")
    except Exception as ex:
        missing = str(ex)
        check("Shared DB schema (v6)", FAIL,
              missing.strip()[:70],
              "Run supabase/005_crm_columns.sql in the Supabase SQL "
              "editor BEFORE using the shared backend — job saves will "
              "fail on every missing column until you do.")

    # ── 5. Backend switch ─────────────────────────────────────────────
    backend = (cfg.get("ems_db_backend") or "sqlite").strip().lower()
    if backend == "supabase":
        check("Backend", OK, "supabase (shared)")
    elif go_cloud:
        cfg["ems_db_backend"] = "supabase"
        config.save(cfg)
        try:
            import ems_db
            ems_db.invalidate_backend()
        except Exception:
            pass
        check("Backend", OK, "switched local → supabase")
    else:
        check("Backend", WARN, f"{backend} (local only)",
              "This PC is NOT on the shared DB yet. Re-run with --cloud, "
              "or Settings → ☁ Shared job database → Use shared.")

    # ── 6. Pending offline writes ─────────────────────────────────────
    q = paths.data("ems_db_queue.jsonl")
    if os.path.isfile(q) and os.path.getsize(q) > 0:
        n = sum(1 for _ in open(q, encoding="utf-8"))
        check("Offline queue", WARN, f"{n} write(s) not yet synced",
              "Settings → 🔄 Sync pending changes.")
    else:
        check("Offline queue", OK, "empty")

    # ── 7. Paths the panels need ──────────────────────────────────────
    for key in ("audit_base", "runs_dir", "photos_root"):
        p = (cfg.get(key) or "").strip()
        if not p:
            check(f"path: {key}", WARN, "not set",
                  "Settings → auto-detect, or set it by hand.")
        elif os.path.isdir(p):
            check(f"path: {key}", OK)
        else:
            check(f"path: {key}", FAIL, f"not reachable: {p}",
                  "Map the X: drive / fix the folder in Settings.")

    return _summary()


def _summary():
    print("\n" + "=" * 68)
    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    if not fails:
        print("  READY" + (f" ({len(warns)} warning(s))" if warns else ""))
    else:
        print(f"  NOT READY — {len(fails)} blocker(s)")
    for state, label, detail, fix in _results:
        if state != OK and fix:
            print(f"\n  {label}")
            print(f"    → {fix}")
    print("=" * 68)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
