"""Job folder creation — the `year → client → child` model.

One client folder per customer; everything else is a CHILD inside it:

    2026 Jobs\\
        Mansolino Sayra\\          <- client
            1st Claim\\            <- child: another claim
            2nd Claim (Kitchen)\\
        Metro at Main\\
            Unit 182\\             <- child: a unit
        Next Door Property Mgmt\\
            Coreland Company u121\\ <- child: a commercial sub-job

Claims, units and commercial sub-jobs are the SAME structure — only the
child's name differs. So this module has one code path, not three.

Why creation matches EXACTLY and never fuzzily
----------------------------------------------
The audit's resolver is deliberately loose so it can find a job someone
spelled differently. Creation must be the opposite: a fuzzy hit here would
nest a brand-new customer's folder inside an unrelated job's. `_match_tokens`
in audit_logic fires on any two shared tokens, which is how every
"<Name> Property Management" matched all the others — exactly the mistake
this must not make. If the name doesn't match exactly, we create a new
client folder and let the operator merge later if it was a duplicate.
"""
from __future__ import annotations

import datetime as _dt
import os
import re

import config

# The skeleton every importer assumes exists.
_SKELETON = (("EMS", "PICS"), ("EMS", "DOCS"))

_CLAIM_ORDINAL_RE = re.compile(
    r"^\s*(?:(\d+)\s*(?:st|nd|rd|th)?|"
    r"(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))"
    r"\s+claim\b", re.IGNORECASE)
_WORD_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4,
                  "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
                  "ninth": 9, "tenth": 10}


def sanitize(name: str) -> str:
    """A folder name Windows will accept, or "" when nothing usable."""
    clean = " ".join((name or "").split()).strip(" .-")
    clean = re.sub(r'[\\/:*?"<>|]', "-", clean)
    return clean.strip(" .-")


def _norm(s: str) -> str:
    """Comparison form — letters and spaces only, matching audit_logic's
    normalization so 'Riley, Robert' and 'riley robert' are one client."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (s or "").lower())).strip()


def ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 11 → '11th', 23 → '23rd'."""
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def claim_ordinal_of(folder_name: str):
    """The claim number a child folder encodes, or None.

    Handles the shapes actually on the share: '1st Claim', '2nd claim',
    '2nd Claim (KItchen)', '3rd Claim 7-29-2026'.
    """
    m = _CLAIM_ORDINAL_RE.match(folder_name or "")
    if not m:
        return None
    if m.group(1):
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return _WORD_ORDINALS.get((m.group(2) or "").lower())


def year_dir(*, base: str = "", year=None) -> str:
    """The '<YYYY> Jobs' folder, or "" when it can't be found.

    Skips the LA FIRES folder, which also carries a year in its name —
    the same exclusion audit_logic uses.
    """
    base = (base or "").strip() or (config.load().get("audit_base") or "").strip()
    if not base or not os.path.isdir(base):
        return ""
    y = str(year or _dt.date.today().year)
    try:
        with os.scandir(base) as it:
            for e in it:
                if not e.is_dir(follow_symlinks=False):
                    continue
                nm = e.name.upper()
                if y in e.name and not ("LA" in nm and "FIRE" in nm):
                    return e.path
    except OSError:
        return ""
    return ""


def find_client_folder(client: str, *, base: str = "", year=None) -> str:
    """The existing client folder for `client`, or "" — EXACT normalized
    match only. See the module note on why this never matches fuzzily."""
    yd = year_dir(base=base, year=year)
    if not yd:
        return ""
    want = _norm(client)
    if not want:
        return ""
    try:
        with os.scandir(yd) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and _norm(e.name) == want:
                    return e.path
    except OSError:
        return ""
    return ""


def list_children(client_dir: str) -> list:
    """Immediate subfolders of a client folder, minus the job skeleton
    (EMS / RECON / CONTENTS / PICS / DOCS), which are containers rather
    than children."""
    skip = {"ems", "recon", "contents", "pics", "photos", "docs", "videos"}
    out = []
    try:
        with os.scandir(client_dir) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and e.name.lower() not in skip:
                    out.append(e.name)
    except OSError:
        return []
    return sorted(out)


def next_claim_name(client_dir: str) -> str:
    """The name for this client's next claim folder.

    A client with no claim children gets '2nd Claim', not '1st': the
    original claim's files sit at the client root, unmoved. That's the
    live convention — 'Calderon Edilson' holds only a '2nd Claim' child.
    """
    highest = 1
    for name in list_children(client_dir):
        n = claim_ordinal_of(name)
        if n and n > highest:
            highest = n
    return f"{ordinal(highest + 1)} Claim"


