"""What every commercial job is called in the three places it is named.

A multi-site job is named in the job folder, on the Trello card and in
CompanyCam, and almost never the same way twice. The convention is four
fields, and each system shows the subset it needs:

    Parent - Site - Unit/Room/Subcategory - Date

    Trello      Menifee Union School District - Callie Kirkpatrick Elementary - Room 9 - 6/9/26
    Folder      Callie Kirkpatrick Elementary - Room 9 - 8.14.26
    CompanyCam  Callie Kirkpatrick Elementary - Room 9

The folder already sits inside the client folder, so it drops the client.
CompanyCam drops the date too — the project is the place, not the visit.
Any field the card doesn't state is simply left out; a job with no rooms
is `Coreland Company - Dicks Sporting Goods - 3/19/26`.

The CARD is the source, because it is the only record carrying all four
fields. Folders and projects are tied to it by comparing site, room and
date AFTER removing the client name — without that, every Menifee record
shares menifee/union/school/district and the site barely counts. Room
numbers are identity: Room 9 never matches Room 33, which is what stopped
two Kirkpatrick jobs being assigned each other's photos.

Read-only. Never renames anything.

    python commercial_naming_audit.py                 # summary
    python commercial_naming_audit.py --json out.json
    python commercial_naming_audit.py --html out.html
"""
import argparse
import html
import io
import json
import os
import re
import sys

import job_folders as jf

SCAFFOLD = {
    "ems", "pics", "docs", "recon", "contents", "photos", "sp invoices",
    "receipts", "old", "backup", "archive", "signed docs", "estimate",
    "estimates", "invoices", "forms", "paperwork",
}
STOP = {"the", "of", "and", "a", "at", "in", "&"}
GENERIC = {
    "property", "properties", "management", "managment", "mgmt", "company",
    "companies", "school", "district", "union", "apartments", "apartment",
    "apts", "partners", "inc", "llc", "group", "services", "service", "self",
    "pay", "paid", "full", "room", "rm",
}
# Boards holding finished work. A closed job is not a rename job. Compared
# against whitespace-collapsed names — the live board is "AR  BOARD", with
# two spaces, which a naive check misses.
DEAD_BOARDS = ("LOGS", "AR BOARD", "RECON CLOSEOUT")
TEMPLATE_RE = re.compile(r"date\s*rec(ei|ie)ved|name of school|\(unit\s*#",
                         re.I)
YEAR = "26"

# Separators repeat in the wild ("4/1//26"), and leaving the remainder
# behind put a stray "26" into the site name.
DATE_RE = re.compile(
    r"(?<![0-9])([0-9]{1,2})[/.\-]+([0-9]{1,2})(?:[/.\-]+([0-9]{2,4}))?"
    r"(?![0-9])")
ROOM_RE = re.compile(
    r"\b(?:rooms?|rm)\b\s*[#:\-]*\s*((?:[0-9]+[A-Za-z]?)"
    r"(?:\s*(?:,|&|and|\+)\s*[0-9]+[A-Za-z]?)*)", re.I)
UNIT_RE = re.compile(
    r"\b(?:unit|apt|apartment|suite|ste)\b\s*[#:\-]*\s*"
    r"([0-9]+[A-Za-z]?(?:-[A-Za-z0-9]+)?)", re.I)
NOISE_RE = re.compile(
    r"\b(?:self\s*pay|paid(?:\s*full)?|program|wtr|po\s*#?\s*[a-z0-9]+)\b",
    re.I)


def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", (s or "").lower())
            if t and t not in STOP and len(t) > 1}


def alltoks(s):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def distinctive(s):
    return toks(s) - GENERIC or toks(s)


def rooms_in(s):
    """Room numbers named in a string — identity, not one token of many."""
    out = set()
    m = ROOM_RE.search(s or "")
    if m:
        out |= {n.strip().lower()
                for n in re.split(r"[,&+]|\band\b", m.group(1)) if n.strip()}
    m = UNIT_RE.search(s or "")
    if m:
        out.add(m.group(1).lower())
    return out


