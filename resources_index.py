"""An index of the reference material on the share — everything that
isn't a job.

X:\\IE_Public holds 53 top-level folders. Three are the year job folders
the audit already covers; the other 50 are the office's reference
material — Forms_Contracts, W9_Insurance, Safety, Vendors, Verbal
Briefing & Other Templates, Estimating Department, and so on — plus a few
loose files at the root (ON CALL PROTOCOL.docx, Office Extension List,
rule-1403.pdf). Nobody can find anything in there without knowing where
it already lives.

Measured before building: **50,256 files in 2,069 folders**, and a
32-thread walk of it takes **73 seconds**. So this can never be a live
search — it is an index that is rebuilt deliberately and then read
instantly. SQLite rather than JSON for the same reason: 50k rows is a
~12MB document, and parsing that per keystroke is the thing the index
exists to avoid.

The job folders are excluded on purpose. They are the biggest part of the
share by far, they change constantly, and the audit already resolves
them — indexing them here would make the rebuild an order of magnitude
slower to answer a question nothing asks.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paths as _paths

DB_PATH = _paths.data("resources.db")

# Year job folders — "2026 Jobs", "2025 LA FIRES".
_JOB_DIR_RE = re.compile(r"^\d{4}\s+(jobs|la\s+fires)\b", re.I)

# Windows/Office debris nobody is ever looking for.
_SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
_SKIP_PREFIX = ("~$",)
_SKIP_EXT = {".tmp", ".lnk"}

# Same reasoning as the audit's child scan: the wait is network latency,
# not disk, so threads buy almost linear speedup.
_WORKERS = 32

_lock = threading.Lock()


def default_root() -> str:
    """The share root, from the audit's own config so there is one
    setting rather than two that can disagree."""
    try:
        import config
        base = (config.load() or {}).get("audit_base") or ""
    except Exception:
        base = ""
    return base


def _skip_file(name: str) -> bool:
    low = name.lower()
    if low in _SKIP_NAMES or low.startswith(_SKIP_PREFIX):
        return True
    return os.path.splitext(low)[1] in _SKIP_EXT


def _connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path       TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            ext        TEXT,
            folder     TEXT,
            top        TEXT,
            size       INTEGER,
            mtime      REAL
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_files_name ON files(name)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_files_top  ON files(top)")
    con.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, value TEXT)""")
    con.commit()


def roots(base: str = "") -> list:
    """The folders to index: everything under the share EXCEPT the year
    job folders. Returns absolute paths."""
    base = base or default_root()
    if not base or not os.path.isdir(base):
        return []
    out = []
    try:
        with os.scandir(base) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and not _JOB_DIR_RE.match(e.name):
                    out.append(e.path)
    except OSError:
        return []
    return sorted(out)


def _walk_one(root):
    """Every file under one root, as insert tuples.

    scandir rather than os.walk + os.stat. os.walk hands back names only,
    so size/mtime cost a stat PER FILE — 50,256 separate round trips to
    the share, which took long enough that the first rebuild never
    finished. A DirEntry carries the stat data from the directory read
    itself, so this is the same walk for free.
    """
    top = os.path.basename(root)
    rows, stack = [], [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:      # `with`, or Windows holds the dir
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(e.path)
                    continue
                if _skip_file(e.name):
                    continue
                st = e.stat(follow_symlinks=False)
                rows.append((e.path, e.name,
                             os.path.splitext(e.name)[1].lower(),
                             cur, top, st.st_size, st.st_mtime))
            except OSError:
                continue
    return rows


def rebuild(base: str = "", *, progress_cb=None) -> dict:
    """Re-walk the share and replace the index.

    Takes about 73 seconds against the live share, so callers should run
    it in a thread and show progress rather than blocking on it. The
    swap happens at the END, in one transaction: a rebuild that dies
    half-way must not leave a half-indexed share looking complete.
    """
    base = base or default_root()
    tops = roots(base)
    if not tops:
        return {"ok": False, "error": "share not reachable", "files": 0}

    # Loose files at the share root belong in the index too — the on-call
    # protocol and the extension list live there.
    collected = []
    try:
        with os.scandir(base) as it:
            for e in it:
                if e.is_file(follow_symlinks=False) and not _skip_file(e.name):
                    try:
                        st = e.stat()
                    except OSError:
                        continue
                    collected.append((e.path, e.name,
                                      os.path.splitext(e.name)[1].lower(),
                                      base, "", st.st_size, st.st_mtime))
    except OSError:
        pass

    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for rows in ex.map(_walk_one, tops):
            collected.extend(rows)
            done += 1
            if progress_cb:
                try:
                    progress_cb({"done": done, "total": len(tops),
                                 "files": len(collected)})
                except Exception:
                    pass

    with _lock:
        con = _connect()
        try:
            _ensure_schema(con)
            with con:
                con.execute("DELETE FROM files")
                con.executemany(
                    "INSERT OR REPLACE INTO files "
                    "(path, name, ext, folder, top, size, mtime) "
                    "VALUES (?,?,?,?,?,?,?)", collected)
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                    ("built_at", str(time.time())))
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                    ("base", base))
        finally:
            con.close()
    return {"ok": True, "files": len(collected), "roots": len(tops),
            "seconds": round(time.time() - started, 1)}