# Containers that hold a single claim's work. Everything else at a client
# root is left alone — see plan_promote_first_claim.
_JOB_CONTAINERS = {"ems", "recon", "contents", "pics", "photos", "videos"}


def _has_job_structure(path: str) -> bool:
    """True when a folder holds a job's work (EMS / RECON / CONTENTS /
    PICS…), i.e. it is a real child job rather than a folder of paperwork.

    Used to decide whether a client's ROOT content is one claim's work —
    see plan_promote_first_claim. Do NOT use it to decide whether a
    subfolder is a child job: that question is `is_child_job_folder`, and
    answering it with this allow-list hid every new or lightly-filled
    sub-job.
    """
    try:
        with os.scandir(path) as it:
            for e in it:
                if (e.is_dir(follow_symlinks=False)
                        and e.name.lower() in _JOB_CONTAINERS):
                    return True
    except OSError:
        return False
    return False


# Folder names under a client that are NEVER a child job: the client's own
# work containers, its paperwork, and tool output.
#
# A DENY-list, not an allow-list. Requiring an EMS/PICS subfolder inside a
# child meant a sub-job was invisible until someone put work in it — which
# is backwards, since a folder is created BEFORE the work goes in. On live
# data it hid 27 real children, including `Metro at Main / Unit 418`,
# `Avana Springs / Unit 545-O`, PCM's work orders and four Western
# Municipal sub-jobs. audit_logic reached the same conclusion separately
# after the "exists but not listed" finding; this is now the shared set so
# the two cannot drift.
NON_JOB_CHILD_NAMES = _JOB_CONTAINERS | {
    "docs", "doc", "documents", "field docs", "paperwork", "forms",
    "sp invoices", "invoices", "receipts", "estimates",
    "from sharepoint", "scans", "signed docs",
    "sketch", "sketches",
    # Tool output, not a job: the photo report is GENERATED into the client
    # folder, so treating it as a sub-job would invent one for every job
    # that has ever had a report run.
    "photo report", "photo reports",
    "old", "backup", "archive", "misc", "temp",
}


def is_child_job_folder(path: str, name: str = "") -> bool:
    """Is this subfolder of a client a child job (claim / unit / sub-job)?

    Empty counts. A folder created today for work that starts tomorrow is
    still the job — and that is exactly when you need to find it.
    """
    leaf = (name or os.path.basename(path or "")).strip().lower()
    if not leaf:
        return False
    return leaf not in NON_JOB_CHILD_NAMES


def plan_promote_first_claim(client_dir: str) -> dict:
    """Can this client's root content become a '1st Claim' folder?

    When a customer's second claim arrives, their original claim's work is
    sitting loose at the client root. Tucking it into '1st Claim' makes the
    client uniform: every claim in its own folder.

    Eligibility turns on WHAT is at the root, not on whether claim folders
    already exist. Live shapes that settled this:

      Calderon Edilson  root: EMS/         + 2nd Claim/  -> PROMOTE
      Mansolino Sayra   root: DOCS/        + 1st/2nd/3rd -> leave alone
      Szynal Donna      root: FIELD DOCS/  + 1st/2nd/3rd -> leave alone

    Only `_JOB_CONTAINERS` (EMS, RECON, CONTENTS, PICS…) hold one claim's
    work. DOCS and FIELD DOCS are client-level paperwork shared by every
    claim, so they stay at the root — burying them inside '1st Claim'
    would lose them. An earlier "skip if any claim folder exists" rule
    read Calderon, the exact case this is for, as ineligible.

    Returns {ok, eligible, reason, moves:[names], target}.
    """
    if not client_dir or not os.path.isdir(client_dir):
        return {"ok": False, "eligible": False, "reason": "no client folder",
                "moves": [], "target": ""}
    if os.path.isdir(os.path.join(client_dir, "1st Claim")):
        return {"ok": True, "eligible": False,
                "reason": "a '1st Claim' folder already exists",
                "moves": [], "target": ""}
    kids = list_children(client_dir)
    # A child only counts as a sub-job if it CONTAINS job structure. A bare
    # folder of paperwork is client-level: 'Szynal Donna' keeps FIELD DOCS
    # at the root, which is not a unit and must not make the client look
    # unit-structured.
    non_claim_kids = [c for c in kids
                      if not claim_ordinal_of(c)
                      and _has_job_structure(os.path.join(client_dir, c))]
    if non_claim_kids:
        # This client is organized by UNITS or sub-jobs, not claims, so
        # "1st Claim" is the wrong shape for it and the root holds
        # umbrella-level material. 'Metro at Main' has Unit 182/188/237
        # plus a check and three prelim PDFs at the root — those cover the
        # whole property and must not end up inside one claim.
        return {"ok": True, "eligible": False,
                "reason": (f"organized by units/sub-jobs "
                           f"({', '.join(non_claim_kids[:3])}"
                           f"{'…' if len(non_claim_kids) > 3 else ''}), "
                           f"not claims — the root is client-level"),
                "moves": [], "target": ""}
    # Loose files belong to claim 1 only when the client has no children
    # at all. Any child means the root is umbrella-level.
    moves = []
    try:
        with os.scandir(client_dir) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    if e.name.lower() in _JOB_CONTAINERS:
                        moves.append(e.name)
                elif e.is_file(follow_symlinks=False) and not kids:
                    moves.append(e.name)
    except OSError as ex:
        return {"ok": False, "eligible": False, "reason": str(ex),
                "moves": [], "target": ""}
    if not moves:
        return {"ok": True, "eligible": False,
                "reason": "nothing at the root belongs to a single claim",
                "moves": [], "target": ""}
    return {"ok": True, "eligible": True, "reason": "",
            "moves": sorted(moves),
            "target": os.path.join(client_dir, "1st Claim")}