def score(a, b):
    ra, rb = rooms_in(a), rooms_in(b)
    if ra and rb and not (ra & rb):
        return 0.0                      # different rooms are different jobs
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _variants(parent):
    v = {parent, parent.replace("Union ", ""), parent.replace(" District", ""),
         parent.replace("Union School District", "School District")}
    return sorted({x for x in v if x}, key=len, reverse=True)


def strip_parent(name, parent):
    """The card name with the client removed, however it was written."""
    out = (name or "").strip()
    for v in _variants(parent):
        cut = re.sub(r"^\s*" + re.escape(v) + r"\s*[\-–—:]*\s*", "", out,
                     flags=re.IGNORECASE)
        if cut != out:
            return cut.strip(" -–—")

    # The card may order the client differently than the folder does —
    # folder "Avana Springs Greystar" vs card "Greystar - Avana Springs".
    # A literal match fails and the client ends up duplicated into the
    # site, so drop leading segments the client already covers.
    ptok = set(alltoks(parent))
    segs = re.split(r"\s*[\-–—]\s*", out)
    i = 0
    while i < len(segs) - 1 and segs[i].strip():
        if set(alltoks(segs[i])) <= ptok and alltoks(segs[i]):
            i += 1
        else:
            break
    if i:
        out = " - ".join(segs[i:])
    return out.strip(" -–—")


def parse_card(name, parent):
    """-> {site, rooms, date_slash, date_dot}. A field the card doesn't
    state stays empty rather than being invented."""
    rest = strip_parent(name, parent)

    date_slash = date_dot = ""
    m = DATE_RE.search(rest)
    if m:
        mo, day = int(m.group(1)), int(m.group(2))
        yr = (m.group(3) or YEAR)[-2:]
        date_slash, date_dot = f"{mo}/{day}/{yr}", f"{mo}.{day}.{yr}"
        rest = rest[:m.start()] + " " + rest[m.end():]

    rooms = ""
    m = ROOM_RE.search(rest)
    if m:
        nums = [n.strip() for n in re.split(r"[,&+]|\band\b", m.group(1))
                if n.strip()]
        if nums:
            rooms = ("Room " if len(nums) == 1 else "Rooms ") + ",".join(nums)
        rest = rest[:m.start()] + " " + rest[m.end():]
    else:
        m = UNIT_RE.search(rest)
        if m:
            rooms = "Unit " + m.group(1)
            rest = rest[:m.start()] + " " + rest[m.end():]

    site = NOISE_RE.sub(" ", rest)
    site = re.sub(r"[()\[\]]", " ", site)
    site = re.sub(r"\s*[\-–—:/]+\s*", " ", site)
    site = re.sub(r"\s{2,}", " ", site).strip(" -–—,.")
    # A client fused into the first segment ("Coreland (Nordstrom Rack")
    # survives the strip above, so shave leading client words here too.
    ptok = set(alltoks(parent))
    words = site.split()
    while words and alltoks(words[0]) and set(alltoks(words[0])) <= ptok:
        words.pop(0)
    site = " ".join(words).strip(" -–—,.")
    return {"site": site, "rooms": rooms,
            "date_slash": date_slash, "date_dot": date_dot}


def _join(parts):
    return " - ".join(p for p in parts if p)


# ── multi-CLAIM jobs ───────────────────────────────────────────────────
#
# A second shape, with the fields in different places:
#
#     Trello      Nathan Bupte - AAA - 1st Claim
#     Folder      1st Claim
#     CompanyCam  Nathan Bupte - 1st Claim
#
# The carrier appears ONLY on Trello, and CompanyCam keeps the name here
# even though the site shape drops it — the project is one household's
# claim, not a place on a campus.

_ORD = {"1": "1st", "2": "2nd", "3": "3rd", "first": "1st",
        "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th"}
