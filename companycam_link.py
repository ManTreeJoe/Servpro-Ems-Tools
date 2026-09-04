"""Tie CompanyCam projects to jobs the way Trello cards already are.

Measured 2026-08-20 on live data: 341 jobs carried a Trello card and 44
carried a CompanyCam project. Photos were therefore matched to jobs by
NAME at read time, and the names do not agree -- CompanyCam projects are
"Michelle Brayley" while the job is "Brayley, Michelle - AAA".

So matching has to survive three differences at once: word order, the
carrier suffix, and punctuation. `canon_key` removes a *recognized* carrier
suffix and a token SET handles the order.

Older releases stripped at the first " - " and therefore collapsed every
claim of a multi-claim job onto one key. Existing data can still contain
those legacy relationships. The first dry run cheerfully proposed tying
"Mansolino, Sayra - AAA - 1st Claim" to the job's SECOND claim, and a unit's
project to its parent. Anything where
the two sides disagree about which claim or unit they mean is refused
outright rather than guessed -- a wrong pin is worse than no pin,
because get_link returns the OLDEST row and a wrong one wins forever.
"""
from __future__ import annotations

import collections
import re

import ems_db
import ems_db_common as C

_STOP = {"and", "the", "of", "llc", "inc", "co", "corp",
         "unit", "apt", "claim", "self", "pay"}

_ORDINAL_RE = re.compile(r"\b(\d+)\s*(?:st|nd|rd|th)\s+claim\b", re.I)
# The \b AFTER the keyword is load-bearing: without it "apartment"
# matched inside "Apartments" and captured the trailing "s" as the unit
# number, so every job at an apartment complex looked like a unit and
# the guard passed everything.
_UNIT_RE = re.compile(r"\b(?:unit|apt|apartment|ste|suite)\b\s*#?\s*"
                      r"([a-z0-9][a-z0-9\-]*)\b", re.I)


def tokens(name: str) -> frozenset:
    """Order-free word set of the carrier-stripped name."""
    base = C.canon_key(name or "")
    base = re.sub(r"[^a-z0-9& ]+", " ", base.lower())
    return frozenset(t for t in base.split()
                     if len(t) > 1 and t not in _STOP and not t.isdigit())


def _claim_no(name: str) -> str:
    m = _ORDINAL_RE.search(name or "")
    return m.group(1) if m else ""


def _unit_no(name: str) -> str:
    m = _UNIT_RE.search(name or "")
    return (m.group(1) or "").lower() if m else ""


def _suffix_tokens(name: str) -> frozenset:
    """Words after the FIRST " - ".

    That strip is why "PCM - Kellogg Terrace Condominiums" and
    "PCM - (Gianni Villas) - 6/15/26" both reduce to "pcm" and looked
    like an exact match. The suffix is where the two disagree, so it has
    to be read before the strip is trusted.
    """
    parts = re.split(r"(?:\s+-\s*|-\s+)", name or "", maxsplit=1)
    if len(parts) < 2:
        return frozenset()
    tail = re.sub(r"[^a-z0-9& ]+", " ", parts[1].lower())
    return frozenset(t for t in tail.split()
                     if len(t) > 1 and t not in _STOP and not t.isdigit())


def _head_tokens(name: str) -> frozenset:
    """Order-free words before the first spaced dash.

    This is only a last-chance candidate finder. ``disagreement`` still has
    to approve the pair, which lets the backfill report a clear refusal for
    two claims/sites sharing a client without ever linking them.
    """
    head = re.split(r"(?:\s+-\s*|-\s+)", name or "", maxsplit=1)[0]
    head = re.sub(r"[^a-z0-9& ]+", " ", head.lower())
    return frozenset(t for t in head.split()
                     if len(t) > 1 and t not in _STOP and not t.isdigit())