def promote_first_claim(client_dir: str, *, repin: bool = True) -> dict:
    """Move the client root's job content into a '1st Claim' subfolder.

    Moves are done one at a time and rolled back if any fails — a
    half-moved job folder is worse than an unmoved one. Pins that pointed
    at the client root are repointed at '1st Claim', or the audit would
    keep resolving the job to a now-empty folder.
    """
    import shutil

    p = plan_promote_first_claim(client_dir)
    if not p.get("ok") or not p.get("eligible"):
        return {**p, "moved": [], "created": False}
    target = p["target"]
    if os.path.exists(target):
        return {**p, "ok": False, "moved": [], "created": False,
                "reason": "1st Claim already exists"}
    try:
        os.makedirs(target)
    except OSError as ex:
        return {**p, "ok": False, "moved": [], "created": False,
                "reason": f"create failed: {ex}"}

    moved = []
    for name in p["moves"]:
        src = os.path.join(client_dir, name)
        dst = os.path.join(target, name)
        try:
            shutil.move(src, dst)
            moved.append(name)
        except (OSError, shutil.Error) as ex:
            # Roll back — a file open in Explorer or a locked SMB handle
            # must not leave the job split across two folders.
            for done in reversed(moved):
                try:
                    shutil.move(os.path.join(target, done),
                                os.path.join(client_dir, done))
                except Exception:
                    pass
            try:
                os.rmdir(target)
            except OSError:
                pass
            return {**p, "ok": False, "moved": [], "created": False,
                    "reason": f"move failed on {name!r}: {ex} — rolled back"}

    repinned = []
    if repin:
        repinned = _repoint_pins(client_dir, target)
    return {**p, "ok": True, "moved": moved, "created": True,
            "target": target, "repinned": repinned}


def _repoint_pins(old_path: str, new_path: str) -> list:
    """Move folder pins from `old_path` to `new_path`, in state.json and in
    the job index. Best-effort: a missed pin costs a re-pin, never data."""
    out = []
    old_norm = os.path.normcase(os.path.normpath(old_path))
    try:
        import persistence
        pins = persistence.get("folder_paths") or {}
        for key, val in list(pins.items()):
            if os.path.normcase(os.path.normpath(str(val or ""))) == old_norm:
                persistence.set_folder_path(key, new_path)
                out.append(key)
    except Exception:
        pass
    try:
        import ems_db
        job = ems_db.find_job_by_link(ems_db.LINK_FOLDER, old_path)
        if job:
            ems_db.set_link(job["canon_key"], ems_db.LINK_FOLDER, new_path,
                            added_by="promote_first_claim")
            ems_db.remove_link(job["canon_key"], ems_db.LINK_FOLDER, old_path)
    except Exception:
        pass
    return out