# "2nd claim", "3rd loss", "claim 2", "second claim". Deliberately NOT a
# bare ordinal: Metro at Main has "1st floor closet" and "2nd floor
# closet", which are floors, not claims.
CLAIM_RE = re.compile(
    r"\b(?:(?P<n>[0-9]{1,2})(?:st|nd|rd|th)?|(?P<w>first|second|third|fourth|"
    r"fifth))\s+(?:claim|loss)\b|\b(?:claim|loss)\s*#?\s*(?P<n2>[0-9]{1,2})\b",
    re.I)


def claim_ordinal(text):
    """'1st Claim' when the text names one, else ''."""
    m = CLAIM_RE.search(text or "")
    if not m:
        return ""
    raw = (m.group("n") or m.group("n2") or m.group("w") or "").lower()
    if raw in _ORD:
        return _ORD[raw] + " Claim"
    if raw.isdigit():
        n = int(raw)
        suf = ("th" if 10 <= n % 100 <= 20
               else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
        return f"{n}{suf} Claim"
    return ""


def carrier_in(text):
    """The carrier named in the text, in its canonical spelling."""
    try:
        import carriers
    except Exception:
        return ""
    low = " " + re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()) + " "
    best = ""
    for opt in carriers.options():
        v = opt.get("value") or ""
        if opt.get("group") == "Status":
            continue
        probe = " " + re.sub(r"[^a-z0-9 ]", " ", v.lower()).strip() + " "
        if probe.strip() and probe in low and len(v) > len(best):
            best = v
    return best


def claim_targets(name, parent):
    """Targets for a multi-claim job, or None when it isn't one."""
    ordinal = claim_ordinal(name)
    if not ordinal:
        return None
    carrier = carrier_in(name)
    # The name is what comes BEFORE the carrier or the claim wording —
    # not "everything that isn't them". Removing them and keeping the
    # remainder dragged the loss description into the name
    # ("Mansolino, Sayra Bathroom Garage", "Giles, Marcus Fire").
    text = name or ""
    cut = len(text)
    m = CLAIM_RE.search(text)
    if m:
        cut = min(cut, m.start())
    if carrier:
        m2 = re.search(re.escape(carrier), text, re.I)
        if m2:
            cut = min(cut, m2.start())
    who = text[:cut]
    who = re.sub(r"[()\[\]:/]", " ", who)
    who = re.sub(r"\s*[\-–—]+\s*$", "", who)
    who = re.sub(r"\s{2,}", " ", who).strip(" -–—,.")
    who = who or parent
    return {
        "trello": _join([who, carrier, ordinal]),
        "folder": ordinal,
        "companycam": _join([who, ordinal]),
        "site": who, "rooms": ordinal, "carrier": carrier,
        "date_slash": "", "date_dot": "", "kind": "claim",
    }


def targets(name, parent):
    claim = claim_targets(name, parent)
    if claim:
        return claim
    f = parse_card(name, parent)

    # What's left may be nothing but the insurer. "Riley, Robert -Safeco"
    # has no claim ordinal and no site, so the site shape proposed a
    # folder called "Safeco" — a carrier is not a place.
    #
    # This is how a multi-claim job whose CARDS don't say which claim they
    # are shows up: Giles Marcus has folders "Claim 1 (water)" and
    # "Claim 2 (Fire)" and two cards both named "Giles, Marcus - Farmers".
    # Which card is which claim is not in the data, so it is asked for
    # rather than guessed.
    bare = f["site"] and not f["rooms"] and not f["date_slash"]
    if bare and carrier_in(f["site"]) and \
            len(toks(f["site"]) - toks(carrier_in(f["site"]))) == 0:
        return {"trello": "", "folder": "", "companycam": "",
                "kind": "unclear", "carrier": carrier_in(f["site"]), **f}

    return {
        "trello": _join([parent, f["site"], f["rooms"], f["date_slash"]]),
        "folder": _join([f["site"], f["rooms"], f["date_dot"]]),
        "companycam": _join([f["site"], f["rooms"]]),
        "kind": "site", **f,
    }