def stats() -> dict:
    """What's in the index and how old it is."""
    if not os.path.isfile(DB_PATH):
        return {"ok": True, "built": False, "files": 0}
    con = _connect()
    try:
        _ensure_schema(con)
        n = con.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
        rows = {r["key"]: r["value"]
                for r in con.execute("SELECT key, value FROM meta")}
    finally:
        con.close()
    built = float(rows.get("built_at") or 0)
    return {"ok": True, "built": bool(n), "files": n,
            "built_at": built, "base": rows.get("base") or "",
            "age_hours": round((time.time() - built) / 3600, 1) if built else None}


def search(query: str, *, limit: int = 50, ext: str = "", top: str = "") -> list:
    """Files whose NAME or FOLDER matches every word of `query`.

    Every word, not any: "w9 vendor" should mean both, or a two-word
    search returns more than a one-word search, which is never what
    anyone means.
    """
    q = " ".join(str(query or "").split()).strip().lower()
    if not os.path.isfile(DB_PATH):
        return []
    where, params = [], []
    for tok in [t for t in q.split() if t]:
        # `_` and `%` are LIKE wildcards. Unescaped, a search for
        # "W9_Insurance" or "a_job_photo" matches almost every row —
        # `_` means "any character" — so the index answers a question
        # nobody asked and looks broken rather than empty.
        tok = tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(LOWER(name) LIKE ? ESCAPE '\\' "
                     "OR LOWER(folder) LIKE ? ESCAPE '\\')")
        params += [f"%{tok}%", f"%{tok}%"]
    if ext:
        where.append("ext = ?")
        params.append(ext if ext.startswith(".") else "." + ext)
    if top:
        where.append("top = ?")
        params.append(top)
    if not where:
        return []
    sql = ("SELECT path, name, ext, folder, top, size, mtime FROM files "
           f"WHERE {' AND '.join(where)} "
           # Newest first: the current version of a form is the one wanted.
           "ORDER BY mtime DESC LIMIT ?")
    params.append(max(1, int(limit or 50)))
    con = _connect()
    try:
        _ensure_schema(con)
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def top_folders() -> list:
    """The reference areas, with a file count each — the index's own
    table of contents."""
    if not os.path.isfile(DB_PATH):
        return []
    con = _connect()
    try:
        _ensure_schema(con)
        return [dict(r) for r in con.execute(
            "SELECT top, COUNT(*) n FROM files WHERE top != '' "
            "GROUP BY top ORDER BY n DESC")]
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    if "--rebuild" in sys.argv:
        def _p(d):
            print(f"\r  {d['done']}/{d['total']} folders · "
                  f"{d['files']:,} files", end="", flush=True)
        print("rebuilding…")
        print("\n", rebuild(progress_cb=_p))
    elif len(sys.argv) > 1:
        for r in search(" ".join(a for a in sys.argv[1:] if not a.startswith("-"))):
            print(f"  {r['name']}\n      {r['folder']}")
    else:
        print(stats())
        for t in top_folders()[:15]:
            print(f"  {t['n']:6,}  {t['top']}")
