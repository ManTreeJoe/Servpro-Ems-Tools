"""Per-job work history compiled from the daily run docs.

This is the *automatic* counterpart to the manually-authored
`job_notes` .md files: nothing here is typed by hand. It walks every
run doc under `runs_dir` (the month subfolders + any loose files),
parses each into (jobs, date), runs the same activity detection the
audit uses on each job's line, and aggregates per client into a
chronological "running doc" of the work done — so a job's whole history
can be seen at a glance, straight from the runs.

Parsing is delegated to `state_hub.hub.parse_run_doc`, which is cached
by file mtime, so a second lookup (any client) reuses the parsed corpus
instead of re-reading the .docx files off OneDrive.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

import config
from audit_logic import detect_activity
from job_notes_logic import _NOTES_ROOT, _safe_filename

# The parsed run-doc corpus is memoized against a signature of every
# doc's (path, mtime). Adding/editing a run doc changes the signature
# and triggers a rebuild; otherwise every client lookup is a dict scan.
_CORPUS = {"sig": None, "docs": None}


def _canon(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _iter_run_docs(runs_dir: str):
    """Yield the path of every .docx under `runs_dir` — both loose files
    saved directly in it and files one level down in a month subfolder
    (`July/…`), which is how the techs organize them. Skips Word lock
    files (`~$…`)."""
    if not runs_dir or not os.path.isdir(runs_dir):
        return
    def _docx_in(d):
        try:
            with os.scandir(d) as it:
                for e in it:
                    if (e.is_file(follow_symlinks=False)
                            and e.name.lower().endswith(".docx")
                            and not e.name.startswith("~$")):
                        yield e.path
        except OSError:
            return
    yield from _docx_in(runs_dir)
    try:
        with os.scandir(runs_dir) as it:
            subdirs = [e.path for e in it if e.is_dir(follow_symlinks=False)]
    except OSError:
        subdirs = []
    for sd in subdirs:
        yield from _docx_in(sd)


def _date_from_docstr(date_str: str):
    """Parse the date string parse_run_doc returns, tolerating the same
    format spread the run-doc filenames use."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%m-%d-%y", "%m-%d-%Y", "%m/%d/%y", "%m/%d/%Y",
                "%m.%d.%y", "%m.%d.%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _date_from_path(path: str):
    """Fall back to the date embedded in the filename ('… 7.13.26 …')."""
    m = re.search(r"\b(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})\b",
                  os.path.basename(path or ""))
    if not m:
        return None
    mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return datetime(y, mo, d)
    except ValueError:
        return None


def _fmt_date(dt) -> str:
    if not dt:
        return ""
    return f"{dt.month}.{dt.day}.{dt.year % 100:02d}"


