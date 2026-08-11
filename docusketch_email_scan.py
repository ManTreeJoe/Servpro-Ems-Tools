"""Close out Docusketch requests from the delivery email.

DocuSketch mails the main inbox from `help@docusketch.com`, so the email
is the notification that a sketch is done and the tracker no longer has
to be ticked by hand.

The mail is machine-generated and regular:

    Subject: Sketch request for the project 5193826 delivered
    ...
    Request ID 3490065
    Request date 2026-08-07
    Project ID 5193826
    Project name Hilaflor hernandez
    Sketch type XACTIMATE Sketch

Two things about it decide the design:

**The job name is in the BODY, not the subject.** The subject only
carries DocuSketch's own project number, which means nothing to us. And
the first ~250 characters of the body are tracking URLs, so the default
255-char preview contains no usable text at all — this reads the full
body (`body_limit=0`).

**"created" and "delivered" are the same shape.** Both arrive for every
job. Only `delivered` may resolve a request; acting on `created` would
close the tracker the moment the sketch was ordered, which is precisely
backwards.

Names are matched against the requests we are ALREADY waiting on rather
than parsed loose from the mail, so a rewording on their end can't
silently stop the tracker closing. A tie matches nothing — that is when
a guess resolves the wrong job.
"""
from __future__ import annotations

import datetime as _dt
import re

import persistence as per

SENDER_DOMAIN = "docusketch.com"
SEEN_KEY = "docusketch_email_seen"
SEEN_CAP = 2000

# "…project 5193826 delivered" — the word that says it is done. `created`
# uses the identical template.
_DELIVERED_RE = re.compile(r"\bdeliver(?:ed|y)\b", re.I)
_CREATED_RE = re.compile(r"\bcreated\b", re.I)

# "Project name Hilaflor hernandez Sketch type XACTIMATE" — the value runs
# to the next known label, since it is a name and may be several words.
_FIELD_RES = {
    "project_name": re.compile(
        r"Project\s+name\s+(.+?)\s+(?:Sketch\s+type|Request\s+ID|"
        r"Project\s+ID|Download|$)", re.I | re.S),
    "project_id": re.compile(r"Project\s+ID\s+(\d+)", re.I),
    "request_id": re.compile(r"Request\s+ID\s+(\d+)", re.I),
    "request_date": re.compile(r"Request\s+date\s+([\d]{4}-[\d]{2}-[\d]{2})",
                               re.I),
}

_MIN_TOKEN = 3


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").casefold()).strip()


def _tokens(s):
    return [t for t in _norm(s).split() if len(t) >= _MIN_TOKEN]


