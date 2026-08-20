"""Add a claim or unit to an existing client — adopt first, create second.

A second claim or another unit turns up constantly, and until now the
folder, the Trello card and the CompanyCam project were made separately
by hand. That is how a client ends up with three spellings of one job and
how Aperto ended up with two units sharing a truncated key.

ADOPT FIRST is the rule, and it is not a preference. Work starts in
Trello here — Nathan: "things are tracked/started in trello as we arent
using the new loss button" — so a provision-everything flow would
cheerfully create a SECOND card beside the one somebody already made,
reintroducing the duplicate-identity problem at the front door. So every
step looks for what already exists before it offers to make anything.

Each step reports its own result. A child whose folder was created but
whose Trello card failed says exactly that, rather than reporting success
because the folder appeared — offline, the folder succeeds locally while
Trello and CompanyCam cannot, and "half provisioned, silently" is the
failure this whole effort has been unwinding.

Nothing here writes until `apply_child` is called; `plan_child` is a
read-only preview.
"""
import os

import ems_db
from ems_db_common import parse_child_levels, normalize_division


def _parent_folder(parent_key):
    """The client's own folder — the shortest linked path."""
    paths = [l["link_value"] for l in (ems_db.get_links(
        parent_key, ems_db.LINK_FOLDER) or []) if l.get("link_value")]
    return min(paths, key=len) if paths else ""


def _existing_folder(parent_path, name):
    """A child folder already on disk, matched case-insensitively."""
    if not (parent_path and name and os.path.isdir(parent_path)):
        return ""
    want = name.strip().lower()
    try:
        with os.scandir(parent_path) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and \
                        e.name.strip().lower() == want:
                    return e.path
    except OSError:
        pass
    return ""


def _find_cards(parent_display, child_name, limit=6):
    """Cards that plausibly belong to this child, best first.

    Searched as "<client> <child>" because that is how the office writes
    them, and the card is the record most likely to exist already.
    """
    try:
        import trello_client as tc
    except Exception:
        return []
    # The full child name carries a date ("Tres Lagos - Unit 6204 -
    # 8.17.26") and searching for that finds nothing — the card is named
    # for the unit, not the visit. Probe the distinctive part first, then
    # widen.
    lv = parse_child_levels(child_name)
    probes = []
    for tail in (lv.get("unit"), lv.get("property"), child_name):
        if tail and f"{parent_display} {tail}".strip() not in probes:
            probes.append(f"{parent_display} {tail}".strip())
    hits, seen = [], set()
    for q in probes:
        try:
            found = tc.find_cards_by_name(q, max_results=limit) or []
        except Exception:
            found = []
        for h in found:
            cid = h.get("card_id")
            if cid and cid not in seen:
                seen.add(cid)
                hits.append(h)
        if len(hits) >= limit:
            break
    hits = hits[:limit]
    return [{"id": h.get("card_id"), "name": h.get("name") or "",
             "board": h.get("board") or "", "lane": h.get("list_name") or ""}
            for h in hits if h.get("card_id")]


def _find_project(parent_display, child_name):
    """An existing CompanyCam project for this child, or None."""
    try:
        import companycam_api as cc
    except Exception:
        return None
    for probe in (f"{parent_display} {child_name}".strip(), child_name):
        if not probe:
            continue
        try:
            pid = cc.find_project_id(probe, use_graph=False)
        except TypeError:
            try:
                pid = cc.find_project_id(probe)
            except Exception:
                pid = ""
        except Exception:
            pid = ""
        if pid:
            proj = None
            try:
                proj = cc.get_project(pid)
            except Exception:
                proj = None
            return {"id": str(pid), "name": (proj or {}).get("name") or probe}
    return None


def _a_sibling(parent_path, exclude_path):
    """Another child folder to copy a skeleton from, or None.

    Must never be the parent: the new child lives inside it, so walking
    the parent would recreate the walker's own output without end.
    """
    if not parent_path or not os.path.isdir(parent_path):
        return None
    skip = os.path.normcase(os.path.abspath(exclude_path or ""))
    try:
        with os.scandir(parent_path) as it:
            for e in it:
                if not e.is_dir(follow_symlinks=False):
                    continue
                if os.path.normcase(os.path.abspath(e.path)) == skip:
                    continue
                return e.path
    except OSError:
        pass
    return None


