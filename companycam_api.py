"""CompanyCam REST API client — project name → id resolution.

The zip-export importer (companycam_import.py) reads a project name out of a
downloaded zip. This module is the API-first counterpart: given a job/client
name, hit CompanyCam's live API, find the matching PROJECT, and hand back its
`id` so downstream code can pull photos (`GET /v2/projects/{id}/photos`) or
check for new ones without a manual export.

Auth: a single Bearer access token (generated in the CompanyCam app) stored in
config as `companycam_api_token`. No OAuth / Azure needed — read + download
only. See docs.companycam.com: List Projects supports a `query=` param that
filters by name or address line 1 server-side, so a "find" is one call.

Rate limits (per token): GET 240/min. We retry 429/503 with backoff, honoring
Retry-After, exactly like trello_client._call.
"""
import json
import os
import time
import urllib.parse
import urllib.request

import config

API_BASE = "https://api.companycam.com/v2"
_USER_AGENT = "EMS-Automation/1.0"


def _token():
    cfg = config.load()
    tok = (cfg.get("companycam_api_token") or "").strip()
    if not tok:
        raise RuntimeError(
            "CompanyCam not configured. Set companycam_api_token in "
            r"%APPDATA%\EMS Automation\config.json (generate an access "
            "token in the CompanyCam app → Integrations → Developer).")
    return tok


def is_configured():
    """True when an access token is present — lets callers hide/skip the
    CompanyCam path gracefully instead of raising."""
    try:
        return bool((config.load().get("companycam_api_token") or "").strip())
    except Exception:
        return False


