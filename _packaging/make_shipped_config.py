"""Regenerate the sanitized config that ships inside the .exe.

    python _packaging/make_shipped_config.py [--dry]

`_packaging/config.json` seeds `%APPDATA%\\Linguar Hub\\config.json` on a
new machine's first run. It was hand-maintained and had drifted badly:
it carried no Supabase credentials, no department profiles, and no
franchise identity, so a fresh install could not reach the shared job
database or match a single Trello card. Generating it from the live
config with an explicit policy is the only way it stays correct.

Three categories, and every key must land in exactly one:

  SHARE          — same for everyone at the franchise. Ships.
  PER_USER       — a credential that identifies a PERSON. Never ships;
                   each user signs in or pastes their own.
  MACHINE_LOCAL  — differs per PC and `paths.auto_detect()` recovers it
                   on first run, so shipping it would be actively wrong
                   (it would hard-code THIS user's OneDrive path).

Anything in the live config that is in none of them is reported as
unclassified rather than silently shipped or silently dropped.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import paths  # noqa: E402

# ── Policy ────────────────────────────────────────────────────────────────
SHARE = {
    # Shared job index. The anon/publishable key is DESIGNED to ship in a
    # client — no RLS policy grants the `anon` role anything, so it reads
    # nothing until a real user signs in (supabase/001_init.sql).
    "supabase_url", "supabase_anon_key",
    # Franchise-wide paths on the X: share — identical on every PC.
    "audit_base", "apa_monitor_root", "snapshot_template",
    "snapshots_root", "dispute_tracker_path",
    # Trello wiring that identifies the APP and the boards, not a person.
    "trello_api_key", "trello_workspace_id", "trello_snapshot_list_id",
    "trello_boards_exclude",
    # Franchise identity used on generated paperwork.
    "franchise_name", "office_phone",
    # Department setup.
    "multi_department_enabled", "active_department",
    # Feature flags / UI defaults.
    "enable_workcenter_alpha", "workcenter_url",
    "show_sort_files", "show_new_job", "snapshot_auto_reconcile",
    "appearance", "ui_scale",
    "graph_client_id", "graph_tenant_id",
    "photos_extra_roots", "user_workbooks",
}

# Per-DEPARTMENT keys worth shipping. trello_token is deliberately absent:
# it authenticates a PERSON, and shipping one would hand every installer
# the author's Trello identity.
SHARE_DEPT = {
    "label", "trello_api_key", "trello_workspace_id",
    "trello_snapshot_list_id", "trello_boards_exclude",
    "audit_base", "apa_monitor_root", "snapshot_template",
    "franchise_name", "office_phone",
}

PER_USER = {
    "trello_token",          # identifies a person; Settings → Connect Trello
    "companycam_api_token",  # per-account access token
    "ems_db_backend",        # each machine opts into cloud deliberately
}

MACHINE_LOCAL = {
    "runs_dir", "photos_root", "snapshot_output",   # per-user OneDrive paths
    "pythonw", "scripts_dir", "dept_browsers", "preferred_browser",
}

# Panel-visibility toggles are per-user taste; they're booleans named after
# each panel and there are ~15 of them, so match them rather than list them.
_PANEL_KEYS = {
    "apa", "audit", "cheat_sheet", "disputes", "hygiene", "iuq", "job_notes",
    "kpi", "multi_unit", "notifications", "photo_folders", "pipeline",
    "settings", "snapshot", "spreadsheet", "wc_audit",
}

# A value matching any of these must never appear anywhere in the output.
_SECRET_SUBSTRINGS = ("service_role", "sbp_", "secret")


def _is_machine_path(v) -> bool:
    """True for a path under someone's user profile.

    OC's whole department profile points at
    `C:\\Users\\<me>\\Servpro12342\\Servpro-OC - OC-Onedrive` — that is a
    OneDrive sync root, so it is per-PC even though the department is
    shared. Shipping it aims every coworker's OC at a folder that doesn't
    exist on their machine. X: paths are a real server share and DO ship.
    """
    if not isinstance(v, str):
        return False
    return ":\\users\\" in v.replace("/", "\\").lower()


def build(live: dict) -> tuple[dict, list[str]]:
    out, unclassified = {}, []
    for key in sorted(live):
        if key in SHARE:
            v = live[key]
            # Applies to lists too — photos_extra_roots is shared in
            # principle but its entries are per-user OneDrive folders.
            if _is_machine_path(v):
                continue
            if isinstance(v, list):
                v = [x for x in v if not _is_machine_path(x)]
            out[key] = v
        elif key in PER_USER or key in MACHINE_LOCAL or key in _PANEL_KEYS:
            continue
        elif key == "departments":
            depts = {}
            for name, prof in (live.get("departments") or {}).items():
                depts[name] = {k: v for k, v in prof.items()
                               if k in SHARE_DEPT and not _is_machine_path(v)}
            if depts:
                out["departments"] = depts
        else:
            unclassified.append(key)
    # Blank rather than omit, so Settings shows the row and the user knows
    # it's theirs to fill.
    for key in ("trello_token", "companycam_api_token"):
        out[key] = ""
    for prof in out.get("departments", {}).values():
        prof["trello_token"] = ""
    return out, unclassified


def audit(out: dict) -> list[str]:
    """Fail loudly rather than ship a credential."""
    problems = []
    blob = json.dumps(out).lower()
    for bad in _SECRET_SUBSTRINGS:
        if bad in blob:
            problems.append(f"output contains {bad!r}")
    if out.get("trello_token"):
        problems.append("trello_token is not blank")
    if out.get("companycam_api_token"):
        problems.append("companycam_api_token is not blank")
    for name, prof in (out.get("departments") or {}).items():
        if prof.get("trello_token"):
            problems.append(f"departments.{name}.trello_token is not blank")
    key = out.get("supabase_anon_key") or ""
    # Publishable keys are `sb_publishable_…` (new) or a JWT with
    # "role":"anon" (legacy). A service_role JWT must never get here.
    if key and not (key.startswith("sb_publishable_") or key.startswith("ey")):
        problems.append("supabase_anon_key is not a recognised publishable key")
    for k, v in out.items():
        if isinstance(v, str) and (":\\Users\\" in v or ":/Users/" in v):
            problems.append(f"{k} hard-codes a user profile path: {v}")
    return problems


def main():
    dry = "--dry" in sys.argv
    live_path = paths.data("config.json")
    with open(live_path, encoding="utf-8") as f:
        live = json.load(f)

    out, unclassified = build(live)
    problems = audit(out)

    print(f"source : {live_path}")
    print(f"keys   : {len(live)} live -> {len(out)} shipped")
    if unclassified:
        print("\nUNCLASSIFIED (not shipped — add to SHARE/PER_USER/"
              "MACHINE_LOCAL to silence):")
        for k in unclassified:
            print(f"   {k}")
    if problems:
        print("\nREFUSING TO WRITE:")
        for p in problems:
            print(f"   {p}")
        return 1

    dest = os.path.join(_HERE, "config.json")
    if dry:
        print(f"\n--dry: would write {dest}")
        print(json.dumps(out, indent=2)[:800])
        return 0
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, dest)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