def survey():
    root = jf.year_dir()
    with os.scandir(root) as it:
        clients = [e.name for e in it if e.is_dir(follow_symlinks=False)]

    parents = {}
    for name in clients:
        try:
            with os.scandir(os.path.join(root, name)) as it2:
                kids = sorted(e.name for e in it2
                              if e.is_dir(follow_symlinks=False)
                              and e.name.strip().lower() not in SCAFFOLD)
        except OSError:
            kids = []
        if len(kids) >= 2:
            parents[name] = kids

    import trello_job_sync as tjs
    import companycam_api as cc
    recs = tjs.collect(exclude_quality=False, exclude_logs=False)["records"]
    cards = [r for r in recs
             if not any(b in " ".join((r.get("board") or "").upper().split())
                        for b in DEAD_BOARDS)
             and not TEMPLATE_RE.search(r.get("display_name") or "")]
    projs = [p for p in cc.list_projects(per_page=100, max_pages=40)
             if (p.get("status") or "") != "deleted"]

    out = {"parents": [],
           "totals": {"clients": len(parents), "cards_live": len(cards),
                      "projects": len(projs)}}

    for parent, kids in sorted(parents.items()):
        d = distinctive(parent)
        pcards = [c for c in cards
                  if len(d & toks(c.get("display_name"))) >= min(2, len(d))
                  or d <= toks(c.get("display_name"))]
        if not pcards:
            continue
        cardlist = sorted(pcards, key=lambda c: c.get("display_name") or "")
        sites = [strip_parent(c.get("display_name") or "", parent)
                 for c in cardlist]

        def _assign(pool, name_of, floor=0.20):
            """Best pair anywhere wins first — assigning card-by-card in
            alphabetical order let an unrelated card consume the folder
            the right one needed."""
            pairs = []
            for i, s in enumerate(sites):
                for item in pool:
                    sc = score(s, strip_parent(name_of(item), parent))
                    if sc >= floor:
                        pairs.append((sc, i, item))
            pairs.sort(key=lambda t: -t[0])
            got, used = {}, set()
            for sc, i, item in pairs:
                k = name_of(item)
                if i in got or k in used:
                    continue
                got[i], _ = (item, sc), used.add(k)
            return got, used

        kid_hit, kid_used = _assign(kids, lambda k: k)
        proj_hit, _ = _assign(projs, lambda p: p.get("name") or "")

        jobs = []
        for i, card in enumerate(cardlist):
            cname = card.get("display_name") or ""
            t = targets(cname, parent)
            kid, ksc = kid_hit.get(i, ("", 0))
            pr, psc = proj_hit.get(i, (None, 0))
            jobs.append({
                "card": cname, "board": card.get("board"),
                "lane": card.get("lane"),
                "want_trello": t["trello"], "want_folder": t["folder"],
                "want_cc": t["companycam"],
                "site": t["site"], "rooms": t["rooms"],
                "od_now": kid, "od_score": round(ksc, 2),
                "cc_now": (pr or {}).get("name") or "",
                "cc_id": str((pr or {}).get("id") or ""),
                "cc_score": round(psc, 2),
            })
        out["parents"].append({
            "parent": parent, "jobs": jobs,
            "orphan_folders": [k for k in kids if k not in kid_used],
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--html", metavar="FILE")
    args = ap.parse_args(argv)

    d = survey()
    jobs = [j for p in d["parents"] for j in p["jobs"]]
    print(f"clients {len(d['parents'])} · live jobs {len(jobs)} · "
          f"cards {d['totals']['cards_live']} · "
          f"projects {d['totals']['projects']}")
    print(f"  no folder      {sum(1 for j in jobs if not j['od_now'])}")
    print(f"  no cc project  {sum(1 for j in jobs if not j['cc_now'])}")
    print(f"  orphan folders {sum(len(p['orphan_folders']) for p in d['parents'])}")

    if args.json:
        io.open(args.json, "w", encoding="utf-8").write(
            json.dumps(d, indent=1))
        print("wrote", args.json)
    if args.html:
        import naming_audit_page as page
        page.write(d, args.html)
        print("wrote", args.html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