def clean_body(body):
    """Strip the markup and tracking URLs the parser must not trip on."""
    txt = re.sub(r"<[^>]*>", " ", str(body or ""))
    txt = re.sub(r"https?://\S+", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def parse_delivery(msg):
    """The structured fields, or None when this isn't a delivery notice.

    Returns {project_name, project_id, request_id, request_date}.
    """
    subject = (msg or {}).get("subject") or ""
    body = clean_body((msg or {}).get("bodyPreview") or "")
    blob = f"{subject} {body}"
    # `created` and `delivered` share a template; only one is an event.
    if not _DELIVERED_RE.search(subject) and not _DELIVERED_RE.search(body):
        return None
    if _CREATED_RE.search(subject) and not _DELIVERED_RE.search(subject):
        return None
    out = {}
    for key, rx in _FIELD_RES.items():
        m = rx.search(blob)
        out[key] = (m.group(1).strip() if m else "")
    return out if (out.get("project_name") or out.get("project_id")) else None


def name_in_text(name, text):
    """Score for `name` appearing in `text`; 0.0 when it doesn't.

    EVERY significant token must be present. Matching a surname alone
    would close the wrong Smith, and these mails mark a job delivered.
    """
    nt = _tokens(name)
    if not nt:
        return 0.0
    hay = set(_tokens(text))
    if not hay:
        return 0.0
    if any(t not in hay for t in nt):
        return 0.0
    return len(nt) + sum(len(t) for t in nt) / 100.0


def best_match(text, candidates):
    """(name, score) for the candidate best evidenced by `text`.

    A TIE returns nothing — a client and their second claim both
    appearing is exactly when a guess resolves the wrong one.
    """
    scored = [(n, name_in_text(n, text)) for n in candidates or []]
    scored = [(n, s) for n, s in scored if s > 0]
    if not scored:
        return None, 0.0
    scored.sort(key=lambda kv: -kv[1])
    if len(scored) > 1 and abs(scored[0][1] - scored[1][1]) < 1e-9:
        return None, 0.0
    return scored[0]


def is_docusketch(msg):
    addr = (((msg or {}).get("from") or {}).get("emailAddress") or {})
    who = f"{addr.get('address', '')} {addr.get('name', '')}".casefold()
    return SENDER_DOMAIN in who


def _seen():
    raw = per.get(SEEN_KEY) or []
    return list(raw) if isinstance(raw, list) else []


def _mark_seen(ids):
    if not ids:
        return
    cur = _seen()
    cur.extend(i for i in ids if i and i not in cur)
    per.set_value(SEEN_KEY, cur[-SEEN_CAP:])


def scan_inbox(*, days: int = 30, top: int = 400, apply: bool = True,
               messages=None):
    """Find delivery notices and close the requests they name.

    `apply=False` reports what it WOULD close. `messages` lets a caller
    (or a test) supply the inbox instead of reading Outlook.
    """
    import docusketch_requests as dr

    pending = dr.pending_requests() or []
    by_name = {}
    for p in pending:
        nm = (p.get("client_name") or p.get("client") or "").strip()
        if nm:
            by_name[nm] = p

    if messages is None:
        try:
            import outlook_local
            since = _dt.datetime.now() - _dt.timedelta(days=int(days))
            # body_limit=0 → the WHOLE body. The default 255 is all
            # tracking URLs on these, so the name would never be seen.
            messages = outlook_local.list_recent_messages(
                folder="inbox", since=since, top=int(top), body_limit=0)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}",
                    "checked": 0, "matched": 0, "resolved": 0,
                    "unmatched": [], "results": []}

    seen = set(_seen())
    results, newly_seen = [], []
    matched = resolved = checked = 0

    for m in messages or []:
        if not is_docusketch(m):
            continue
        info = parse_delivery(m)
        if not info:
            continue           # a "created" notice, or an invoice
        mid = m.get("id") or ""
        if mid and mid in seen:
            continue
        checked += 1
        pname = info.get("project_name") or ""
        name, score = best_match(
            f"{pname} {clean_body(m.get('bodyPreview') or '')}",
            list(by_name))
        row = {"id": mid, "subject": m.get("subject", ""),
               "received": m.get("receivedDateTime", ""),
               "project_name": pname,
               "project_id": info.get("project_id", ""),
               "client": name or "", "score": round(score, 3),
               "resolved": False}
        if not name:
            # No pending request — but the job usually still exists, and
            # "a sketch arrived for Hernandez, Hilaflor" is far more
            # actionable than "1 unmatched email". The request may simply
            # never have been raised through the app.
            try:
                import ems_db
                hit = ems_db.find_job_by_name(pname) if pname else None
                if hit:
                    row["known_job"] = hit.get("display_name") or ""
            except Exception:
                pass
            # NOT marked seen — it may match once the request is raised.
            results.append(row)
            continue
        matched += 1
        if apply:
            try:
                dr.resolve((by_name[name] or {}).get("card_id") or "")
                row["resolved"] = True
                resolved += 1
            except Exception as ex:
                row["error"] = f"{type(ex).__name__}: {ex}"
            if mid:
                newly_seen.append(mid)
        results.append(row)

    if apply:
        _mark_seen(newly_seen)
    return {"ok": True, "checked": checked, "matched": matched,
            "resolved": resolved,
            "unmatched": [r for r in results if not r["client"]],
            "results": results}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(scan_inbox(apply="--apply" in sys.argv), indent=2,
                     default=str))