def _parse_trello_date(s):
    """Trello timestamps are ISO-8601 ('2026-07-13T14:20:45.000Z')."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return None


def _load_corpus(force: bool = False):
    """Parse every run doc into
    {path, date(datetime|None), date_str, jobs:[...]} — memoized by the
    set of (path, mtime)."""
    from state_hub import hub
    runs_dir = ""
    try:
        runs_dir = config.load().get("runs_dir", "") or ""
    except Exception:
        pass
    paths = list(_iter_run_docs(runs_dir))
    sig = tuple(sorted((p, _mtime(p)) for p in paths))
    if not force and _CORPUS["sig"] == sig and _CORPUS["docs"] is not None:
        return _CORPUS["docs"]
    docs = []
    for p in paths:
        try:
            jobs, date_str = hub.parse_run_doc(p)
        except Exception:
            continue
        dt = _date_from_docstr(date_str) or _date_from_path(p)
        docs.append({"path": p, "date": dt,
                     "date_str": _fmt_date(dt) or (date_str or ""),
                     "jobs": jobs or []})
    _CORPUS["sig"] = sig
    _CORPUS["docs"] = docs
    return docs


def _matches(target_canon: str, job_client_canon: str) -> bool:
    if not target_canon or not job_client_canon:
        return False
    if job_client_canon == target_canon:
        return True
    # Tolerate the spelling drift across runs (last-name-only lines, a
    # trailing carrier suffix, etc.) — same containment rule the audit
    # PICS resolver uses.
    return (len(target_canon) >= 4
            and (target_canon in job_client_canon
                 or job_client_canon in target_canon))


def history_for_client(client: str) -> list:
    """Chronological (newest-first) work log for `client`, derived from
    every run doc. Each entry:
        {date_str, iso, labels:[str], raw:str, doc:str}
    where `labels` is the detected work (Demo, Mold Prep, …) and `raw`
    is the verbatim run-doc line it came from."""
    target = _canon(client)
    if not target:
        return []
    out = []
    seen = set()
    for doc in _load_corpus():
        for j in doc["jobs"]:
            if not _matches(target, _canon(j.get("client"))):
                continue
            try:
                info = detect_activity(j.get("raw") or "",
                                       section=j.get("section"),
                                       new_loss=j.get("new_loss"))
                labels = list(info.get("labels") or [])
            except Exception:
                labels = []
            raw = (j.get("raw") or "").strip()
            # "Unspecified" is detect_activity's catch-all when the line
            # matched no known stage — the raw line is more useful there.
            if labels and labels != ["Unspecified"]:
                work = ", ".join(labels)
            else:
                work = raw or "—"
            date_str = doc["date_str"] or "(undated)"
            # Variant run docs can repeat a date (a "Document" + a
            # "Subject" copy) — collapse identical date+work rows.
            dedupe_key = (date_str, work)
            if dedupe_key in seen:
                break
            seen.add(dedupe_key)
            out.append({
                "date_str": date_str,
                "iso": doc["date"].strftime("%Y-%m-%d") if doc["date"] else "",
                "labels": labels,
                "work": work,
                "raw": raw,
                # WHO was on the job that day — parse_run_doc already
                # unions the techs across the morning/afternoon lines, so
                # this is the full crew for the day. Line-level, not tied
                # to a single activity (the run docs don't record that).
                "techs": list(j.get("techs") or []),
                "time_slot": j.get("time_slot") or "",
                "doc": os.path.basename(doc["path"]),
            })
            break   # one entry per run doc
    out.sort(key=lambda r: r["iso"] or "0000-00-00", reverse=True)
    return out


def upload_events_for_client(client: str) -> list:
    """Trello attachment-upload history for `client`'s pinned card: WHO
    uploaded which form/photo, and WHEN. This is the one real
    per-action personnel signal — run-doc techs are line-level, but an
    attachment upload records the exact member + timestamp. Newest-first
    ``[{iso, date_str, file, uploader, is_image}]``; empty when there's
    no pinned card or Trello is unreachable (never raises)."""
    if not client:
        return []
    try:
        import persistence
        card_id = persistence.get_trello_card_id(client) or ""
    except Exception:
        card_id = ""
    if not card_id:
        return []
    try:
        import trello_client as tc
        atts = tc.card_attachments(card_id) or []
        uploaders = tc._attachment_uploaders(card_id) or {}
    except Exception:
        return []
    out = []
    for a in atts:
        if not a.get("isUpload"):
            continue    # skip link-only attachments; keep real uploads
        dt = _parse_trello_date(a.get("date"))
        mime = (a.get("mimeType") or "").lower()
        out.append({
            "iso": dt.strftime("%Y-%m-%d") if dt else "",
            "date_str": _fmt_date(dt),
            "file": a.get("name") or a.get("fileName") or "(file)",
            "uploader": uploaders.get(a.get("id")) or "",
            "is_image": mime.startswith("image/"),
        })
    out.sort(key=lambda r: r["iso"] or "0000-00-00", reverse=True)
    return out


def job_tracker(client: str) -> dict:
    """The full job tracker: run-doc activity (with the day's crew) AND
    Trello upload events (who uploaded which form/photo) woven into one
    newest-first timeline. Returns
    ``{activity:[...], uploads:[...], timeline:[...]}`` where each
    timeline row carries ``kind`` ('activity' | 'upload')."""
    activity = history_for_client(client)
    uploads = upload_events_for_client(client)
    timeline = []
    for a in activity:
        timeline.append({
            "kind": "activity",
            "iso": a["iso"], "date_str": a["date_str"],
            "work": a["work"], "labels": a["labels"],
            "techs": a.get("techs") or [],
            "time_slot": a.get("time_slot") or "", "raw": a["raw"],
        })
    for u in uploads:
        timeline.append({
            "kind": "upload",
            "iso": u["iso"], "date_str": u["date_str"],
            "file": u["file"], "uploader": u["uploader"],
            "is_image": u["is_image"],
        })
    timeline.sort(key=lambda r: r["iso"] or "0000-00-00", reverse=True)
    return {"activity": activity, "uploads": uploads, "timeline": timeline}


def running_doc_path(client: str, year=None) -> str:
    if year is None:
        year = datetime.now().year
    key = str(year)
    m = re.search(r"\d{4}", key)
    if m:
        key = m.group(0)
    return os.path.join(_NOTES_ROOT, key,
                        f"{_safe_filename(client)} - work log.md")


def save_running_doc(client: str, tracker=None, year=None) -> str:
    """Write/refresh the per-job running doc (Markdown) and return its
    path. Two sections — the run-doc activity (with the crew each day)
    and the Trello upload history (who uploaded what). Regenerated from
    the latest runs + card each time it's saved."""
    if tracker is None:
        tracker = job_tracker(client)
    activity = tracker.get("activity") or []
    uploads = tracker.get("uploads") or []
    lines = [
        f"# Job tracker — {client}",
        "",
        f"_Auto-generated from the daily runs + Trello · "
        f"{len(activity)} activity, {len(uploads)} upload(s)._",
        "",
        "## Activity (from run docs)",
        "",
    ]
    if activity:
        for h in activity:
            work = h.get("work") or "—"
            slot = f" ({h['time_slot']})" if h.get("time_slot") else ""
            who = f" · {', '.join(h['techs'])}" if h.get("techs") else ""
            lines.append(f"- **{h['date_str']}**{slot} — {work}{who}")
    else:
        lines.append("_No run-doc activity found for this job yet._")
    lines += ["", "## Uploads (from Trello)", ""]
    if uploads:
        for u in uploads:
            who = f" — {u['uploader']}" if u.get("uploader") else ""
            lines.append(f"- **{u['date_str'] or '(undated)'}** · "
                         f"{u['file']}{who}")
    else:
        lines.append("_No Trello upload history (or no card pinned)._")
    text = "\n".join(lines) + "\n"
    path = running_doc_path(client, year)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