def _call(path, *, params=None, method="GET", data=None, _max_retries=5):
    """One request against the CompanyCam API. Bearer auth header, JSON
    body for writes, parsed-JSON return. Retries 429 (rate limit) and 503
    (transient, idempotent methods only) with Retry-After / exponential
    backoff. Raises urllib HTTPError on other non-2xx."""
    qs = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{API_BASE}{path}" + (f"?{qs}" if qs else "")
    headers = {
        "User-Agent": _USER_AGENT,
        "Authorization": "Bearer " + _token(),
        "Accept": "application/json",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            break
        except urllib.request.HTTPError as ex:
            retryable = (ex.code == 429
                         or (ex.code == 503 and method != "POST"))
            if retryable and attempt < _max_retries:
                retry_after = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                if delay <= 0:
                    delay = float(min(2 ** attempt, 8))
                time.sleep(delay)
                attempt += 1
                continue
            raise
    if not raw:
        return None
    return json.loads(raw)


# ── Projects ────────────────────────────────────────────────────────────

def list_projects(query="", per_page=100, max_pages=20, modified_since=""):
    """Return raw project dicts. `query` filters by name / address-line-1
    server-side (empty = all). Pages through until a short page or
    `max_pages` (safety cap — 20×100 = 2000 projects). per_page maxes at
    100 API-side."""
    out = []
    per_page = max(1, min(int(per_page or 100), 100))
    page = 1
    while page <= max_pages:
        params = {"page": page, "per_page": per_page}
        if query:
            params["query"] = query
        if modified_since:
            params["modified_since"] = modified_since
        batch = _call("/projects", params=params) or []
        if not isinstance(batch, list):
            break
        out.extend(batch)
        if len(batch) < per_page:
            break                       # last page
        page += 1
    return out


def _fmt_address(proj):
    """Best-effort one-line address from a project's `address` object.
    CompanyCam nests street/city/state/postal — degrade gracefully if the
    shape differs."""
    addr = proj.get("address") or {}
    if not isinstance(addr, dict):
        return ""
    parts = [
        addr.get("street_address_1") or addr.get("street_address") or "",
        addr.get("city") or "",
        addr.get("state") or "",
        addr.get("postal_code") or addr.get("zip") or "",
    ]
    return ", ".join(p for p in (str(x).strip() for x in parts) if p)


def _shape(proj):
    """Trim a raw project to the fields callers need to tie a name to an id."""
    return {
        "id":         str(proj.get("id") or ""),
        "name":       (proj.get("name") or "").strip(),
        "address":    _fmt_address(proj),
        "status":     proj.get("status") or "",
        "created_at": proj.get("created_at"),
        "photo_url":  proj.get("project_url") or proj.get("photo_url") or "",
    }


# ── Name matching ───────────────────────────────────────────────────────

def _tokens(s):
    """Lowercased alphanumeric word tokens, punctuation dropped. Handles
    'Bernardo, Foilan' and 'Foilan Bernardo' identically (order/comma-
    insensitive set)."""
    return {t for t in ''.join(
        c if c.isalnum() else ' ' for c in (s or "").lower()).split()
        if len(t) >= 2}


def _score(query_name, proj_name):
    """0-100 similarity between a job/client name and a project name.
    Token-set based so 'Last, First' == 'First Last'. Full-set equality is
    a perfect score; otherwise Jaccard overlap, nudged up when one name's
    tokens are a subset of the other's (an initial vs full first name)."""
    q = _tokens(query_name)
    p = _tokens(proj_name)
    if not q or not p:
        return 0
    if q == p:
        return 100
    inter = q & p
    if not inter:
        return 0
    union = q | p
    jac = len(inter) / len(union)
    score = int(round(jac * 80))
    # Subset bonus: every query token is present in the project (or vice
    # versa) — e.g. "David Smith" ⊆ "David Smith Water Loss".
    if q <= p or p <= q:
        score = max(score, 85)
    return min(score, 99)


def find_project(name, address_hint="", threshold=60):
    """Find the CompanyCam project for a job/client name and tie it to its
    id.

    Returns:
      {ok: True, match: {id, name, address, ...} | None,
       candidates: [ {..., score} ... sorted best-first ],
       reason: str}

    `match` is the top candidate only when its score clears `threshold`
    AND it's unambiguous (beats the runner-up by >10, or is the sole hit).
    Otherwise match=None and the caller should let the user pick from
    `candidates`. `address_hint` breaks ties when two projects share a
    name (common for a customer with two losses)."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "no name given", "match": None,
                "candidates": []}
    try:
        # Server-side query narrows the set; fall back to a full scan only
        # if the query returns nothing (e.g. project titled by address).
        raw = list_projects(query=name)
        if not raw:
            raw = list_projects(query=name.split(",")[0].strip())
    except urllib.request.HTTPError as ex:
        return {"ok": False, "error": f"HTTP {ex.code}", "match": None,
                "candidates": []}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "match": None,
                "candidates": []}

    hint_tokens = _tokens(address_hint)
    scored = []
    for proj in raw:
        shaped = _shape(proj)
        sc = _score(name, shaped["name"])
        # Address hint: reward a project whose address shares tokens with
        # the hint so the right loss wins when names collide. +12 (uncapped)
        # is deliberately bigger than the 10-pt disambiguation gap below, so
        # an address confirmation can break a tie between two identically
        # named projects (a customer with two losses).
        if hint_tokens and shaped["address"] and (
                hint_tokens & _tokens(shaped["address"])):
            sc += 12
        shaped["score"] = sc
        scored.append(shaped)
    scored.sort(key=lambda s: (-s["score"], s["name"].lower()))

    match = None
    reason = "no candidates" if not scored else "below threshold"
    if scored:
        top = scored[0]
        second = scored[1]["score"] if len(scored) > 1 else 0
        if top["score"] >= threshold and (top["score"] - second > 10
                                          or len(scored) == 1):
            match = top
            reason = "matched"
        elif top["score"] >= threshold:
            reason = "ambiguous — multiple close matches"
    return {"ok": True, "match": match,
            "candidates": scored[:10], "reason": reason}


def find_project_id(name, address_hint="", *, use_graph=True,
                    folder_path="", trello_card=""):
    """The matched project id for a job name, or "" when unresolved.

    When `use_graph` (default), first checks the shared job-identity graph
    (ems_db): if this name — or any known alias of it — already has a
    `companycam_project` link, that id is returned WITHOUT an API call
    (cache hit, saves rate-limit budget). On a fresh API resolve, the id is
    written back into the graph and the spelling is tied to the job, so the
    next lookup (from any tool / spelling) is a cache hit. Pass `folder_path`
    / `trello_card` to tie CompanyCam to the SAME job those identify."""
    if use_graph:
        try:
            import ems_db
            job = ems_db.find_job_by_name(name)
            if job:
                cached = ems_db.get_link(job["canon_key"],
                                         ems_db.LINK_COMPANYCAM)
                if cached:
                    return cached
        except Exception:
            pass

    res = find_project(name, address_hint=address_hint)
    m = res.get("match") if res.get("ok") else None
    pid = m["id"] if m else ""

    if pid and use_graph:
        try:
            import ems_db
            ems_db.resolve_and_link(
                name, companycam_project=pid,
                folder_path=folder_path, trello_card=trello_card,
                create=True, source="companycam")
        except Exception:
            pass
    return pid


# ── Photos ──────────────────────────────────────────────────────────────

_IMG_EXT_BY_CT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/heic": ".heic", "image/webp": ".webp", "image/gif": ".gif",
}


def _original_uri(photo):
    """The full-resolution download URL from a photo's `uris` array. Falls
    back to `web` then any uri. CompanyCam uris look like
    [{"type": "original", "uri": "https://..."}, ...]."""
    uris = photo.get("uris") or []
    by_type = {}
    for u in uris:
        if isinstance(u, dict) and u.get("type"):
            by_type[str(u["type"]).lower()] = u.get("uri") or u.get("url") or ""
    for t in ("original", "web", "thumbnail"):
        if by_type.get(t):
            return by_type[t]
    # Unknown shape — grab the first url-ish value.
    for u in uris:
        if isinstance(u, dict):
            v = u.get("uri") or u.get("url")
            if v:
                return v
    return ""


def _shape_photo(photo):
    """Trim a raw photo to what the downloader / new-check needs."""
    return {
        "id":                str(photo.get("id") or ""),
        "captured_at":       photo.get("captured_at"),
        "created_at":        photo.get("created_at"),
        "processing_status": photo.get("processing_status") or "",
        "original_url":      _original_uri(photo),
        "coordinates":       photo.get("coordinates"),
        "photo_url":         photo.get("photo_url") or "",
        "creator_name":      photo.get("creator_name") or "",
    }


def list_project_photos(project_id, per_page=100, max_pages=50):
    """Every photo for a project, newest capture first (API default order).
    Paginated; max_pages×per_page caps a runaway pull (50×100 = 5000)."""
    pid = str(project_id or "").strip()
    if not pid:
        return []
    out = []
    per_page = max(1, min(int(per_page or 100), 100))
    page = 1
    while page <= max_pages:
        batch = _call(f"/projects/{pid}/photos",
                      params={"page": page, "per_page": per_page}) or []
        if not isinstance(batch, list):
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out


def new_photos(project_id, since_epoch=None, include_unprocessed=False):
    """Shaped photos captured AFTER `since_epoch` (unix seconds). None =
    everything. Skips photos still processing (no final `original` yet)
    unless `include_unprocessed`. Returns newest-first."""
    try:
        cutoff = int(since_epoch) if since_epoch is not None else None
    except (TypeError, ValueError):
        cutoff = None
    out = []
    for raw in list_project_photos(project_id):
        p = _shape_photo(raw)
        cap = p["captured_at"]
        try:
            cap = int(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap = None
        if cutoff is not None and (cap is None or cap <= cutoff):
            continue
        if not include_unprocessed and p["processing_status"] not in (
                "", "processed"):
            continue
        if not p["original_url"]:
            continue
        out.append(p)
    out.sort(key=lambda x: (x["captured_at"] or 0), reverse=True)
    return out


def _download(url, dest_path, _max_retries=3):
    """Stream one photo to disk. The `uris` are pre-signed storage URLs, so
    they're fetched WITHOUT the Bearer header. Best-effort retry on
    transient errors. Writes atomically (temp + rename)."""
    import shutil
    tmp = dest_path + ".part"
    headers = {"User-Agent": _USER_AGENT}
    req = urllib.request.Request(url, headers=headers)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=60) as r, \
                    open(tmp, "wb") as fh:
                shutil.copyfileobj(r, fh)
            break
        except urllib.request.HTTPError as ex:
            if ex.code in (429, 500, 502, 503) and attempt < _max_retries:
                time.sleep(min(2 ** attempt, 8))
                attempt += 1
                continue
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        except (urllib.request.URLError, TimeoutError):
            if attempt < _max_retries:
                time.sleep(min(2 ** attempt, 8))
                attempt += 1
                continue
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    os.replace(tmp, dest_path)
    return dest_path


def _photo_filename(photo, tech=""):
    """A stable, sortable filename carrying the tech + capture time + a short
    id token (so re-runs dedup by name, like the zip importer). e.g.
    'CC FB 2026-06-30 13-04-11 a1b2c3d4.jpg'."""
    import datetime as _dt
    cap = photo.get("captured_at")
    stamp = ""
    try:
        if cap is not None:
            stamp = _dt.datetime.fromtimestamp(int(cap)).strftime(
                "%Y-%m-%d %H-%M-%S")
    except (TypeError, ValueError, OSError, OverflowError):
        stamp = ""
    ext = os.path.splitext(urllib.parse.urlparse(
        photo.get("original_url") or "").path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif"):
        ext = ".jpg"
    idtok = (photo.get("id") or "")[:8]
    t = (tech or "").strip()
    parts = ["CC"] + ([t] if t else []) + ([stamp] if stamp else []) + [idtok]
    return " ".join(p for p in parts if p).strip() + ext


def count_new_photos(project_id, since_epoch=None):
    """Fast 'do we have new photos?' — just the count of new processed
    photos since `since_epoch`, no download."""
    return len(new_photos(project_id, since_epoch=since_epoch))


def probe_new(project_id, since_epoch="auto"):
    """Count new photos + the distinct uploaders (creator_name) WITHOUT
    downloading — so the UI can pre-fill the tech picker."""
    import persistence
    pid = str(project_id or "").strip()
    if not pid:
        return {"count": 0, "uploaders": []}
    since = (persistence.get_companycam_seen(pid).get("last_captured_at")
             if since_epoch == "auto" else since_epoch)
    try:
        photos = new_photos(pid, since_epoch=since)
    except Exception:
        return {"count": 0, "uploaders": []}
    ups, seen = [], set()
    for p in photos:
        nm = (p.get("creator_name") or "").strip()
        if nm and nm.lower() not in seen:
            seen.add(nm.lower())
            ups.append(nm)
    return {"count": len(photos), "uploaders": ups}


def pull_new_photos(project_id, dest_dir, *, since_epoch="auto", job="",
                    subfolder="", advance_watermark=True, tech=""):
    """Download NEW project photos into `dest_dir` and advance the per-
    project high-water mark.

    since_epoch:
      "auto" (default) → use persistence.get_companycam_seen(project_id)
      None             → pull ALL photos
      int              → pull photos captured after this unix time
    subfolder: optional child of dest_dir to drop files into (e.g. a stage
      like "Initial"); created on demand.
    Returns {ok, downloaded, skipped, latest, files:[paths], error?}.
    Dedups by filename (capture-time + id token), so a same-day re-run
    combines instead of writing '(2)' copies."""
    import persistence
    pid = str(project_id or "").strip()
    if not pid:
        return {"ok": False, "error": "no project id", "downloaded": 0,
                "skipped": 0, "files": [], "latest": None}

    if since_epoch == "auto":
        since = persistence.get_companycam_seen(pid).get("last_captured_at")
    else:
        since = since_epoch

    try:
        photos = new_photos(pid, since_epoch=since)
    except urllib.request.HTTPError as ex:
        return {"ok": False, "error": f"HTTP {ex.code}", "downloaded": 0,
                "skipped": 0, "files": [], "latest": None}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "downloaded": 0,
                "skipped": 0, "files": [], "latest": None}

    target = dest_dir if not subfolder else os.path.join(dest_dir, subfolder)
    os.makedirs(target, exist_ok=True)
    # Existing basenames anywhere under dest_dir → skip re-downloads.
    existing = set()
    for _root, _dirs, _files in os.walk(dest_dir):
        for _f in _files:
            existing.add(_f.lower())

    downloaded, skipped, files, latest = 0, 0, [], since
    for p in photos:
        fname = _photo_filename(p, tech)
        if fname.lower() in existing:
            skipped += 1
        else:
            dest = os.path.join(target, fname)
            try:
                _download(p["original_url"], dest)
            except Exception:
                continue          # transient — leave for the next run
            # Stamp file time to capture time so Explorer sorts by shoot date.
            try:
                if p["captured_at"] is not None:
                    ts = float(int(p["captured_at"]))
                    os.utime(dest, (ts, ts))
            except (OSError, OverflowError, ValueError):
                pass
            existing.add(fname.lower())
            files.append(dest)
            downloaded += 1
        cap = p["captured_at"]
        if cap is not None and (latest is None or int(cap) > int(latest)):
            latest = int(cap)

    if advance_watermark and latest is not None:
        persistence.set_companycam_seen(pid, latest, job=job)

    return {"ok": True, "downloaded": downloaded, "skipped": skipped,
            "files": files, "latest": latest}