def disagreement(project_name: str, job_name: str) -> str:
    """Why these two must NOT be tied, or "" if nothing objects.

    Silence is not approval — it only means no marker contradicted the
    other side.
    """
    pc, jc = _claim_no(project_name), _claim_no(job_name)
    if pc and jc and pc != jc:
        return f"project says claim {pc}, job says claim {jc}"
    if pc and not jc:
        return f"project names claim {pc}; the job does not say which"
    if jc and not pc:
        return f"job is claim {jc}; the project does not say which"

    pu, ju = _unit_no(project_name), _unit_no(job_name)
    if pu and ju and pu != ju:
        return f"project is unit {pu}, job is unit {ju}"
    if pu and not ju:
        return f"project is unit {pu}; the job is the parent"
    if ju and not pu:
        return f"job is unit {ju}; the project does not say which"

    # Both name something after the dash and they share NOTHING. One
    # side saying nothing is fine — that is just a shorter name — but two
    # different somethings means two different jobs.
    ps, js = _suffix_tokens(project_name), _suffix_tokens(job_name)
    if ps and js and not (ps & js):
        return (f"they disagree after the dash: "
                f"{' '.join(sorted(ps))} vs {' '.join(sorted(js))}")
    return ""


def plan(projects, jobs, linked_keys=frozenset()) -> dict:
    """Classify every project against the job list. Reads only.

    `projects` = [{id, name}], `jobs` = [{canon_key, display_name}].
    Returns buckets: `link` (safe), `refused` (a marker disagreed),
    `ambiguous` (more than one job), `unmatched`, `already`.
    """
    by_key: dict = {}
    by_tokens = collections.defaultdict(list)
    by_head = collections.defaultdict(list)
    for j in jobs:
        name = j.get("display_name") or ""
        by_key.setdefault(C.canon_key(name), j)
        t = tokens(name)
        if t:
            by_tokens[t].append(j)
        h = _head_tokens(name)
        if h:
            by_head[h].append(j)

    out = {"link": [], "refused": [], "ambiguous": [], "unmatched": [],
           "already": []}
    for p in projects:
        pname = (p.get("name") or "").strip()
        pid = str(p.get("id") or "")
        if not (pname and pid):
            continue

        job, how = by_key.get(C.canon_key(pname)), "exact"
        if job is None:
            cand = by_tokens.get(tokens(pname)) or []
            if not cand:
                cand = by_head.get(_head_tokens(pname)) or []
            if len(cand) > 1:
                out["ambiguous"].append({
                    "project": pname, "id": pid,
                    "jobs": [c.get("display_name") for c in cand]})
                continue
            job, how = (cand[0] if cand else None), "tokens"
        if job is None:
            out["unmatched"].append({"project": pname, "id": pid})
            continue

        jname = job.get("display_name") or ""
        why = disagreement(pname, jname)
        if why:
            out["refused"].append({"project": pname, "id": pid,
                                   "job": jname, "reason": why})
            continue
        if job.get("canon_key") in linked_keys:
            out["already"].append({"project": pname, "job": jname})
            continue
        out["link"].append({"project": pname, "id": pid, "job": jname,
                            "canon_key": job.get("canon_key"), "how": how})

    # Two projects proposing the SAME job is not two links, it is a
    # question about which project is the real one. Checking each match
    # only against the jobs — and never against the other matches — is
    # the identical mistake the folder rename made, on the identical
    # client ("Jennifer Parks" / "Jennifer Parks -Self Pay").
    claimed = collections.Counter(r["canon_key"] for r in out["link"])
    contested = {k for k, n in claimed.items() if n > 1}
    if contested:
        kept = [r for r in out["link"] if r["canon_key"] not in contested]
        for k in contested:
            rows = [r for r in out["link"] if r["canon_key"] == k]
            out["ambiguous"].append({
                "project": " / ".join(r["project"] for r in rows),
                "id": "", "jobs": [rows[0]["job"]],
                "reason": "more than one project claims this job"})
        out["link"] = kept
    return out


def apply(pairs, *, source="companycam_backfill") -> dict:
    """Write the approved pairs. Only ever called with `plan()['link']`
    the user has actually looked at."""
    done, failed = 0, []
    for row in pairs:
        key, pid = row.get("canon_key"), str(row.get("id") or "")
        if not (key and pid):
            continue
        try:
            ems_db.set_link(key, C.LINK_COMPANYCAM, pid, added_by=source)
            done += 1
        except Exception as ex:
            failed.append({"job": row.get("job"),
                           "error": f"{type(ex).__name__}: {ex}"})
    return {"linked": done, "failed": failed}