def plan_child(parent_key, child_name, *, division=""):
    """What adding this child would adopt and what it would create.

    Read-only. Returns {ok, parent, child, levels, folder, cards,
    project, existing_child}.
    """
    job = ems_db.get_job(parent_key)
    if job is None:
        return {"ok": False, "error": f"no job {parent_key!r}"}
    name = (child_name or "").strip()
    if not name:
        return {"ok": False, "error": "child name required"}

    parent_path = _parent_folder(parent_key)
    levels = parse_child_levels(name)

    # Already a child? Then this is an edit, not an add — say so rather
    # than silently creating a second row that set_child would merge.
    existing = None
    for c in (ems_db.children_of(parent_key) or []):
        if (c.get("name") or "").strip().lower() == name.lower():
            existing = c
            break

    folder = _existing_folder(parent_path, name)
    display = job.get("display_name") or parent_key

    cards = _find_cards(display, name)
    project = _find_project(display, name)
    # A child that already exists carries its OWN card and project. Those
    # are the truth, and searching Trello for a name the card was never
    # given would report "none found" for a job that is already linked.
    if existing:
        linked_card = (existing.get("trello_card") or "").strip()
        if linked_card and not any(c["id"] == linked_card for c in cards):
            cards.insert(0, {"id": linked_card, "name": "(already linked)",
                             "board": "", "lane": "", "linked": True})
        linked_proj = (existing.get("companycam") or "").strip()
        if linked_proj:
            project = {"id": linked_proj, "name": "(already linked)",
                       "linked": True}
    return {
        "ok": True,
        "parent": {"key": parent_key, "display_name": display,
                   "path": parent_path},
        "child": name,
        "levels": levels,
        "division": normalize_division(division),
        "existing_child": existing,
        "folder": {"path": folder or os.path.join(parent_path, name),
                   "exists": bool(folder)},
        "cards": cards,
        "project": project,
    }


def apply_child(parent_key, child_name, *, card_id="", project_id="",
                create_folder=True, create_project=False,
                division="", levels=None):
    """Create/adopt the pieces and record the child.

    Every step is independent and reports its own outcome. Returns
    {ok, steps:{folder,card,project,child}, child}. `ok` is True only
    when nothing failed — a partial result is never reported as success.
    """
    plan = plan_child(parent_key, child_name, division=division)
    if not plan.get("ok"):
        return plan
    name = plan["child"]
    parent_path = plan["parent"]["path"]
    lv = dict(levels or plan["levels"])
    steps = {}

    # ── folder ────────────────────────────────────────────────────
    folder_path = plan["folder"]["path"] if plan["folder"]["exists"] else ""
    if folder_path:
        steps["folder"] = {"ok": True, "action": "adopted",
                           "path": folder_path}
    elif create_folder and parent_path:
        try:
            import child_folder_ops as cfo
            made = cfo.reserve_child_dir(parent_path, name)
            if made:
                try:
                    # A SIBLING child folder, never the parent. Passing
                    # the parent makes it walk the tree that now contains
                    # the folder it is filling, so it recreates its own
                    # output forever. None falls back to the minimal
                    # EMS/PICS + EMS/DOCS skeleton the importers expect.
                    cfo.replicate_sibling_skeleton(made, _a_sibling(
                        parent_path, made))
                except Exception:
                    pass          # skeleton is a nicety, not the folder
                folder_path = made
                steps["folder"] = {"ok": True, "action": "created",
                                   "path": made}
            else:
                steps["folder"] = {"ok": False, "action": "create",
                                   "error": "could not reserve directory"}
        except Exception as ex:
            steps["folder"] = {"ok": False, "action": "create",
                               "error": f"{type(ex).__name__}: {ex}"}
    else:
        steps["folder"] = {"ok": True, "action": "skipped"}

    # ── trello ────────────────────────────────────────────────────
    if card_id:
        steps["card"] = {"ok": True, "action": "adopted", "id": card_id}
    else:
        steps["card"] = {"ok": True, "action": "none",
                         "note": "no card chosen — pick one later"}

    # ── companycam ────────────────────────────────────────────────
    pid = project_id or ""
    if pid:
        steps["project"] = {"ok": True, "action": "adopted", "id": pid}
    elif create_project:
        try:
            import companycam_api as cc
            title = f"{plan['parent']['display_name']} - {name}"
            proj = cc.create_project(title)
            pid = str((proj or {}).get("id") or "")
            steps["project"] = ({"ok": True, "action": "created", "id": pid}
                                if pid else
                                {"ok": False, "action": "create",
                                 "error": "no id returned"})
        except Exception as ex:
            steps["project"] = {"ok": False, "action": "create",
                                "error": f"{type(ex).__name__}: {ex}"}
    else:
        steps["project"] = {"ok": True, "action": "none"}

    # ── the child row ─────────────────────────────────────────────
    try:
        row = ems_db.set_child(
            parent_key, name,
            folder_path=folder_path or "",
            trello_card=card_id or "",
            companycam=pid or "",
            property=lv.get("property") or "",
            unit=lv.get("unit") or "",
            claim_date=lv.get("claim_date") or "",
            department=(ems_db.get_job(parent_key) or {}).get(
                "department") or "")
        steps["child"] = {"ok": True, "action": "recorded"}
    except Exception as ex:
        row = {}
        steps["child"] = {"ok": False, "action": "record",
                          "error": f"{type(ex).__name__}: {ex}"}

    failed = [k for k, v in steps.items() if not v.get("ok")]
    return {"ok": not failed, "steps": steps, "child": row,
            "failed": failed}