def client_context(client: str, client_dir: str = "") -> dict:
    """What this client already has — folders, claims, Trello cards, a
    CompanyCam project.

    Drives the "New claim?" toggle: the dialog shouldn't ask when there's
    nothing to attach to, and when there IS prior work it should say what,
    so the operator can tell a second claim apart from a first one that was
    simply filed under a different spelling.
    """
    ctx = {"known": False, "claims": [], "children": [], "cards": [],
           "companycam": "", "display_name": "", "has_folder": False}
    ctx["has_folder"] = bool(client_dir and os.path.isdir(client_dir))
    if ctx["has_folder"]:
        ctx["children"] = list_children(client_dir)
        ctx["claims"] = [c for c in ctx["children"] if claim_ordinal_of(c)]
    try:
        import ems_db
        job = ems_db.find_job_by_name(client)
        if job:
            ctx["known"] = True
            ctx["display_name"] = job.get("display_name") or ""
            key = job.get("canon_key") or ""
            ctx["cards"] = [l["link_value"] for l in
                            ems_db.get_links(key, ems_db.LINK_TRELLO)]
            ctx["companycam"] = ems_db.get_link(
                key, ems_db.LINK_COMPANYCAM) or ""
    except Exception:
        pass
    # Prior work of ANY kind is the signal — a client can have a Trello
    # card and a CompanyCam project before a single folder exists.
    ctx["suggest_new_claim"] = bool(
        ctx["claims"] or ctx["children"] or ctx["has_folder"]
        or len(ctx["cards"]) > 0 or ctx["companycam"])
    return ctx


def plan(client: str, *, child: str = "", second_claim: bool = False,
         base: str = "", year=None) -> dict:
    """What `create` would do, without touching the disk.

    Returns {mode, client, client_dir, child, path, exists, children}.
    mode is 'new_client' (no folder yet) or 'child' (client exists, so the
    new work becomes a subfolder — never a second top-level folder).
    """
    clean_client = sanitize(client)
    if not clean_client:
        return {"ok": False, "error": "No client name"}
    yd = year_dir(base=base, year=year)
    if not yd:
        return {"ok": False, "error": "No current-year jobs folder found"}

    client_dir = find_client_folder(clean_client, base=base, year=year)
    if not client_dir:
        target = os.path.join(yd, clean_client)
        # No folder doesn't mean no history: a card or CompanyCam project
        # may already exist under a different spelling, which is exactly
        # when the operator needs to be asked rather than told.
        return {"ok": True, "mode": "new_client", "client": clean_client,
                "client_dir": target, "child": "", "path": target,
                "exists": os.path.isdir(target), "children": [],
                "context": client_context(clean_client, ""),
                "promote_first_claim": {"ok": True, "eligible": False,
                                        "reason": "new client", "moves": [],
                                        "target": ""}}

    kids = list_children(client_dir)
    name = sanitize(child)
    if not name:
        # No explicit child name → this is another claim on the same
        # property, so take the next ordinal.
        name = next_claim_name(client_dir)
    elif second_claim:
        name = next_claim_name(client_dir)
    path = os.path.join(client_dir, name)
    return {"ok": True, "mode": "child", "client": os.path.basename(client_dir),
            "client_dir": client_dir, "child": name, "path": path,
            "exists": os.path.isdir(path), "children": kids,
            "context": client_context(clean_client, client_dir),
            # Offered, never automatic: it MOVES existing production files.
            "promote_first_claim": plan_promote_first_claim(client_dir)}


def create(client: str, *, child: str = "", second_claim: bool = False,
           base: str = "", year=None, skeleton: bool = True,
           promote_first: bool = False) -> dict:
    """Create the client folder, or a child inside an existing one.

    Never creates a second top-level folder for a client that already has
    one — that's the duplicate-job problem this exists to prevent.

    `promote_first=True` also tucks the client root's existing job content
    into a '1st Claim' folder first, so both claims end up as siblings.
    Off by default because it MOVES live files; the caller should have
    confirmed it from `plan()['promote_first_claim']`.
    """
    p = plan(client, child=child, second_claim=second_claim, base=base,
             year=year)
    if not p.get("ok"):
        return p
    promoted = None
    if promote_first and p.get("mode") == "child":
        promoted = promote_first_claim(p["client_dir"])
        if not promoted.get("ok") and promoted.get("eligible"):
            # The move failed and rolled back — stop rather than create a
            # second claim beside a root we just failed to tidy.
            return {**p, "ok": False, "created": False,
                    "error": promoted.get("reason") or "promote failed",
                    "promoted": promoted}
    path = p["path"]
    if p["exists"]:
        return {**p, "ok": False, "error": "That folder already exists",
                "created": False}
    try:
        os.makedirs(path, exist_ok=True)
        if skeleton:
            for parts in _SKELETON:
                os.makedirs(os.path.join(path, *parts), exist_ok=True)
    except OSError as ex:
        return {**p, "ok": False, "error": f"create failed: {ex}",
                "created": False}
    return {**p, "ok": True, "created": True, "promoted": promoted}
