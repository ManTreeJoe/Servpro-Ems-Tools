"""Verify the IE / OC department split — run this on any machine.

Offline checks (config only):
  * every department has its own Trello workspace + file shares
  * no two departments resolve to the SAME identity value
  * no department inherits an identity value from the editable base

Online checks (--online, one Trello call per department):
  * the configured workspace exists, is visible to the token, and its
    boards look like that department's boards

Exit code 0 = clean, 1 = problems found. Safe to run any time; makes no
changes.

    python check_departments.py
    python check_departments.py --online
"""
import sys

import config


def _fmt(problems):
    order = {"error": 0, "warn": 1}
    for p in sorted(problems, key=lambda p: order.get(p.get("level"), 9)):
        icon = "ERROR" if p.get("level") == "error" else "warn "
        print(f"  [{icon}] {p.get('message')}")


def offline():
    print("=== department configuration ===")
    if not config.is_multi_dept():
        print("  multi-department mode is OFF — nothing to separate.")
        return []
    base = config.load_base()
    depts = base.get("departments") or {}
    active = config.active_department()
    for dk in depts:
        eff = config.load_for(dk)
        prof = depts.get(dk) if isinstance(depts.get(dk), dict) else {}
        mark = " (active)" if dk == active else ""
        print(f"\n  {dk}{mark} — {prof.get('label') or dk}")
        for k in config.DEPT_IDENTITY_KEYS:
            src = "explicit" if not config._is_blank(prof.get(k)) else "INHERITED"
            print(f"     {k:22} {eff.get(k)!r}  [{src}]")

    problems = config.check_department_integrity()
    print("\n=== integrity ===")
    if not problems:
        print("  OK — each department has its own workspace and shares.")
    else:
        _fmt(problems)
    return problems


def online():
    """Confirm each department's workspace actually resolves, and show the
    boards that department would search. Catches a valid-looking id that
    points at the wrong (or a deleted) workspace."""
    import trello_client as tc

    print("\n=== live Trello per department ===")
    problems = []
    base = config.load_base()
    for dk in (base.get("departments") or {}):
        eff = config.load_for(dk)
        ws = (eff.get("trello_workspace_id") or "").strip()
        print(f"\n  {dk}: workspace {ws or '(none)'}")
        if not ws:
            problems.append({"level": "error",
                             "message": f"{dk} has no Trello workspace"})
            continue
        try:
            org = tc._call(f"/organizations/{ws}",
                           params={"fields": "displayName,name"})
            print(f"     name: {org.get('displayName')!r}")
            boards = tc._call(f"/organizations/{ws}/boards",
                              params={"fields": "id,name,shortLink",
                                      "filter": "open"})
            excl = set(eff.get("trello_boards_exclude") or [])
            keep = [b for b in boards or []
                    if b.get("shortLink") not in excl and b.get("id") not in excl]
            print(f"     boards it would search: {len(keep)}")
            for b in keep:
                print(f"       - {b.get('name')}")
            if not keep:
                problems.append({
                    "level": "error",
                    "message": (f"{dk}: workspace resolves but every board is "
                                f"excluded — searches will return nothing")})
            # An exclude list is written in shortLinks, which are scoped to
            # ONE workspace. A department that inherits the other's list is
            # excluding nothing at all — its "hidden" boards are live.
            known = {b.get("shortLink") for b in boards or []}
            known |= {b.get("id") for b in boards or []}
            stray = [e for e in excl if e not in known]
            if stray:
                problems.append({
                    "level": "warn",
                    "message": (f"{dk}: {len(stray)} excluded board(s) "
                                f"{stray} don't exist in this workspace — "
                                f"the exclude list belongs to another "
                                f"department, so nothing is actually hidden")})
        except Exception as ex:
            problems.append({"level": "error",
                             "message": f"{dk}: workspace unreachable — {ex}"})
            print(f"     FAILED: {ex}")
    if problems:
        print("\n=== live problems ===")
        _fmt(problems)
    return problems


def main(argv):
    problems = offline()
    if "--online" in argv:
        problems = problems + online()
    if problems:
        print(f"\n{len(problems)} problem(s). Fix in Settings → Departments: "
              f"give each department its OWN Trello workspace ID and folder "
              f"roots — never leave one blank to inherit.")
        return 1
    print("\nClean.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
