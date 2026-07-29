"""Tracked to-do notes — tied to a job or loose ('untied'). Each note has
an open/done state so you can track what's still outstanding. Stored
locally in persistence `tracked_notes`. Pure data layer; UI in the audit
panel. Never raises to the caller.
"""
from __future__ import annotations
import datetime as _dt

import persistence


def _now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def list_notes(job: str = "", include_done: bool = False) -> list:
    """Notes filtered by `job` (a client name; "__untied__" = loose notes;
    "" = all jobs). Open notes first, then newest-first. Done excluded
    unless include_done."""
    try:
        notes = list(persistence._load().get("tracked_notes") or [])
    except Exception:
        return []
    jf = (job or "").strip()
    out = []
    for n in notes:
        if not include_done and n.get("done"):
            continue
        if jf == "__untied__":
            if (n.get("job") or "").strip():
                continue
        elif jf and (n.get("job") or "").strip().lower() != jf.lower():
            continue
        out.append(n)
    out.sort(key=lambda n: n.get("created_at", ""), reverse=True)  # newest 1st
    out.sort(key=lambda n: bool(n.get("done")))                    # open before done
    return out


def open_count(job: str = "") -> int:
    return len(list_notes(job, include_done=False))


def add(text: str, job: str = "") -> dict:
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty note"}
    try:
        st = persistence._load()
        notes = st.setdefault("tracked_notes", [])
        seq = int(st.get("tracked_notes_seq", 0)) + 1
        st["tracked_notes_seq"] = seq
        note = {
            "id":         seq,
            "text":       text,
            "job":        (job or "").strip(),
            "created_at": _now_iso(),
            "done":       False,
            "done_at":    "",
        }
        notes.append(note)
        persistence._save(st)
        return {"ok": True, "note": note}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def _find_and_save(note_id, mutate) -> dict:
    try:
        st = persistence._load()
        for n in st.get("tracked_notes", []):
            if n.get("id") == note_id:
                mutate(n)
                persistence._save(st)
                return {"ok": True, "note": n}
        return {"ok": False, "error": "note not found"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def set_done(note_id, done: bool) -> dict:
    def _m(n):
        n["done"] = bool(done)
        n["done_at"] = _now_iso() if done else ""
    return _find_and_save(note_id, _m)


def update(note_id, text: str) -> dict:
    t = (text or "").strip()
    if not t:
        return {"ok": False, "error": "empty note"}
    return _find_and_save(note_id, lambda n: n.__setitem__("text", t))


def delete(note_id) -> dict:
    try:
        st = persistence._load()
        notes = st.get("tracked_notes") or []
        before = len(notes)
        st["tracked_notes"] = [n for n in notes if n.get("id") != note_id]
        if len(st["tracked_notes"]) == before:
            return {"ok": False, "error": "note not found"}
        persistence._save(st)
        return {"ok": True}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
