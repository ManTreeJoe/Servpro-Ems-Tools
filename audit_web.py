"""Daily Run Audit — Pywebview panel (biggest block).

Web-rendered audit dashboard. Loads today's run-doc, runs the
existing audit_logic.audit_jobs on every client in it, and renders
each result as a card. Full per-row workflow: import (SP/WC), pin
folder, comment, Trello link, docusketch request, single-card
re-audit, multi-unit picker, attachments manager, bulk actions
(import / flag / copy issues / re-audit), one-off audit mode, year
scope, smart filters (needs attention, starred, stale).

Backend reuse: every data function comes from the existing audit
stack. No business logic forked — only the GUI layer swaps.

  • run-doc parse:        state_hub.parse_run_doc
  • client → audit result: audit_logic.audit_jobs (via run_audit_gui wrapper)
  • Trello pin lookup:     persistence.get_trello_card_id
  • activity detection:    audit_logic.detect_activity
  • OD folder open:        os.startfile

Launch:
    python audit_web.py
    # or via launcher:
    python launcher.py --tool audit_web
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import threading
import webbrowser
import dept_browser

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Backend imports — reused without modification. The audit logic lives in
# UI-free modules (run_doc, sp_enrich, wc_zip_import) so this web panel no
# longer drags the 8K-line Tk run_audit_gui into the live app. See
# EMS_Tk_Extraction_Plan.md.
import audit_logic
import persistence
from state_hub import hub as _state_hub
from run_doc import (
    _find_run_doc_for_date, _extract_date_from_folder_name,
    _activity_labels_from_run_doc, audit_jobs,
)
from sp_enrich import enrich_with_sharepoint, _append_sp_manifest_originals
import wc_zip_import as _wcz

# Downloads folder — same one-liner every tool in the suite defines locally
# (no shared home for it). Used by the WC/DocuSign zip-discovery flow.
DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")


ASSETS_DIR = os.path.join(_HERE, "audit_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


from web_helpers import (
    jsonify_datetime as _jsonify_datetime,
    job_root_from_pics as _wh_job_root_from_pics,
    pics_from_jobroot as _wh_pics_from_jobroot,
    contents_pics_from_jobroot as _wh_contents_pics_from_jobroot,
    run_bg as _wh_run_bg,
)


def _emit_js_all(js: str) -> None:
    """Dispatch `js` on every open webview window AND forward it into the
    embedded tool iframe (panel event listeners live on the iframe's
    window, not the shell's — see `Api._emit`).

    Unlike `Api._emit`, this is instance-free: it targets
    `webview.windows` directly. `do_import` needs that because the IUQ
    and Snapshot panels delegate imports to a freshly-built, *windowless*
    `audit_web.Api()`, so `self._window` is None there and per-instance
    emits silently no-op. There's a single shell window hosting whichever
    tool iframe is active, so emitting to all windows reaches the panel
    the user actually clicked in. Best-effort; failures are swallowed."""
    iframe_js = js.replace(
        "window.dispatchEvent(", "__ems_iframe_win__.dispatchEvent(")
    wrapped = (
        "(function(){"
        "try{" + js + "}catch(e){}"
        "try{"
        "var __f=document.getElementById('content-frame');"
        "if(__f && __f.contentWindow){"
        "var __ems_iframe_win__=__f.contentWindow;"
        + iframe_js +
        "}"
        "}catch(e){}"
        "})();"
    )
    try:
        for _w in (webview.windows or []):
            try:
                _w.evaluate_js(wrapped)
            except Exception:
                pass
    except Exception:
        pass


def _find_scope_pdfs(downloads_dir: str, *, client_hint: str = "") -> list:
    """Scan the Downloads folder for scope PDFs the user dropped there.

    Match rules:
      • File extension is ``.pdf``
      • Filename contains ``\\bscope\\b`` (word boundary so
        "microscope" never matches)
      • Sorted: client-matching files first (newest mtime first
        within each bucket), then generic scopes by mtime.

    Returns a list of ``{path, filename, mtime, client_match}``.

    `client_hint` enables a per-client scoring boost: tokens 3+ chars
    from the client name (`["smith", "john"]`) that appear in the
    filename mark the entry as a client match.
    """
    if not downloads_dir or not os.path.isdir(downloads_dir):
        return []
    import re as _re
    scope_re = _re.compile(r"\bscope\b", _re.IGNORECASE)
    # Build client tokens for the boost. Strip non-letters, keep
    # tokens >= 3 chars so "Jo" doesn't sweep every filename.
    client_tokens = []
    if client_hint:
        for tok in _re.findall(r"[A-Za-z]{3,}", str(client_hint).lower()):
            if tok not in client_tokens:
                client_tokens.append(tok)
    out = []
    try:
        with os.scandir(downloads_dir) as it:
            for e in it:
                if not e.is_file(follow_symlinks=False):
                    continue
                fn = e.name
                if not fn.lower().endswith(".pdf"):
                    continue
                if not scope_re.search(fn):
                    continue
                try:
                    mtime = e.stat().st_mtime
                except OSError:
                    mtime = 0
                fn_lower = fn.lower()
                client_match = any(t in fn_lower for t in client_tokens)
                out.append({
                    "path":          e.path,
                    "filename":      fn,
                    "mtime":         mtime,
                    "client_match":  client_match,
                })
    except OSError:
        return []
    # Client matches first; within each bucket newest mtime first.
    out.sort(key=lambda r: (not r["client_match"], -r["mtime"]))
    return out


def _parse_simple_scope(raw: str) -> list:
    """Fallback scope parser for plain-text user input. Recognizes a
    room header (a short non-empty line that doesn't start with a list
    bullet) followed by one or more bulleted/indented lines.

    Example input:

        Living Room
        - Demo carpet
        - Replace baseboards

        Master Bedroom
        - Pack contents
        - Remove drywall

    Output:
        [{"name": "Living Room", "items": ["Demo carpet", ...]}, ...]

    Used when snapshot_gui.parse_scope's strict material-vocab matcher
    rejects the paste (most common with simple user-edited scopes).
    """
    rooms: list[dict] = []
    current: dict | None = None
    for raw_line in (raw or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            # Blank line ends the current room (next non-empty line
            # becomes a header). Keeps multi-paragraph pastes clean.
            if current and current.get("items"):
                rooms.append(current); current = None
            continue
        stripped = line.lstrip()
        # Bullet markers commonly seen in pasted scope: "- ", "* ",
        # "• ", "·  ", numbered "1. " / "1) ", or leading tab/4-space
        # indentation. Treat ANY of these as an item line.
        is_bullet = bool(stripped) and stripped[0] in "-*•·"
        # Numbered "1. " / "12) " — count ALL leading digits so 10+ don't
        # fall through and get mis-read as room headers (was: stripped[1]
        # only, which broke on any two-digit number).
        ndig = 0
        while ndig < len(stripped) and stripped[ndig].isdigit():
            ndig += 1
        is_numbered = (ndig > 0 and ndig < len(stripped)
                       and stripped[ndig] in ".)")
        is_indented = line.startswith(("\t", "    ")) and len(stripped) > 0
        if is_bullet or is_numbered or is_indented:
            # Strip the leading bullet character + following whitespace.
            item = stripped
            if is_bullet:
                item = stripped[1:].lstrip()
            elif is_numbered:
                # "1. text" / "12) text" — drop the number + delimiter.
                item = stripped[ndig + 1:].lstrip()
            if not item:
                continue
            if current is None:
                current = {"name": "General", "items": []}
            current["items"].append(item)
        else:
            # Non-bullet line → new room header.
            if current and current.get("items"):
                rooms.append(current)
            current = {"name": stripped.rstrip(":").strip(), "items": []}
    if current and current.get("items"):
        rooms.append(current)
    return rooms


def _safe_is_starred(client):
    """Best-effort is_starred lookup. Never raises — old persistence
    files that haven't seen a star yet should return False cleanly."""
    try:
        return bool(persistence.is_starred(client))
    except Exception:
        return False


def _pair_results_to_jobs(jobs, results):
    """Yield (job, result) for each audit result, mapping it back to the
    run-doc job it came from.

    Normally results line up 1:1 with jobs, but a multi-claim job (one
    run-doc line → several "Nth Claim" folders) expands into multiple
    results that all trace back to the SAME job via `claim_origin`. A
    plain zip() would misalign every row after the expansion, so we pair
    by canonical client name instead, falling back to positional zip when
    a result carries no recognizable origin."""
    def _canon(s):
        return " ".join((s or "").strip().lower().split())
    # Group jobs by canonical client so a name can map to MORE than one
    # run-doc line — the multi-claim case where one property is dispatched
    # as "(1s claim)" + "(2nd claim Kitchen)" on two lines.
    groups = {}
    for j in (jobs or []):
        groups.setdefault(_canon(j.get("client")), []).append(j)
    used = set()
    out = []
    leftovers = list(jobs or [])
    for i, r in enumerate(results or []):
        r = r or {}
        origin = r.get("claim_origin") or r.get("client") or ""
        group = groups.get(_canon(origin)) or []
        j = None
        if group:
            # Prefer an as-yet-unpaired line; fall back to the whole group
            # so a 1→N fan-out (one line → several claim folders) still
            # maps every result back to its single source line.
            pool = [g for g in group if id(g) not in used] or group
            rn = audit_logic.claim_number_from_hint(
                r.get("claim_subfolder") or "")
            if rn is not None and len(pool) > 1:
                j = next(
                    (g for g in pool
                     if audit_logic.claim_number_from_hint(
                         g.get("claim_hint") or "") == rn), None)
            if j is None:
                j = pool[0]
            used.add(id(j))
        if j is None and i < len(leftovers):
            j = leftovers[i]
        out.append((j or {}, r))
    return out


def _card_display_map(jobs):
    """{client: pinned-card name} for a whole batch of rows, in two queries.

    Pass the result to `_shape_job(display_map=...)`. Without it, each row
    costs its own `find_job_by_name` + `get_link` — ~600 queries on a
    300-row audit, which is free against local SQLite and ruinous against
    a hosted one. Never raises: a failure here just means rows fall back to
    the run-doc spelling, exactly as they did before a card was pinned.
    """
    try:
        import ems_db as _emsdb
        return _emsdb.card_display_names_for(
            [(j.get("client") or "") for j in jobs or ()])
    except Exception:
        return {}


def _shells_for(path):
    """{"own": [...], "from_children": [...]} — which work shells a job has.

    "Does this one have a recon side?" currently means opening the folder.
    Live 2026: EMS 79%, RECON 25%, CONTENTS 14%, and 320 of 580 clients
    are EMS-only.

    An umbrella keeps its shells one level down inside each unit, so its
    own root has none — reporting an empty list for the whole property
    would be true and useless. Falls back to the union across children,
    flagged separately so the UI can say where they came from.

    Two scandirs at worst, and only when a folder was resolved.
    """
    if not path:
        return {"own": [], "from_children": []}
    try:
        import job_folders
        own = job_folders.shells_at(path)
        if own:
            return {"own": own, "from_children": []}
        return {"own": [], "from_children": job_folders.shells_of_children(path)}
    except Exception:
        return {"own": [], "from_children": []}


def _shape_job(j, audit_result, pin_id, display_map=None):
    """Combine one run-doc job + its audit result into a single
    JSON-shaped row for the frontend. Pulls activity labels via
    `detect_activity` so chip rendering matches the Tk version.

    `display_map` is the batched card-name lookup from
    `_card_display_map`; omit it for a single row and the per-row
    lookup is used instead.

    Every field must be JSON-serializable — pywebview's bridge
    cannot pass datetime objects. `_jsonify_datetime` handles the
    `last` field; other fields are already primitives.
    """
    raw = j.get("raw") or ""
    section = j.get("section") or "work"
    try:
        info = audit_logic.detect_activity(
            raw, section=section, new_loss=j.get("new_loss"))
        activity_labels = list(info.get("labels") or [])
    except Exception:
        activity_labels = []

    form_issues_raw  = list(audit_result.get("form_issues")  or [])
    photo_issues_raw = list(audit_result.get("photo_issues") or [])
    aging = int(audit_result.get("aging") or 0)
    found = bool(audit_result.get("found"))

    is_commercial = False
    try:
        is_commercial = bool(persistence.is_commercial(j.get("client") or ""))
    except Exception:
        is_commercial = False

    # ── Resolved + commercial filtering ─────────────────────────────
    # Render-time filter (mirrors Tk's pattern in run_audit_gui where
    # each row checks `is_resolved(run_date, client, persist_key(item))`
    # before rendering it as missing). Without this, toggling the 🏢
    # Commercial flag wrote resolved entries to persistence but the
    # row's form_issues array still showed ATP/CIF/CER/CoS because
    # audit_logic.check_forms returns the raw missing list.
    client_name = j.get("client") or ""
    try:
        import audit_logic as _al
        run_date_iso = ""
        try:
            run_date_iso = _dt.date.today().strftime("%Y-%m-%d")
        except Exception:
            pass

        def _is_resolved(item):
            if not client_name or not run_date_iso:
                return False
            try:
                return bool(persistence.is_resolved(
                    run_date_iso, client_name, _al.persist_key(item)))
            except Exception:
                return False

        def _commercial_skip(item):
            # When marked commercial, the four commercial-only forms
            # (ATP, CIF, CER, CoS) aren't required for this job — drop
            # them from the missing list AND mark them resolved in
            # persistence so subsequent re-audits stay clean.
            if not is_commercial:
                return False
            try:
                if _al.is_commercial_form(item):
                    try:
                        persistence.set_resolved(
                            run_date_iso, client_name,
                            _al.persist_key(item), True)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
            return False

        form_issues  = [it for it in form_issues_raw
                        if not _is_resolved(it) and not _commercial_skip(it)]
        photo_issues = [it for it in photo_issues_raw
                        if not _is_resolved(it)]
    except Exception:
        form_issues = form_issues_raw
        photo_issues = photo_issues_raw

    # Day-by-day photo requirements (day 2+). The existing photo check
    # covers day 1; this surfaces a per-day expectation for repeated
    # activities (Demo day 2 photos, etc.) that auto-clears once a photo
    # dated to that day is on disk. Each entry → {label, date, day_num}.
    requirements = []
    try:
        from datetime import datetime as _rdt
        for req in (audit_result.get("requirements") or []):
            if req.get("satisfied") or int(req.get("day_num", 1)) < 2:
                continue
            try:
                _rd = _rdt.strptime(req["date"], "%Y-%m-%d")
                _rds = f"{_rd.month}/{_rd.day}"
            except Exception:
                _rds = req.get("date", "")
            requirements.append({
                "label":   req.get("label", "photos"),
                "date":    _rds,
                "day_num": int(req.get("day_num", 1)),
            })
    except Exception:
        requirements = []

    # Misplaced items — found elsewhere in a commercial parent's tree
    # (wrong folder), NOT missing. Surfaced so the row can render a
    # "⚠ in <folder>, not in <campus>" note instead of a false red.
    # Each entry: {label, where}.
    misplaced_forms  = [m for m in (audit_result.get("misplaced_forms") or [])
                        if isinstance(m, dict)]
    misplaced_photos = [m for m in (audit_result.get("misplaced_photos") or [])
                        if isinstance(m, dict)]

    # Re-derive `flagged` after filtering — if commercial removed
    # everything, the row should flip to clean instead of staying red.
    # Misplaced items keep the row flagged (it still needs re-filing).
    flagged = bool(form_issues or photo_issues or requirements
                   or misplaced_forms or misplaced_photos or (not found))
    # SharePoint matches (set by enrich_with_sharepoint in run_audit
    # / run_audit_filtered). Each match dict is shaped down to just
    # what the import dialog needs — keeps the payload light and
    # avoids leaking pywebview-unfriendly types.
    sp_matches_raw = audit_result.get("sharepoint_matches") or []
    sharepoint_matches = []
    for m in sp_matches_raw:
        # `match_stats` (set by enrich_with_sharepoint) breaks the
        # new/imported split into the three signals it actually
        # considered — basename hits, fingerprint hits, size-alone
        # hits, and the surviving "new" set. Lets the dialog show
        # "26 already in OD by name · 0 by fingerprint · 0 by size
        # · 0 still new" so the user can SEE why the diff is large
        # instead of being told to trust the number.
        # `new_names` is the actual surviving basename set — a
        # bounded slice ships so the dialog can list them inline
        # ("These files are flagged new:") for the user to verify.
        stats = m.get("match_stats") or {}
        new_names = list(m.get("new_names") or [])
        sharepoint_matches.append({
            "name":         m.get("name") or "",
            "path":         m.get("path") or "",
            "tech":         m.get("tech") or "",
            "new_count":    int(m.get("new_count") or 0),
            # The source dict from sharepoint._build_sp_match stores
            # the image count under "count" — the prior shape read
            # "img_count" which nothing writes, so every match showed
            # "0 files · 0 new" in the dialog even when the chip
            # showed N new on SP (Cindy Costales 21+ case 2026-05-28).
            "img_count":    int(m.get("img_count") or m.get("count") or 0),
            "matches_date": bool(m.get("matches_date")),
            "match_stats": {
                "name":  int(stats.get("name")  or 0),
                "fp":    int(stats.get("fp")    or 0),
                "size":  int(stats.get("size")  or 0),
                "new":   int(stats.get("new")   or 0),
                "total": int(stats.get("total") or 0),
            },
            # Cap at 50 names — the dialog only needs enough to show
            # the user the flavor of what's flagged; full list isn't
            # useful in UI and inflates the bridge payload.
            "new_names": sorted(new_names)[:50],
        })
    sharepoint_new = int(audit_result.get("sharepoint_new") or 0)
    pics_count = int(audit_result.get("pics_count") or 0)

    # Multi-unit fields — surfaced so the list row can display
    # "Avila Apartments — Unit 1413" instead of just the property
    # name. `unit` comes from the run-doc parse (UNIT_RE), and
    # `unit_folder` is the actual subfolder audit_logic.find_unit
    # descended into (e.g. "Unit 1413"). Either or both may be
    # populated for a multi-unit row.
    unit_val = (audit_result.get("unit") or j.get("unit") or "") or ""
    # Stable per-row identifier. The same property can appear
    # multiple times in the run-doc with different units (Avila
    # Apartments Unit 1413 + Unit 1416 on Tue 5/26 is the canonical
    # example). The frontend's selection / lookup state keys off
    # this so two rows for the same client are individually
    # selectable. Falls back to `client` for single-unit jobs so
    # existing behavior is unchanged.
    client_name_for_key = j.get("client") or ""
    row_key = (f"{client_name_for_key}::{unit_val}"
               if unit_val else client_name_for_key)
    # Display name = the pinned Trello card's name — the job's canonical
    # identity per the 2026-07-22 rule ("jobs represented by the name on
    # the Trello card"). Only overrides when a card is actually pinned;
    # the run-doc / folder spelling stays as `client`, the matching key,
    # so folder + pin lookups are unaffected.
    display_name = ""
    if pin_id:
        if display_map is not None:
            display_name = display_map.get(j.get("client") or "") or ""
        else:
            try:
                import ems_db as _emsdb
                _j = _emsdb.find_job_by_name(j.get("client") or "")
                if (_j and _j.get("display_name") and _emsdb.get_link(
                        _j.get("canon_key") or "", _emsdb.LINK_TRELLO)):
                    display_name = _j["display_name"]
            except Exception:
                display_name = ""
    return {
        "client":           j.get("client") or "",
        "display_name":     display_name,
        "row_key":          row_key,
        "section":          section,
        "activity":         activity_labels,
        "techs":            list(j.get("techs") or []),
        "new_loss":         bool(j.get("new_loss")),
        "folder":           audit_result.get("folder") or "",
        "path":             audit_result.get("path") or "",
        "shells":           _shells_for(audit_result.get("path") or ""),
        "found":            found,
        "form_issues":      form_issues,
        "photo_issues":     photo_issues,
        "aging_days":       aging,
        "last_seen":        _jsonify_datetime(audit_result.get("last")),
        "flagged":          flagged,
        "trello_card_id":   pin_id or "",
        "is_commercial":    is_commercial,
        "is_starred":       _safe_is_starred(j.get("client")),
        # Multi-unit context — both empty for single-unit jobs.
        "unit":             str(unit_val),
        "unit_folder":      audit_result.get("unit_folder") or "",
        "tenant":           audit_result.get("tenant") or j.get("tenant") or "",
        "time_slot":        audit_result.get("time_slot") or j.get("time_slot") or "",
        # Commercial-parent grouping: `claim_origin` is the parent insured
        # (e.g. "Menifee Union School District"); `subjob` marks a campus
        # child row so the frontend can indent it under a collapsible
        # parent header. Empty/False for normal single-folder jobs.
        "claim_origin":     audit_result.get("claim_origin") or "",
        "subjob":           bool(audit_result.get("subjob")),
        # Commercial-parent umbrella head — a container, not a job. The UI
        # drops its per-job buttons + it gets no SP scan / missing checks.
        "is_parent":        bool(audit_result.get("is_parent")),
        # Misplaced (found in wrong folder) — renders as a ⚠ note, not a
        # missing row. Each: {label, where}.
        "misplaced_forms":  misplaced_forms,
        "misplaced_photos": misplaced_photos,
        # SharePoint match data — drives the 📥 +N chip + per-row
        # SP import dialog (no need to re-search on demand).
        "sharepoint_matches": sharepoint_matches,
        "sharepoint_new":     sharepoint_new,
        "pics_count":         pics_count,
        # Day-by-day photo requirements (day 2+) still owed.
        "requirements":     requirements,
        # Convenience: any issue at all so the JS filter chips can
        # quickly bucket without re-counting.
        "any_issue":        bool(form_issues or photo_issues or requirements
                                 or misplaced_forms or misplaced_photos),
        # Misplaced items are NOT counted as missing — they exist, just in
        # the wrong folder. The frontend renders their own ⚠ count.
        "total_missing":    len(form_issues) + len(photo_issues) + len(requirements),
        "total_misplaced":  len(misplaced_forms) + len(misplaced_photos),
    }


def _unpack_arg_bundle(*args):
    """Defensive args unpacker for bridge methods.

    Pywebview 6.x has been observed (in production, audit_web's
    archive_month_apply call) to deliver multi-arg JS calls as a
    single bundled list in the first Python positional, rather than
    expanding them across the declared positionals. Symptom:
    ``int(year)`` crashes with "int() argument must be ... not
    'list'" because `year` arrives as `[year, month, [srcs...]]`.

    This helper checks if the first arg is a list/tuple while the
    rest are None — if so, unpacks. Returns the args in the original
    order with `None` padding for missing entries.
    """
    args = list(args)
    if args and isinstance(args[0], (list, tuple)) and \
            all(a is None for a in args[1:]):
        bundle = list(args[0])
        bundle.extend([None] * max(0, len(args) - len(bundle)))
        return tuple(bundle[:len(args)])
    return tuple(args)


# Carrier tokens dropped when grouping audit-picker candidates, so
# "Ensign, Michael - Mercury" folds into "Ensign, Michael". Kept to
# distinctive carrier words (no ambiguous surname-like tokens such as
# "state"/"farm"/"national" — the superset-fold catches those cases).
_CANDIDATE_CARRIER_TOKENS = {
    "mercury", "allstate", "geico", "progressive", "nationwide",
    "farmers", "travelers", "lemonade", "usaa", "safeco", "statefarm",
    "hartford", "chubb", "erie", "amica", "csaa", "wawanesa", "kemper",
    "hippo", "encompass", "foremost", "metlife", "esurance", "aaa",
}


def _candidate_group_key(name):
    """Order-independent token-set for `name`, carrier tokens dropped, so
    'Kathy Ensign'/'Ensign Kathy'/'Ensign, Kathy' share a key and
    'Ensign, Michael - Mercury' folds toward 'Ensign, Michael'."""
    from web_helpers import norm_tokens as _nt
    toks = _nt(name) - _CANDIDATE_CARRIER_TOKENS
    return frozenset(toks) if toks else frozenset(_nt(name))


def _group_audit_candidates(raw):
    """Collapse the flat source hits (`raw`: list of dicts with name /
    source / detail / path / score / has_card) into ONE combined candidate
    per job. Groups by token-set (carrier-stripped) with a superset-fold,
    picks the most-complete variant as the winner, and aggregates sources
    + the mergeable variant list. Returns the sorted candidate list.

    Pulled out of Api.list_audit_candidates so it's unit-testable without
    run-doc / persistence / Trello wiring."""
    buckets = {}
    for r in raw:
        buckets.setdefault(_candidate_group_key(r["name"]), []).append(r)

    # Superset-fold — smaller token-sets first so a base name becomes the
    # bucket, then any strict-superset bucket ("…-Mercury") folds in.
    folded = {}
    for k in sorted(buckets.keys(), key=len):
        target = next((fk for fk in folded if fk and fk < k), None)
        if target is not None:
            folded[target].extend(buckets[k])
        else:
            folded[k] = list(buckets[k])

    def _rank(m):
        # folder+card > folder > card > score.
        return (1 if (m["has_card"] and m["path"]) else 0,
                1 if m["path"] else 0,
                1 if m["has_card"] else 0,
                m["score"])

    cands = []
    for members in folded.values():
        winner = max(members, key=_rank)
        label = winner["name"]
        if winner["has_card"]:
            try:
                import ems_db as _db
                _j = _db.find_job_by_name(winner["name"])
                if _j and _j.get("display_name"):
                    label = _j["display_name"]
            except Exception:
                pass
        sources = [s for s in ("run", "pin", "folder")
                   if any(m["source"] == s for m in members)]
        path = winner["path"] or next(
            (m["path"] for m in members if m["path"]), "")
        variants = sorted({m["name"] for m in members})
        cands.append({
            "name":      winner["name"],
            "label":     label,
            "source":    winner["source"],
            "sources":   sources,
            "detail":    winner["detail"],
            "path":      path,
            "score":     max(m["score"] for m in members),
            "variants":  variants,
            "mergeable": len(variants) >= 2,
            "has_card":  any(m["has_card"] for m in members),
        })

    # Best score first; at a tie prefer the "Last, First" comma form, then
    # alphabetical for stability.
    cands.sort(key=lambda c: (-c["score"],
                              0 if "," in c["name"] else 1,
                              c["name"].lower()))
    return cands


from companycam_web_api import CompanyCamApi
from job_settings_api import JobSettingsApi


class Api(JobSettingsApi, CompanyCamApi):
    """Methods exposed to JS via `pywebview.api`."""

    def __init__(self):
        self._window = None
        self._audit_running = False
        # In-memory cache of the last DAILY RUN audit. Hydrated from
        # disk on first access so results survive home-window restarts.
        # One-off audits live in _oneoff_rows below — kept separate so
        # the user's per-job spot-checks don't pollute the main list.
        self._last_rows = []
        self._last_meta = {}
        # One-off audits — populated by `audit_one_job`. Keyed by
        # canonical client name so re-typing "Munson" 5 times updates
        # the same row instead of creating duplicates.
        self._oneoff_rows = []
        self._cache_loaded = False

    def attach(self, window):
        self._window = window
        self._hydrate_cache_from_disk()

    # ── Disk-persistent cache (date-keyed) ───────────────────────────
    def _cache_path(self):
        import paths
        try:
            base = paths.DATA_DIR
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "audit_web_cache.json")

    def _hydrate_cache_from_disk(self):
        """Load cached rows from disk if they're for today's date.
        Stale (different date) caches are ignored — they'll be
        overwritten on the next run.

        Migration: an earlier build wrote one-off-audited rows into
        `_last_rows`. After a hydrate, anything in the cache whose
        client isn't in today's run-doc is split into `_oneoff_rows`
        so it stops polluting the Daily Run list."""
        if self._cache_loaded:
            return
        self._cache_loaded = True
        path = self._cache_path()
        if not os.path.isfile(path):
            return
        try:
            import json
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return
        cached_date = (data.get("meta") or {}).get("date_iso") or ""
        today = _dt.date.today().strftime("%Y-%m-%d")
        if cached_date != today:
            return  # stale — keep empty cache, user will Run Audit
        cached_rows = data.get("rows") or []
        meta = data.get("meta") or {}
        # Split cached rows by run-doc membership.
        rundoc_clients = set()
        try:
            doc = _find_run_doc_for_date(_dt.date.today())
            if doc:
                jobs, _ = _state_hub.parse_run_doc(doc)
                rundoc_clients = {(j.get("client") or "") for j in jobs}
        except Exception:
            rundoc_clients = set()
        daily_rows, oneoff_rows = [], []
        for r in cached_rows:
            client = r.get("client") or ""
            if not rundoc_clients or client in rundoc_clients:
                daily_rows.append(r)  # belongs in Daily Run
            else:
                oneoff_rows.append(r)  # migrated from old mixed cache
        self._last_rows = daily_rows
        self._last_meta = meta
        if oneoff_rows:
            # Prepend instead of replacing — don't clobber any one-
            # off audits the user may have run in the current process
            # before the first read.
            existing = {r.get("client") for r in self._oneoff_rows}
            for r in oneoff_rows:
                if r.get("client") not in existing:
                    self._oneoff_rows.append(r)
            # Persist the de-mixed cache so subsequent process starts
            # see a clean Daily-Run-only file.
            self._persist_cache_to_disk()

    def _persist_cache_to_disk(self):
        """Write cache to disk after a successful audit run."""
        try:
            import json
            path = self._cache_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {"rows": self._last_rows, "meta": self._last_meta}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, default=str)
        except Exception:
            pass

    # ── Reads ────────────────────────────────────────────────────────
    def today_meta(self) -> dict:
        """Return run-doc metadata (date, path, job count) without
        running the actual audit. Lets the UI show the header
        immediately while the audit thread spins up."""
        d = _dt.date.today()
        try:
            doc_path = _find_run_doc_for_date(d)
        except Exception:
            doc_path = None
        jobs = []
        if doc_path:
            try:
                jobs, _ = _state_hub.parse_run_doc(doc_path)
            except Exception:
                jobs = []
        return {
            "date_iso":   d.strftime("%Y-%m-%d"),
            "date_label": d.strftime("%A, %B %d, %Y"),
            "doc_path":   doc_path or "",
            "doc_exists": bool(doc_path and os.path.isfile(doc_path)),
            "job_count":  len(jobs),
        }

    def last_audit(self) -> dict:
        """Return the cached audit rows from the most-recent run in
        this process. Empty list on a cold start. Used so the UI
        re-renders instantly when the user changes filter chips
        without re-running the audit."""
        return {
            "rows": list(self._last_rows),
            "meta": dict(self._last_meta),
        }

    # ── Actions ──────────────────────────────────────────────────────
    def run_audit(self, use_cache: bool = True) -> dict:
        """Kick off the actual audit on a background thread. Returns
        immediately with {"started": bool}; results stream back via
        window.evaluate_js() events.

        ``use_cache`` is positional (not keyword-only) because
        pywebview's JS bridge marshals JS arguments positionally —
        `await pywebview.api.run_audit(true)` becomes
        `run_audit(True)` on the Python side, and a `*,` keyword-
        only signature blows up with TypeError.

        Events fired:
          • audit:progress {i, n, client}
          • audit:done     {ok, rows, meta, error}
        """
        if self._audit_running:
            return {"started": False, "reason": "audit already running"}
        self._audit_running = True

        def _bg():
            try:
                # Full re-scan (use_cache=False) — also drop the
                # year-folder listing cache so a brand-new client
                # folder created since the cache was warmed gets
                # picked up. Cached audits keep the listing.
                if not use_cache:
                    try:
                        import audit_logic as _al
                        if hasattr(_al, "invalidate_year_index_cache"):
                            _al.invalidate_year_index_cache()
                    except Exception:
                        pass
                d = _dt.date.today()
                doc_path = _find_run_doc_for_date(d)
                if not doc_path:
                    self._emit_done(
                        ok=False,
                        error="No run doc found for today")
                    return
                jobs, run_date = _state_hub.parse_run_doc(doc_path)
                # Drop empty-client rows AND pass the FULL job dicts
                # (not just names) so audit_jobs sees `unit`, `tenant`,
                # `new_loss`, `raw`, `time_slot`. Stripping to bare
                # names — the prior behavior — silently lost the unit
                # info, so multi-unit rows like the two Avila
                # Apartments lines (Unit 1413 + Unit 1416 on Tue 5/26)
                # both audited the property root with unit=None and
                # never descended into their respective unit subfolders.
                # Tk's daily-run code path passes the full dicts (see
                # run_audit_gui.py:2364 — `names = [j for j in
                # self.jobs ...]`).
                jobs = [j for j in jobs if (j.get("client") or "").strip()]
                client_names = jobs
                total = len(jobs)
                self._emit(
                    f"window.dispatchEvent(new CustomEvent("
                    f"'audit:progress', "
                    f"{{detail: {{i: 0, n: {total}, "
                    f"client: 'starting audit…'}}}}));")

                # Per-job progress callback — fires once per audited
                # client so the UI shows "Auditing 12/47 · Smith, John"
                # instead of a silent spinner for 10-30s.
                import json as _json
                def _progress(idx, total_n, name):
                    try:
                        payload = {"i": int(idx), "n": int(total_n),
                                   "client": str(name or "")}
                        self._emit(
                            "window.dispatchEvent(new CustomEvent("
                            "'audit:progress', {detail: "
                            + _json.dumps(payload) + "}));")
                    except Exception:
                        pass

                # Run the actual audit — this is the slow part.
                results, err = audit_jobs(
                    client_names,
                    run_date=run_date,
                    use_cache=use_cache,
                    progress_cb=_progress,
                    expand_subjobs=True)
                if err:
                    self._emit_done(ok=False, error=err)
                    return

                # ── Done with the audit core — paint rows NOW ───
                # SP enrichment used to run inline here (adding 30-120s
                # to wall-clock time before audit:done fired). That
                # made the loading icon look stuck. Now we emit done
                # immediately and run SP enrichment as a SEPARATE
                # background pass that streams per-row updates via
                # `audit:sp_update` events. JS splices each updated
                # row into state.rows as they arrive.
                rows = []
                _pairs = list(_pair_results_to_jobs(jobs, results))
                # Batch the pinned-card name lookup for the whole render.
                # Keyed on the RESOLVED client (an expanded sub-job or
                # multi-claim row carries its own), so it must be computed
                # after that adoption rule, not from the raw run-doc jobs.
                _display_map = _card_display_map([
                    {"client": ((r or {}).get("client") or "")
                               or (j or {}).get("client") or ""}
                    for j, r in _pairs])
                for j, r in _pairs:
                    r = r or {}
                    _rc = r.get("client") or ""
                    if _rc and _rc != (j or {}).get("client"):
                        # Expanded row — a commercial sub-job OR a multi-claim
                        # "Nth Claim" folder — carries its OWN per-row client.
                        # Adopt it so the row's client / row_key / pin / folder
                        # are distinct from the base run-doc line AND sibling
                        # claims. Multi-claim rows are NOT flagged `subjob`, so
                        # the old subjob-only check collapsed both Mansolino
                        # claims onto one row (same row_key → select/pin/folder
                        # on one hit both). (2026-06-23) Inherit the parent
                        # line's raw / section / techs for activity chips.
                        j = {**(j or {}), "client": _rc}
                        if r.get("subjob"):
                            j["subjob"] = True
                    client = (_rc or j.get("client") or "")
                    try:
                        pin = persistence.get_trello_card_id(client) or ""
                    except Exception:
                        pin = ""
                    rows.append(_shape_job(j, r, pin,
                                           display_map=_display_map))
                self._last_rows = rows
                self._last_meta = {
                    "date_iso":   d.strftime("%Y-%m-%d"),
                    "ran_at":     _dt.datetime.now().strftime("%H:%M"),
                    "total":      len(rows),
                    "flagged":    sum(1 for r in rows if r["flagged"]),
                    "ok":         sum(1 for r in rows if not r["flagged"]),
                    "use_cache":  use_cache,
                }
                self._persist_cache_to_disk()
                # Prime persistence with every freshly-resolved folder
                # so other actions (post comment, SP import, list pics
                # stages, request docusketch, etc.) that read
                # `persistence.get_folder_path` directly see the path
                # without each needing its own resolver fallback.
                # Original symptom: audit found the folder, OD button
                # worked, but every other action returned "no folder
                # pinned" because persistence was empty for resolved-
                # but-never-pinned clients.
                self._prime_folder_pins(rows)
                self._emit_done(ok=True)

                # ── Background SP enrichment pass ─────────────────
                # Spawn a separate thread so the audit:done event
                # already fired — the user sees rows + interacts
                # immediately while SP chips fill in lazily.
                self._spawn_sp_enrichment_pass(jobs, results, run_date)
            except Exception as ex:
                msg = f"{type(ex).__name__}: {ex}"
                self._emit_done(ok=False, error=msg)
            finally:
                self._audit_running = False

        _wh_run_bg(_bg)
        return {"started": True}

    def _spawn_sp_enrichment_pass(self, jobs, results, run_date):
        """Run SharePoint enrichment in a background thread AFTER
        audit:done has already fired. For each enriched result, emit
        `audit:sp_update` so the JS can splice the SP fields into
        state.rows progressively. Single index build + match_cache
        shared across the loop so per-client work stays cheap.
        """
        if not results:
            return
        import threading as _t, json as _json

        def _bg_sp():
            try:
                from sharepoint import build_sharepoint_folder_index
                folder_index = build_sharepoint_folder_index()
            except Exception:
                folder_index = None
            match_cache = {}
            for r in (results or []):
                r = r or {}
                client = r.get("client") or ""
                if not client:
                    continue
                try:
                    enrich_with_sharepoint(
                        r, run_date,
                        folder_index=folder_index,
                        match_cache=match_cache)
                except Exception:
                    continue
                # Re-shape JUST the SP slice and stream it. Avoid
                # re-running _shape_job (which calls audit_logic again);
                # the SP fields are the only ones changing.
                sp_matches_raw = r.get("sharepoint_matches") or []
                def _shape_m(m):
                    stats = m.get("match_stats") or {}
                    return {
                        "name":         m.get("name") or "",
                        "path":         m.get("path") or "",
                        "tech":         m.get("tech") or "",
                        "new_count":    int(m.get("new_count") or 0),
                        "img_count":    int(m.get("img_count") or m.get("count") or 0),
                        "matches_date": bool(m.get("matches_date")),
                        "match_stats": {
                            "name":  int(stats.get("name")  or 0),
                            "fp":    int(stats.get("fp")    or 0),
                            "size":  int(stats.get("size")  or 0),
                            "new":   int(stats.get("new")   or 0),
                            "total": int(stats.get("total") or 0),
                        },
                        "new_names": sorted(list(m.get("new_names") or []))[:50],
                    }
                sp_matches = [_shape_m(m) for m in sp_matches_raw]
                payload = {
                    "client":             client,
                    "sharepoint_matches": sp_matches,
                    "sharepoint_new":     int(r.get("sharepoint_new") or 0),
                    "pics_count":         int(r.get("pics_count") or 0),
                }
                # Mirror onto the in-memory _last_rows so subsequent
                # reads (last_audit / reaudit_one) carry the SP data. SP is
                # per-CLIENT (folder-keyed), so update EVERY row with this
                # client — not just the first. The `break` here dropped SP
                # data for all but one row on multi-unit properties (both
                # Avila Apartments units share the client); the frontend
                # onSpUpdate already updates them all, so this matches it.
                for row in self._last_rows:
                    if row.get("client") == client:
                        row.update(payload)
                try:
                    self._emit(
                        "window.dispatchEvent(new CustomEvent("
                        "'audit:sp_update', {detail: "
                        + _json.dumps(payload, default=str) + "}));")
                except Exception:
                    pass
            # Persist final cache (with SP data merged in)
            try: self._persist_cache_to_disk()
            except Exception: pass
            # Signal completion so the UI can show a "SP scan done" toast
            try:
                self._emit(
                    "window.dispatchEvent(new CustomEvent("
                    "'audit:sp_done', {detail: {}}));")
            except Exception:
                pass

        _t.Thread(target=_bg_sp, daemon=True).start()

    def open_folder(self, path: str) -> bool:
        """Open the job's OD folder in Explorer. No-op when the path
        doesn't resolve."""
        if not path or not os.path.isdir(path):
            return False
        try:
            os.startfile(path)
            return True
        except Exception:
            return False

    def claim_folders(self, path: str) -> dict:
        """List the PAST claim / date sibling folders for a job so the
        audit row can offer a 🗂 Claims jump-list. `path` is the row's
        resolved folder (a claim subfolder for multi-claim rows — the
        helper scans its parent too, so siblings still surface).
        Returns {ok, folders:[{name, path, kind, number, is_current}]}."""
        if not path:
            return {"ok": True, "folders": []}
        try:
            import audit_logic as _al
            return {"ok": True, "folders": _al.list_claim_folders(path)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "folders": []}

    def od_contents(self, path: str) -> dict:
        """List the folders + files directly inside a job's OD folder so
        the audit row can SHOW what's actually there — 📁 folders (drillable
        by the frontend) and 📄 files with size. Each file also reports
        whether it's a OneDrive *cloud-only placeholder* (not yet downloaded)
        vs. physically present, since audit reads fail on un-hydrated
        placeholders. `os.scandir` + the cached `stat()` avoid hydrating the
        files just to list them. Skips the hidden desktop.ini marker.
        Returns {ok, path, name, folders:[{name,path}], files:[{name,path,
        size,cloud_only}]}."""
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": "folder not found",
                    "folders": [], "files": []}
        OFFLINE = 0x1000        # FILE_ATTRIBUTE_OFFLINE
        RECALL = 0x00400000     # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
        folders, files = [], []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        if e.name.lower() == "desktop.ini":
                            continue
                        if e.is_dir(follow_symlinks=False):
                            folders.append({"name": e.name, "path": e.path})
                        elif e.is_file(follow_symlinks=False):
                            try:
                                st = e.stat()
                                attrs = getattr(st, "st_file_attributes", 0)
                                size = st.st_size
                            except OSError:
                                attrs, size = 0, 0
                            files.append({
                                "name": e.name, "path": e.path, "size": size,
                                "cloud_only": bool(attrs & (OFFLINE | RECALL))})
                    except OSError:
                        continue
        except OSError as ex:
            return {"ok": False, "error": str(ex),
                    "folders": [], "files": []}
        folders.sort(key=lambda d: d["name"].lower())
        files.sort(key=lambda d: d["name"].lower())
        return {"ok": True, "path": path,
                "name": os.path.basename(path.rstrip(os.sep)),
                "folders": folders, "files": files}

    def job_work_log(self, client: str) -> dict:
        """Full job tracker for a client — the run-doc activity (with the
        crew each day) AND the Trello upload history (who uploaded which
        form/photo) woven into one newest-first timeline. Backed by
        `job_history.job_tracker`. The run-doc corpus is cached by mtime;
        the Trello leg is a couple of card calls (skipped when no card is
        pinned). Returns {ok, client, timeline:[{kind, date_str, ...}],
        activity_count, upload_count, saved_path}."""
        if not client:
            return {"ok": False, "error": "no client", "timeline": []}
        try:
            import job_history as _jh
            tr = _jh.job_tracker(client)
            saved = _jh.running_doc_path(client)
            return {"ok": True, "client": client,
                    "timeline": tr["timeline"],
                    "activity_count": len(tr["activity"]),
                    "upload_count": len(tr["uploads"]),
                    "saved_path": saved if os.path.isfile(saved) else ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "timeline": []}

    def save_job_work_log(self, client: str) -> dict:
        """Generate/refresh the per-job work-log .md from the latest runs
        and return its path so the frontend can open it in Explorer."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import job_history as _jh
            return {"ok": True, "path": _jh.save_running_doc(client)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_od_for_client(self, client: str,
                             hint_path: str = "") -> dict:
        """Smart open. Resolution order: persistence pin → hint path
        → audit-row caches → audit_jobs resolver. Each candidate is
        validated with `os.path.isdir` so stale entries fall through
        instead of failing the open. Returns
        ``{ok, path, used_hint, refreshed, error, needs_find}``.

        `refreshed=True` means the caller's hint was stale and a
        different valid path was resolved; the frontend should splice
        the fresh path into its row state so the next action doesn't
        re-hit the dead value.

        Symptom this fixes: the audit row showed "found" but clicking
        📁 OD silently failed because the folder had moved/renamed
        since the audit ran. The earlier two-step variant of this
        method only consulted persistence after the hint failed,
        which left IUQ rows (no audit-row cache to fall back on)
        showing a generic "couldn't open folder" error.
        """
        # Candidate list in preference order. Persistence pin first
        # (most authoritative — user explicitly pinned), then the
        # caller's hint, then the resolver's findings.
        candidates: list[tuple[str, str]] = []  # (label, path)
        if client:
            try:
                pin = persistence.get_folder_path(client) or ""
                if pin:
                    candidates.append(("persistence", pin))
            except Exception:
                pass
        if hint_path:
            candidates.append(("hint", hint_path))
        if client:
            try:
                resolved = self._resolve_client_path(client) or ""
                if resolved:
                    candidates.append(("resolver", resolved))
            except Exception:
                pass
        if not client and hint_path:
            # No client to anchor against — best we can do is honor
            # the hint even with no validation chain available.
            pass

        # Validated walk: open the first candidate that resolves on
        # disk. Track whether we ended up on the hint (used_hint)
        # vs a fresh resolution (refreshed).
        first_label = candidates[0][0] if candidates else ""
        seen = set()
        for label, path in candidates:
            if not path or path in seen:
                continue
            seen.add(path)
            if not os.path.isdir(path):
                continue
            try:
                os.startfile(path)
                return {
                    "ok":        True,
                    "path":      path,
                    "used_hint": label == "hint",
                    "refreshed": label != first_label,
                }
            except Exception as ex:
                # startfile failed on a valid dir — surface the error
                # so the user sees what went wrong (permission,
                # antivirus block, etc.) rather than a generic miss.
                return {"ok": False, "error": str(ex), "path": path}
        # Every candidate failed validation. Offer the find-folder
        # path so the user can pin a fresh location without leaving
        # the dialog.
        return {
            "ok":         False,
            "error":      (f"No OD folder resolved for {client or 'this row'}. "
                           "Pin one via 🔎 Find folder."),
            "path":       "",
            "needs_find": True,
        }

    def reveal_in_explorer(self, path: str) -> bool:
        """Open Explorer with `path` selected (highlighted), not just
        the containing folder open. Used by the post-save Scope modal
        so the user can see exactly which file just landed."""
        if not path or not os.path.isfile(path):
            return False
        try:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True
        except Exception:
            try:
                os.startfile(os.path.dirname(path))
                return True
            except Exception:
                return False

    def open_file(self, path: str) -> bool:
        """Open any file in its default system handler. PDFs land in
        the system PDF viewer (Edge / Acrobat / etc.)."""
        if not path or not os.path.isfile(path):
            return False
        try:
            os.startfile(path)
            return True
        except Exception:
            return False

    def read_pdf_b64(self, path: str) -> dict:
        """Read a PDF off disk and return its bytes base64-encoded.
        Used by the Scope modal's inline PDF preview — pywebview
        doesn't reliably let an iframe load `file://` URLs from a
        local-file page origin, so we ship the bytes through the JS
        bridge as a `data:application/pdf;base64,...` URL instead.
        Cap at 10 MB so a stray huge PDF can't OOM the WebView."""
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "file not found"}
        try:
            size = os.path.getsize(path)
            if size > 10 * 1024 * 1024:
                return {"ok": False,
                        "error": f"PDF too large to preview ({size // 1024} KB) — "
                                 "open it in the default viewer instead"}
            import base64
            with open(path, "rb") as fh:
                data = fh.read()
            return {
                "ok":     True,
                "b64":    base64.b64encode(data).decode("ascii"),
                "size":   size,
                "name":   os.path.basename(path),
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_trello_card(self, card_id: str) -> bool:
        """Open the Trello card in the user's default browser.
        Trello URL format: https://trello.com/c/<short_link>. We have
        the long ID; Trello accepts both forms."""
        if not card_id:
            return False
        try:
            dept_browser.open_url(f"https://trello.com/c/{card_id}")
            return True
        except Exception:
            return False

    def copy_to_clipboard(self, text: str) -> bool:
        if not text:
            return False
        # Win32 clipboard, NOT a throwaway tk.Tk() — Tk's delayed-rendering
        # clipboard left a dead owner that froze the next paste everywhere.
        from web_helpers import set_clipboard_text
        return set_clipboard_text(text)

    # ── P0: section toggle + day walker + single-job audit ──────────
    def run_audit_filtered(self, include_work: bool = True,
                            include_monitor: bool = True,
                            use_cache: bool = True,
                            date_offset_days: int = 0) -> dict:
        """Variant of run_audit that filters by section (work / monitor)
        and lets the user walk to a different date via day_offset. Same
        background-thread + events pattern as `run_audit`."""
        if self._audit_running:
            return {"started": False, "reason": "audit already running"}
        self._audit_running = True
        import threading

        def _bg():
            try:
                d = _dt.date.today() + _dt.timedelta(days=date_offset_days)
                doc_path = _find_run_doc_for_date(d)
                if not doc_path:
                    self._emit_done(ok=False, error=f"No run doc for {d}")
                    return
                jobs, run_date = _state_hub.parse_run_doc(doc_path)
                # Filter by section
                filtered = []
                for j in jobs:
                    sec = (j.get("section") or "work").lower()
                    if sec == "monitor" and not include_monitor:
                        continue
                    if sec != "monitor" and not include_work:
                        continue
                    filtered.append(j)
                # Same fix as run_audit — pass full job dicts so the
                # audit sees unit / tenant / new_loss / time_slot.
                filtered = [j for j in filtered if (j.get("client") or "").strip()]
                client_names = filtered
                # Keep `jobs` aligned with the audited set for the
                # zip(jobs, results) loop below.
                jobs = filtered
                # Per-job progress callback (same shape as run_audit)
                import json as _json
                def _progress(idx, total_n, name):
                    try:
                        payload = {"i": int(idx), "n": int(total_n),
                                   "client": str(name or "")}
                        self._emit(
                            "window.dispatchEvent(new CustomEvent("
                            "'audit:progress', {detail: "
                            + _json.dumps(payload) + "}));")
                    except Exception:
                        pass
                results, err = audit_jobs(
                    client_names, run_date=run_date, use_cache=use_cache,
                    progress_cb=_progress, expand_subjobs=True)
                if err:
                    self._emit_done(ok=False, error=err)
                    return
                # SP enrichment moved to background — see run_audit
                # for the rationale. Rows paint immediately and SP
                # chips fill in via audit:sp_update events.
                rows = []
                _pairs = list(_pair_results_to_jobs(filtered, results))
                _display_map = _card_display_map([
                    {"client": ((r or {}).get("client") or "")
                               or (j or {}).get("client") or ""}
                    for j, r in _pairs])
                for j, r in _pairs:
                    r = r or {}
                    _rc = r.get("client") or ""
                    if _rc and _rc != (j or {}).get("client"):
                        # Expanded row (commercial sub-job OR multi-claim) →
                        # adopt its own per-row client so row_key/pin/folder
                        # stay distinct per claim. See the matching note in
                        # run_audit. (2026-06-23)
                        j = {**(j or {}), "client": _rc}
                        if r.get("subjob"):
                            j["subjob"] = True
                    pin = ""
                    try:
                        pin = persistence.get_trello_card_id(
                            r.get("client") or j.get("client") or "") or ""
                    except Exception:
                        pass
                    rows.append(_shape_job(j, r, pin,
                                           display_map=_display_map))
                self._last_rows = rows
                self._last_meta = {
                    "date_iso":      d.strftime("%Y-%m-%d"),
                    "date_label":    d.strftime("%A, %B %d, %Y"),
                    "ran_at":        _dt.datetime.now().strftime("%H:%M"),
                    "total":         len(rows),
                    "flagged":       sum(1 for r in rows if r["flagged"]),
                    "ok":            sum(1 for r in rows if not r["flagged"]),
                    "use_cache":     use_cache,
                    "include_work":  include_work,
                    "include_monitor": include_monitor,
                    "doc_path":      doc_path,
                }
                self._persist_cache_to_disk()
                # Prime persistence with every freshly-resolved folder
                # (see comment at the other audit completion site).
                self._prime_folder_pins(rows)
                self._emit_done(ok=True)
                # SP enrichment in the background — rows paint
                # immediately, SP chips fill in via audit:sp_update.
                self._spawn_sp_enrichment_pass(filtered, results, run_date)
            except Exception as ex:
                self._emit_done(
                    ok=False,
                    error=f"{type(ex).__name__}: {ex}")
            finally:
                self._audit_running = False
        _wh_run_bg(_bg)
        return {"started": True}

    def _canonicalize_client_name(self, typed: str) -> str:
        """Resolve a typed fragment ("Munson") to the canonical full
        client name ("Munson, Marta") by checking, in order:
          1. The current daily-run-doc's job list (prefer exact match,
             then partial substring/token overlap).
          2. The persistence pin map — every client that has a Trello
             pin (case + carrier-suffix insensitive token match).
          3. Folder names under the audit_base year (substring match).
        Falls back to the typed string when nothing resolves so the
        caller always gets something to audit against."""
        if not typed: return ""
        typed = typed.strip()
        if not typed: return ""
        from web_helpers import norm_name as _norm, norm_tokens as _norm_tokens
        typed_n = _norm(typed)
        typed_tokens = _norm_tokens(typed)

        candidates = []

        # 0. One-off rows already audited THIS session. A client's name is a
        #    set of tokens regardless of order, so "Smith John" and "John
        #    Smith" share the same token set — reuse the existing row instead
        #    of spawning a duplicate one-off when the user re-types the name
        #    last-first vs first-last. (Same-token-set scores highest so it
        #    beats an unrelated substring folder hit.)
        try:
            for r in (self._oneoff_rows or []):
                name = r.get("client") or ""
                if not name:
                    continue
                n = _norm(name)
                if n == typed_n:
                    return name
                n_tokens = {t for t in n.split() if len(t) >= 2}
                if typed_tokens and typed_tokens == n_tokens:
                    candidates.append((12, name))   # same name, any order
                elif typed_tokens & n_tokens:
                    candidates.append((6, name))
        except Exception:
            pass

        # 1. Daily run-doc clients
        try:
            d = _dt.date.today()
            doc = _find_run_doc_for_date(d)
            if doc:
                jobs, _ = _state_hub.parse_run_doc(doc)
                for j in jobs:
                    name = j.get("client") or ""
                    if not name: continue
                    n = _norm(name)
                    if n == typed_n:
                        return name  # perfect match — short-circuit
                    if typed_n in n or (len(n) >= 4 and n in typed_n):
                        candidates.append((10, name))
                    elif typed_tokens & set(t for t in n.split() if len(t) >= 2):
                        candidates.append((5, name))
        except Exception:
            pass

        # 2. Persistence pin map — every client with at least one
        #    pinned Trello card. The map is canon-keyed (lowercase
        #    + carrier-suffix stripped) so even "Munson, Marta - State
        #    Farm" gets fuzz-matched on the substring "munson".
        try:
            pins = persistence._load().get("trello_card_ids") or {}
            if isinstance(pins, dict):
                for client_key in pins.keys():
                    n = _norm(client_key)
                    if n == typed_n: return client_key
                    if typed_n in n or (len(n) >= 4 and n in typed_n):
                        candidates.append((8, client_key))
                    elif typed_tokens & set(t for t in n.split() if len(t) >= 2):
                        candidates.append((4, client_key))
        except Exception:
            pass

        # 3. Year-folder names (last resort)
        try:
            res = self.list_folder_candidates(typed)
            for c in (res.get("candidates") or [])[:6]:
                if c.get("score", 0) > 0:
                    candidates.append((c["score"], c["name"]))
        except Exception:
            pass

        # Pick highest score; at equal score prefer the canonical
        # "Last, First" comma form over a reordered "First Last" one.
        # The pin map can hold BOTH spellings for one client (e.g.
        # "white, margaret" AND "margaret white"); without the comma
        # tiebreak the reordered form wins alphabetically, giving an
        # ugly lowercased name that also misses the proper pin key.
        # Final tiebreak alphabetical for stability.
        candidates.sort(key=lambda x: (-x[0], 0 if "," in x[1] else 1,
                                        x[1].lower()))
        return candidates[0][1] if candidates else typed

    def suggest_jobs(self, query: str, limit: int = 8) -> dict:
        """Type-ahead candidates for the search box. DB only.

        The search box used to fire a full `audit_one_job` — year-folder
        walk, SharePoint scan, Trello lookups — as soon as three characters
        were typed, against ONE guessed canonical name. This answers "which
        job did you mean" from the job index instead, so the expensive scan
        runs once, after a pick.
        """
        try:
            import job_search
            rows = job_search.suggest(query, limit=int(limit or 8))
            return {"ok": True, "rows": rows, "query": query}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}",
                    "rows": []}

    def audit_one_job(self, client_name: str, folder_path: str = "",
                      skip_canon: bool = False) -> dict:
        """Audit a single named job (one-off, not from the run-doc).

        Resolution order:
          1. Canonicalize the typed name — "Munson" → "Munson, Marta"
             via run-doc / Trello-pin / folder lookups. SKIPPED when
             `skip_canon` is set (the caller already picked the exact
             canonical name from the candidate picker, so don't re-fuzz).
          2. Run audit_logic against the canonical name.
          3. Cache the result in `_oneoff_rows` (separate list from
             the Daily Run results). Re-typing the same name updates
             the same row instead of creating a duplicate.

        `folder_path` (optional): when the user picked a specific folder
        from the candidate list, pin it FIRST so audit_logic resolves to
        exactly that folder instead of a re-fuzzed guess.
        """
        if not client_name or not client_name.strip():
            return {"ok": False, "error": "name required"}
        typed = client_name.strip()
        canonical = typed if skip_canon else self._canonicalize_client_name(typed)
        # Honor an explicit folder pick from the picker — pin it before
        # auditing so the resolved folder is the one the user confirmed.
        if folder_path:
            try:
                if os.path.isdir(folder_path):
                    persistence.set_folder_path(canonical, folder_path)
            except Exception:
                pass
        try:
            # `run_date` must be a "MM-DD-YYYY" STRING downstream —
            # audit_logic._audit_one strptime()s it and sharepoint
            # splits it on "-". Passing a date object raises
            # "strptime() argument 1 must be str, not datetime.date"
            # and the one-off audit silently fails. Mirrors reaudit_one.
            results, err = audit_jobs(
                [canonical], run_date=_dt.date.today().strftime("%m-%d-%Y"),
                use_cache=False, expand_subjobs=True)
            if err:
                return {"ok": False, "error": err}
            if not results:
                return {"ok": False, "error": "no result"}
            # Build ONE row per result. A multi-claim name (Sayra Mansolino
            # → 1st/2nd Claim) or a commercial parent (Menifee → one folder
            # per campus) expands into several results — show them ALL, not
            # just results[0]. The one-off LIST is driven by
            # self._oneoff_rows (list_oneoff), so every expanded row goes in.
            new_rows = []
            for res in results:
                res = res or {}
                rclient = res.get("client") or canonical
                try:
                    rpin = persistence.get_trello_card_id(rclient) or ""
                except Exception:
                    rpin = ""
                fjob = {"client": rclient, "section": "work", "raw": "",
                        "techs": [], "new_loss": bool(res.get("new_loss"))}
                new_rows.append(_shape_job(fjob, res, rpin))
                # Auto-pin each resolved folder (mirrors the Daily Run flow,
                # so SP/WC import resolves via persistence.get_folder_path).
                try:
                    rp = res.get("path") or ""
                    if (rp and os.path.isdir(rp)
                            and not (persistence.get_folder_path(rclient) or "")):
                        persistence.set_folder_path(rclient, rp)
                except Exception:
                    pass
            # Replace any existing one-off rows for this name (the canonical
            # OR any expanded child) with the fresh set, newest-first.
            _new_clients = {r.get("client") for r in new_rows} | {canonical}
            self._oneoff_rows = [r for r in self._oneoff_rows
                                 if r.get("client") not in _new_clients]
            self._oneoff_rows[:0] = new_rows
            return {"ok": True, "row": new_rows[0], "rows": new_rows,
                    "count": len(new_rows), "canonical": canonical,
                    "typed": typed, "resolved": typed != canonical}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def list_audit_candidates(self, typed: str, scope: str = "") -> dict:
        """Return ranked job candidates for a typed name so the Audit-one
        dialog can show the matches and let the user CONFIRM the right
        job — instead of audit_one_job silently grabbing the single
        top fuzzy pick (_canonicalize_client_name's old behavior).

        Combines three sources:
          • today's run-doc job list   (source="run")
          • pinned Trello cards         (source="pin")
          • year-folder names           (source="folder"; `scope` passes
            straight through to list_folder_candidates — "" = current
            year, "all" = every year + fire jobs)

        Each candidate: {name, label, source, detail, path, score}.
        `name` is what you pass back to audit_one_job(skip_canon=True).
        De-duped by normalized name (best score wins; a name found in
        more than one source keeps the highest score and any known
        folder path). `exact` flags a perfect name hit in run-doc/pins.
        """
        typed = (typed or "").strip()
        if not typed:
            return {"ok": False, "error": "name required"}
        from web_helpers import norm_name as _norm, norm_tokens as _norm_tokens
        typed_n = _norm(typed)
        typed_tokens = _norm_tokens(typed)

        # Collect EVERY source hit flat; variants of one job are grouped
        # afterward (token-set, carrier-stripped) so a misspelling / name-
        # order / carrier-suffix no longer splits one job into many rows.
        raw: list = []
        try:
            _pins_map = persistence._load().get("trello_card_ids") or {}
        except Exception:
            _pins_map = {}
        if not isinstance(_pins_map, dict):
            _pins_map = {}

        def _has_card(nm):
            try:
                import ems_db as _db
                return bool(_pins_map.get(_db.canon_key(nm)))
            except Exception:
                return bool(_pins_map.get(_norm(nm)))

        def _add(name, source, detail, path, score):
            if not name:
                return
            raw.append({"name": name, "source": source, "detail": detail,
                        "path": path or "", "score": score,
                        "has_card": (source == "pin") or _has_card(name)})

        exact = False

        # 1. Today's run-doc jobs — most authoritative for "audit one".
        try:
            doc = _find_run_doc_for_date(_dt.date.today())
            if doc:
                jobs, _ = _state_hub.parse_run_doc(doc)
                for j in jobs:
                    name = j.get("client") or ""
                    if not name:
                        continue
                    n = _norm(name)
                    if n == typed_n:
                        exact = True; score = 100
                    elif typed_n in n or (len(n) >= 4 and n in typed_n):
                        score = 30
                    elif typed_tokens & set(t for t in n.split() if len(t) >= 2):
                        score = 15
                    else:
                        continue
                    try:
                        pin_path = persistence.get_folder_path(name) or ""
                    except Exception:
                        pin_path = ""
                    _add(name, "run", "On today's run-doc", pin_path, score)
        except Exception:
            pass

        # 2. Pinned Trello cards.
        try:
            pins = persistence._load().get("trello_card_ids") or {}
            if isinstance(pins, dict):
                for client_key in pins.keys():
                    n = _norm(client_key)
                    if n == typed_n:
                        exact = True; score = 90
                    elif typed_n in n or (len(n) >= 4 and n in typed_n):
                        score = 25
                    elif typed_tokens & set(t for t in n.split() if len(t) >= 2):
                        score = 12
                    else:
                        continue
                    try:
                        pin_path = persistence.get_folder_path(client_key) or ""
                    except Exception:
                        pin_path = ""
                    _add(client_key, "pin", "Pinned Trello card",
                         pin_path, score)
        except Exception:
            pass

        # 3. Year-folder candidates (scope-aware).
        try:
            res = self.list_folder_candidates(typed, scope)
            for c in (res.get("candidates") or [])[:40]:
                sc = c.get("score", 0)
                if sc <= 0:
                    continue
                detail = c.get("year_folder") or c.get("year") or "folder"
                if c.get("is_fire"):
                    detail = "🔥 " + detail
                _add(c.get("name") or "", "folder", detail,
                     c.get("path") or "", sc)
        except Exception:
            pass

        cands = _group_audit_candidates(raw)
        return {"ok": True, "candidates": cands, "exact": exact,
                "scope": scope or "current", "typed": typed}

    def merge_candidates(self, winner_name: str, variant_names: list) -> dict:
        """Permanently fold duplicate spellings of ONE job into `winner`.

        Powers the picker's 🔗 Merge button: consolidates the persisted
        pins (every variant's Trello card + the first real folder) onto the
        winner, drops the dupe spellings' pins, and merges the shared jobs-
        graph identities (ems_db.merge_jobs). After this the misspelled /
        reordered / carrier-suffixed variants stop existing as their own
        thing everywhere, not just in this picker."""
        winner = (winner_name or "").strip()
        variants = [v.strip() for v in (variant_names or []) if v and v.strip()]
        if not winner:
            return {"ok": False, "error": "no winner"}
        try:
            import ems_db as _db
            wkey = _db.canon_key(winner)
            # Real dupes only — a variant whose canon key differs from the
            # winner. Without this an empty/no-op merge would still upsert a
            # bogus job for `winner` via resolve_and_link(create=True).
            from_keys = [_db.canon_key(v) for v in variants
                         if _db.canon_key(v) != wkey]
            if not from_keys:
                return {"ok": False, "error": "nothing to merge"}
            group = [winner] + variants
            # Union every pinned card across the group (winner's first).
            cards: list = []
            for nm in group:
                try:
                    for cid in (persistence.get_trello_card_ids(nm) or []):
                        if cid and cid not in cards:
                            cards.append(cid)
                except Exception:
                    pass
            # First real folder across the group.
            folder = ""
            for nm in group:
                try:
                    fp = persistence.get_folder_path(nm) or ""
                except Exception:
                    fp = ""
                if fp:
                    folder = fp
                    break
            # Consolidate onto the winner.
            try:
                if cards:
                    persistence.set_trello_card_ids(winner, cards)
                if folder:
                    persistence.set_folder_path(winner, folder)
            except Exception:
                pass
            # Drop each dupe spelling's pins — but NEVER one that canon-
            # collapses to the winner (that's the winner's own entry).
            dropped = 0
            for v in variants:
                if _db.canon_key(v) == wkey:
                    continue
                try:
                    persistence.set_trello_card_ids(v, [])
                except Exception:
                    pass
                try:
                    persistence.set_folder_path(v, "")
                except Exception:
                    pass
                dropped += 1
            # Merge the shared jobs-graph identities (upsert winner first).
            try:
                _db.resolve_and_link(
                    winner, folder_path=folder,
                    trello_card=(cards[0] if cards else ""),
                    create=True, display_name=winner)
                _db.merge_jobs(wkey, from_keys)
            except Exception:
                pass
            return {"ok": True, "winner": winner, "dropped": dropped,
                    "cards": len(cards), "folder": folder}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def suggest_card_for(self, client_name: str) -> dict:
        """Return the best-matching open Trello card(s) for a cardless job
        so the picker can offer Attach/Skip at pick/merge time. One clear
        match, a short list, or none."""
        name = (client_name or "").strip()
        if not name:
            return {"ok": False, "error": "name required", "cards": []}
        try:
            import trello_client as _tc
            found = _tc.find_cards_by_name(name, max_results=8) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "cards": []}
        out = []
        for c in found:
            cid = c.get("card_id") or c.get("id") or ""
            if not cid:
                continue
            out.append({"card_id": cid,
                        "name":      c.get("name") or "",
                        "board":     c.get("board") or "",
                        "list_name": c.get("list_name") or ""})
        return {"ok": True, "cards": out, "count": len(out)}

    def list_oneoff(self) -> dict:
        """Return the one-off audits run today (separate from
        Daily Run)."""
        return {"ok": True, "rows": list(self._oneoff_rows),
                "total": len(self._oneoff_rows)}

    def clear_oneoff(self) -> dict:
        """Clear the one-off audit list. Doesn't touch persistence."""
        self._oneoff_rows = []
        return {"ok": True}

    def find_run_doc_for(self, date_offset_days: int = 0) -> dict:
        """Open Word with the run-doc for today + day-offset."""
        d = _dt.date.today() + _dt.timedelta(days=date_offset_days)
        try:
            p = _find_run_doc_for_date(d)
        except Exception:
            p = None
        return {"path": p or "", "exists": bool(p and os.path.isfile(p)),
                "date_label": d.strftime("%A %m/%d/%y")}

    def open_run_doc(self, date_offset_days: int = 0) -> bool:
        d = _dt.date.today() + _dt.timedelta(days=date_offset_days)
        try:
            p = _find_run_doc_for_date(d)
            if p and os.path.isfile(p):
                os.startfile(p)
                return True
        except Exception:
            pass
        return False

    # ── P0: Scope dialog backend (parse Trello room block → PDF) ─────
    def parse_scope_text(self, raw: str) -> dict:
        """Parse a pasted scope block into rooms. Returns
        {ok, rooms: [{name, items: [str]}]}.

        Two-stage parser:
          1. `snapshot_gui.parse_scope` — strict Trello-style detector
             tuned for tech material vocabulary (drywall/demo/sqft/etc.).
             Requires ≥3 material-matching lines per block. Handles the
             messy real-world Trello comment dumps.
          2. Fallback: simple "Room header\\n- bulleted items" parser for
             plain-text pastes the strict pass rejects.

        Bug history: the previous shape extracted `r["name"]` but
        snapshot_gui.parse_scope returns `r["room"]` — every room came
        back with an empty name, so the UI showed "No rooms parsed"
        even when the parser had succeeded.
        """
        if not (raw or "").strip():
            return {"ok": True, "rooms": []}
        try:
            import snapshot_logic as sg
            rooms = sg.parse_scope(raw)
            if rooms:
                return {"ok": True, "rooms": [
                    {"name": r.get("room") or r.get("name") or "",
                     "items": list(r.get("items") or [])}
                    for r in rooms if (r.get("items") or [])]}
            # Fallback: plain "Room header" then "- bullet" / "* bullet"
            # / indented lines. Catches the common user-edited paste the
            # strict parser ignores (e.g. "Living Room\\n- Demo carpet").
            return {"ok": True, "rooms": _parse_simple_scope(raw)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def preview_scope_path(self, client: str) -> dict:
        """Return the path the Scope PDF WOULD be saved to (without
        writing the file). Lets the UI show the destination before the
        user commits so they can see-and-correct if the resolved
        client folder is wrong."""
        if not client:
            return {"ok": False, "error": "client required"}
        target_path = self._resolve_client_path(client) or ""
        if not target_path:
            return {"ok": False,
                    "error": f"no OD folder pinned for {client} — "
                             "pin one via Find Folder before saving"}
        try:
            from audit_logic import find_docs_dir, active_job_base
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Multi-claim jobs hold the current claim in a "Nth Claim" subfolder;
        # descend into it deterministically so the scope doesn't land in the
        # shared job root / a stale claim's DOCS.
        target_path = active_job_base(target_path)
        ems = os.path.join(target_path, "EMS")
        base = ems if os.path.isdir(ems) else target_path
        docs = find_docs_dir(base) or os.path.join(base, "DOCS")
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "-", client).strip(" .-") or "Scope"
        out_path = os.path.join(docs, f"{safe} - Scope.pdf")
        return {
            "ok":            True,
            "path":          out_path,
            "dir":           docs,
            "filename":      f"{safe} - Scope.pdf",
            "job_root":      target_path,
            "dir_exists":    os.path.isdir(docs),
            "would_overwrite": os.path.isfile(out_path),
        }

    def pick_scope_save_dir(self, start_dir: str = "") -> dict:
        """Open a native folder picker so the user can override the
        auto-resolved destination. Returns the chosen path (or empty
        string when the user cancels)."""
        try:
            if self._window is None:
                return {"ok": False, "error": "no window"}
            # webview.FOLDER_DIALOG = 2 (constant) — picks a directory.
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=start_dir or "",
                allow_multiple=False,
            )
            if not result:
                return {"ok": True, "path": ""}
            chosen = result[0] if isinstance(result, (list, tuple)) else result
            return {"ok": True, "path": chosen}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def save_scope(self, client: str, rooms: list,
                    override_dir: str = "",
                    override_filename: str = "") -> dict:
        """Build a Scope.pdf from the room/items list + write it. By
        default lands in the client's EMS/DOCS folder; pass
        `override_dir` to redirect (e.g. the user picked a different
        location in the preview UI) and/or `override_filename` to
        rename the output. Mirrors Tk's scope dialog flow."""
        if not client:
            return {"ok": False, "error": "client required"}
        if not rooms:
            return {"ok": False, "error": "no rooms provided"}
        try:
            import snapshot_logic as sg
            from audit_logic import find_docs_dir, active_job_base
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Build the default destination first so the override logic
        # has something to fall through to.
        if override_dir and os.path.isdir(override_dir):
            docs = override_dir
        else:
            target_path = self._resolve_client_path(client)
            if not target_path:
                return {"ok": False,
                        "error": f"no folder found for {client}"}
            # Descend into the active "Nth Claim" subfolder for multi-claim
            # jobs so the scope lands under the current claim, deterministically.
            target_path = active_job_base(target_path)
            ems = os.path.join(target_path, "EMS")
            base = ems if os.path.isdir(ems) else target_path
            docs = find_docs_dir(base) or os.path.join(base, "DOCS")
        try:
            os.makedirs(docs, exist_ok=True)
        except OSError as ex:
            return {"ok": False, "error": f"folder error: {ex}"}
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "-",
                       override_filename or client).strip(" .-") or "Scope"
        filename = safe if safe.lower().endswith(".pdf") else f"{safe} - Scope.pdf"
        out_path = os.path.join(docs, filename)
        # Normalize the room dicts to the shape build_scope_pdf wants
        # — it reads `room_data["room"]` (NOT `["name"]`). Our
        # parse_scope_text + the simple fallback parser both emit
        # `{"name": ..., "items": [...]}` to match the snapshot/audit
        # frontend convention. Without this conversion the PDF build
        # raised KeyError("room") and the user saw a "docs dir created
        # but nothing inside" symptom (the makedirs succeeded but the
        # build_scope_pdf step blew up silently from the user's POV).
        normalized = [
            {"room": (r.get("room") or r.get("name") or "").strip(),
             "items": [str(it).strip() for it in (r.get("items") or [])
                       if str(it).strip()]}
            for r in rooms
        ]
        normalized = [r for r in normalized if r["items"]]
        if not normalized:
            return {"ok": False, "error": "no rooms with items after normalization"}
        try:
            sg.build_scope_pdf(normalized, client, out_path)
        except Exception as ex:
            import traceback
            return {"ok": False,
                    "error": f"{type(ex).__name__}: {ex}",
                    "traceback": traceback.format_exc()}
        if not os.path.isfile(out_path):
            return {"ok": False,
                    "error": f"build returned but file missing: {out_path}"}
        return {"ok": True, "path": out_path}

    # ── New Loss from carrier assignment email ───────────────────────
    def parse_new_loss(self, text: str) -> dict:
        """Parse a pasted carrier assignment email into editable fields."""
        try:
            import new_loss_intake as nli
            fields = nli.parse_assignment_email(text or "")
            fields["loss_type"] = nli.loss_type_from(fields.get("type_of_loss"))
            fields["card_name"] = nli.suggest_card_name(fields)
            return {"ok": True, "fields": fields}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def new_loss_templates(self) -> dict:
        """Which loss templates (water/fire/property) exist on the active
        department's WIP board — so the dialog can show/grey the options."""
        try:
            import new_loss_intake as nli
            t = nli.list_templates()
            return {
                "ok":      bool(t),
                "water":   "water" in t,
                "fire":    "fire" in t,
                "property": "property" in t,
                "board":   (t.get("_board") or {}).get("name", ""),
                "intake":  (t.get("_intake") or {}).get("name", ""),
            }
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def plan_new_loss_folder(self, fields: dict, child: str = "",
                             second_claim: bool = False) -> dict:
        """Where this new loss's folder would go — show it in the confirm
        dialog BEFORE anything is created.

        Returns mode 'new_client' (first job for this customer) or 'child'
        (they already have a folder, so this becomes a subfolder inside it:
        another claim, a unit, or a commercial sub-job). `children` lists
        what's already in there so the operator can pick a non-clashing
        name."""
        try:
            import new_loss_intake as nli
            return nli.plan_folder(dict(fields or {}), child=child,
                                   second_claim=bool(second_claim))
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def create_new_loss(self, fields: dict, child: str = "",
                        second_claim: bool = False,
                        promote_first: bool = False,
                        make_folder: bool = True,
                        make_companycam: bool = False) -> dict:
        """Clone the matching template into the intake list, fill it, and
        (by default) create the job folder.

        The card and the folder are created independently: a client with
        several claims or units has several cards but ONE client folder,
        so the two aren't one-to-one. A folder failure never fails the
        card — the card is the part that can't be redone by hand.

        `make_companycam` also creates the CompanyCam project now and
        pins its id, instead of leaving it to be fuzzy-matched by name
        later (projects are named by the INSURED, run-doc names often
        aren't — that match is the part that fails). OFF by default: it
        posts a record every tech can see. Like the folder, it never
        fails the card.
        """
        try:
            import new_loss_intake as nli
            fields = dict(fields or {})
            res = nli.create_new_loss(fields, fields.get("loss_type"))
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        if not res.get("ok"):
            return res
        if make_folder:
            try:
                folder = nli.create_folder(
                    fields, child=child, second_claim=bool(second_claim),
                    promote_first=bool(promote_first))
            except Exception as ex:
                folder = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
            res["folder"] = folder
        if make_companycam:
            try:
                res["companycam"] = nli.create_companycam_project(
                    fields,
                    card_name=res.get("name") or "",
                    trello_card=res.get("card_id") or "",
                    folder_path=(res.get("folder") or {}).get("path") or "",
                    confirm_create=True)
            except Exception as ex:
                res["companycam"] = {"ok": False,
                                     "error": f"{type(ex).__name__}: {ex}"}
        return res

    # ── P0: XactAnalysis quick link from right-click menu ────────────
    def open_xa_link(self, client: str, card_id: str = "") -> bool:
        """Open the client's XactAnalysis link from the pinned Trello card.

        Prefer the `card_id` the row already carries (what the Trello button
        uses) — re-looking it up by name via get_trello_card_id is fragile
        (a display-name / pin-key drift makes it silently miss). Fall back to
        the name lookup only when the caller didn't pass an id."""
        card_id = (card_id or "").strip()
        if not card_id:
            if not client:
                return False
            card_id = persistence.get_trello_card_id(client) or ""
        if not card_id:
            return False
        try:
            import trello_client as tc
            # card_xa_link needs the card DICT (it parses .desc) — fetch it,
            # don't pass the bare id (that silently returned "" before).
            card = tc.get_card(card_id) or {}
            url = tc.card_xa_link(card) if hasattr(tc, "card_xa_link") else ""
            if url:
                dept_browser.open_url(url)
                return True
        except Exception:
            pass
        return False

    def open_companycam_link(self, client: str) -> bool:
        """Open the client's CompanyCam project link, read from the
        pinned Trello card's LINKS section (parallel to open_xa_link).
        Returns False — so the UI can toast 'no link' — when the client
        has no pinned card or the card carries no CompanyCam link yet."""
        if not client:
            return False
        try:
            import trello_client as tc
            card_id = persistence.get_trello_card_id(client) or ""
            if not card_id:
                return False
            card = tc.get_card(card_id) or {}
            url = (tc.card_companycam_link(card)
                   if hasattr(tc, "card_companycam_link") else "")
            if url:
                dept_browser.open_url(url)
                return True
        except Exception:
            pass
        return False

    def get_claim_number(self, client: str) -> dict:
        """Pull the claim number from the client's pinned Trello card desc
        (INSURANCE INFORMATION → CLAIM NUMBER). Backs the audit's
        '📋 Copy claim #' action — same idea as Copy name, but the claim
        lives on the card, not the audit row. {ok, claim} or {ok:False}."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import trello_client as tc
            card_id = persistence.get_trello_card_id(client) or ""
            if not card_id:
                return {"ok": False, "error": "no pinned Trello card"}
            card = tc.get_card(card_id) or {}
            fields = tc.parse_card_desc(card.get("desc") or "") or {}
            claim = ((fields.get("INSURANCE INFORMATION") or {})
                     .get("CLAIM NUMBER") or "").strip()
            if not claim:
                return {"ok": False, "error": "no claim # on the card"}
            return {"ok": True, "claim": claim}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_initial_cat_class(self, client: str, card_id: str = "") -> dict:
        """Pull the water Category + Class out of the initial-inspection
        notes the tech posts in the card's Trello COMMENTS (not the card
        desc). Backs the audit Initial-section '🔢 Cat / Class' button.
        Returns {ok, text, cat, klass} where text reads "Cat 2 · Class 3"
        (whichever parts the notes actually carried)."""
        import re as _re
        try:
            import trello_client as tc
            import initial_notes_parser as inp
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        cid = (card_id or "").strip() or (
            persistence.get_trello_card_id(client) or "")
        if not cid:
            return {"ok": False, "error": "no pinned Trello card"}
        try:
            comments = tc.get_all_comments(cid) or []
        except Exception as ex:
            return {"ok": False, "error": f"comment fetch failed: {ex}"}
        text = "\n".join((a.get("data") or {}).get("text", "")
                         for a in comments)
        blocks = inp.parse_initial_inspection_notes(text) or []
        # Prefer the earliest block that names a Category/Class; merge so a
        # block with only one of the two still contributes.
        cat = klass = ""
        for b in blocks:
            cat = cat or str(b.get("Category") or "").strip()
            klass = klass or str(b.get("Class") or "").strip()
            if cat and klass:
                break
        if not (cat or klass):
            return {"ok": False,
                    "error": "no Category/Class in the card's initial notes"}

        def _fmt(label, val):
            v = (val or "").strip()
            if not v:
                return ""
            # Don't double the label when the value already spells it out
            # ("Cat 2" / "Category 2" / "Class 3").
            if _re.search(r'categor|\bcat\b|class', v, _re.I):
                return v
            return f"{label} {v}"

        parts = [p for p in (_fmt("Cat", cat), _fmt("Class", klass)) if p]
        return {"ok": True, "text": " · ".join(parts),
                "cat": cat, "klass": klass}

    def import_initial_notes(self, client: str, card_id: str = "") -> dict:
        """Parse the FULL initial-inspection field template out of the card's
        Trello comments and return a clean summary. Backs the audit Initial-
        section '📋 Import notes' button (the whole-template sibling of the
        Cat/Class grab). Returns {ok, summary, fields} where `summary` is a
        formatted multi-line block ready to paste into the snapshot / job
        notes, and `fields` is the structured dict of the first block."""
        try:
            import trello_client as tc
            import initial_notes_parser as inp
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        cid = (card_id or "").strip() or (
            persistence.get_trello_card_id(client) or "")
        if not cid:
            return {"ok": False, "error": "no pinned Trello card"}
        try:
            comments = tc.get_all_comments(cid) or []
        except Exception as ex:
            return {"ok": False, "error": f"comment fetch failed: {ex}"}
        text = "\n".join((a.get("data") or {}).get("text", "")
                         for a in comments)
        blocks = inp.parse_initial_inspection_notes(text) or []
        if not blocks:
            return {"ok": False,
                    "error": "no initial-inspection notes found on the card"}
        summary = inp.format_initial_notes(blocks) or ""
        if not summary.strip():
            return {"ok": False, "error": "initial notes parsed empty"}
        return {"ok": True, "summary": summary, "fields": blocks[0]}

    def get_job_log(self, client: str, card_id: str = "") -> dict:
        """Email-aware job log from the card's Trello comments, plus EQ-on-
        site status. Strips quoted email/proposal noise and stamps each field
        event with its comment date (so a bare 'Air scrubber picked up' note
        is still dated). Backs the audit Initial-section '🗒 Job log' button.
        Returns {ok, text, rows, eq, eq_warn, count}."""
        try:
            import trello_client as tc
            import snapshot_logic as sg
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        cid = (card_id or "").strip() or (
            persistence.get_trello_card_id(client) or "")
        if not cid:
            return {"ok": False, "error": "no pinned Trello card"}
        try:
            comments = tc.get_all_comments(cid) or []
        except Exception as ex:
            return {"ok": False, "error": f"comment fetch failed: {ex}"}
        log = sg.extract_job_log(comments)
        eq = sg.eq_lifecycle(comments)
        lines = [
            f"{r['date']} {r['weekday']} — {r['activity']}"
            + (f" ({r['who']})" if r['who'] else "")
            for r in log
        ]
        eq_warn = ""
        if eq.get("outstanding"):
            d = eq.get("days_out")
            eq_warn = ("⚠ Equipment still on site"
                       + (f" ({d}d)" if d else "")
                       + f" — placed {', '.join(eq.get('placed') or [])}, "
                       "no pickup logged")
        if not log and not eq_warn:
            return {"ok": False, "error": "no datable field events in comments"}
        return {"ok": True, "text": "\n".join(lines), "rows": log,
                "eq": eq, "eq_warn": eq_warn, "count": len(log)}

    # ── P1: Escalation dialog (Teams to role + mark escalated) ──────
    def get_escalation_roles(self):
        """All saved escalation contacts (role → email)."""
        try:
            return persistence.get_escalation_emails() or {}
        except Exception:
            return {}

    def set_escalation_email(self, role, email):
        if not role:
            return {"ok": False, "error": "role required"}
        try:
            persistence.set_escalation_email(role, email or "")
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def is_escalated(self, client):
        """Has this client been escalated today?"""
        try:
            d = self._last_meta.get("date_iso") or _dt.date.today().strftime("%Y-%m-%d")
            return bool(persistence.is_escalated(d, client))
        except Exception:
            return False

    def escalate(self, client, role, note=""):
        """Send a Teams message to the role's email + mark escalated
        for today. Mirrors the Tk escalation dialog."""
        if not client or not role:
            return {"ok": False, "error": "client + role required"}
        try:
            email = persistence.get_escalation_email(role) or ""
        except Exception:
            email = ""
        if not email:
            return {"ok": False, "needs_email": True, "role": role,
                    "error": f"no email saved for role {role}"}
        # Find the row for context
        row = next((r for r in self._last_rows
                    if r.get("client") == client), None)
        missing = []
        if row:
            missing = list(row.get("form_issues") or []) + list(row.get("photo_issues") or [])
        body = f"Escalation: {client} has been flagged for {len(missing)} days."
        if missing:
            body += "\n\nMissing items:\n" + "\n".join(f"  • {m}" for m in missing)
        if note:
            body += f"\n\nNote: {note}"
        # Use msteams: URI same as APA Teams
        try:
            import apa_logic as _apa
            ok = _apa.open_teams_chat(email, body)
        except Exception:
            ok = False
        # Mark escalated regardless of Teams launch (user might use
        # their own communication channel and just want the tracking)
        try:
            d = self._last_meta.get("date_iso") or _dt.date.today().strftime("%Y-%m-%d")
            persistence.set_escalated(d, client, True)
        except Exception:
            pass
        return {"ok": True, "teams_opened": bool(ok), "email": email}

    def get_xa_apology_note(self):
        """Return the canonical XA apology note text. Single source of
        truth is `ar_followup.DEFAULT_NOTE` — fetched over the bridge
        so the audit + Hygiene web buttons stay in sync with a wording
        change in one place. Returns `{ok, note}`."""
        try:
            from ar_followup import DEFAULT_NOTE as _note
            return {"ok": True, "note": _note}
        except Exception:
            return {"ok": True,
                    "note": ("Our apologies for the delay. Please note "
                              "our estimating team is diligently working "
                              "on the file.")}

    # ── P1: Push new losses → APA Initial Uploads ───────────────────
    def push_new_losses_to_apa(self):
        """Walk today's run-doc, find every new-loss row, add each as
        an item under the APA 'Initial Uploads' section. Skips ones
        already in the section to avoid duplicates."""
        try:
            d = _dt.date.today()
            doc_path = _find_run_doc_for_date(d)
            if not doc_path:
                return {"ok": False, "error": "no run-doc"}
            jobs, _run_date = _state_hub.parse_run_doc(doc_path)
            import apa_logic as apa
            apa_path = apa.doc_path_for_today(d)
            sections = (apa.parse_existing_doc(apa_path)
                        if apa_path and os.path.isfile(apa_path) else {})
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

        target = apa.SEC_INITIAL_UPLOADS
        existing_clients = set()
        for it in sections.get(target, []):
            if isinstance(it, tuple):
                t = it[0]
            elif isinstance(it, dict):
                t = it.get("text") or ""
            else:
                t = str(it)
            # Normalize for dedupe
            existing_clients.add(t.split(" - ")[0].strip().lower())

        added = []
        for j in jobs:
            if not j.get("new_loss"):
                continue
            client = (j.get("client") or "").strip()
            if not client:
                continue
            if client.lower() in existing_clients:
                continue
            sections.setdefault(target, []).append((client, False))
            added.append(client)
            existing_clients.add(client.lower())

        if not added:
            return {"ok": True, "added": [], "note": "no new new-losses"}
        # Backfill all SECTION_ORDER + write
        for s in apa.SECTION_ORDER:
            sections.setdefault(s, [])
        try:
            apa.write_doc(apa_path, d, sections)
        except Exception as ex:
            return {"ok": False, "error": f"write failed: {ex}"}
        return {"ok": True, "added": added}

    # ── P1: Post daily misses → Trello bulk ─────────────────────────
    def post_daily_misses_to_trello(self):
        """For every flagged row in the current cached audit that has
        a pinned Trello card, post a 'Daily miss' comment listing the
        missing items. Returns counts of posted vs skipped."""
        if not self._last_rows:
            return {"ok": False, "error": "no cached audit — run one first"}
        try:
            import trello_client as tc
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        posted, skipped_no_pin, errored = [], [], []
        for r in self._last_rows:
            if not r.get("flagged"):
                continue
            card_id = r.get("trello_card_id") or ""
            if not card_id:
                skipped_no_pin.append(r.get("client", ""))
                continue
            missing = list(r.get("form_issues") or []) + list(r.get("photo_issues") or [])
            if not missing:
                continue
            body = (f"📋 **Daily miss** — items still missing:\n"
                    + "\n".join(f"  • {m}" for m in missing))
            try:
                tc.post_comment(card_id, body)
                posted.append(r.get("client", ""))
            except Exception:
                errored.append(r.get("client", ""))
        return {"ok": True, "posted": posted,
                "skipped_no_pin": skipped_no_pin, "errored": errored}

    # ── P1: SP Recent + Backlog modes ───────────────────────────────
    def list_sp_recent(self, days_back: int = 7) -> dict:
        """Recent SharePoint folders modified within the window —
        same dataset the Tk SP Recent tab shows. Filters out dismissed
        rows by default. Each row is shaped like an audit row so the
        existing list/detail UI can render them with minimal forking.
        """
        try:
            import sp_recent_audit as _sp
            now = _dt.datetime.now()
            end_ts = now.timestamp()
            start_ts = (now - _dt.timedelta(days=int(days_back))).timestamp()
            folders = _sp._list_recent_sp_folders(start_ts, end_ts) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        rows = []
        for f in folders:
            try:
                dismissed = persistence.is_sp_recent_dismissed(f.get("path") or "")
            except Exception:
                dismissed = False
            rows.append({
                "client":      f.get("name", ""),
                "techs":       [f.get("tech", "")] if f.get("tech") else [],
                "path":        f.get("path", ""),
                "folder":      f.get("name", ""),
                "found":       True,
                "form_issues": [],
                "photo_issues": [],
                "aging_days":  int(f.get("age_days") or 0),
                "last_seen":   _dt.datetime.fromtimestamp(f.get("mtime") or 0).strftime("%Y-%m-%d %H:%M"),
                "flagged":     False,
                "section":     "sp_recent",
                "activity":    [],
                "new_loss":    False,
                "trello_card_id": "",
                "is_commercial":  False,
                "any_issue":   False,
                "total_missing": 0,
                "dismissed":   bool(dismissed),
            })
        return {"ok": True, "rows": rows,
                "days_back": int(days_back),
                "total": len(rows)}

    def dismiss_sp_recent(self, sp_path: str) -> dict:
        if not sp_path:
            return {"ok": False}
        try:
            persistence.dismiss_sp_recent(sp_path)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def undismiss_sp_recent(self, sp_path: str) -> dict:
        if not sp_path:
            return {"ok": False}
        try:
            persistence.undismiss_sp_recent(sp_path)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def _job_root_from_pics(self, pics_root: str) -> str:
        return _wh_job_root_from_pics(pics_root)

    def _unit_match_tokens(self, text: str) -> set:
        """Lowercase tokens (len >= 3) suitable for insured-name
        overlap. Drops digits + stopwords. Mirrors
        run_audit_gui._name_tokens_for_unit_match."""
        if not text: return set()
        import re as _re
        stopwords = {"unit", "apt", "apartment", "the", "and",
                     "for", "from", "ems", "sp", "demo", "mit",
                     "pics", "photos"}
        toks = {t for t in _re.findall(r"[a-z]+", text.lower())
                if len(t) >= 3}
        return toks - stopwords

    # ── SharePoint importer (per-row) ────────────────────────────────
    def sp_find_matches(self, client: str, unit: str = "") -> dict:
        """List SharePoint folder candidates for a client, with OD diff
        counts computed so the Copy button activates immediately.
        Mirrors the Tk per-row SP dialog's match step including the
        enrich_with_sharepoint OD-diff pass. `unit` lets multi-unit
        jobs narrow to a specific unit number."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            from sharepoint import find_sharepoint_folders_for_client
            # `run_date` must be a "MM-DD-YYYY" string — internal
            # `_date_variants` calls `.split("-")` on it. Passing a
            # date object causes the matches_date check downstream to
            # raise 'in <string>' requires string as left operand.
            run_date_str = _dt.date.today().strftime("%m-%d-%Y")
            matches = find_sharepoint_folders_for_client(
                client, run_date=run_date_str,
                unit=unit or None) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "matches": []}
        try:
            rejected = persistence.get_sp_match_rejects(client) or set()
        except Exception:
            rejected = set()
        matches = [m for m in matches if m.get("path") not in rejected]

        # Compute OD diff (new_count) for each match by comparing SP
        # filenames against what's already in the job's OD PICS tree.
        # Without this every match shows new_count=0 and the Copy
        # button is always disabled — pinned folders look like they
        # "did nothing". Mirrors enrich_with_sharepoint in run_audit_gui.
        try:
            # Find the cached row so we have the OD path without
            # re-running a full audit.
            cached_r = None
            for r in (self._oneoff_rows + self._last_rows):
                if r.get("client") == client:
                    cached_r = r
                    break
            if cached_r:
                enrich_with_sharepoint(cached_r, run_date_str)
                # Splice the fresh new_count values back onto our
                # local matches list (keyed by path).
                enriched = {
                    m.get("path"): m
                    for m in (cached_r.get("sharepoint_matches") or [])
                }
                for m in matches:
                    fresh = enriched.get(m.get("path"))
                    if fresh:
                        m["new_count"] = fresh.get("new_count", 0)
                        m["new_names"] = list(fresh.get("new_names") or [])
                        m["match_stats"] = fresh.get("match_stats") or {}
        except Exception:
            pass

        rows = []
        for m in matches:
            path = m.get("path") or ""
            rows.append({
                "name":         m.get("name") or os.path.basename(path),
                "path":         path,
                "tech":         m.get("tech") or "",
                "new_count":    int(m.get("new_count") or 0),
                "img_count":    int(m.get("img_count") or m.get("count") or 0),
                "matches_date": bool(m.get("matches_date")),
                "mtime":        m.get("mtime") or "",
                "match_stats":  m.get("match_stats") or {},
                "new_names":    list(m.get("new_names") or [])[:20],
            })
        return {"ok": True, "matches": rows, "total": len(rows)}

    def match_diagnostic(self, client: str) -> dict:
        """Explain why a folder matched (or didn't) for `client`.
        Mirrors the Tk audit's _open_match_diagnostic dialog —
        walks the same name-normalization rules audit_logic uses
        and surfaces every candidate folder with a score.

        Helps when the user says "why didn't the audit find Smith?"
        — shows whether the issue is name spelling, year folder
        membership, or unit-specific filtering.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            from audit_logic import _audit_jobs_core  # noqa
            # We mostly need the year_folder listings — re-use the
            # cached helper added in the audit_logic perf pass.
            from audit_logic import _cached_year_listing
            import paths
            base = paths.audit_base()
            now = _dt.date.today()
            years = [now.year, now.year - 1]
            year_folders = {}
            for y in years:
                yp = next((os.path.join(base, d) for d in os.listdir(base)
                           if os.path.isdir(os.path.join(base, d))
                           and str(y) in d), None)
                if yp:
                    year_folders[y] = (yp, _cached_year_listing(yp))
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

        from web_helpers import norm_name as _norm, norm_tokens as _norm_tokens
        target = _norm(client)
        target_tokens = _norm_tokens(client)

        candidates = []
        for y, (yp, names) in year_folders.items():
            for n in names:
                nl = _norm(n)
                if not nl: continue
                # Score: substring → 10, token overlap → token-count
                score = 0
                why = []
                if target and (target in nl or nl in target):
                    score += 10
                    why.append("substring match")
                ntoks = set(t for t in nl.split() if len(t) >= 2)
                inter = ntoks & target_tokens
                if inter:
                    score += len(inter)
                    why.append(f"shared tokens: {sorted(inter)}")
                if score > 0:
                    candidates.append({
                        "year": y, "folder": n,
                        "path":  os.path.join(yp, n),
                        "score": score,
                        "why":   "; ".join(why),
                    })
        candidates.sort(key=lambda c: -c["score"])
        # Trello pin info — sometimes the auto-resolve is wrong because
        # there's no pin and the name-match is ambiguous.
        pin = ""
        try:
            pin = persistence.get_trello_card_id(client) or ""
        except Exception:
            pass
        # Persisted override (Find/Change Folder pinned a specific path)
        override = ""
        try:
            override = persistence.get_folder_path(client) or ""
        except Exception:
            pass
        return {
            "ok":          True,
            "client":      client,
            "candidates":  candidates[:20],
            "trello_pin":  pin,
            "override":    override,
            "year_count":  len(year_folders),
            "norm_query":  target,
            "norm_tokens": sorted(target_tokens),
        }

    def clear_trello_hover_cache(self) -> dict:
        """Drop the 60-second card-hover cache. Useful when a card
        was just updated on Trello and the user wants fresh data
        without waiting for the TTL to expire."""
        try:
            cache = getattr(self, "_card_hover_cache", None)
            if cache is not None:
                cache.clear()
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def trello_card_hover(self, card_id: str) -> dict:
        """Lightweight card lookup for the hover popover — name + lane
        + last-activity date. Mirrors the Tk audit's pinned-card
        tooltip. Cached briefly so hovering several rows doesn't
        re-fetch the same card."""
        if not card_id:
            return {"ok": False}
        try:
            cache = getattr(self, "_card_hover_cache", None)
            if cache is None:
                cache = {}
                self._card_hover_cache = cache
            import time as _time
            now = _time.time()
            cached = cache.get(card_id)
            if cached and (now - cached[0]) < 60:
                return cached[1]
            import trello_client as tc
            card = tc.get_card(card_id) or {}
            lane = ""
            try:
                if hasattr(tc, "get_lane_name"):
                    lane = tc.get_lane_name(card.get("idBoard") or "",
                                              card.get("idList") or "") or ""
            except Exception:
                lane = ""
            try:
                board = tc.get_board_name(card.get("idBoard") or "") if hasattr(tc, "get_board_name") else ""
            except Exception:
                board = ""
            last_act = card.get("dateLastActivity") or ""
            payload = {
                "ok":     True,
                "name":   card.get("name") or "",
                "lane":   lane,
                "board":  board,
                "url":    card.get("shortUrl") or
                            (f"https://trello.com/c/{card_id}" if card_id else ""),
                "labels": [l.get("name") or "" for l in (card.get("labels") or []) if l],
                "last_activity": last_act[:10] if isinstance(last_act, str) else "",
            }
            cache[card_id] = (now, payload)
            return payload
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def trello_enrichment(self, client: str, card_id: str = "") -> dict:
        """Rich Trello read for the audit detail pane — everything the
        row itself doesn't carry, from ONE get_card call: lane/status +
        last activity, loss type + labels, due date, checklist progress,
        assigned members, adjuster/customer email, and the latest few
        comments (pulled from the card's inlined actions — no extra
        call). Cached 60s per card. Returns {ok, has_card, ...};
        has_card=False when nothing is pinned so the frontend renders
        nothing."""
        if not card_id and client:
            try:
                card_id = persistence.get_trello_card_id(client) or ""
            except Exception:
                card_id = ""
        if not card_id:
            return {"ok": True, "has_card": False}
        try:
            cache = getattr(self, "_card_enrich_cache", None)
            if cache is None:
                cache = {}
                self._card_enrich_cache = cache
            import time as _time
            now = _time.time()
            hit = cache.get(card_id)
            if hit and (now - hit[0]) < 60:
                return hit[1]
            import trello_client as tc
            card = tc.get_card(card_id) or {}
            try:
                lane = tc.get_lane_name(card.get("idBoard") or "",
                                        card.get("idList") or "") or ""
            except Exception:
                lane = ""
            try:
                loss = tc.card_loss_type(card) or ""
            except Exception:
                loss = ""
            try:
                done, total = tc.checklist_progress(card)
            except Exception:
                done, total = 0, 0
            members = [m.get("fullName") or m.get("username") or ""
                       for m in (card.get("members") or []) if m]
            members = [m for m in members if m]
            try:
                fields = tc.parse_card_desc(card.get("desc") or "") or {}
            except Exception:
                fields = {}
            ins = fields.get("INSURANCE INFORMATION") or {}
            cust = fields.get("CUSTOMER INFORMATION") or {}
            adjuster_email = (ins.get("ADJUSTER EMAIL") or "").strip()
            customer_email = (cust.get("EMAIL")
                              or cust.get("EMAIL ADDRESS") or "").strip()
            # These template fields sometimes hold a website/URL, not an
            # address — only keep a real-looking email so "Copy email"
            # never hands back "https://…".
            if "@" not in adjuster_email:
                adjuster_email = ""
            if "@" not in customer_email:
                customer_email = ""
            # Latest comments ride along in the card's inlined actions —
            # no separate paged fetch needed.
            comments = []
            for a in (card.get("actions") or []):
                if a.get("type") != "commentCard":
                    continue
                txt = ((a.get("data") or {}).get("text") or "").strip()
                if not txt:
                    continue
                comments.append({
                    "author": (a.get("memberCreator") or {}).get("fullName") or "",
                    "date": (a.get("date") or "")[:10],
                    "text": txt})
                if len(comments) >= 5:
                    break
            due = card.get("due") or ""
            payload = {
                "ok": True, "has_card": True,
                "name": card.get("name") or "",
                "lane": lane,
                "labels": [l.get("name") or "" for l in (card.get("labels") or [])
                           if l and (l.get("name") or "")],
                "loss_type": loss,
                "due": due[:10] if isinstance(due, str) else "",
                "due_complete": bool(card.get("dueComplete")),
                "last_activity": (card.get("dateLastActivity") or "")[:10],
                "checklist_done": done, "checklist_total": total,
                "members": members,
                "adjuster_email": adjuster_email,
                "customer_email": customer_email,
                "comments": comments,
                "url": card.get("shortUrl")
                or (f"https://trello.com/c/{card_id}" if card_id else ""),
            }
            cache[card_id] = (now, payload)
            return payload
        except Exception as ex:
            return {"ok": False, "has_card": True, "error": str(ex)}

    def get_inprogress_checklist(self, client: str) -> dict:
        """Return the IN PROGRESS - ADMIN checklist for a client's pinned
        Trello card so the audit card can render it inline with a checkbox
        per item. Briefly cached so re-rendering a row doesn't re-fetch.

        Returns {ok, card_id, items: [{id, name, complete}]}. ok=False
        with no error when there's simply no pinned card / no checklist
        — the frontend just renders nothing in that case."""
        if not client:
            return {"ok": False}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False}
        try:
            cache = getattr(self, "_inprog_cl_cache", None)
            if cache is None:
                cache = {}
                self._inprog_cl_cache = cache
            import time as _time
            now = _time.time()
            cached = cache.get(card_id)
            if cached and (now - cached[0]) < 45:
                return cached[1]
            import trello_client as tc
            card = tc.get_card(card_id, actions_limit=0) or {}
            checklist = None
            for c in (card.get("checklists") or []):
                if (c.get("name") or "").strip().lower() == \
                        "in progress - admin":
                    checklist = c
                    break
            if checklist is None:
                payload = {"ok": False, "card_id": card_id, "items": []}
                cache[card_id] = (now, payload)
                return payload
            items = [{
                "id":       it.get("id") or "",
                "name":     it.get("name") or "?",
                "complete": (it.get("state") or "").lower() == "complete",
            } for it in (checklist.get("checkItems") or [])]
            payload = {"ok": True, "card_id": card_id, "items": items}
            cache[card_id] = (now, payload)
            return payload
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def toggle_checklist_item(self, card_id: str, item_id: str,
                               complete) -> dict:
        """Tick / un-tick one checklist item on a Trello card. `complete`
        is truthy for done. Updates the in-memory checklist cache so a
        subsequent re-render shows the new state without a re-fetch."""
        if not card_id or not item_id:
            return {"ok": False, "error": "card_id + item_id required"}
        state = "complete" if complete else "incomplete"
        try:
            import trello_client as tc
            ok = bool(tc.set_check_item_state(card_id, item_id, state))
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if ok:
            for _cache_attr in ("_inprog_cl_cache", "_initial_cl_cache"):
                try:
                    cache = getattr(self, _cache_attr, None)
                    if cache and card_id in cache:
                        _ts, payload = cache[card_id]
                        for cl in (payload.get("checklists")
                                   or [{"items": payload.get("items") or []}]):
                            for it in cl.get("items") or []:
                                if it.get("id") == item_id:
                                    it["complete"] = bool(complete)
                except Exception:
                    pass
        return {"ok": ok}

    def get_initial_checklists(self, client: str) -> dict:
        """Return the 'INITIAL' + 'INITIAL - ADMIN' Trello checklists for a
        client's pinned card so the AUDIT detail can render the same intake
        checklist the IUQ used to own. (Folded in 2026-06-18 — the initial
        checklist + canned comments were the only real difference between
        the two panels.) 45s cache. Shape:
        {ok, card_id, checklists: [{name, items:[{id,name,complete}]}]}."""
        if not client:
            return {"ok": False}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False}
        try:
            cache = getattr(self, "_initial_cl_cache", None)
            if cache is None:
                cache = {}
                self._initial_cl_cache = cache
            import time as _time
            now = _time.time()
            cached = cache.get(card_id)
            if cached and (now - cached[0]) < 45:
                return cached[1]
            import trello_client as tc
            card = tc.get_card(card_id, actions_limit=0) or {}
            by_name = {(c.get("name") or "").strip().lower(): c
                       for c in (card.get("checklists") or [])}
            out = []
            for nm in ("initial", "initial - admin"):
                c = by_name.get(nm)
                if not c:
                    continue
                out.append({
                    "name": c.get("name") or nm.title(),
                    "items": [{
                        "id":       it.get("id") or "",
                        "name":     it.get("name") or "?",
                        "complete": (it.get("state") or "").lower() == "complete",
                    } for it in (c.get("checkItems") or [])],
                })
            payload = {"ok": True, "card_id": card_id, "checklists": out}
            cache[card_id] = (now, payload)
            return payload
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_all_checklists(self, client: str) -> dict:
        """Return EVERY Trello checklist on the client's pinned card, in board
        order. Same shape as get_initial_checklists. 45s cache."""
        if not client:
            return {"ok": False}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False}
        try:
            cache = getattr(self, "_all_cl_cache", None)
            if cache is None:
                cache = {}
                self._all_cl_cache = cache
            import time as _time
            now = _time.time()
            cached = cache.get(card_id)
            if cached and (now - cached[0]) < 45:
                return cached[1]
            import trello_client as tc
            card = tc.get_card(card_id, actions_limit=0) or {}
            cls = sorted((card.get("checklists") or []),
                         key=lambda c: c.get("pos", 0))
            out = [{
                "name": c.get("name") or "Checklist",
                "id":   c.get("id") or "",
                "items": [{
                    "id":       it.get("id") or "",
                    "name":     it.get("name") or "?",
                    "complete": (it.get("state") or "").lower() == "complete",
                } for it in (c.get("checkItems") or [])],
            } for c in cls]
            payload = {"ok": True, "card_id": card_id, "checklists": out}
            cache[card_id] = (now, payload)
            return payload
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def activity_comment_text(self, stage: str, tech: str,
                              date_iso: str = "") -> dict:
        """The dated activity comment, in the shape the office already
        writes by hand:

            Saturday 08/01

            Monitor - ME

        Built here rather than in JS so the Trello comment and anything
        else that logs the same visit cannot drift in wording. `date_iso`
        defaults to today.

        The tech is written as roster INITIALS ("ME", not "Mark E") —
        that is the handwritten form, and the picker hands us full names.
        Same `initials_for_name(...) or tech` fallback the CompanyCam
        import uses, so a helper with no roster entry keeps their name
        rather than vanishing.
        """
        stage = (stage or "").strip()
        tech = (tech or "").strip()
        if not stage:
            return {"ok": False, "error": "stage required"}
        if tech:
            try:
                tech = audit_logic.initials_for_name(tech) or tech
            except Exception:
                pass
        try:
            d = (_dt.date.fromisoformat(date_iso) if date_iso
                 else _dt.date.today())
        except ValueError:
            d = _dt.date.today()
        # Zero-padded: %-d/%-m aren't portable to Windows, and the
        # handwritten form is "08/01" anyway, not "8/1".
        head = f"{d.strftime('%A')} {d.strftime('%m/%d')}"
        body = f"{stage} - {tech}" if tech else stage
        return {"ok": True, "text": f"{head}\n\n{body}",
                "stage": stage, "tech": tech, "date": d.isoformat()}

    def list_activity_stages(self) -> dict:
        """Stage labels for the activity-comment picker, in timeline
        order. Read from `stages.LABELS` rather than hardcoded in JS so
        adding a stage there shows up here without a second edit."""
        try:
            import stages as _stages
            return {"ok": True, "stages": list(_stages.LABELS)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "stages": []}

    def post_activity_comment(self, card_id: str, stage: str, tech: str,
                              date_iso: str = "") -> dict:
        """Post the dated activity comment to a card."""
        built = self.activity_comment_text(stage, tech, date_iso)
        if not built.get("ok"):
            return built
        if not card_id:
            return {"ok": False, "error": "no Trello card pinned"}
        try:
            import trello_client as tc
            tc.post_comment(card_id, built["text"])
            return {"ok": True, "text": built["text"]}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def post_canned(self, card_id: str, key: str) -> dict:
        """Post a canned intake comment to a Trello card — folded in from
        the IUQ. `key` is 'ipr' or 'upload'."""
        canned = {
            "ipr":    "Initial Photo Report Created and Uploaded to OD.",
            "upload": "Initial Upload submitted To WC.",
        }
        text = canned.get(key, "")
        if not card_id or not text:
            return {"ok": False, "error": "card_id + valid key required"}
        try:
            import trello_client as tc
            tc.post_comment(card_id, text)
            return {"ok": True, "text": text}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_rundoc_for_sp_match(self, sp_path: str) -> dict:
        """Open the run-doc for the date encoded in the SP folder.
        Resolution order (mirrors Tk's _copy_match date logic):
          1. Date parsed from the SP folder name (e.g.
             'Smith 5-22-26 Demo' → 5/22/26)
          2. SP folder's mtime (when the tech didn't date the name)
          3. Today (last-resort)

        Tries each candidate in order, walking back up to 7 days
        from each if that exact date has no run-doc — handles
        weekend SP folders where the closest run-doc is the
        preceding Friday.
        """
        candidates = []
        if sp_path:
            sp_name = os.path.basename(sp_path.rstrip(os.sep))
            # 1. Parse from name
            try:
                d1 = _extract_date_from_folder_name(sp_name)
                if d1: candidates.append(("folder name", d1))
            except Exception:
                pass
            # 2. SP folder mtime — what the Tk audit's _copy_match uses
            try:
                if os.path.isdir(sp_path):
                    mt = os.path.getmtime(sp_path)
                    candidates.append(("folder mtime",
                                       _dt.datetime.fromtimestamp(mt)))
            except Exception:
                pass
        # 3. Today (last resort)
        candidates.append(("today", _dt.datetime.today()))

        for source, dt_val in candidates:
            try:
                d = dt_val.date() if hasattr(dt_val, "date") else dt_val
            except Exception:
                continue
            # Walk back up to 7 days from this anchor — weekend SP
            # folders find the preceding Friday's run-doc
            for back in range(0, 8):
                day = d - _dt.timedelta(days=back)
                try:
                    doc = _find_run_doc_for_date(day)
                except Exception:
                    doc = None
                if doc and os.path.isfile(doc):
                    try:
                        os.startfile(doc)
                    except Exception as ex:
                        return {"ok": False, "error": str(ex)}
                    return {
                        "ok": True, "path": doc,
                        "date_label": day.strftime("%A %m/%d/%Y"),
                        "source": source,
                        "days_back": back,
                    }
        return {"ok": False,
                "error": "No run-doc found for the SP folder's date or any of the past 7 days"}

    def sp_cloud_only_count(self, sp_path: str) -> dict:
        """Return how many files under `sp_path` are cloud-only
        OneDrive placeholders (not actually downloaded). Mirrors
        sp_sync_state.count_cloud_only — drives the ☁ chip + the
        Force pull button in the SP import dialog so the user knows
        when files won't actually be copyable without a download
        pass first.
        """
        if not sp_path or not os.path.isdir(sp_path):
            return {"ok": False, "count": 0}
        try:
            import sp_sync_state
            result = sp_sync_state.count_cloud_only(sp_path) or {}
            return {
                "ok":         True,
                "count":      int(result.get("count") or 0),
                "total":      int(result.get("total") or 0),
                "samples":    list((result.get("samples") or []))[:5],
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex), "count": 0}

    def sp_force_pull(self, sp_path: str) -> dict:
        """Trigger OneDrive to download every cloud-only file under
        `sp_path` by opening each for a 1-byte read. Streams progress
        through the `sp:pull-progress` event so the dialog shows the
        file-by-file pull. Mirrors sp_sync_state.force_pull. Slow on
        big folders — every file is a network round-trip."""
        if not sp_path or not os.path.isdir(sp_path):
            return {"started": False, "reason": "no folder"}
        if getattr(self, "_sp_pulling", False):
            return {"started": False, "reason": "pull already running"}
        self._sp_pulling = True
        import threading as _t

        def _bg():
            try:
                import sp_sync_state
                import web_event
                def _progress(done, total, name):
                    web_event.event(self._window, "sp:pull-progress",
                                    {"done": done, "total": total,
                                     "name": name})
                result = sp_sync_state.force_pull(
                    sp_path, progress_cb=_progress) or {}
                try:
                    web_event.event(self._window, "sp:pull-done", {
                        "ok": True, "result": result,
                    })
                except Exception:
                    pass
            except Exception as ex:
                try:
                    import web_event
                    web_event.event(self._window, "sp:pull-done", {
                        "ok": False, "error": f"{type(ex).__name__}: {ex}",
                    })
                except Exception:
                    pass
            finally:
                self._sp_pulling = False

        _t.Thread(target=_bg, daemon=True).start()
        return {"started": True}

    def sp_open_folder(self, sp_path: str) -> bool:
        if not sp_path: return False
        try:
            os.startfile(sp_path); return True
        except Exception:
            return False

    def sp_reject_match(self, client: str, sp_path: str) -> dict:
        try:
            persistence.add_sp_match_reject(client, sp_path)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def sp_browse_for_folder(self) -> str:
        """Open the native folder picker so the user can point at any
        SP tech folder the auto-matcher didn't find. Returns the
        absolute path, or "" when canceled. PHOTOS_ROOT seeded as the
        starting directory."""
        try:
            from sharepoint import PHOTOS_ROOT
            init_dir = PHOTOS_ROOT if os.path.isdir(PHOTOS_ROOT) else None
        except Exception:
            init_dir = None
        try:
            if self._window is None:
                return ""
            result = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=init_dir or "",
                allow_multiple=False)
            if not result:
                return ""
            picked = result[0] if isinstance(result, (list, tuple)) else result
            return str(picked) if picked else ""
        except Exception:
            return ""

    def sp_pin_folder(self, client: str, sp_path: str) -> dict:
        """Manually attach an SP folder to a client. Walks the folder
        once to confirm it has images, persists the override, and
        returns the new match dict shaped for the dialog. Mirrors
        Tk's _pin_folder.
        """
        if not client or not sp_path:
            return {"ok": False, "error": "client + sp_path required"}
        if not os.path.isdir(sp_path):
            return {"ok": False, "error": "folder doesn't exist"}
        try:
            from sharepoint import (PHOTOS_ROOT, _build_sp_match,
                                     _date_variants)
        except Exception as ex:
            return {"ok": False, "error": f"sharepoint import: {ex}"}
        # Soft guardrail: warn if outside PHOTOS_ROOT but allow attach
        outside = False
        try:
            norm_pick = os.path.normpath(os.path.abspath(sp_path))
            norm_root = os.path.normpath(os.path.abspath(PHOTOS_ROOT))
            outside = not norm_pick.startswith(norm_root + os.sep)
        except Exception:
            pass
        # Persist the override BEFORE the image check so the user
        # sees the pin even when the count is 0 — they can remove via
        # the ✕ Reject button if they pinned the wrong place.
        try:
            persistence.add_sp_match_override(client, sp_path)
        except Exception as ex:
            return {"ok": False, "error": f"persist: {ex}"}
        # Build a match record for the dialog. _build_sp_match returns
        # None when the folder has no image files. _date_variants
        # expects a "MM-DD-YYYY" string, NOT a date object — passing
        # the date directly leaks through to `d in name.lower()` and
        # raises `'in <string>' requires string as left operand, not
        # datetime.date`. Convert up-front.
        try:
            d = _dt.date.today()
            run_date_str = d.strftime("%m-%d-%Y")
            dates = _date_variants(run_date_str) if run_date_str else []
            rec = _build_sp_match(sp_path, dates, override=True)
        except Exception:
            rec = None
        if rec is None:
            # Roll back — nothing to attach
            try:
                persistence.remove_sp_match_override(client, sp_path)
            except Exception:
                pass
            return {"ok": False,
                    "error": "That folder has no image files — nothing to attach."}
        # Re-run enrich_with_sharepoint on the cached row so the pinned
        # folder gets its OD diff computed (new_count > 0 → Copy button
        # appears). Mirrors Tk's _do_refresh() call after _pin_folder.
        try:
            run_date_str = _dt.date.today().strftime("%m-%d-%Y")
            target_list = (
                self._oneoff_rows
                if any(r.get("client") == client for r in self._oneoff_rows)
                else self._last_rows)
            for cached_r in target_list:
                if cached_r.get("client") == client:
                    enrich_with_sharepoint(cached_r, run_date_str)
                    # Pull the freshly-computed new_count for this path.
                    for m in (cached_r.get("sharepoint_matches") or []):
                        if m.get("path") == sp_path:
                            rec["new_count"] = int(m.get("new_count") or 0)
                            break
                    break
        except Exception:
            pass

        # Shape for the JS modal (mirrors sp_find_matches return shape)
        match = {
            "name":         rec.get("name") or os.path.basename(sp_path),
            "path":         rec.get("path") or sp_path,
            "tech":         rec.get("tech") or "",
            "new_count":    int(rec.get("new_count") or 0),
            "img_count":    int(rec.get("img_count") or rec.get("count") or 0),
            "matches_date": bool(rec.get("matches_date")),
        }
        return {"ok": True, "match": match, "outside_root": outside}

    def sp_mark_in_od(self, client: str, sp_path: str) -> dict:
        """User says these SP files are already in OD (just renamed
        or recompressed so the diff didn't catch them). Records the
        SP basenames in the PICS manifest at every PICS variant so
        future audits stop counting them as 'new'. Mirrors Tk's
        _mark_in_od."""
        if not client or not sp_path or not os.path.isdir(sp_path):
            return {"ok": False, "error": "client + sp_path required"}
        try:
            import sharepoint as _sp
            files = list(_sp.list_image_names_in_tree(sp_path) or [])
        except Exception as ex:
            return {"ok": False, "error": f"walk: {ex}"}
        if not files:
            return {"ok": False, "error": "no image files to mark"}
        # Resolve PICS root (same logic as sp_copy_to_pics)
        pics_root = ""
        try:
            folder = persistence.get_folder_path(client) or ""
            if folder and os.path.isdir(folder):
                cand = os.path.join(folder, "EMS", "PICS")
                pics_root = cand if os.path.isdir(cand) else os.path.join(folder, "PICS")
        except Exception:
            pics_root = ""
        if not pics_root or not os.path.isdir(pics_root):
            return {"ok": False, "error": "Couldn't resolve PICS folder"}
        try:
            _append_sp_manifest_originals(pics_root, files)
        except Exception as ex:
            return {"ok": False, "error": f"manifest write: {ex}"}
        return {"ok": True, "marked": len(files), "pics_root": pics_root}

    def sp_copy_to_pics(self, client: str, sp_path: str,
                         target_pics: str = "",
                         job_path: str = "", side: str = "ems",
                         tech: str = "") -> dict:
        """Copy NEW images from `sp_path` into the job's PICS tree.

        Resolution order for the destination PICS root:
          1. `target_pics` if the caller hands one directly.
          2. `job_path` — the audit row's resolved job folder. Used by
             the audit panel since it already resolved the folder; no
             need to round-trip through persistence.
          3. `persistence.get_folder_path(client)` — works when the
             user has explicitly pinned a folder via Find/Change.
          4. Walk `_last_rows` for a row with this client + its path.
        Returns counts so the UI can render a progress summary.
        """
        if not client or not sp_path:
            return {"ok": False, "error": "client + sp_path required"}
        if not os.path.isdir(sp_path):
            return {"ok": False, "error": "SP folder doesn't exist"}
        import shutil

        _pics_from_jobroot = _wh_pics_from_jobroot

        # Step 1: explicit target_pics
        pics_root = target_pics or ""
        # Step 2: explicit job_path (NEW — passed by the audit dialog)
        if not pics_root and job_path:
            pics_root = _pics_from_jobroot(job_path)
        # Step 3: persistence pin
        if not pics_root:
            try:
                folder = persistence.get_folder_path(client) or ""
                pics_root = _pics_from_jobroot(folder)
            except Exception:
                pass
        # Step 4: last-resort — find the client in either cached row
        # list. One-off audits (🔍 Audit one) live in _oneoff_rows,
        # NOT _last_rows — without this walk a single-audit row's
        # resolved path was invisible to the importer even though
        # the audit row itself had it. That was the "single audit
        # found the folder but SP import says it didn't" bug.
        if not pics_root:
            for r in (self._last_rows + self._oneoff_rows):
                if (r.get("client") or "").strip() == client.strip():
                    pics_root = _pics_from_jobroot(r.get("path") or "")
                    if pics_root: break
        if not pics_root:
            return {"ok": False,
                    "error": f"Couldn't resolve PICS folder for {client}. Pin the OD folder first via Find/Change Folder."}
        # ── Contents-side override ────────────────────────────────
        # When the user toggled "Contents side" in the SP dialog, flip
        # the resolved EMS-side pics_root to the CONTENTS side of the
        # SAME job folder (CONTENTS/PICS) so the import lands there.
        if (side or "").strip().lower() == "contents":
            _root = (job_path if (job_path and os.path.isdir(job_path))
                     else _wh_job_root_from_pics(pics_root))
            _cpics = _wh_contents_pics_from_jobroot(_root) if _root else ""
            if _cpics:
                pics_root = _cpics
        if not os.path.isdir(pics_root):
            try:
                os.makedirs(pics_root, exist_ok=True)
            except Exception as ex:
                return {"ok": False, "error": f"mkdir PICS: {ex}"}

        # ── Multi-unit auto-route ─────────────────────────────────
        # Commercial jobs with units (Avila Apartments, Action Property
        # Management → Villaigo, etc.) have a Unit XXX subfolder per
        # tenant — and the SP photos arrive labeled per-unit too.
        # Mirror Tk's auto-router at run_audit_gui.py:3874-3911 so
        # 'Avila Apt 207 Demo' lands under '<job>/Unit 207/EMS/PICS/'
        # instead of the property root PICS.
        #
        # Disambiguates by insured-name token overlap when multiple
        # unit folders share the same number — keeps "Mendiola Unit
        # 104" out of the "Straub Unit 104" folder.
        try:
            from multi_unit_logic import (parse_unit_token,
                                          list_unit_subfolders)
            sp_basename = os.path.basename(sp_path.rstrip(os.sep))
            sp_unit = parse_unit_token(sp_basename)
            if sp_unit is not None:
                # Job folder (parent of pics_root)
                job_root = job_path or self._job_root_from_pics(pics_root)
                if job_root:
                    units = list_unit_subfolders(job_root) or []
                    matches = [u for u in units
                               if (u.get("unit_number") or u.get("num")) == sp_unit]
                    if matches:
                        # Token-overlap scoring on the insured name —
                        # see _name_tokens_for_unit_match in Tk.
                        sp_tokens = self._unit_match_tokens(sp_basename)
                        scored = []
                        for u in matches:
                            opt_tokens = self._unit_match_tokens(
                                u.get("client_display") or u.get("name") or "")
                            overlap = len(sp_tokens & opt_tokens)
                            scored.append((overlap, u))
                        scored.sort(key=lambda t: -t[0])
                        best_overlap, best_u = scored[0]
                        # Auto-route when either there's exactly one
                        # Unit-X candidate OR the best one has at least
                        # one name-token match. Refuses to guess when
                        # multiple equal candidates exist.
                        if len(matches) == 1 or best_overlap > 0:
                            unit_path = best_u.get("path") or ""
                            if unit_path and os.path.isdir(unit_path):
                                # Prefer Unit/EMS/PICS, fall back to
                                # Unit/PICS, then make EMS/PICS.
                                cand_pics = _pics_from_jobroot(unit_path)
                                if cand_pics:
                                    pics_root = cand_pics
        except Exception:
            # Multi-unit routing is opportunistic — failures just
            # fall through to the property-root PICS.
            pass

        # ── Destination folder name ────────────────────────────────
        # KEEP the SP folder name verbatim — the tech named it the way
        # they wanted it filed (date + activity + client). Renaming it
        # to a synthetic "<TECH> <DATE> <CLIENT>" was clobbering the
        # tech's original labeling (Cindy Costales case — landed in
        # "Mike 05-26-2026 Cindy Costales" instead of the SP-folder's
        # original "Cindy Costales 5-26-26 Initial" name).
        #
        # If you ever need the renamed form back, the helpers below
        # are still available — re-enable by toggling.
        import re as _re
        from sharepoint import _infer_tech
        # Image imports must attribute a tech. SP folders are usually named
        # by the tech, so infer first; require the caller to supply one only
        # when it can't be determined (frontend then prompts, pre-filled).
        tech = (tech or "").strip() or (_infer_tech(sp_path) or "")
        if not tech or tech.strip().lower() == "unknown":
            return {"ok": False, "need_tech": True,
                    "error": ("Couldn't tell which tech shot this SharePoint "
                              "folder — pick one before importing.")}
        sp_name = os.path.basename(sp_path.rstrip(os.sep)) or "SharePoint"

        def _safe(s):
            cleaned = _re.sub(r'[\\/:*?"<>|]', "_", str(s or "")).strip()
            return cleaned or "X"

        folder_name = _safe(sp_name)

        # Stage subfolder routing (e.g. "Initial" / "Demo pics") —
        # when the SP folder name encodes a stage, drop the import into
        # <PICS>/<stage>/ instead of the PICS root. Uses the same
        # `stages.detect_sp_folder_subfolder` helper Tk's audit dialog
        # routes through via m["stage_subfolder"]. The earlier
        # `run_audit_gui._extract_stage_from_folder_name` lookup was a
        # wrong name — that function doesn't exist, so stage routing
        # silently no-op'd for everyone (Cindy Costales case 2026-05-28
        # landed at PICS root instead of PICS/Initial/).
        stage_dest = pics_root
        stage_match = ""
        try:
            import stages as _stages
            stage_match = _stages.detect_sp_folder_subfolder(sp_name) or ""
        except Exception:
            stage_match = ""
        # When the SP folder name itself doesn't name a stage, fall back
        # to the run-doc activity for this job — so a run-doc "Demo"
        # routes the SP pics into PICS/<Demo pics> instead of dumping at
        # the PICS root. The run-doc is the one for the DATE embedded in
        # the SP folder name ("Melvin 6-10-26" → 6-10-26), so photos route
        # by the activity on the DAY THEY WERE TAKEN — not today. Falls
        # back to today's run-doc only when the folder name carries no
        # parseable date. Only fires when the job is on that day's run-doc
        # with a single clear activity: no match (empty labels) or an
        # ambiguous multi-activity day leaves it at the PICS root, exactly
        # as before. The tech's own SP folder-name stage label still wins
        # when present ("unless specified"). (2026-06-17, dated 2026-06-19)
        if not stage_match:
            try:
                from audit_logic import resolve_pics_subfolder
                _fdate = _extract_date_from_folder_name(sp_name)
                _date_str = (_fdate.strftime("%m-%d-%Y") if _fdate
                             else _dt.date.today().strftime("%m-%d-%Y"))
                _labels = _activity_labels_from_run_doc(_date_str, client)
                if _labels:
                    _sub2, _needs2 = resolve_pics_subfolder(_labels)
                    if _sub2 and not _needs2:
                        stage_match = _sub2
            except Exception:
                stage_match = ""
        if stage_match:
            stage_dest = os.path.join(pics_root, stage_match)

        # Reuse the existing same-name folder and MERGE into it — add the
        # new items rather than spawning "<name> (2)" / "(3)" every re-import.
        # Per-file dedup (existing basenames, below) skips photos already in
        # OD, and the per-file " (2)" suffix handles a genuine same-name/
        # different-file clash — so merging can't lose or duplicate. (2026-07-01)
        target_dir = os.path.join(stage_dest, folder_name)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception as ex:
            return {"ok": False, "error": f"mkdir dest: {ex}"}

        # Existing image basenames (under PICS, recursively) so the
        # diff matches Tk's behavior — basename-only, case-insensitive.
        IMG_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif",
                    ".bmp", ".tif", ".tiff", ".webp"}
        # Videos ride along with SP imports; they stay in the same target
        # folder but tucked into a "Videos" subfolder (user rule 2026-07-01)
        # so they don't clutter the photo set. Broad extension set so phone /
        # bodycam / drone clips aren't silently dropped.
        VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
                      ".3gp", ".3g2", ".mts", ".m2ts", ".wmv", ".mpg",
                      ".mpeg", ".hevc", ".flv"}
        MEDIA_EXTS = IMG_EXTS | VIDEO_EXTS
        existing = set()
        for root, _dirs, files in os.walk(pics_root):
            for f in files:
                if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                    existing.add(f.lower())

        # Walk source recursively — preserve subfolder structure
        # under target_dir. Techs sometimes pre-organize photos into
        # Kitchen/, Bathroom/, etc. Tk does the same at line 4051-4053.
        #
        # OneDrive cloud-only files: when a file is a placeholder
        # (FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS), shutil.copy2 will
        # transparently trigger a download — but the first read can
        # fail with PathNotFound if Windows hasn't fully hydrated the
        # placeholder yet. We do a deliberate 1-byte read first so
        # the file is on local disk before copy2 reads it. Mirrors
        # how the Tk SP copy + sp_sync_state.force_pull work.
        try:
            import sp_sync_state as _sss
        except Exception:
            _sss = None
        copied = 0; skipped = 0; errors = []; pulled = 0
        imported_originals = []
        for root, _dirs, files in os.walk(sp_path):
            rel_dir = os.path.relpath(root, sp_path)
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in MEDIA_EXTS:
                    continue
                is_video = ext in VIDEO_EXTS
                if f.lower() in existing:
                    skipped += 1
                    continue
                src = os.path.join(root, f)
                # Hydrate cloud-only placeholders first — silently
                # no-op for already-local files. Without this step
                # copy2 sometimes fails on never-opened SP files.
                if _sss is not None:
                    try:
                        if _sss.is_cloud_only(src):
                            with open(src, "rb") as fh:
                                fh.read(1)
                            pulled += 1
                    except Exception:
                        # Pull failed — record but still TRY the copy
                        # (copy2's read might hydrate anyway, or the
                        # error will surface there with a real msg).
                        pass
                if is_video:
                    # Same target folder, videos nested in a Videos subfolder.
                    dest_sub = os.path.join(target_dir, "Videos")
                else:
                    dest_sub = (target_dir if rel_dir in (".", "")
                                else os.path.join(target_dir, rel_dir))
                try:
                    os.makedirs(dest_sub, exist_ok=True)
                    # File-level collision: preserve the original name
                    # via " (2)", " (3)" suffix instead of overwriting.
                    # Mirrors Tk's run_audit_gui.py:4068-4072.
                    dst = os.path.join(dest_sub, f)
                    if os.path.exists(dst):
                        stem, ext = os.path.splitext(f)
                        k = 2
                        while os.path.exists(dst):
                            dst = os.path.join(dest_sub, f"{stem} ({k}){ext}")
                            k += 1
                    shutil.copy2(src, dst)
                    copied += 1
                    imported_originals.append(f)
                except Exception as ex:
                    errors.append(f"{f}: {ex}")
        # Nothing new landed (every SP image already existed in OD) →
        # don't leave an empty destination folder behind. Remove the
        # reserved target_dir (and the stage folder if WE just made it
        # and it's now empty too). (2026-06-17)
        if copied == 0:
            for _empty in (target_dir, stage_dest):
                try:
                    if (_empty and _empty != pics_root
                            and os.path.isdir(_empty)
                            and not os.listdir(_empty)):
                        os.rmdir(_empty)
                except OSError:
                    pass
            return {"ok": True, "copied": 0, "skipped": skipped,
                    "pulled": pulled, "errors": errors[:8],
                    "dest": target_dir, "folder_name": folder_name,
                    "tech": tech, "stage_routed": stage_dest != pics_root}
        # Stamp the target folder's mtime to match the SP source so it
        # sorts as "from that day" in Explorer, not "created today".
        # Mirrors run_audit_gui.py:4096-4097.
        try:
            src_mtime = os.path.getmtime(sp_path)
            os.utime(target_dir, (src_mtime, src_mtime))
        except OSError:
            pass
        # Convert any HEIC files that landed in the target to JPEG.
        try:
            from wc_zip_import import convert_heic_in_dir
            convert_heic_in_dir(target_dir)
        except Exception:
            pass
        # Record imported originals in the PICS manifest so future audits
        # don't re-flag them as "new on SP". Even though we preserved the
        # filenames, the manifest is the source of truth for "this file
        # has been imported" (mirrors Tk run_audit_gui.py:4107-4108).
        if imported_originals:
            try:
                _append_sp_manifest_originals(pics_root, imported_originals)
            except Exception:
                pass
        return {"ok": True, "copied": copied, "skipped": skipped,
                "pulled": pulled,
                "errors": errors[:8], "dest": target_dir,
                "folder_name": folder_name, "tech": tech,
                "stage_routed": stage_dest != pics_root,
                "side": (side or "ems").strip().lower()}

    # ── Archive month (SharePoint photo cleanup) ─────────────────────
    def archive_month_plan(self, year=None, month=None) -> dict:
        """Preview what would move into `<MonthName YYYY>` archive
        folders under each tech root. Read-only — `archive_month_apply`
        does the actual moves.

        Pywebview's JS-to-Python bridge has been observed to bundle
        positional args as a single list when one of them is typed
        `list`. Even though THIS method has only scalar args, the
        observed failure mode ("int() argument must be ... not
        'list'") matches that bundling. Unpacking defensively keeps
        the call working regardless of which dispatch path the bridge
        picks at runtime.
        """
        year, month, _ = _unpack_arg_bundle(year, month, None)
        try:
            from sharepoint import plan_month_archive
            plan = plan_month_archive(int(year), int(month)) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "plan": []}
        # Group by tech for the UI
        by_tech: dict[str, list] = {}
        for entry in plan:
            tech = entry.get("tech") or "Unknown"
            by_tech.setdefault(tech, []).append({
                "name": entry.get("name") or "",
                "src":  entry.get("src") or "",
                "dst":  entry.get("dst") or "",
            })
        groups = sorted(
            ({"tech": t, "folders": fs, "count": len(fs)}
             for t, fs in by_tech.items()),
            key=lambda g: g["tech"].lower())
        return {"ok": True, "groups": groups, "total": len(plan),
                "year": int(year), "month": int(month)}

    def archive_month_apply(self, year=None, month=None,
                              selected_srcs=None) -> dict:
        """Apply a previously-previewed plan. `selected_srcs` lets the
        UI pass a filtered subset of source paths; passing None moves
        everything in the (year, month) plan.

        Same defensive arg unpack as `archive_month_plan` — pywebview
        was delivering this 3-arg call with all args bundled into the
        first positional, which caused `int(year)` to fail with
        "int() argument must be ... not 'list'".
        """
        year, month, selected_srcs = _unpack_arg_bundle(
            year, month, selected_srcs)
        try:
            from sharepoint import (plan_month_archive,
                                     apply_month_archive)
            plan = plan_month_archive(int(year), int(month)) or []
            if selected_srcs:
                picked_set = set(selected_srcs)
                plan = [e for e in plan if e.get("src") in picked_set]
            if not plan:
                return {"ok": False, "error": "Nothing selected to move"}
            result = apply_month_archive(plan) or {}
            return {"ok": True, "moved": int(result.get("moved") or 0),
                    "errors": result.get("errors") or []}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Audit Export → PDF ────────────────────────────────────────────
    # ── Paperwork-request via Teams ─────────────────────────────────
    # Persistent default channel URL — the team's collect-paperwork
    # group chat. User set this 2026-05-29; if they want to route to a
    # different chat per-run, they can override via set_paperwork_chat_url.
    _DEFAULT_PAPERWORK_CHAT_URL = (
        "https://teams.microsoft.com/l/chat/"
        "19:6ecb503465074657a1d2b975579a47e3@thread.v2/conversations"
        "?context=%7B%22contextType%22%3A%22chat%22%7D"
    )

    def get_paperwork_chat_url(self) -> dict:
        """Return the saved paperwork-request chat URL (or the default)."""
        try:
            stored = persistence.get("paperwork_chat_url") or ""
        except Exception:
            stored = ""
        return {"ok": True, "url": stored or self._DEFAULT_PAPERWORK_CHAT_URL,
                "is_default": not stored}

    def set_paperwork_chat_url(self, url: str) -> dict:
        """Save the Teams chat URL the paperwork-request action opens.
        Pass empty string to reset to the built-in default."""
        try:
            persistence.set_value("paperwork_chat_url",
                                    (url or "").strip())
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def send_paperwork_request(self, client: str, tech: str,
                                  message: str = "") -> dict:
        """Open Teams in the saved paperwork-request group chat with
        the message pre-filled. The message @-mentions the tech by
        first/last name; that's the cue Teams uses to flip the chat
        title text into a name-prefixed message ready to send.

        Default message (matches the user's canonical wording):
            "{Tech name} Please collect paperwork for {client}, thank you"

        Caller can override via `message` — the modal exposes a
        textarea so the user can tweak per row.
        """
        if not client or not tech:
            return {"ok": False, "error": "client + tech required"}
        body = (message or
                f"{tech} Please collect paperwork for {client}, thank you")
        # Resolve the destination chat. Prefer the explicit group-chat
        # URL the user configured (e.g. a "Paperwork collection" group)
        # so every paperwork request lands in the same thread the team
        # is already monitoring. Falls back to a 1:1 chat with the
        # tech's email when no group URL is saved.
        chat_url = ""
        try:
            stored = persistence.get("paperwork_chat_url") or ""
            chat_url = stored or self._DEFAULT_PAPERWORK_CHAT_URL
        except Exception:
            chat_url = self._DEFAULT_PAPERWORK_CHAT_URL
        import urllib.parse as _up
        # Teams group-chat deeplinks: append `&message=…` to pre-fill
        # the compose box on chat open. Encode the body once.
        # Teams accepts both `?` and `&` separators on these URLs;
        # detect what the user pasted so we use the correct join.
        sep = "&" if "?" in chat_url else "?"
        url = chat_url + sep + "message=" + _up.quote(body)
        try:
            os.startfile(url)
            return {"ok": True, "tech": tech, "body": body, "url": url,
                    "chat": "group" if chat_url else "1:1"}
        except Exception as ex:
            # Fallback: if opening the group URL fails (e.g. Teams isn't
            # registered for the https URL scheme), try the 1:1 msteams://
            # deeplink with the tech's saved email.
            email = persistence.get_tech_email(tech) if tech else ""
            if email:
                try:
                    fb_url = (f"msteams:/l/chat/0/0?users={_up.quote(email)}"
                              f"&message={_up.quote(body)}")
                    os.startfile(fb_url)
                    return {"ok": True, "tech": tech, "body": body,
                            "url": fb_url, "chat": "1:1",
                            "fallback_used": True}
                except Exception:
                    pass
            return {"ok": False, "error": str(ex),
                    "tech": tech, "body": body, "url": url}

    def get_tech_email(self, tech: str) -> dict:
        """Look up the saved Teams email for one tech. Returns
        `{ok, email}` with `email=""` when nothing's saved yet."""
        try:
            return {"ok": True,
                    "email": persistence.get_tech_email(tech) or ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def set_tech_email(self, tech: str, email: str) -> dict:
        """Save a tech's Teams email. Empty `email` clears the entry."""
        if not tech:
            return {"ok": False, "error": "no tech"}
        try:
            persistence.set_tech_email(tech, email or "")
            return {"ok": True, "tech": tech, "email": (email or "").strip()}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def list_tech_emails(self) -> dict:
        """Return the full {tech: email} map for the editor dialog."""
        try:
            return {"ok": True, "emails": persistence.get_tech_emails() or {}}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "emails": {}}

    def list_techs(self) -> dict:
        """Roster of tech names for the import tech-picker (CompanyCam
        photos carry no photographer, so the user picks who shot them).
        Merges the configured roster + anyone with a saved Teams email."""
        names = []
        try:
            ut = persistence.get_user_techs() or {}
            names += list(ut.get("names") or [])
        except Exception:
            pass
        try:
            names += list((persistence.get_tech_emails() or {}).keys())
        except Exception:
            pass
        seen, out = set(), []
        for n in names:
            n = (n or "").strip()
            k = n.lower()
            if n and k not in seen:
                seen.add(k)
                out.append(n)
        out.sort(key=str.lower)
        return {"ok": True, "techs": out}

    def parse_trello_url(self, text: str) -> dict:
        """Detect + parse a Trello URL from arbitrary pasted text.
        Returns `{ok, card_id, name, lane, board, short_url}` or
        `{ok: False, error}`. Used by paste handlers everywhere —
        text inputs that detect a Trello link auto-fetch + offer
        to pin the card."""
        if not text or not isinstance(text, str):
            return {"ok": False, "error": "no text"}
        import re as _re
        # trello.com/c/<id-or-shortlink>/<slug?> — accept full or
        # shortlink form, with/without trailing slug.
        m = _re.search(r"trello\.com/c/([A-Za-z0-9]+)(?:/|\?|#|$)", text)
        if not m:
            return {"ok": False, "error": "no Trello URL found"}
        short = m.group(1)
        try:
            import trello_client as tc
            card = tc.get_card(short, actions_limit=0) or {}
            if not card:
                return {"ok": False, "error": "card not found"}
            return {
                "ok":         True,
                "card_id":    card.get("id") or short,
                "name":       card.get("name") or "",
                "lane":       (card.get("idList") and
                                tc._call(f"/lists/{card.get('idList')}",
                                          params={"fields": "name"}) or {})
                               .get("name", ""),
                "board":      "",
                "short_url":  card.get("shortUrl") or f"https://trello.com/c/{short}",
            }
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def client_memory(self, client: str) -> dict:
        """All sticky per-client state in one payload — folder pin,
        Trello card pins, commercial flag, search aliases, day-units,
        property group membership. Used by the "Memory" right-click
        item / Property Structure dialog so the user can see + edit
        every setting from one place instead of digging through five
        different right-click items."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            folder_pin = persistence.get_folder_path(client) or ""
        except Exception:
            folder_pin = ""
        try:
            trello_pin = persistence.get_trello_card_id(client) or ""
        except Exception:
            trello_pin = ""
        try:
            trello_pins_all = list(persistence.get_trello_card_ids(client) or [])
        except Exception:
            trello_pins_all = []
        try:
            is_comm = bool(persistence.is_commercial(client))
        except Exception:
            is_comm = False
        try:
            aliases = list(persistence.get_search_aliases(client) or [])
        except Exception:
            aliases = []
        try:
            day_units = list(persistence.get_run_day_units(
                _dt.date.today(), client) or [])
        except Exception:
            day_units = []
        property_group = ""
        try:
            grp = persistence.find_property_group_for(client) \
                if hasattr(persistence, "find_property_group_for") else ""
            property_group = grp or ""
        except Exception:
            pass
        return {
            "ok":              True,
            "client":          client,
            "folder_pin":      folder_pin,
            "folder_exists":   bool(folder_pin and os.path.isdir(folder_pin)),
            "trello_pin":      trello_pin,
            "trello_pins_all": trello_pins_all,
            "is_commercial":   is_comm,
            "aliases":         aliases,
            "day_units":       day_units,
            "property_group":  property_group,
        }

    def day_summary_markdown(self) -> dict:
        """Render today's audit results as a copy-ready Markdown
        snippet for the EOD message thread. Lightweight: just reads
        `_last_rows` so it's instant + no Trello round-trip.

        Returns `{ok, markdown, total, flagged, ok_count}`. Frontend
        copies `markdown` to clipboard via navigator.clipboard.
        """
        try:
            rows = list(self._last_rows or [])
        except Exception:
            rows = []
        meta = getattr(self, "_last_meta", {}) or {}
        date_iso = meta.get("date_iso") or _dt.date.today().strftime("%Y-%m-%d")
        flagged = [r for r in rows if r.get("flagged")]
        ok_rows = [r for r in rows if not r.get("flagged")]

        def _bullet(r):
            client = r.get("client") or ""
            unit = r.get("unit_folder") or r.get("unit") or ""
            unit_str = f" — {unit}" if unit else ""
            forms = list(r.get("form_issues") or [])
            photos = list(r.get("photo_issues") or [])
            missing = forms + photos
            if missing:
                tail = ", ".join(missing[:5])
                if len(missing) > 5:
                    tail += f" +{len(missing) - 5} more"
                return f"- **{client}**{unit_str} — missing: {tail}"
            return f"- {client}{unit_str}"

        lines = [
            f"# EMS Audit — {date_iso}",
            f"_{len(rows)} jobs · {len(flagged)} flagged · {len(ok_rows)} OK_",
            "",
        ]
        if flagged:
            lines.append("## 🚩 Flagged")
            lines.extend(_bullet(r) for r in flagged)
            lines.append("")
        if ok_rows:
            lines.append("## ✓ Clean")
            lines.extend(_bullet(r) for r in ok_rows)
        markdown = "\n".join(lines).rstrip() + "\n"
        return {
            "ok":        True,
            "markdown":  markdown,
            "total":     len(rows),
            "flagged":   len(flagged),
            "ok_count":  len(ok_rows),
            "date_iso":  date_iso,
        }

    def export_audit_pdf(self, scope: str = "all") -> dict:
        """Generate the daily-audit PDF for the current `_last_rows`.

        `scope` ∈ {"all", "flagged"}. Returns the PDF path on success;
        opens it via os.startfile if the caller hasn't already.
        Uses audit_export._build_pdf so output is identical to the Tk
        export dialog.
        """
        rows = list(self._last_rows or [])
        if scope == "flagged":
            rows = [r for r in rows if r.get("flagged")]
        if not rows:
            return {"ok": False,
                    "error": "Nothing to export — run an audit first"}
        try:
            import audit_export
        except Exception as ex:
            return {"ok": False, "error": f"audit_export import: {ex}"}
        try:
            import paths
            out_dir = os.path.join(paths.DATA_DIR, "audit_exports")
        except Exception:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(out_dir, exist_ok=True)
        run_date = (self._last_meta or {}).get("date_iso") \
            or _dt.date.today().strftime("%Y-%m-%d")
        safe_label = f"{run_date}_{scope}"
        out_path = os.path.join(out_dir, f"audit_{safe_label}.pdf")
        try:
            audit_export._build_pdf(rows, run_date, out_path)
        except Exception as ex:
            return {"ok": False, "error": f"PDF build: {ex}"}
        try: os.startfile(out_path)
        except Exception: pass
        return {"ok": True, "path": out_path,
                "rows": len(rows), "scope": scope}

    def close_backlog_row(self, client: str) -> dict:
        """Mark a backlog row as manually closed. Writes a record to
        persistence so future loads filter it out. The job stays in
        the audit_export backlog file (which is the raw daily-audit
        log) but the web view honors the closed-list."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            closed = persistence.get("backlog_closed") or {}
            if not isinstance(closed, dict): closed = {}
            closed[client.strip()] = _dt.datetime.now().isoformat(timespec="seconds")
            persistence.set_value("backlog_closed", closed)
            # Drop from the in-memory rows
            self._last_rows = [r for r in self._last_rows
                               if r.get("client") != client]
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def reopen_backlog_row(self, client: str) -> dict:
        try:
            closed = persistence.get("backlog_closed") or {}
            if isinstance(closed, dict) and client in closed:
                del closed[client]
                persistence.set_value("backlog_closed", closed)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def check_backlog_auto_close(self) -> dict:
        """Walk every backlog row, check the pinned Trello card's
        list name; if the card is now in an 'EMS LOG' lane, auto-mark
        the row closed. Returns the list of auto-closed clients so
        the UI can show a toast."""
        try:
            data = self.list_backlog()
            rows = data.get("rows") or []
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        try:
            import trello_client as tc
        except Exception:
            return {"ok": False, "error": "trello_client unavailable"}
        auto_closed = []
        for r in rows:
            client = r.get("client") or ""
            card_id = r.get("trello_card_id") or ""
            if not client or not card_id:
                continue
            try:
                card = tc.get_card(card_id, actions_limit=1)
                if not card: continue
                list_id = card.get("idList") or ""
                board_id = card.get("idBoard") or ""
                lane_name = tc.get_lane_name(board_id, list_id) or ""
                if "EMS LOG" in (lane_name or "").upper() or "EMS_LOG" in (lane_name or "").upper():
                    self.close_backlog_row(client)
                    auto_closed.append({"client": client, "lane": lane_name})
            except Exception:
                continue
        return {"ok": True, "auto_closed": auto_closed}

    def toggle_starred_client(self, client="") -> dict:
        """Flip a client's starred state. Persists across days so the
        ⭐ Starred mode (and the per-row star icon) keep tracking this
        client regardless of whether they're on today's run-doc.
        Canon-keyed under the hood so the star follows the client even
        when their name appears in different forms across panels.

        Returns the new `starred` boolean so the JS doesn't need a
        round-trip to know which icon to render.
        """
        if isinstance(client, (list, tuple)) and client:
            client = client[0]
        client = str(client or "").strip()
        if not client:
            return {"ok": False, "error": "client required"}
        try:
            new_state = not persistence.is_starred(client)
            persistence.set_starred(client, new_state)
            return {"ok": True, "client": client,
                    "starred": bool(new_state)}
        except Exception as ex:
            return {"ok": False,
                    "error": f"{type(ex).__name__}: {ex}"}

    def get_starred_clients(self) -> list:
        """Return a list of currently-starred client names lowercased
        — what the JS state.starred_clients tracks for the row-render
        ★/☆ check (case-insensitive `.includes`).
        """
        try:
            return [c.lower()
                    for c in (persistence.get_starred_clients() or [])
                    if c]
        except Exception:
            return []

    def list_starred(self) -> dict:
        """Audit every currently-starred client and return rows in the
        same shape Daily Run / Backlog use. Starred clients survive
        across days — this mode shows them all in one place regardless
        of whether they're on today's run-doc.

        Empties cleanly when no stars exist so the JS can render a
        helpful empty state.
        """
        try:
            starred = persistence.get_starred_clients() or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}
        if not starred:
            return {"ok": True, "rows": [], "total": 0,
                    "empty_reason": "No starred clients yet — click "
                                    "the ☆ on any audit row to follow."}
        try:
            results, err = audit_jobs(
                [c for c in starred if c],
                use_cache=True)
            if err:
                return {"ok": False, "error": err, "rows": []}
        except Exception as ex:
            return {"ok": False,
                    "error": f"{type(ex).__name__}: {ex}", "rows": []}
        rows = []
        for client, r in zip(starred, results or []):
            j = {"client": client, "section": "starred",
                 "raw": "", "techs": [], "new_loss": False}
            try:
                pin = persistence.get_trello_card_id(client) or ""
            except Exception:
                pin = ""
            shaped = _shape_job(j, r or {}, pin)
            shaped["section"] = "starred"
            shaped["is_starred"] = True
            rows.append(shaped)
        return {"ok": True, "rows": rows, "total": len(rows)}

    def list_backlog(self) -> dict:
        """Persisted backlog of flagged jobs from prior days. Mirrors
        the Tk Backlog tab. Reads from audit_export's persisted store.
        Filters out rows the user has manually marked closed (via the
        Closed button) by reading the `backlog_closed` persistence
        map."""
        try:
            import audit_export as _ae
            data = _ae.load_audit_backlog() or {}
            jobs = data.get("jobs") or []
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        try:
            closed = persistence.get("backlog_closed") or {}
            if not isinstance(closed, dict): closed = {}
        except Exception:
            closed = {}
        rows = []
        for j in jobs:
            if (j.get("client") or "") in closed:
                continue
            rows.append({
                "client":         j.get("client", ""),
                "techs":          j.get("techs") or [],
                "path":           j.get("path", ""),
                "folder":         j.get("folder") or j.get("path", "").split("\\")[-1],
                "found":          bool(j.get("found", True)),
                "form_issues":    list(j.get("form_issues") or []),
                "photo_issues":   list(j.get("photo_issues") or []),
                "aging_days":     int(j.get("aging") or j.get("aging_days") or 0),
                "last_seen":      str(j.get("last_audited") or ""),
                "flagged":        (j.get("status") or "").upper() == "FLAG",
                "section":        "backlog",
                "activity":       list(j.get("activity") or []),
                "new_loss":       bool(j.get("new_loss")),
                "trello_card_id": j.get("card_id") or "",
                "is_commercial":  bool(j.get("is_commercial")),
                "any_issue":      bool(j.get("form_issues") or j.get("photo_issues")),
                "total_missing":  len(j.get("form_issues") or []) + len(j.get("photo_issues") or []),
                "audit_count":    int(j.get("audit_count") or 0),
            })
        return {"ok": True, "rows": rows, "total": len(rows)}

    # ── P0: Find / Change folder (manual override) ──────────────────
    def list_year_folders(self) -> dict:
        """Enumerate every year-style top-level folder under audit_base.
        Surfaces both regular year folders (e.g. '2026 Jobs', '2025 Jobs')
        AND the LA fire-job folders (e.g. '2026 LA Fire Jobs') so the
        Find Folder dialog can filter to a specific scope when a job
        spans years or is a fire-job."""
        try:
            import config as _cfg
            audit_base = (_cfg.load() or {}).get("audit_base") or ""
        except Exception:
            audit_base = ""
        if not audit_base or not os.path.isdir(audit_base):
            return {"ok": False, "error": "audit_base not configured",
                    "folders": []}
        import re as _re
        out = []
        try:
            for entry in os.listdir(audit_base):
                p = os.path.join(audit_base, entry)
                if not os.path.isdir(p):
                    continue
                m = _re.search(r"\b(20\d{2})\b", entry)
                if not m:
                    continue
                up = entry.upper()
                is_fire = ("FIRE" in up)
                out.append({
                    "name":    entry,
                    "path":    p,
                    "year":    m.group(1),
                    "is_fire": is_fire,
                })
        except OSError as ex:
            return {"ok": False, "error": str(ex), "folders": []}
        # Newest year first; fire folders last within the same year so
        # the default scope is the regular year folder.
        out.sort(key=lambda f: (-int(f["year"]), f["is_fire"], f["name"].lower()))
        return {"ok": True, "folders": out}

    def list_subfolders(self, path: str) -> dict:
        """List the immediate subfolders of `path`.

        Lets the Find / Change Folder dialog drill INTO a folder and pin
        a specific SUB-folder — a commercial parent's campus (Menifee →
        Kirkpatrick Elementary), a multi-unit property's Unit folder, a
        multi-claim job's '2nd Claim' folder, etc. — instead of being
        stuck picking the top-level job folder. Returns each child dir's
        name + full path; the frontend keeps its own breadcrumb stack
        for 'up' navigation.
        """
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": "folder not found",
                    "subfolders": []}
        out = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            out.append({"name": e.name, "path": e.path})
                    except OSError:
                        continue
        except OSError as ex:
            return {"ok": False, "error": str(ex), "subfolders": []}
        out.sort(key=lambda d: d["name"].lower())
        return {"ok": True, "path": path,
                "name": os.path.basename(path.rstrip(os.sep)),
                "subfolders": out}

    def list_folder_candidates(self, client: str, year: str = "") -> dict:
        """List job folders under one or more year-style folders that
        could match `client`. Used by the Find Folder dialog when audit
        couldn't auto-resolve a folder.

        `year` semantics:
          • ""        → current year (default behavior, same as before)
          • "2025"    → only the '2025 …' folder
          • "all"     → walk every year folder INCLUDING fire-job folders
          • "fire"    → only LA fire-job folders (any year)
          • "<full folder name>" → that exact top-level folder

        Each candidate carries the year-folder it came from so the
        Find dialog can show 'Apr 2025 · Smith Fire Job' style labels.
        """
        try:
            import config as _cfg
            audit_base = (_cfg.load() or {}).get("audit_base") or ""
        except Exception:
            audit_base = ""
        if not audit_base or not os.path.isdir(audit_base):
            return {"ok": False, "error": "audit_base not configured"}

        # Build the list of year folders to scan based on `year`.
        try:
            yr_payload = self.list_year_folders()
            all_folders = yr_payload.get("folders") or []
        except Exception:
            all_folders = []

        scope = (year or "").strip().lower()
        if not scope:
            # Default = current year (mirrors prior behavior)
            cur = _dt.date.today().strftime("%Y")
            scan = [f for f in all_folders
                    if f["year"] == cur and not f["is_fire"]]
        elif scope == "all":
            scan = list(all_folders)
        elif scope == "fire":
            scan = [f for f in all_folders if f["is_fire"]]
        elif scope.isdigit():
            scan = [f for f in all_folders
                    if f["year"] == scope and not f["is_fire"]]
        else:
            # Treat as a full folder name (case-insensitive)
            scan = [f for f in all_folders
                    if f["name"].lower() == scope]

        if not scan:
            return {"ok": False,
                    "error": f"no folder matches scope '{year or 'current year'}'"}

        from web_helpers import norm_name as _norm, norm_tokens as _norm_tokens
        canon = _norm(client or "")
        canon_tokens = list(_norm_tokens(client or ""))

        candidates = []
        for yf in scan:
            year_folder = yf["path"]
            try:
                with os.scandir(year_folder) as it:
                    for e in it:
                        if not e.is_dir(follow_symlinks=False):
                            continue
                        fn = _norm(e.name)
                        tokens = [t for t in fn.split() if len(t) >= 2]
                        overlap = len(set(canon_tokens) & set(tokens))
                        substr = (canon in fn or (len(fn) >= 4 and fn in canon))
                        score = overlap + (3 if substr else 0)
                        candidates.append({
                            "name":         e.name,
                            "path":         e.path,
                            "score":        score,
                            "year":         yf["year"],
                            "year_folder":  yf["name"],
                            "is_fire":      yf["is_fire"],
                        })
            except OSError:
                continue

        # Sort by score desc, then newer year first, then alphabetical.
        candidates.sort(key=lambda c: (-c["score"], -int(c["year"] or 0),
                                        c["name"].lower()))
        return {"ok": True,
                "year": year or _dt.date.today().strftime("%Y"),
                "scope": scope or "current",
                "year_folders": [f["name"] for f in scan],
                "candidates": candidates}

    def set_folder_path(self, client: str, path: str) -> dict:
        """Persist a sticky folder override for `client`. Used when
        the user picks from the Find Folder dialog OR overrides an
        auto-resolved folder via the right-click 'Change folder'."""
        if not client or not path:
            return {"ok": False, "error": "client + path required"}
        if not os.path.isdir(path):
            return {"ok": False, "error": "path doesn't exist"}
        try:
            persistence.set_folder_path(client, path)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Update the cached row's path in BOTH caches. Multi-unit jobs
        # (two rows with the same client name but different units) need
        # extra care: if the pinned path encodes a specific unit AND
        # only ONE row's unit matches that path's unit token, update
        # ONLY that row. Otherwise (single-unit job, or pin is the
        # umbrella) update every matching row as before. Without this
        # check, pinning the Unit 1413 folder for the 1413 row would
        # clobber the 1416 row's path with the 1413 folder too — and
        # the displayed unit label would flip to 1413 for both rows.
        import re as _re
        base = os.path.basename((path or "").rstrip(os.sep))
        pinned_unit_m = _re.search(
            r"\b(?:unit|apt\.?|suite)\s*#?\s*(\w{1,5})\b|#\s*(\w{1,5})\b",
            base, _re.IGNORECASE)
        pinned_unit = ""
        if pinned_unit_m:
            pinned_unit = (pinned_unit_m.group(1) or pinned_unit_m.group(2)
                           or "").strip()
        for r in (self._last_rows + self._oneoff_rows):
            if r.get("client") != client:
                continue
            row_unit = str(r.get("unit") or "").strip()
            # Skip rows whose unit conflicts with the pinned path's unit.
            if pinned_unit and row_unit and pinned_unit.lower() != row_unit.lower():
                continue
            r["path"] = path
            r["folder"] = os.path.basename(path)
            r["found"] = True
        return {"ok": True, "path": path,
                "pinned_unit": pinned_unit or ""}

    def clear_folder_path(self, client: str) -> dict:
        """Drop the sticky override so audit re-auto-resolves."""
        if not client:
            return {"ok": False}
        try:
            persistence.set_folder_path(client, "")
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True}

    # ── Search aliases (mirrors Tk job_widgets context menu) ────────
    def get_search_aliases(self, client: str) -> list:
        """Return the per-client search aliases. Used by audit / SP
        folder matching to find folders whose names don't match the
        canonical client string. Mirrors Tk's 'Edit search aliases…'
        right-click menu item."""
        if not client:
            return []
        try:
            return list(persistence.get_search_aliases(client) or [])
        except Exception:
            return []

    def set_search_aliases(self, client: str, aliases) -> dict:
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            clean = [a.strip() for a in (aliases or []) if a and a.strip()]
            persistence.set_search_aliases(client, clean)
            return {"ok": True, "aliases": clean}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Property groups (multi-unit / multi-building umbrella) ──────
    def list_property_groups(self) -> dict:
        """Return every known property group + the folders in each.
        Used by the right-click 'Add to property…' submenu to let
        the user park a job under a multi-unit umbrella."""
        try:
            groups = persistence.get_property_groups() or {}
            out = []
            for name in sorted(groups.keys(), key=str.lower):
                out.append({
                    "name":    name,
                    "folders": list(groups.get(name) or []),
                })
            return {"ok": True, "groups": out}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "groups": []}

    def find_property_for_folder(self, folder_basename: str) -> str:
        """Return the property group name that contains `folder_basename`,
        or '' if it's not in one. Used by the right-click menu to
        decide whether to show 'Add to property…' or 'Remove from
        property X'."""
        if not folder_basename:
            return ""
        try:
            return persistence.find_property_for_folder(folder_basename) or ""
        except Exception:
            return ""

    def add_folder_to_property_group(self, group_name: str,
                                     folder_basename: str) -> dict:
        if not group_name or not folder_basename:
            return {"ok": False, "error": "group + folder required"}
        try:
            persistence.add_folder_to_property_group(group_name, folder_basename)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def remove_folder_from_property_group(self, group_name: str,
                                          folder_basename: str) -> dict:
        if not group_name or not folder_basename:
            return {"ok": False, "error": "group + folder required"}
        try:
            persistence.remove_folder_from_property_group(group_name, folder_basename)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def create_property_group(self, group_name: str,
                              folder_basename: str = "") -> dict:
        """Create a new property group + optionally add `folder_basename`
        to it. Mirrors Tk's '+ New property…' submenu item."""
        if not group_name or not group_name.strip():
            return {"ok": False, "error": "group name required"}
        try:
            # persistence.add_folder_to_property_group auto-creates the
            # group when it doesn't exist; "no folder" path uses a
            # placeholder add+remove to materialize the empty group.
            if folder_basename:
                persistence.add_folder_to_property_group(group_name.strip(),
                                                          folder_basename)
            else:
                persistence.add_folder_to_property_group(group_name.strip(),
                                                          "__placeholder__")
                persistence.remove_folder_from_property_group(group_name.strip(),
                                                               "__placeholder__")
            return {"ok": True, "name": group_name.strip()}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── 📎 Trello photo attachments manager ────────────────────────
    # Lists every attachment on a Trello card + lets the user pull
    # the image ones into the job's OD folder. Surfaces from audit /
    # snapshot / IUQ right-click menus.
    def list_card_attachments(self, card_id: str) -> dict:
        """Return every attachment on `card_id` with name / url /
        date / mime / size + an `is_image` flag derived from
        mimeType or extension. Used by the 📎 Trello photos modal."""
        if not card_id:
            return {"ok": False, "error": "card_id required",
                    "attachments": []}
        try:
            import trello_client as tc
            # Direct /attachments endpoint — returns full field set
            # (mimeType, bytes, previews) not just the trimmed view
            # get_card returns.
            raw = tc._call(f"/cards/{card_id}/attachments",
                            params={"fields": "name,url,date,isUpload,mimeType,bytes,previews"})
        except Exception as ex:
            return {"ok": False, "error": str(ex), "attachments": []}
        out = []
        _IMG_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif", ".webp",
                     ".bmp", ".tif", ".tiff", ".gif",
                     ".mp4", ".mov", ".m4v", ".avi"}
        for a in (raw or []):
            name = (a.get("name") or "").strip()
            url  = (a.get("url")  or "").strip()
            mime = (a.get("mimeType") or "").strip().lower()
            ext  = os.path.splitext(name or url.rsplit("/", 1)[-1])[1].lower()
            is_image = (mime.startswith("image/") or mime.startswith("video/")
                        or ext in _IMG_EXTS)
            # Smallest preview URL for thumbnail rendering (Trello
            # serves 70/150/256/480/960/1280px scales). Pick the
            # smallest >= 150 so the modal renders quickly.
            preview = ""
            for p in (a.get("previews") or []):
                if p.get("width", 0) >= 150:
                    preview = p.get("url") or ""
                    break
            out.append({
                "id":         a.get("id") or "",
                "name":       name or os.path.basename(url) or "(unnamed)",
                "url":        url,
                "date":       a.get("date") or "",
                "mime":       mime,
                "is_image":   is_image,
                "is_upload":  bool(a.get("isUpload")),
                "size":       int(a.get("bytes") or 0),
                "preview":    preview,
            })
        # Newest first so the most recent photos float to the top
        out.sort(key=lambda a: a.get("date") or "", reverse=True)
        n_img = sum(1 for a in out if a["is_image"])
        return {"ok": True, "attachments": out,
                "total": len(out), "image_count": n_img}

    def fetch_trello_image(self, url: str,
                           max_bytes: int = 6_000_000) -> dict:
        """Download a Trello-hosted image (a preview or attachment URL)
        with the OAuth header Trello requires, and return it as a base64
        `data:` URI the webview <img> can render inline. A raw Trello
        preview URL 401s without auth — that's why the 📎 modal showed
        blank thumbnails. Locked to Trello/S3 hosts so it can't be used
        as a generic fetch proxy. {ok, data_uri} or {ok: False, error}.
        """
        if not url:
            return {"ok": False, "error": "no url"}
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if not (host == "trello.com" or host.endswith(".trello.com")
                or host.endswith(".trellocdn.com")
                or host.endswith(".amazonaws.com")):
            return {"ok": False, "error": f"host not allowed: {host}"}
        import urllib.request as _req
        import base64 as _b64
        try:
            import trello_client as tc
            key, tok = tc._creds()
        except Exception:
            key, tok = "", ""
        headers = {"User-Agent": "EMS-Tools/1.0"}
        if key and tok:
            headers["Authorization"] = (f'OAuth oauth_consumer_key="{key}", '
                                        f'oauth_token="{tok}"')
        try:
            with _req.urlopen(_req.Request(url, headers=headers),
                              timeout=20) as resp:
                data = resp.read(max_bytes + 1)
                ctype = (resp.headers.get("Content-Type")
                         or "image/jpeg").split(";")[0].strip()
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if len(data) > max_bytes:
            return {"ok": False, "error": "image too large"}
        b64 = _b64.b64encode(data).decode("ascii")
        return {"ok": True, "data_uri": f"data:{ctype};base64,{b64}"}

    def download_card_attachments(self, card_id: str,
                                  attachment_ids,
                                  client: str = "") -> dict:
        """Download selected Trello attachments into the job's PICS
        folder. Lands them under `Trello attachments/<Uploader>
        <MM-DD-YYYY>/` so a card touched by several techs across several
        days sorts itself by WHO uploaded each photo and WHEN — instead
        of one flat dump — and never mingles with audit-tracked stages.
        Falls back to Downloads when no OD folder is pinned for `client`.

        Auth: re-uses trello_client's API key + token. Returns the
        list of files saved with their on-disk paths.
        """
        if not card_id:
            return {"ok": False, "error": "card_id required"}
        ids = list(attachment_ids or [])
        if not ids:
            return {"ok": False, "error": "no attachments selected"}
        # Resolve target folder.
        target = ""
        if client:
            try:
                job = persistence.get_folder_path(client) or ""
                if job and os.path.isdir(job):
                    pics = os.path.join(job, "EMS", "PICS")
                    if not os.path.isdir(pics):
                        pics = os.path.join(job, "PICS")
                    target = os.path.join(pics, "Trello attachments")
            except Exception:
                target = ""
        if not target:
            target = os.path.join(os.path.expanduser("~"),
                                    "Downloads",
                                    f"Trello attachments — {client or card_id}")
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as ex:
            return {"ok": False, "error": f"mkdir: {ex}"}

        # Fetch full attachment list so we can match ids → URLs.
        info = self.list_card_attachments(card_id)
        if not info.get("ok"):
            return info
        by_id = {a["id"]: a for a in (info.get("attachments") or [])}

        import urllib.request as _req, urllib.error as _err
        from datetime import datetime as _dtm
        try:
            import trello_client as tc
            api_key, api_tok = tc._creds()
        except Exception:
            api_key, api_tok = "", ""
        # {attachment_id: uploader_full_name} for the per-uploader subfolder.
        try:
            uploaders = tc._attachment_uploaders(card_id)
        except Exception:
            uploaders = {}

        try:
            import audit_logic as _al
        except Exception:
            _al = None

        def _subfolder_for(att, att_id):
            """"<Tech> <MM-DD-YYYY>" — who attached the photo and when.
            The uploader's Trello name is mapped to roster initials
            (Fernando → FB, Mark Escobar → ME, …) so folders match the
            short tech codes the user works in; falls back to the raw
            name when no roster tech is recognized."""
            raw_who = uploaders.get(att_id) or ""
            who = ""
            if _al and raw_who:
                try:
                    who = _al.initials_for_name(raw_who)
                except Exception:
                    who = ""
            who = who or raw_who or "Unknown"
            raw = att.get("date") or ""
            try:
                when = _dtm.strptime(
                    raw[:10], "%Y-%m-%d").strftime("%m-%d-%Y")
            except Exception:
                when = raw[:10] or "no-date"
            return tc._tc_sanitize(f"{who} {when}", fallback="Unknown")

        downloaded = []
        failed = []
        for aid in ids:
            a = by_id.get(aid)
            if not a:
                failed.append({"id": aid, "error": "not found on card"})
                continue
            url = a.get("url") or ""
            if not url:
                failed.append({"id": aid, "error": "no url"})
                continue
            # Trello-uploaded attachments require an OAuth Authorization
            # header. External-link attachments (URL pasted, not
            # uploaded) work plain. Try authed first when we have
            # creds — Trello ignores the header on public URLs.
            auth_hdr = (f'OAuth oauth_consumer_key="{api_key}", '
                        f'oauth_token="{api_tok}"') if api_key and api_tok else ""
            req = _req.Request(url, headers={
                "User-Agent": "EMS-Tools/1.0",
                **({"Authorization": auth_hdr} if auth_hdr else {}),
            })
            # Route into a "<Uploader> <date>" subfolder, collision-safe.
            file_dir = os.path.join(target, _subfolder_for(a, aid))
            try:
                os.makedirs(file_dir, exist_ok=True)
            except OSError:
                file_dir = target
            base = a.get("name") or os.path.basename(url) or aid
            dest = os.path.join(file_dir, base)
            i = 2
            stem, ext = os.path.splitext(base)
            while os.path.isfile(dest):
                dest = os.path.join(file_dir, f"{stem}_{i}{ext}")
                i += 1
            try:
                with _req.urlopen(req, timeout=30) as resp, \
                        open(dest, "wb") as fh:
                    fh.write(resp.read())
                downloaded.append({"id": aid, "path": dest,
                                   "name": os.path.basename(dest)})
            except _err.HTTPError as ex:
                failed.append({"id": aid,
                               "error": f"HTTP {ex.code} on {url}"})
            except Exception as ex:
                failed.append({"id": aid, "error": str(ex)})

        # Open the destination folder so the user can immediately
        # eyeball what landed.
        if downloaded:
            try: os.startfile(target)
            except Exception: pass

        return {"ok": True,
                "downloaded": downloaded,
                "failed": failed,
                "target": target,
                "downloaded_count": len(downloaded),
                "failed_count": len(failed)}

    # ── 📋 Copy PICS folder to clipboard (for XA / Xactimate upload) ──
    # User stages a Ctrl+V into XactAnalysis or Xactimate. Resolves
    # the client's job folder, then walks EMS/PICS/<stage>/ for image
    # files and places them on the Windows clipboard via CF_HDROP.
    def list_pics_stages(self, client: str) -> dict:
        """List every PICS/<subfolder> for the client that has at
        least one image. Used by the frontend to populate a stage
        picker — most jobs have multiple (Initial, Demo, Mold Prep,
        Post, etc.) so we let the user pick which one to copy."""
        if not client:
            return {"ok": False, "error": "no client", "stages": []}
        try:
            job_path = persistence.get_folder_path(client) or ""
            if not job_path or not os.path.isdir(job_path):
                return {"ok": False, "error": "no folder pinned",
                        "stages": []}
            import clipboard_files as _cf
            pics_root = os.path.join(job_path, "EMS", "PICS")
            if not os.path.isdir(pics_root):
                # Some jobs store directly in PICS/ at job root
                pics_root = os.path.join(job_path, "PICS")
            stages = []
            if os.path.isdir(pics_root):
                try:
                    with os.scandir(pics_root) as it:
                        for e in it:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                            imgs = _cf.list_image_files(e.path)
                            if imgs:
                                stages.append({
                                    "name":  e.name,
                                    "path":  e.path,
                                    "count": len(imgs),
                                })
                except OSError:
                    pass
                # Also surface PICS root itself when it has direct
                # images (no subfolder).
                root_imgs = _cf.list_image_files(pics_root)
                if root_imgs:
                    stages.insert(0, {
                        "name":  "(root)",
                        "path":  pics_root,
                        "count": len(root_imgs),
                    })
            stages.sort(key=lambda s: s["name"].lower())
            return {"ok": True, "stages": stages,
                    "pics_root": pics_root,
                    "job_path": job_path}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "stages": []}

    def copy_pics_to_clipboard(self, client: str, stage: str = "") -> dict:
        """Stage every image in `<job>/EMS/PICS/<stage>/` into a
        TEMP folder + open the folder in Explorer so the user can
        drag-and-drop into XactAnalysis / Xactimate.

        XA doesn't accept CF_HDROP clipboard pastes — it only
        responds to a real drag-from-Explorer gesture. So we copy
        (or hardlink) the matched images into a per-stage temp
        folder, pop Explorer on it, and auto-delete after 5 min.

        Stage matching is fuzzy + case-insensitive:
          • exact match (preferred): "Initial" → "Initial"
          • prefix match:            "Initial" → "Initial Inspection"
          • substring match:         "Initial" → "Initial - JG"
        Files are walked recursively so nested tech/date subfolders
        (PICS/Initial/JG/photo.jpg) are included. Empty stage copies
        the PICS root.

        Name kept as `copy_pics_to_clipboard` for frontend
        compatibility — the behavior just changed under it.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import clipboard_files as _cf
            stages_info = self.list_pics_stages(client)
            if not stages_info.get("ok"):
                return stages_info
            wanted = (stage or "(root)").strip().lower()
            avail = stages_info.get("stages") or []
            # Three-tier match: exact → prefix → substring. Pick the
            # FIRST match so the user gets predictable results.
            target = ""
            for s in avail:
                if s["name"].lower() == wanted:
                    target = s["path"]; break
            if not target:
                for s in avail:
                    if s["name"].lower().startswith(wanted):
                        target = s["path"]; break
            if not target:
                for s in avail:
                    if wanted in s["name"].lower():
                        target = s["path"]; break
            if not target and stage:
                # Last resort — build the path manually under PICS root
                # (handles the case where the folder exists but has no
                # images yet so list_pics_stages didn't list it).
                target = os.path.join(stages_info.get("pics_root") or "",
                                       stage)
            if not target or not os.path.isdir(target):
                # Helpful error — surface what stages ARE available so
                # the frontend can suggest one.
                names = [s["name"] for s in avail]
                return {"ok": False,
                        "error": f"no PICS subfolder matching '{stage}'. "
                                 f"Available: {', '.join(names) or '(none)'}",
                        "available": names}
            # Recursive — handles PICS/Initial/<Tech>/<photos>.jpg layouts
            paths = _cf.list_image_files(target, recursive=True)
            if not paths:
                return {"ok": False,
                        "error": f"no images under {os.path.basename(target)}/ "
                                 f"(walked recursively)",
                        "folder": target}
            # Stage into a temp folder + open Explorer. User drags
            # from there into XA. Auto-deletes after 5 min.
            label = f"{client}_{os.path.basename(target)}"
            res = _cf.stage_files_in_temp(paths,
                                           label=label,
                                           ttl_seconds=60,
                                           open_in_explorer=True)
            res["source_folder"]  = target
            res["matched_stage"]  = os.path.basename(target)
            return res
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── 🏠 Per-day unit picker (mirrors Tk run_audit_gui.py:2780) ───
    # Multi-unit jobs (umbrella folder with Unit/Apt subfolders) can
    # be pinned to specific units for TODAY ONLY — each pinned unit
    # gets its own audit row in the next render. Tomorrow's audit
    # re-derives from scratch unless re-pinned.
    def property_structure(self, client: str) -> dict:
        """Walk the multi-unit umbrella folder for `client` and return
        the full OD structure: umbrella path + every unit subfolder
        with file counts + last-modified + EMS/PICS presence. Used by
        the 🏢 Property structure dialog for commercial multi-unit
        properties (Avila Apartments, Keystone-Highland Village, etc.).

        Run-doc shape example that benefits:
            "Avila Apartments: 28155 Encanto Dr Unit 1413 Menifee
             92585/951-… (Demo) Nestor/Cesar"
        → property="Avila Apartments", unit="1413". The umbrella is
        ``X:\\IE_Public\\2026\\Avila Apartments\\`` with one Unit XXXX
        subfolder per active claim.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import audit_logic as _al
            # Try the pinned folder first; fall back to auto-resolve.
            umbrella = persistence.get_folder_path(client) or ""
            if not umbrella:
                resolved = self._resolve_client_path(client)
                umbrella = resolved or ""
        except Exception:
            umbrella = ""
        if not umbrella or not os.path.isdir(umbrella):
            return {"ok": False,
                    "error": "no umbrella folder pinned/resolved for "
                             f"{client}",
                    "client": client}
        # Settings — commercial flag + persisted aliases. Lets the
        # dialog show them inline so the user can edit without leaving.
        try:
            is_commercial = bool(persistence.is_commercial(client))
        except Exception:
            is_commercial = False
        try:
            aliases = list(persistence.get_search_aliases(client) or [])
        except Exception:
            aliases = []
        try:
            units = _al.list_unit_subfolders(umbrella) or []
        except Exception:
            units = []
        try:
            pinned = set(persistence.get_run_day_units(
                _dt.date.today(), client) or [])
        except Exception:
            pinned = set()
        # Per-unit summary: count photos in EMS/PICS, last activity,
        # whether the standard subfolders exist. Bounded scan so a
        # property with 200 units doesn't time out.
        IMG_EXTS = {".jpg", ".jpeg", ".jfif", ".png", ".heic", ".heif",
                    ".webp", ".bmp", ".tif", ".tiff", ".gif"}
        unit_rows = []
        for u in units[:200]:
            uname = u.get("name") or ""
            upath = u.get("path") or ""
            ems_path = os.path.join(upath, "EMS")
            pics_path = (os.path.join(ems_path, "PICS")
                         if os.path.isdir(ems_path)
                         else os.path.join(upath, "PICS"))
            docs_path = (os.path.join(ems_path, "DOCS")
                         if os.path.isdir(ems_path)
                         else os.path.join(upath, "DOCS"))
            photo_count = 0
            try:
                if os.path.isdir(pics_path):
                    with os.scandir(pics_path) as it:
                        for e in it:
                            try:
                                if e.is_file() and os.path.splitext(e.name)[1].lower() in IMG_EXTS:
                                    photo_count += 1
                                elif e.is_dir():
                                    # one level deeper — stage subfolders
                                    try:
                                        with os.scandir(e.path) as it2:
                                            for e2 in it2:
                                                if e2.is_file() and os.path.splitext(e2.name)[1].lower() in IMG_EXTS:
                                                    photo_count += 1
                                    except OSError:
                                        pass
                            except OSError:
                                pass
            except OSError:
                pass
            try:
                last_mtime = os.path.getmtime(upath)
                last_str = _dt.datetime.fromtimestamp(last_mtime).strftime("%Y-%m-%d")
            except OSError:
                last_str = ""
            unit_rows.append({
                "name":         uname,
                "path":         upath,
                "ems_exists":   os.path.isdir(ems_path),
                "pics_exists":  os.path.isdir(pics_path),
                "pics_path":    pics_path,
                "docs_exists":  os.path.isdir(docs_path),
                "docs_path":    docs_path,
                "photo_count":  photo_count,
                "last_modified": last_str,
                "pinned_today": upath in pinned,
            })
        return {
            "ok":            True,
            "client":        client,
            "umbrella":      umbrella,
            "unit_count":    len(units),
            "units":         unit_rows,
            "settings": {
                "is_commercial": is_commercial,
                "aliases":       aliases,
            },
        }

    def set_property_settings(self, client: str,
                               is_commercial: bool = None,
                               aliases: list = None) -> dict:
        """Save the commercial flag + alias list for a property. Either
        field can be omitted to leave it untouched."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            if is_commercial is not None:
                persistence.set_commercial(client, bool(is_commercial))
            if aliases is not None:
                clean = [str(a).strip() for a in (aliases or [])
                         if str(a).strip()]
                # Dedupe while preserving order
                seen = set(); deduped = []
                for a in clean:
                    k = a.lower()
                    if k in seen: continue
                    seen.add(k); deduped.append(a)
                persistence.set_search_aliases(client, deduped)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def list_day_units(self, client: str) -> dict:
        """Return the multi-unit subfolders the umbrella folder for
        `client` exposes (Unit 1416, Apt 2413, etc.) plus whichever
        ones are currently pinned for today's run-date.

        Front-end uses this to render the checkbox list — each unit
        with a checked state from the persisted set.
        """
        if not client:
            return {"ok": False, "error": "no client", "units": []}
        try:
            import audit_logic as _al
            base_path = persistence.get_folder_path(client) or ""
        except Exception:
            base_path = ""
        if not base_path or not os.path.isdir(base_path):
            return {"ok": False,
                    "error": "no umbrella folder pinned",
                    "units": []}
        try:
            units = _al.list_unit_subfolders(base_path) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "units": []}
        try:
            pinned = set(persistence.get_run_day_units(
                _dt.date.today(), client) or [])
        except Exception:
            pinned = set()
        out = []
        for u in units:
            out.append({
                "name":   u.get("name") or "",
                "path":   u.get("path") or "",
                "pinned": u.get("path") in pinned,
            })
        return {"ok": True,
                "client": client,
                "umbrella": base_path,
                "units": out,
                "pinned_count": sum(1 for u in out if u["pinned"])}

    def set_day_units(self, client: str, paths) -> dict:
        """Persist the day-only unit pin set for `client`. Empty list
        clears all pins for today. Returns the updated count."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            clean = [p.strip() for p in (paths or [])
                     if p and p.strip()]
            persistence.set_run_day_units(_dt.date.today(),
                                            client, clean)
            return {"ok": True, "count": len(clean)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def create_and_route_unit(self, parent_path: str, unit_name: str,
                              import_paths=None) -> dict:
        """Create a missing referenced unit folder under `parent_path`,
        scaffold it (mirroring an existing sibling's skeleton), and move
        any `import_paths` (the in-progress import's files) into its
        EMS/PICS. The ➕ create-missing-child action.

        The caller (JS confirm dialog) supplies the editable `unit_name`
        and the file list, so this does NOT prompt. Returns
        {ok, path, created, moved, failed, error}."""
        if not parent_path or not os.path.isdir(parent_path):
            return {"ok": False, "error": "parent folder not found"}
        name = (unit_name or "").strip()
        if not name:
            return {"ok": False, "error": "no unit name"}
        try:
            import child_folder_ops as _cfops
            import audit_logic as _al
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        # Pick an existing sibling unit to copy the subfolder skeleton
        # from; None → create_and_route falls back to EMS/PICS+DOCS.
        sibling = ""
        try:
            sibs = _al.list_unit_subfolders(parent_path) or []
            for s in sibs:
                if s.get("num") is not None and s.get("path"):
                    sibling = s["path"]
                    break
            if not sibling and sibs:
                sibling = sibs[0].get("path") or ""
        except Exception:
            sibling = ""
        files = [p for p in (import_paths or []) if p and os.path.isfile(p)]
        try:
            return _cfops.create_and_route_unit(
                parent_path, name, import_files=files,
                sibling_path=sibling or None)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def count_loose_parent_photos(self, parent_path: str) -> dict:
        """Count media files sitting loose in a multi-unit parent's root
        (top-level, and root-level PICS/Photos) — i.e. photos that never
        made it into a unit subfolder. Flag-only signal for the ⚠ chip;
        does NOT move anything. Returns {count, sample:[names]}."""
        exts = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif",
                ".bmp", ".tif", ".tiff", ".webp", ".mp4", ".mov"}
        if not parent_path or not os.path.isdir(parent_path):
            return {"count": 0, "sample": []}
        names = []
        scan_dirs = [parent_path,
                     os.path.join(parent_path, "PICS"),
                     os.path.join(parent_path, "Photos")]
        for d in scan_dirs:
            if not os.path.isdir(d):
                continue
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if not e.is_file(follow_symlinks=False):
                                continue
                        except OSError:
                            continue
                        if os.path.splitext(e.name)[1].lower() in exts:
                            names.append(e.name)
            except OSError:
                continue
        return {"count": len(names), "sample": names[:8]}

    # ── Reset all per-client memory (Tk's right-click bottom item) ──
    def reset_client_memory(self, client: str) -> dict:
        """Wipe every sticky per-client pin + flag. Mirrors Tk
        job_widgets._reset_memory: clears folder pin, Trello card pins,
        commercial flag, and search aliases. The user gets a fresh
        re-auto-resolve on the next run."""
        if not client:
            return {"ok": False, "error": "no client"}
        cleared = []
        try:
            persistence.set_folder_path(client, "")
            cleared.append("folder pin")
        except Exception: pass
        try:
            persistence.set_trello_card_ids(client, [])
            cleared.append("Trello pins")
        except Exception: pass
        try:
            persistence.set_commercial(client, False)
            cleared.append("commercial flag")
        except Exception: pass
        try:
            persistence.set_search_aliases(client, [])
            cleared.append("aliases")
        except Exception: pass
        return {"ok": True, "cleared": cleared}

    # ── P0: Commercial toggle (per-job sticky) ──────────────────────
    def is_commercial(self, client: str) -> bool:
        """Sticky per-client commercial flag — read."""
        if not client:
            return False
        try:
            return bool(persistence.is_commercial(client))
        except Exception:
            return False

    def set_commercial(self, client: str, on: bool) -> dict:
        """Sticky per-client commercial flag — write + cascade. When
        turned ON, every missing form whose name matches
        `is_commercial_form()` (ATP, CIF, CER, CoS) is auto-marked
        resolved for the current run-date. Mirrors the Tk
        CommercialToggle's `_on_toggle` + `auto_apply_if_sticky` flow.
        Returns the count of items auto-resolved so the JS can toast.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            persistence.set_commercial(client, bool(on))
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        resolved_count = 0
        try:
            from audit_logic import (is_commercial_form, persist_key,
                                     REQUIRED_FORMS)
            run_date = (self._last_meta.get("date_iso") or
                        _dt.date.today().strftime("%Y-%m-%d"))
            if on:
                # Auto-resolve the commercial forms currently flagged missing.
                row = next((r for r in self._last_rows
                            if r.get("client") == client), None)
                if row is not None:
                    for item in (row.get("form_issues") or []):
                        if is_commercial_form(item):
                            try:
                                persistence.set_resolved(
                                    run_date, client, persist_key(item), True)
                                resolved_count += 1
                            except Exception:
                                pass
            else:
                # Turning commercial OFF must UN-hide the forms it resolved,
                # else they stay filtered out forever (the toggle was one-way).
                # The row's form_issues are empty by now (they were resolved),
                # so clear the known commercial forms by name.
                for name, _pat in REQUIRED_FORMS:
                    if is_commercial_form(name):
                        try:
                            persistence.set_resolved(
                                run_date, client, persist_key(name), False)
                            resolved_count += 1
                        except Exception:
                            pass
        except Exception:
            pass
        return {"ok": True, "on": bool(on), "resolved_count": resolved_count}

    # ── Single-card re-audit ─────────────────────────────────────────
    def _auto_pin_unit_folder(self, client: str) -> bool:
        """When `client` names a specific unit of a multi-unit property but
        has no folder pin yet, resolve the umbrella folder and pin the
        matching `Unit …` subfolder — so the audit resolves the RIGHT unit
        instead of landing on the umbrella (or 'folder not found').

        Deliberately conservative: no-op when a pin already exists, when the
        name carries no unit token, or when the umbrella holds 0 OR >1 folders
        for that unit number (ambiguous — e.g. two dated 'Unit 1611' folders).
        In the ambiguous case the user still gets the picker. Returns True
        only when it actually pinned a folder."""
        if not client:
            return False
        try:
            import multi_unit_logic as _mu
            import persistence as _ps
            import audit_logic as _al
            import config as _cfg
        except Exception:
            return False
        try:
            if (_ps.get_folder_path(client) or "").strip():
                return False   # respect an existing pin (incl. picker pins)
        except Exception:
            pass
        try:
            num = _mu.parse_unit_token(client)
        except Exception:
            num = None
        if num is None:
            return False
        prop = client
        try:
            import ems_db as _db
            p, _u = _db.detect_property_and_unit(client)
            if p:
                prop = p
        except Exception:
            pass
        try:
            base = (_cfg.load() or {}).get("audit_base") or ""
            path, _bn, _yr = _al.try_resolve_folder_by_terms(base, [prop])
        except Exception:
            path = None
        if not path:
            return False
        try:
            units = _mu.list_unit_subfolders(path) or []
        except Exception:
            return False
        matches = [u for u in units if u.get("num") == num]
        if len(matches) != 1:
            return False   # 0 or ambiguous → let the picker decide
        try:
            _ps.set_folder_path(client, matches[0]["path"])
            return True
        except Exception:
            return False

    def reaudit_one(self, client: str) -> dict:
        """Re-audit just one client and update the cached row in
        place. Returns the updated row dict so the JS can splice it
        into state without a full re-fetch.

        Resolution: prefers the run-doc entry (carries section /
        techs / new_loss flags), falls back to a synthetic job dict
        when the client is a one-off audit not in today's run-doc.
        Without the fallback re-running audit on a one-off row
        errored with "not in today's run-doc".
        """
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            d = _dt.date.today()
            doc_path = _find_run_doc_for_date(d)
            # `run_date` is a "MM-DD-YYYY" string everywhere downstream
            # (sharepoint._date_variants splits on "-"). Default to
            # the string form so the no-run-doc path doesn't blow up
            # with 'in <string>' requires string as left operand.
            run_date = d.strftime("%m-%d-%Y")
            match = None
            if doc_path:
                try:
                    jobs, run_date = _state_hub.parse_run_doc(doc_path)
                    match = next((j for j in jobs
                                  if (j.get("client") or "").strip() == client.strip()),
                                 None)
                except Exception:
                    match = None
            if match is None:
                # One-off path — synthesize a minimal job dict so
                # the audit can still run. Pulls section/new_loss
                # info from the existing cached row when available
                # so we don't lose chip context on re-audit.
                cached = next((r for r in (self._last_rows + self._oneoff_rows)
                               if r.get("client") == client), None)
                match = {
                    "client":   client,
                    "section":  (cached.get("section") if cached else "work") or "work",
                    "raw":      "",
                    "techs":    (cached.get("techs") if cached else []) or [],
                    "new_loss": bool(cached.get("new_loss") if cached else False),
                }
            # ── Multi-claim: resolve the RIGHT claim folder ──────────
            # A claim-suffixed client ("Mansolino Sayra 1st Claim") audited
            # directly makes the folder lookup descend to the LATEST claim
            # (2nd) — the snapshot/single-card audit then showed the WRONG
            # claim's folder + files. The Daily Run avoids this by expanding
            # the BASE name into per-claim rows (each with a folder_override).
            # Mirror that here: when the name carries a claim label, expand
            # the base + pick the row for THIS claim. (2026-06-24, parity
            # with the Daily Run multi-claim fix.)
            target_client = match.get("client") or client
            claim_lbl = ""
            try:
                claim_lbl = audit_logic.claim_label_from_folder(target_client)
            except Exception:
                claim_lbl = ""
            audit_name = target_client
            if claim_lbl:
                _idx = target_client.lower().rfind(claim_lbl.lower())
                if _idx > 0:
                    audit_name = target_client[:_idx].strip() or target_client
            # Multi-unit: auto-pin the matching Unit subfolder when this name
            # unambiguously points to one unit of an umbrella (and isn't
            # already pinned) so the resolver finds the unit, not the parent.
            try:
                self._auto_pin_unit_folder(audit_name)
            except Exception:
                pass
            results, err = audit_jobs(
                [audit_name],
                run_date=run_date,
                use_cache=False,                 # force fresh check
                expand_subjobs=bool(claim_lbl))
            if err or not results:
                return {"ok": False, "error": err or "no result"}
            # Pick the result for THIS client. For a claim-suffixed name,
            # match the expanded per-claim row (exact, then by claim label);
            # otherwise the single result.
            def _cn(s):
                return " ".join((s or "").strip().lower().split())
            chosen = None
            if claim_lbl:
                chosen = next(
                    (r for r in results
                     if _cn(r.get("client")) == _cn(target_client)), None)
                if chosen is None:
                    _cl = claim_lbl.lower()
                    chosen = next(
                        (r for r in results
                         if _cl in _cn(r.get("client"))), None)
            chosen = chosen or results[0]
            # Adopt the resolved per-claim/result client so the row's
            # client / row_key / pin / folder are correct + distinct
            # (mirrors the Daily Run _shape_job client-adoption fix).
            _rc = chosen.get("client") or ""
            if _rc and _rc != match.get("client"):
                match = {**match, "client": _rc}
            # SP enrichment so the row's 📥 +N chip + match dialog
            # stay in sync after a re-audit. Single-row call so we
            # skip the (expensive) folder_index build.
            try:
                enrich_with_sharepoint(chosen, run_date)
            except Exception:
                pass
            try:
                pin = persistence.get_trello_card_id(
                    match.get("client") or client) or ""
            except Exception:
                pin = ""
            new_row = _shape_job(match, chosen, pin)
            # Splice into whichever cache the client lives in. One-off
            # audits stay in _oneoff_rows; daily-run rows stay in
            # _last_rows. Falling through to _last_rows append would
            # leak one-offs into the Daily Run list.
            target_list = (self._oneoff_rows
                           if any(r.get("client") == client
                                   for r in self._oneoff_rows)
                           else self._last_rows)
            for i, r in enumerate(target_list):
                if r.get("client") == client:
                    target_list[i] = new_row
                    break
            else:
                target_list.append(new_row)
            # Prime persistence with this single freshly-resolved path
            # so subsequent non-OD-folder actions for this client see
            # the path immediately.
            self._prime_folder_pins([new_row])
            return {"ok": True, "row": new_row}
        except Exception as ex:
            return {"ok": False,
                    "error": f"{type(ex).__name__}: {ex}"}

    # ── Phase 2: Import center ───────────────────────────────────────
    def scan_downloads(self, client: str = "") -> dict:
        """Scan the Downloads folder for every importable zip — WC
        attachments, WC documents, DocuSign packets. Returns enough
        info for the Import view to render the candidate list and
        let the user pick one to extract.

        When `client` is provided, DS zips matching that client's
        surname float to the top; otherwise we list newest-first.
        """
        import wc_zip_import as _wcz
        try:
            import docusign_import as _dsi
        except Exception:
            _dsi = None

        downloads = DOWNLOADS

        # Repair extensionless downloads FIRST, so the extension-based
        # scans below (scope/document PDFs, zips) can see them and so the
        # files open normally in Windows. CompanyCam's web export drops
        # PDFs/photos with no extension (e.g. `Servpro Authorization`);
        # this sniffs the real type and appends the right suffix. Only
        # touches files that have no extension — safe + reversible.
        try:
            import file_signature as _fsig
            repaired = _fsig.repair_directory(downloads)
        except Exception:
            repaired = []

        candidates = []

        # WC attachments (mixed photos+forms, IUQ style)
        try:
            attach = _wcz.find_wc_zips(downloads, _wcz.WC_ATTACHMENTS_RE)
        except Exception:
            attach = []
        for group_label, paths in attach:
            candidates.append({
                "kind":   "wc_attachments",
                "label":  group_label,
                "paths":  list(paths),
                "kind_label": "WC attachments (photos + forms)",
                "icon":   "📥",
            })

        # WC documents (forms-only export)
        try:
            docs = _wcz.find_wc_zips(downloads, _wcz.WC_DOCUMENTS_RE)
        except Exception:
            docs = []
        for group_label, paths in docs:
            candidates.append({
                "kind":   "wc_documents",
                "label":  group_label,
                "paths":  list(paths),
                "kind_label": "WC documents (forms only)",
                "icon":   "📄",
            })

        # DocuSign packets
        ds_zips = []
        if _dsi is not None:
            try:
                ds_zips = _dsi.find_docusign_zips(
                    downloads, client_hint=client or None) or []
            except Exception:
                ds_zips = []
        for fn in ds_zips:
            candidates.append({
                "kind":   "docusign",
                "label":  fn,
                "paths":  [os.path.join(downloads, fn)],
                "kind_label": "DocuSign signed packet",
                "icon":   "📝",
            })

        # DocuSketch zips — DOCUSKETCH_RE matches Tour_N_Order_N_all_sketchesN.zip
        # filenames. These don't carry the client name so we list every one in
        # Downloads — the user picks which one matches the target job.
        try:
            from audit_logic import DOCUSKETCH_RE
            ds_sketch_zips = sorted(
                [f for f in os.listdir(downloads)
                 if DOCUSKETCH_RE.match(f)
                 and os.path.isfile(os.path.join(downloads, f))],
                key=lambda f: os.path.getmtime(os.path.join(downloads, f)),
                reverse=True)
        except Exception:
            ds_sketch_zips = []
        for fn in ds_sketch_zips:
            candidates.append({
                "kind":   "docusketch",
                "label":  fn,
                "paths":  [os.path.join(downloads, fn)],
                "kind_label": "DocuSketch sketches",
                "icon":   "📐",
            })

        # CompanyCam photo exports — `photos-YYYY-MM-DD-xxxx.zip`. The
        # client name is the zip's TOP FOLDER (not the filename), so we
        # read it for the label and surname-match it to this job. Many
        # same-date zips coexist (one per job) — the project name is how
        # the user tells them apart, so it leads the label.
        try:
            import companycam_import as _ccz
            cc_zips = _ccz.find_companycam_zips(
                downloads, client_hint=client or None)
        except Exception:
            cc_zips = []
        for e in cc_zips:
            proj = e.get("project") or "(unknown project)"
            candidates.append({
                "kind":   "companycam",
                "label":  f"{proj}  ·  {e['filename']}",
                "paths":  [e["path"]],
                "kind_label": "CompanyCam photos",
                "icon":   "📸",
            })

        # Scope PDFs — written scopes the user drops in Downloads. The
        # tech typically names them "Scope.pdf" or "Scope - Smith.pdf"
        # or "Smith Scope.pdf"; word-boundary `\bscope\b` (no
        # "microscope" false matches) is enough. Client-name token
        # match floats relevant files to the top of the candidate
        # list. On import these land at <EMS>/DOCS/Scope.pdf which
        # is the canonical filename audit_logic.check_forms looks for.
        try:
            scope_pdfs = _find_scope_pdfs(downloads, client_hint=client)
        except Exception:
            scope_pdfs = []
        for entry in scope_pdfs:
            candidates.append({
                "kind":   "scope",
                "label":  entry["filename"],
                "paths":  [entry["path"]],
                "kind_label": ("Scope PDF · matches client"
                                if entry.get("client_match")
                                else "Scope PDF"),
                "icon":   "📋",
            })

        # Drying Report PDFs — Phoenix/Thermastor equipment dashboards
        # export reports as `DryingReport_<Month>-<Day>-<Year>.pdf`.
        # These don't carry the client name so we surface every match
        # in Downloads (newest first) and let the user pick. On import
        # they land at <EMS>/DOCS/<original filename> so the date in
        # the filename stays visible.
        try:
            from audit_logic import DRYING_REPORT_RE
            drying_pdfs = sorted(
                [f for f in os.listdir(downloads)
                 if DRYING_REPORT_RE.match(f)
                 and os.path.isfile(os.path.join(downloads, f))],
                key=lambda f: os.path.getmtime(
                    os.path.join(downloads, f)),
                reverse=True)
        except Exception:
            drying_pdfs = []
        for fn in drying_pdfs:
            candidates.append({
                "kind":   "drying_report",
                "label":  fn,
                "paths":  [os.path.join(downloads, fn)],
                "kind_label": "Drying report PDF",
                "icon":   "💧",
            })

        # Loose client-named documents — invoices / statements / reports
        # the user downloads per job as "<Client>.pdf" (no "invoice" in
        # the name). Surface them as DOCS imports, surname-matched to the
        # current job so only THIS client's doc shows (not every PDF in
        # Downloads). Skips files already classified above (scope / drying
        # / docusign) and anything with "scope" in the name.
        try:
            _cn = (client or "").strip()
            _head = (_cn.split(",", 1)[0] if "," in _cn
                     else (_cn.split()[-1] if _cn.split() else ""))
            _surname = _head.strip().lower()
            _surname = _surname if len(_surname) >= 2 else ""
            _already = {os.path.basename(p)
                        for c in candidates for p in c.get("paths", [])}
            doc_pdfs = []
            for f in os.listdir(downloads):
                low = f.lower()
                if not low.endswith(".pdf") or "scope" in low:
                    continue
                if f in _already:
                    continue
                if not os.path.isfile(os.path.join(downloads, f)):
                    continue
                if _surname and _surname not in low:
                    continue
                doc_pdfs.append(f)
            doc_pdfs.sort(key=lambda f: os.path.getmtime(
                os.path.join(downloads, f)), reverse=True)
        except Exception:
            doc_pdfs = []
        for fn in doc_pdfs:
            candidates.append({
                "kind":   "document",
                "label":  fn,
                "paths":  [os.path.join(downloads, fn)],
                "kind_label": "Document → DOCS (invoice / statement / report)",
                "icon":   "🧾",
            })

        return {
            "downloads": downloads,
            "client":    client,
            "candidates": candidates,
            "repaired":  repaired,
        }

    def do_import(self, client: str, kind: str,
                   zip_paths: list[str], dest_subfolder: str = "",
                   tech: str = "", side: str = "ems") -> dict:
        """Extract one zip group into the target job's EMS folder.

        `dest_subfolder` (optional) is the PICS stage folder the user
        picked in the stage dialog (Demo / Mold Prep / Monitor / …). When
        set (and not "AUTO"), ALL photos route there instead of the
        run-doc / per-tag auto-routing. Empty / "AUTO" keeps auto-routing.

        `kind` is one of: "wc_attachments" / "wc_documents" /
        "docusign". `zip_paths` is the list returned by
        `scan_downloads()` (may be multi-part). Resolves the target
        client's path via persistence + auto-discovery so the web
        doesn't have to ferry path strings around.

        Returns a dict with `ok`, optional `error`, and the count of
        files extracted per destination (`pics_count`, `docs_count`).
        Recycles the source zip(s) on success — mirrors the Tk
        importer's cleanup behavior.
        """
        try:
            target_path = self._resolve_client_path(client)
            if not target_path:
                return {"ok": False,
                        "error": f"Couldn't find OD folder for {client!r}"}
            from sharepoint import _IMAGE_EXTS as _img_exts
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

        if not zip_paths:
            return {"ok": False, "error": "no zip paths given"}

        # Contents-side routing: when side="contents" the whole import
        # targets the CONTENTS sibling of EMS (CONTENTS/PICS, CONTENTS/
        # DOCS) — a separate tree OUTSIDE EMS. Mirrors the SP import's
        # 📦 Contents-side toggle. Creates CONTENTS/ if the job doesn't
        # have one yet. (2026-06-22)
        _is_contents = (side or "").strip().lower() == "contents"
        base_dir  = os.path.join(target_path,
                                 "CONTENTS" if _is_contents else "EMS")
        pics_root = os.path.join(base_dir, "PICS")
        docs_root = os.path.join(base_dir, "DOCS")

        try:
            os.makedirs(base_dir,  exist_ok=True)
            os.makedirs(pics_root, exist_ok=True)
            os.makedirs(docs_root, exist_ok=True)
        except OSError as ex:
            return {"ok": False, "error": f"Folder error: {ex}"}

        # Decide PICS subfolder by run-doc activity. Falls back to
        # "Initial" on any error so an unknown activity still imports.
        try:
            from audit_logic import resolve_pics_subfolder
            today_str = _dt.date.today().strftime("%m-%d-%Y")
            labels = _activity_labels_from_run_doc(
                today_str, client)
            sub, needs_prompt = resolve_pics_subfolder(labels)
            if needs_prompt or not sub:
                sub = "Initial"
        except Exception:
            sub = "Initial"

        # Initial is a ONE-SHOT target. The first WC import for a job
        # seeds PICS/Initial with the genuine initial-inspection photos.
        # Any later import that also resolves to "Initial" — typically a
        # monitoring / equipment run whose activity didn't map to a stage
        # and fell back here — must NOT pile on top of the real initials
        # (that's how they get mixed and become indistinguishable). When
        # Initial already holds photos, redirect this batch to a dated
        # "WC Photos <MM-DD-YYYY>" folder instead. Only Initial is
        # guarded; real stage subfolders (Demo, Mold Prep, …) are
        # intentional and may legitimately receive multiple imports.
        if sub == "Initial":
            initial_dir = os.path.join(pics_root, "Initial")
            already = False
            if os.path.isdir(initial_dir):
                for _r, _d, _fs in os.walk(initial_dir):
                    if any(os.path.splitext(f)[1].lower() in _img_exts
                           for f in _fs):
                        already = True
                        break
            if already:
                sub = "WC Photos " + _dt.date.today().strftime(
                    "%m-%d-%Y")

        # User explicitly chose a destination in the stage picker → that
        # wins over the run-doc auto-routing AND the Initial one-shot guard.
        # A "DOCS" / "DOCS:<sub>" pick routes the wc/pick-a-file files to
        # the DOCS folder instead of a PICS stage.
        _user_dest = (dest_subfolder or "").strip()
        _docs_dest = None
        if _user_dest.upper() == "DOCS" or _user_dest.upper().startswith("DOCS:"):
            _docs_dest = (_user_dest.split(":", 1)[1].strip()
                          if ":" in _user_dest else "")
        elif _user_dest and _user_dest.upper() != "AUTO":
            sub = _user_dest

        # Every IMAGE import must attribute a tech (companycam has no
        # photographer in the export; wc_attachments are field photos).
        # A DOCS-forced pick is paperwork, so it's exempt. Frontend prompts
        # for the tech (pre-filled from the run-doc); this is the guarantee.
        if (kind in ("companycam", "wc_attachments")
                and _docs_dest is None and not (tech or "").strip()):
            return {"ok": False, "need_tech": True,
                    "error": "Pick a tech before importing photos."}

        # Resolve the PICS target but DON'T create it yet. The per-file
        # placement loop below makes it lazily — and only when an image
        # actually lands there. Creating it up front left empty
        # "WC Photos <date>" / stage folders behind whenever an import
        # had no photos (forms-only WC docs, empty/loose-doc imports).
        # (2026-06-17)
        pics_target = os.path.join(pics_root, sub)

        pics_count, docs_count = 0, 0
        sketches_count = 0
        # Basenames of every file that lands in DOCS this import — used to
        # decide whether a COS (Certificate of Satisfaction) was added, so
        # the CLOSE OUT "FINAL PAPERWORK" checklist item only auto-ticks
        # when the COS itself arrives (not on any docusign/WC doc). (2026-06-22)
        _docs_landed_names: list[str] = []
        # Basenames of files whose move+copy fallback BOTH failed — they
        # never landed, so they must NOT be counted as imported (audit
        # bug #6: silent `except OSError: pass` reported them as success).
        _import_failed: list[str] = []
        try:
            if kind == "document":
                # Loose client-named doc (invoice / statement / report) →
                # DOCS, original filename kept, collision-bumped.
                import shutil as _sh
                for src in zip_paths:
                    if not os.path.isfile(src):
                        continue
                    fn0 = os.path.basename(src)
                    stem0, ext0 = os.path.splitext(fn0)
                    dst = os.path.join(docs_root, fn0)
                    n = 2
                    while os.path.exists(dst):
                        dst = os.path.join(docs_root, f"{stem0} ({n}){ext0}")
                        n += 1
                    try:
                        _sh.move(src, dst)
                    except OSError:
                        _sh.copy2(src, dst)
                        try: os.remove(src)
                        except OSError: pass
                    docs_count += 1
                    _docs_landed_names.append(os.path.basename(dst))
            elif kind == "scope":
                # Written scope PDF — drop into <EMS>/DOCS/Scope.pdf
                # (the canonical filename audit_logic.check_forms
                # looks for). On collision suffix with " (N).pdf".
                import shutil as _sh
                src = zip_paths[0]
                if not os.path.isfile(src):
                    return {"ok": False,
                            "error": f"Scope file missing: {src}"}
                dst = os.path.join(docs_root, "Scope.pdf")
                if os.path.exists(dst):
                    n = 2
                    while os.path.exists(os.path.join(
                            docs_root, f"Scope ({n}).pdf")):
                        n += 1
                    dst = os.path.join(docs_root, f"Scope ({n}).pdf")
                try:
                    _sh.move(src, dst)
                except OSError:
                    _sh.copy2(src, dst)
                    try: os.remove(src)
                    except OSError: pass
                docs_count = 1
            elif kind == "drying_report":
                # Drying report PDF — keep the original filename so the
                # date in `DryingReport_May-29-2026.pdf` stays visible
                # in DOCS. A job can have multiple drying reports (one
                # per equipment day / room) so we DON'T canonicalize
                # to a fixed name; just collide-bump with " (N)".
                import shutil as _sh
                src = zip_paths[0]
                if not os.path.isfile(src):
                    return {"ok": False,
                            "error": f"Drying report missing: {src}"}
                base_fn = os.path.basename(src)
                stem, ext = os.path.splitext(base_fn)
                dst = os.path.join(docs_root, base_fn)
                n = 2
                while os.path.exists(dst):
                    dst = os.path.join(docs_root,
                                         f"{stem} ({n}){ext}")
                    n += 1
                try:
                    _sh.move(src, dst)
                except OSError:
                    _sh.copy2(src, dst)
                    try: os.remove(src)
                    except OSError: pass
                docs_count = 1
            elif kind == "docusign":
                import docusign_import as _dsi
                # DS packets go to DOCS; one zip per call. `landed` is
                # {form_kind: [filenames]} — flatten the names so the COS
                # check below can see exactly what came in.
                landed = _dsi.import_zip(zip_paths[0], docs_root)
                docs_count = len(landed) if hasattr(landed, "__len__") else 0
                try:
                    for _v in (landed or {}).values():
                        _docs_landed_names.extend(_v or [])
                except Exception:
                    pass
            elif kind == "companycam":
                # CompanyCam export — route photos into PICS/<stage> by
                # their tag (Post/Demo/Mold/…); room-only photos land in a
                # dated "CompanyCam <date>" folder. Bypasses the run-doc
                # `sub` resolution above (each photo self-routes).
                import companycam_import as _ccz
                # Use the photo CAPTURE date (from the filename stamps), not
                # the zip name — CompanyCam names the zip with the EXPORT/
                # download date (today), which was landing every import in a
                # "today" folder regardless of when the photos were shot.
                _raw = (_ccz.date_from_photos(zip_paths[0])
                        or _ccz.date_from_zip_name(os.path.basename(zip_paths[0])))
                try:
                    _date_lbl = _dt.datetime.strptime(
                        _raw, "%Y-%m-%d").strftime("%m-%d-%Y")
                except Exception:
                    _date_lbl = _raw
                # If the user picked a PICS folder, force ALL photos there;
                # otherwise self-route each photo by its tag. (DOCS picks
                # don't apply to a photo export.)
                _force = ("" if _docs_dest is not None
                          else (_user_dest if (_user_dest
                                and _user_dest.upper() != "AUTO") else ""))
                # CompanyCam exports carry no photographer — `tech`
                # (picked in the UI, defaulting to the run-doc tech)
                # attributes the batch via a "<Tech> <date>" folder. Lead
                # techs are filed by their roster initials (FB / ME / ML /
                # RQ / PG / AP / JL); helpers keep their full first name.
                # initials_for_name returns "" for non-leads → fall back to
                # the raw name. (2026-06-19)
                try:
                    _tech_lbl = (audit_logic.initials_for_name(tech or "")
                                 or (tech or ""))
                except Exception:
                    _tech_lbl = tech or ""
                _landed = _ccz.import_zip(
                    zip_paths[0], pics_root, date_label=_date_lbl,
                    force_subfolder=_force, tech=_tech_lbl)
                pics_count = sum(_landed.values())
                # Surface the real stage folder(s) in the toast.
                sub = _force or _ccz.summarize_landed(_landed)
            elif kind == "docusketch":
                # DocuSketch zips extract straight into EMS/DOCS/Docusketch/
                # — same target the Tk audit's Docusketch import uses.
                import zipfile as _zf
                sketch_dir = os.path.join(docs_root, "Docusketch")
                os.makedirs(sketch_dir, exist_ok=True)
                with _zf.ZipFile(zip_paths[0], "r") as z:
                    members = z.namelist()
                    z.extractall(sketch_dir)
                # Count files (skip dir entries)
                sketches_count = sum(
                    1 for m in members if m and not m.endswith("/"))
            else:
                # WC: extract + split-route by extension. Mirrors the
                # IUQ + audit's per-extension routing logic. Handles both
                # zip exports AND hand-picked loose files via
                # place_import_paths (zips extracted, loose files copied).
                import shutil, tempfile
                from wc_zip_import import place_import_paths
                with tempfile.TemporaryDirectory(prefix="aweb_") as staging:
                    place_import_paths(zip_paths, staging)
                    import child_folder_ops as _cfops
                    for root, _dirs, files in os.walk(staging):
                        for fn in files:
                            src = os.path.join(root, fn)
                            ext = os.path.splitext(fn)[1].lower()
                            if _docs_dest is not None:
                                # User chose DOCS in the picker → everything
                                # goes to DOCS (optionally a subfolder).
                                dest_dir = (os.path.join(docs_root, _docs_dest)
                                            if _docs_dest else docs_root)
                                is_docs = True
                            elif ext in _img_exts:
                                dest_dir = pics_target
                                is_docs = False
                            else:
                                dest_dir = docs_root
                                is_docs = True
                            # Collision-safe, cloud-aware move; returns the
                            # final path or None on total failure. Count ONLY
                            # on a confirmed write (bug #6), and record the
                            # ACTUAL landed name (bug #9 — collision-bumped).
                            landed = _cfops.safe_move(src, dest_dir)
                            if not landed:
                                _import_failed.append(fn)
                                continue
                            if is_docs:
                                docs_count += 1
                                _docs_landed_names.append(
                                    os.path.basename(landed))
                            else:
                                pics_count += 1
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

        # Photos only: HEIC → JPEG, then sort into per-room subfolders
        # (Bed 1, Bath 2, Garage…) when filenames carry room labels.
        # Both no-op safely when there's nothing to do.
        if pics_count:
            try:
                from wc_zip_import import (convert_heic_in_dir,
                                            organize_by_room)
                import json as _json

                # Stream HEIC→JPEG conversion progress to the active
                # panel so a big dump (10-30s of converting) shows a live
                # "Converting N/M…" indicator instead of a frozen button.
                def _heic_progress(done, total):
                    payload = {"done": int(done), "total": int(total),
                               "client": str(client or "")}
                    _emit_js_all(
                        "window.dispatchEvent(new CustomEvent("
                        "'import:progress', {detail: "
                        + _json.dumps(payload) + "}));")

                # CompanyCam self-routes photos into several stage folders
                # under PICS (not the single pics_target), so convert the
                # whole PICS tree for it; other imports land in pics_target.
                _convert_root = pics_root if kind == "companycam" else pics_target
                convert_heic_in_dir(_convert_root, progress_cb=_heic_progress)
                organize_by_room(pics_target)
            except Exception:
                pass

        # Tick the matching Trello checklist item for what we imported:
        #   docusketch → PHYSICAL SKETCH (INITIAL - ADMIN)
        #   wc photos  → INITIAL PHOTOS/PHOTO REPORT
        #   wc docs / docusign → INITIAL / FINAL PAPERWORK
        # Best-effort; a Trello hiccup never blocks the import success.
        _tick_ticked = []
        try:
            import persistence as _per
            import trello_autotick as _at
            _cid = _per.get_trello_card_id(client) or ""
            if _cid:
                # Did a COS (Certificate of Satisfaction) land in DOCS this
                # import? FINAL PAPERWORK auto-ticks ONLY then — not on any
                # docusign packet / WC doc (user 2026-06-22). Works for any
                # import path that drops the COS in OD (docusign packet, WC
                # zip, loose doc, pick-a-file).
                _cos_imported = False
                try:
                    from docusign_import import classify_pdf as _classify_pdf
                    _cos_imported = any(
                        _classify_pdf(n) == "CoS" for n in _docs_landed_names)
                except Exception:
                    _cos_imported = False
                _ev = []
                if kind == "docusketch":
                    _ev.append("docusketch_imported")
                elif kind == "docusign":
                    # Final paperwork is gated on the COS below — a docusign
                    # packet WITHOUT a COS (e.g. ATP/CIF only) ticks nothing.
                    pass
                elif kind == "companycam":
                    # Stage-tagged field photos — no canonical checklist
                    # item maps cleanly, so don't auto-tick anything.
                    pass
                else:
                    if pics_count:
                        _ev.append("wc_photos_initial")
                    if docs_count:
                        _ev.append("wc_docs_imported")
                # FINAL PAPERWORK — only when the COS itself was imported,
                # regardless of which import kind delivered it.
                if _cos_imported:
                    _ev.append("final_paperwork")
                if _ev:
                    _tick_ticked = _at.autotick(
                        _cid, events=tuple(_ev), client=client)
        except Exception:
            _tick_ticked = []

        # Recycle the source zip(s) — same cleanup the Tk importers do.
        try:
            from wc_zip_import import trash_imported_zips
            trash_imported_zips(zip_paths)
        except Exception:
            pass

        # Detect photos that landed with NO EXIF capture date (screenshots
        # / pasted PNGs / undated downloads) so the UI can offer to stamp
        # one — "when were these taken?". Scoped to this import's stage
        # folder. Skipped for CompanyCam (field photos carry their own
        # dates) and doc-only kinds.
        undated, undated_dir = 0, ""
        if pics_count and kind not in (
                "docusketch", "docusign", "document", "scope",
                "drying_report", "companycam"):
            try:
                import image_dates as _idt
                undated_dir = pics_target
                undated = len(_idt.find_undated(pics_target))
            except Exception:
                undated, undated_dir = 0, ""

        return {
            "ok":             True,
            "pics_count":     pics_count,
            "docs_count":     docs_count,
            "sketches_count": sketches_count,
            "kind":           kind,
            "target":         target_path,
            "subfolder":      sub if pics_count else None,
            "ticked":         [it for _cl, it in _tick_ticked],
            "undated_photos": undated,
            "undated_dir":    undated_dir,
            "side":           "contents" if _is_contents else "ems",
            # Files that failed to land (never counted in pics/docs) so the
            # UI can warn instead of falsely reporting a clean import.
            "failed":         _import_failed,
        }

    def detect_import_groups(self, zip_paths: list) -> dict:
        """Peek the photo filenames in `zip_paths` (no extraction) and
        split them into (day, stage) groups so the import review panel can
        auto-route folders by stage and prompt one tech per day+stage.
        Returns import_grouping.detect_groups(...) plus ok."""
        import zipfile
        try:
            from sharepoint import _IMAGE_EXTS as _img_exts
        except Exception:
            _img_exts = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
        names = []
        for p in (zip_paths or []):
            try:
                if zipfile.is_zipfile(p):
                    with zipfile.ZipFile(p) as z:
                        for n in z.namelist():
                            if n.endswith("/"):
                                continue
                            if os.path.splitext(n)[1].lower() in _img_exts:
                                names.append(os.path.basename(n))
                elif os.path.splitext(p)[1].lower() in _img_exts:
                    names.append(os.path.basename(p))
            except Exception:
                continue
        try:
            import import_grouping as _ig
            res = _ig.detect_groups(names)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, **res}

    def do_import_grouped(self, client: str, kind: str, zip_paths: list,
                          assignments: list, side: str = "ems") -> dict:
        """Multi-stage photo import: each file routes to the PICS stage
        folder assigned to its (day,stage) group in `assignments` (list of
        {date_key, stage, folder, tech}). Mirrors do_import's extraction +
        HEIC convert + zip recycle, but fans out to several stage folders
        in one pass. Files matching no assignment fall back to 'Initial'."""
        try:
            target_path = self._resolve_client_path(client)
            if not target_path:
                return {"ok": False,
                        "error": f"Couldn't find OD folder for {client!r}"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not zip_paths:
            return {"ok": False, "error": "no zip paths given"}
        if not assignments:
            return {"ok": False, "error": "no group assignments given"}

        _is_contents = (side or "").strip().lower() == "contents"
        base_dir  = os.path.join(target_path,
                                 "CONTENTS" if _is_contents else "EMS")
        pics_root = os.path.join(base_dir, "PICS")
        try:
            os.makedirs(pics_root, exist_ok=True)
        except OSError as ex:
            return {"ok": False, "error": f"Folder error: {ex}"}

        # (date_key, stage) → folder. A photo kind needs a tech per group.
        route = {}
        for a in assignments:
            folder = (a.get("folder") or "").strip()
            if not folder:
                return {"ok": False,
                        "error": f"No folder chosen for {a.get('stage') or a.get('date_key') or 'a group'}"}
            if (kind in ("companycam", "wc_attachments")
                    and not (a.get("tech") or "").strip()):
                return {"ok": False, "need_tech": True,
                        "error": f"Pick a tech for {folder} ({a.get('date_key') or '?'})."}
            route[(a.get("date_key") or "", a.get("stage") or "")] = folder

        import child_folder_ops as _cfops
        import import_grouping as _ig
        touched = {}          # folder -> count
        failed = []
        import tempfile
        from wc_zip_import import place_import_paths
        try:
            with tempfile.TemporaryDirectory(prefix="grp_") as staging:
                place_import_paths(zip_paths, staging)
                for root, _dirs, files in os.walk(staging):
                    for fn in files:
                        src = os.path.join(root, fn)
                        stage = _ig.detect_stage(fn)
                        dkey, _ = _ig.detect_date(fn)
                        folder = (route.get((dkey or "", stage or ""))
                                  or route.get(("", stage or ""))
                                  or (stage or "Initial"))
                        dest_dir = os.path.join(pics_root, folder)
                        landed = _cfops.safe_move(src, dest_dir)
                        if landed:
                            touched[folder] = touched.get(folder, 0) + 1
                        else:
                            failed.append(fn)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

        # HEIC → JPEG + room-sort each folder that received photos.
        try:
            from wc_zip_import import convert_heic_in_dir, organize_by_room
            for folder in touched:
                d = os.path.join(pics_root, folder)
                convert_heic_in_dir(d)
                organize_by_room(d)
        except Exception:
            pass
        # Recycle the source zips — same cleanup as do_import.
        try:
            from wc_zip_import import trash_imported_zips
            trash_imported_zips(zip_paths)
        except Exception:
            pass

        total = sum(touched.values())
        return {"ok": True, "pics_count": total, "routed": touched,
                "failed": failed,
                "side": "contents" if _is_contents else "ems"}

    def track_events(self, events: list) -> dict:
        """Persist a batch of UI usage events (web_shared/usage_track.js).
        Best-effort — never raises to the caller."""
        try:
            import usage_tracker as _ut
            return _ut.record(events or [])
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def usage_report(self, days: int = 30) -> dict:
        """Aggregated usage stats for the 📊 My Usage view."""
        try:
            import usage_tracker as _ut
            return _ut.report(int(days or 30))
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def usage_reset(self) -> dict:
        try:
            import usage_tracker as _ut
            return _ut.reset()
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Hygiene job board (shared with the Hygiene panel) ────────────
    def hygiene_board_rows(self) -> dict:
        """Active jobs + their four admin milestones (DocuSign / initial /
        final paperwork / weekly check-in). Powers the audit Overview and
        the simplified Hygiene page from ONE source."""
        try:
            import hygiene_board as _hb
            return {"ok": True, "rows": _hb.board_rows()}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}

    def hygiene_mark(self, canon: str, milestone: str,
                     card_id: str = "") -> dict:
        try:
            import hygiene_board as _hb
            return _hb.mark_milestone(canon, milestone, card_id=card_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Request items from the lead (shared dialog) ─────────────────
    def request_item_options(self) -> dict:
        try:
            import request_items as _ri
            return {"ok": True, "items": _ri.ITEMS,
                    "handles": _ri.recent_handles()}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "items": [], "handles": []}

    def request_items_send(self, card_id: str, canon: str, keys,
                           other: str = "", handle: str = "",
                           client: str = "") -> dict:
        try:
            import request_items as _ri
            return _ri.send(card_id, canon, keys or [], other, handle, client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Xactimate 'new estimate from scratch' prep ──────────────────
    def xa_prep_resolve(self, client: str) -> dict:
        try:
            import xactimate_prep as _xp
            return {"ok": True, "fields": _xp.resolve(client)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def xa_set_pricelist(self, carrier: str, pricelist: str) -> dict:
        try:
            import xactimate_prep as _xp
            return _xp.set_pricelist(carrier, pricelist)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Tracked to-do notes (job-tied or loose) ─────────────────────
    def notes_list(self, job: str = "", include_done: bool = False) -> dict:
        try:
            import notes_tracker as _nt
            return {"ok": True, "notes": _nt.list_notes(job, include_done)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "notes": []}

    def notes_add(self, text: str, job: str = "") -> dict:
        try:
            import notes_tracker as _nt
            return _nt.add(text, job)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def notes_set_done(self, note_id, done: bool) -> dict:
        try:
            import notes_tracker as _nt
            return _nt.set_done(note_id, done)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def notes_update(self, note_id, text: str) -> dict:
        try:
            import notes_tracker as _nt
            return _nt.update(note_id, text)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def notes_delete(self, note_id) -> dict:
        try:
            import notes_tracker as _nt
            return _nt.delete(note_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def notes_open_count(self, job: str = "") -> dict:
        try:
            import notes_tracker as _nt
            return {"ok": True, "count": _nt.open_count(job)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "count": 0}

    def stamp_photo_dates(self, folder: str, date_iso: str) -> dict:
        """Stamp EXIF capture date = `date_iso` (YYYY-MM-DD) on every
        dateless image under `folder`, converting PNG/HEIC → JPEG.
        Backs the import 'when were these taken?' dialog. Originals go to
        the Recycle Bin."""
        if not folder or not os.path.isdir(folder):
            return {"ok": False, "error": "folder not found"}
        try:
            when = _dt.date.fromisoformat((date_iso or "").strip())
        except Exception:
            return {"ok": False, "error": "bad date (need YYYY-MM-DD)"}
        try:
            import image_dates as _idt
            n = _idt.stamp_folder(folder, when)
            return {"ok": True, "stamped": n,
                    "date": when.strftime("%m/%d/%Y")}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def pick_and_import_file(self, client: str,
                             dest_subfolder: str = "",
                             side: str = "ems", tech: str = "") -> dict:
        """Open a native file picker rooted at Downloads so the user can
        hand-select ANY file(s) to import — regardless of whether the
        auto-scanner found anything. Zips are extracted + split-routed
        (images → PICS, everything else → DOCS); loose files route the
        same way by extension. HEIC → JPEG + per-room organize apply to
        photos. Mirrors `do_import`'s WC routing but with a manual file
        source.

        Returns the same shape as `do_import` (ok, pics_count,
        docs_count, …), plus `picked` (the chosen paths) for the UI."""
        if not client:
            return {"ok": False, "error": "no client"}
        if self._window is None:
            return {"ok": False, "error": "no window"}
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        init_dir = downloads if os.path.isdir(downloads) else ""
        try:
            # webview.OPEN_DIALOG = 10 — file open, multi-select on.
            # IMPORTANT: pywebview's parse_file_type rejects any filter
            # whose description has non-word chars (slashes, commas) — it
            # silently raised "not a valid file filter" and the picker
            # appeared to do nothing. Keep descriptions word+space only.
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=init_dir,
                allow_multiple=True,
                file_types=("Importable files "
                            "(*.zip;*.jpg;*.jpeg;*.png;*.heic;*.pdf)",
                            "All files (*.*)"))
        except Exception as ex:
            return {"ok": False, "error": f"file dialog: {ex}"}
        if not result:
            return {"ok": False, "error": "", "cancelled": True}
        picked = list(result) if isinstance(result, (list, tuple)) else [result]
        # Route through do_import's WC branch (handles zip + loose,
        # split-routes by extension, converts HEIC, organizes rooms).
        # Photos honor the user-picked stage folder (dest_subfolder).
        res = self.do_import(client, "wc_attachments", picked,
                             dest_subfolder, tech=tech, side=side)
        if isinstance(res, dict):
            res["picked"] = picked
        return res

    # ── Phase 2: Pin Trello card ─────────────────────────────────────
    def search_trello(self, query: str, boards: list | None = None) -> list[dict]:
        """Trello card search by name, LIVE work first.

        Reads `card_id` (the key `find_cards_by_name` actually
        publishes) — previously read `h.get("id")` which is always
        missing in that helper's return shape, so every hit had an
        empty card_id and the pin call rejected with 'missing client
        or card_id'.

        Results are ordered by `trello_boards.sort_key`, so cards from
        the boards the office actually works come before THE LOGS and
        the AR BOARD. Those two hold 2,480 of the cards — in Trello's
        own relevance order they buried live jobs by sheer volume.
        Archived hits are still returned, just after: pinning a finished
        job is exactly when you go looking for one.

        `boards` optionally restricts the search to those board names
        (the filter UI passes the ticked ones). Empty/None = all.

        The fetch limit is raised well above the 20 shown because the
        cap applies BEFORE tiering — with 20, a common surname could
        come back as 20 LOGS cards and the live job would never be in
        the list to promote.
        """
        if not query or len(query.strip()) < 2:
            return []
        try:
            import trello_client as tc
            hits = tc.find_cards_by_name(query.strip(), max_results=60) or []
        except Exception:
            return []

        import trello_boards as tb
        wanted = {tb.normalize(b) for b in (boards or []) if b}
        out = []
        for h in hits:
            board = (h.get("board") or h.get("board_name")
                     or h.get("idBoard") or "")
            if wanted and tb.normalize(board) not in wanted:
                continue
            out.append({
                "card_id":   h.get("card_id") or h.get("id") or "",
                "name":      h.get("name") or "",
                "board":     board,
                "tier":      tb.tier(board),
                "lane":      h.get("list_name") or h.get("lane") or "",
                "short_url": h.get("url") or h.get("shortUrl") or "",
            })
        # Stable sort: Trello's relevance order survives inside a board.
        out.sort(key=lambda r: tb.sort_key(r["board"]))
        return out[:25]

    def list_search_boards(self) -> dict:
        """Boards the card search covers, tagged active/archive, for the
        filter UI. Excluded boards never appear — `list_boards` has
        already applied `trello_boards_exclude`."""
        try:
            import trello_client as tc
            import trello_boards as tb
            names = [b.get("name") or "" for b in (tc.list_boards() or [])]
            return {"ok": True, "boards": tb.classify(names)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "boards": []}

    def request_docusketch(self, client: str, card_id: str = "") -> dict:
        """Post the canonical Docusketch request comment on the
        Trello card + record the pending entry so Hygiene tracks it
        until the zip arrives. Resolution chain lives in card_resolver."""
        import card_resolver as _cr
        cid, err = _cr.resolve(client, card_id)
        if not cid:
            return {"ok": False, "error": err}
        try:
            import docusketch_requests as dr
            entry = dr.request(cid, client_name=client)
            if entry is None:
                return {"ok": False,
                        "error": f"Trello lookup failed for card {cid} (archived or no access)"}
            return {"ok": True, "card_id": cid,
                    "posted": bool(entry.get("comment_posted", True))}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def pin_trello(self, client: str, card_id: str) -> dict:
        """Pin `card_id` to `client` via persistence + refresh the
        cached row's `trello_card_id` so the detail pane reflects
        the new pin without a full re-audit."""
        if not client or not card_id:
            return {"ok": False, "error": "missing client or card_id"}
        try:
            persistence.set_trello_card_id(client, card_id)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        for r in self._last_rows:
            if r.get("client") == client:
                r["trello_card_id"] = card_id
                break
        return {"ok": True, "card_id": card_id}

    def unpin_trello(self, client: str) -> dict:
        if not client:
            return {"ok": False}
        try:
            persistence.set_trello_card_id(client, "")
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        for r in self._last_rows:
            if r.get("client") == client:
                r["trello_card_id"] = ""
        return {"ok": True}

    # ── CLOSE OUT checklist (single-sourced; Snapshot proxies these) ──
    def load_closeout_checklist(self, client: str,
                                card_id: str = "") -> dict:
        import card_resolver as _cr
        cid, err = _cr.resolve(client, card_id)
        if not cid:
            return {"ok": False, "error": err}
        try:
            import trello_client as tc
            from initial_upload_queue import (
                CLOSE_OUT_CHECKLIST_NAME, CLOSE_OUT_ITEMS_ORDER)
            card = tc.get_card(cid, actions_limit=0)
            if not card:
                return {"ok": False,
                        "error": f"Trello card {cid} not found (archived?)"}
            all_checklists = list(card.get("checklists") or [])
            other_names = [(c.get("name") or "") for c in all_checklists]
            import re as _re
            def _norm(s):
                return _re.sub(r"[^a-z]", "", (s or "").lower())
            target_norms = [_norm(a) for a in CLOSE_OUT_CHECKLIST_NAME]
            cl = None
            for cand in all_checklists:
                cn = _norm(cand.get("name") or "")
                if not cn:
                    continue
                if any(t in cn for t in target_norms):
                    cl = cand
                    break
            if cl is None:
                return {"ok": True, "card_id": cid,
                        "card_name": card.get("name") or "",
                        "checklist_id": "",
                        "items": [],
                        "missing_checklist": True,
                        "card_checklists": other_names}
            check_items = list(cl.get("checkItems") or [])
            by_norm = {}
            for it in check_items:
                by_norm[_norm(it.get("name") or "")] = it
            items = []
            used_ids = set()
            for name in CLOSE_OUT_ITEMS_ORDER:
                it = by_norm.get(_norm(name))
                if it:
                    used_ids.add(it.get("id"))
                    items.append({
                        "id":       it.get("id") or "",
                        "name":     it.get("name") or name,
                        "complete": (it.get("state") or "").lower() == "complete",
                        "missing":  False,
                        "extra":    False,
                    })
                else:
                    items.append({
                        "id":       "",
                        "name":     name,
                        "complete": False,
                        "missing":  True,
                        "extra":    False,
                    })
            for it in check_items:
                if it.get("id") in used_ids:
                    continue
                items.append({
                    "id":       it.get("id") or "",
                    "name":     it.get("name") or "",
                    "complete": (it.get("state") or "").lower() == "complete",
                    "missing":  False,
                    "extra":    True,
                })
            return {"ok": True, "card_id": cid,
                    "card_name": card.get("name") or "",
                    "checklist_id":   cl.get("id") or "",
                    "checklist_name": cl.get("name") or "",
                    "items": items,
                    "missing_checklist": False,
                    "card_checklists": other_names}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def toggle_closeout_item(self, card_id: str, item_id: str,
                             complete: bool) -> dict:
        """Round-trip a CLOSE OUT checklist item toggle to Trello."""
        if not card_id or not item_id:
            return {"ok": False, "error": "card_id + item_id required"}
        try:
            import trello_client as tc
            state = "complete" if complete else "incomplete"
            tc.set_check_item_state(card_id, item_id, state)
            return {"ok": True, "state": state}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def delete_closeout_item(self, checklist_id: str,
                             item_id: str) -> dict:
        """Delete a checklist item from Trello entirely (right-click
        'Remove' in the CLOSE OUT modal)."""
        if not checklist_id or not item_id:
            return {"ok": False, "error": "checklist_id + item_id required"}
        try:
            import trello_client as tc
            tc.delete_check_item(checklist_id, item_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Phase 2: Per-item resolved checkboxes ────────────────────────
    def get_resolved_map(self, client: str) -> dict:
        """Return {item_text: True/False} for items the user has
        already crossed off this run-doc date. Reads
        `persistence.get_resolved` for each item on the row's
        form_issues + photo_issues lists."""
        if not client:
            return {}
        row = next((r for r in self._last_rows if r["client"] == client), None)
        if not row:
            return {}
        try:
            from audit_logic import persist_key
        except Exception:
            persist_key = lambda x: x
        out = {}
        run_date = self._last_meta.get("date_iso") or ""
        for item in (row.get("form_issues") or []) + (row.get("photo_issues") or []):
            try:
                out[item] = bool(persistence.get_resolved(
                    run_date, client, persist_key(item)))
            except Exception:
                out[item] = False
        return out

    def toggle_resolved(self, client: str, item_text: str,
                         resolved: bool) -> dict:
        """Mark one missing-item row resolved (or not). Persists per
        run-date + client + item_key so a re-audit picks up the
        manual cross-off state."""
        if not client or not item_text:
            return {"ok": False}
        try:
            from audit_logic import persist_key
        except Exception:
            persist_key = lambda x: x
        run_date = self._last_meta.get("date_iso") or _dt.date.today().strftime("%Y-%m-%d")
        try:
            persistence.set_resolved(run_date, client,
                                       persist_key(item_text), bool(resolved))
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True}

    # ── Phase 2: Comment posting ─────────────────────────────────────
    def post_comment(self, client: str, text: str,
                      include_item: str = "") -> dict:
        """Post `text` as a Trello comment on the client's pinned
        card. When `include_item` is set, prefixes the comment with
        the missing-item label for traceability — mirrors the Tk
        💬 button's behavior."""
        if not client or not text:
            return {"ok": False, "error": "missing client or text"}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False,
                    "error": f"{client} has no Trello pin — pin a card first."}
        body = text.strip()
        if include_item:
            body = f"**Re: {include_item}**\n\n{body}"
        try:
            import trello_client as tc
            tc.post_comment(card_id, body)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        return {"ok": True, "card_id": card_id}

    def xa_note_members(self, client: str) -> dict:
        """Board members of the client's pinned card, for the XA-note
        '@ tag someone' dropdown."""
        try:
            card_id = persistence.get_trello_card_id(client) or ""
            if not card_id:
                return {"ok": True, "members": []}
            import trello_client as tc
            card = tc.get_card(card_id, actions_limit=0) or {}
            board_id = card.get("idBoard") or ""
            members = []
            if board_id:
                raw = tc._call(f"/boards/{board_id}/members",
                               params={"fields": "fullName,username"}) or []
                members = [{"username": m.get("username") or "",
                            "name": m.get("fullName") or m.get("username") or ""}
                           for m in raw if m.get("username")]
            return {"ok": True, "members": members}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "members": []}

    def post_xa_note(self, client: str, note: str, tag: str = "",
                     card_id: str = "") -> dict:
        """XA-note workflow: post `note` to the job's Trello card (dated +
        optional @tag) and return the note + the card's XA link, so the UI
        can copy the note to the clipboard and open XactAnalysis. One button →
        logged in Trello, copied for pasting into XA, and XA opened."""
        note = (note or "").strip()
        if not note:
            return {"ok": False, "error": "Note is empty"}
        cid = (card_id or "").strip()
        if not cid:
            try:
                cid = persistence.get_trello_card_id(client) or ""
            except Exception:
                cid = ""
        if not cid:
            return {"ok": False,
                    "error": f"{client} has no Trello pin — pin a card first."}
        import datetime as _dt
        now = _dt.datetime.now()
        stamp = (f"{now.month}/{now.day}/{now.year} "
                 f"{now.hour % 12 or 12}:{now.minute:02d} "
                 f"{'AM' if now.hour < 12 else 'PM'}")
        t = (tag or "").strip().lstrip("@")
        header = f"🗒 XA note · {stamp}" + (f" @{t}" if t else "")
        comment = f"{header}\n{note}"
        try:
            import trello_client as tc
            tc.post_comment(cid, comment)
        except Exception as ex:
            return {"ok": False, "error": f"post failed: {ex}"}
        xa_url = ""
        try:
            import trello_client as tc
            card = tc.get_card(cid) or {}
            if hasattr(tc, "card_xa_link"):
                xa_url = tc.card_xa_link(card) or ""
        except Exception:
            xa_url = ""
        return {"ok": True, "card_id": cid, "note": note, "xa_url": xa_url}

    # ── Phase 2: Flag missing dialog ─────────────────────────────────
    def flag_missing(self, client: str, item_text: str,
                      note: str = "") -> dict:
        """Record a missing-item flag in persistence + post a Trello
        comment when a card is pinned. Mirrors Tk's flag_missing_dialog
        outputs but skips the GUI form — the web side collects the
        same fields and forwards them here."""
        if not client or not item_text:
            return {"ok": False, "error": "missing client or item_text"}
        try:
            run_date = self._last_meta.get("date_iso") or _dt.date.today().strftime("%Y-%m-%d")
            try:
                from missing_items_tracker import capture_missing_items
                capture_missing_items(
                    client_name=client,
                    items=[item_text],
                    stage="audit",
                    note=note,
                    run_date=run_date)
            except Exception:
                pass
            # Also post to Trello if pinned, so the field tech / PM
            # sees the flag without opening the audit panel.
            try:
                card_id = persistence.get_trello_card_id(client) or ""
            except Exception:
                card_id = ""
            posted = False
            if card_id:
                try:
                    import trello_client as tc
                    body = f"🚩 **Flagged missing**: {item_text}"
                    if note:
                        body += f"\n\n{note}"
                    tc.post_comment(card_id, body)
                    posted = True
                except Exception:
                    posted = False
            return {"ok": True, "posted_trello": posted}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Phase 2: DocuSign request flow ───────────────────────────────
    def request_docusign(self, client: str) -> dict:
        """Mirror Tk's 'Send DocuSign via Trello' flow — finds the
        Trello card, posts the DS request comment, records a Hygiene
        pending entry. Returns the same shape on success/failure."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            from docusketch_requests import find_card_for_client
            import docusign_requests as dsr
            hit = find_card_for_client(client)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        if hit is None:
            return {"ok": False,
                    "error": f"No Trello card found for {client!r}"}
        try:
            entry = dsr.request(hit["card_id"], client_name=client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if entry is None:
            return {"ok": False, "error": "Request failed (check ems.log)"}
        return {
            "ok": True,
            "card_id":    hit.get("card_id") or "",
            "card_name":  entry.get("card_name") or "",
            "state":      entry.get("state") or "",
            "email":      entry.get("email") or "",
            "posted":     bool(entry.get("comment_posted", True)),
        }

    def _prime_folder_pins(self, rows) -> None:
        """Write every freshly-resolved row.path through to persistence
        so other call sites (post comment, list pics stages, request
        docusketch, …) that read `persistence.get_folder_path` raw see
        the path the audit just figured out. Skips clients that
        already have a user-pinned path (don't clobber a deliberate
        override that points at a different unit / property).
        """
        for r in (rows or []):
            client = (r.get("client") or "").strip()
            path = r.get("path") or ""
            if not client or not path or not os.path.isdir(path):
                continue
            try:
                existing = persistence.get_folder_path(client)
                if not existing or not os.path.isdir(existing):
                    persistence.set_folder_path(client, path)
            except Exception:
                pass

    def _resolve_client_path(self, client: str) -> str:
        """Path lookup: cached audit row → persistence → audit_jobs
        folder resolver. Returns "" when no folder maps to this
        client (caller decides what to do).

        EVERY candidate is validated against the filesystem before
        returning — without this, a folder rename / move / archive
        between the audit run and the import action left a stale
        path in `_last_rows` that this resolver kept handing back.
        Symptom: row showed "folder found" in the audit, but every
        import action said "no folder" until the user re-pinned via
        Find/Change Folder (the re-pin updated persistence, which the
        validated chain then picked up). One-off audits live in
        `_oneoff_rows` so they need to be walked too.

        Self-healing: when the audit row knows the folder but
        persistence doesn't, we write it through to persistence so
        every OTHER call site that reads `persistence.get_folder_path`
        directly (list_pics_stages, post_comment, SP-folder discovery,
        request_docusketch, etc.) starts seeing the resolved path
        without needing its own resolver-chain plumbing. The original
        symptom — "audit finds the folder but every action that isn't
        the OD folder button loses it" — was the price of having
        ~15 call sites read persistence raw.
        """
        if not client:
            return ""
        # 1. Cached audit row from the last audit run — daily + one-off.
        #    Validate isdir so a stale cached path doesn't shadow a
        #    fresh persistence pin / one-off entry.
        for r in (self._last_rows + self._oneoff_rows):
            if r.get("client") == client:
                p = r.get("path") or ""
                if p and os.path.isdir(p):
                    # Write-through to persistence so the other
                    # bare-read call sites pick up this path on their
                    # next call. Only when persistence is empty/stale —
                    # don't clobber an existing user pin (which may
                    # point at a different unit / property).
                    try:
                        existing = persistence.get_folder_path(client)
                        if not existing or not os.path.isdir(existing):
                            persistence.set_folder_path(client, p)
                    except Exception:
                        pass
                    return p
        # 2. Persistence override pin (already validates isdir).
        try:
            stored = persistence.get_folder_path(client)
            if stored and os.path.isdir(stored):
                return stored
        except Exception:
            pass
        # 3. Bail — re-audit to discover would be heavy.
        return ""

    # ── Bridge helpers ───────────────────────────────────────────────
    def _emit(self, js: str) -> None:
        """Run `js` on the home-shell window, then also forward to the
        embedded tool iframe. Event listeners in the audit panel live
        on the iframe's window (not the parent shell's), so without
        the forwarding step `audit:done` etc. fire silently into the
        wrong context — the audit loading icon spins forever.

        The forwarding rewrites `window.dispatchEvent` → the iframe's
        contentWindow.dispatchEvent. Same-origin (both served via
        the local http_server) so the access is allowed.
        """
        if self._window is None:
            return
        # Rewrite the dispatch target so the same string also fires
        # on the iframe. Wrapping in a try block keeps a failure in
        # one context from blocking the other.
        iframe_js = js.replace(
            "window.dispatchEvent(",
            "__ems_iframe_win__.dispatchEvent(")
        wrapped = (
            "(function(){"
            "try{" + js + "}catch(e){}"
            "try{"
            "var __f=document.getElementById('content-frame');"
            "if(__f && __f.contentWindow){"
            "var __ems_iframe_win__=__f.contentWindow;"
            + iframe_js +
            "}"
            "}catch(e){}"
            "})();"
        )
        try:
            self._window.evaluate_js(wrapped)
        except Exception:
            pass

    def _emit_done(self, *, ok: bool, error: str = "") -> None:
        import json
        payload = {
            "ok":   ok,
            "rows": self._last_rows if ok else [],
            "meta": self._last_meta if ok else {},
            "error": error,
        }
        # default=str catches anything that slipped past _shape_job's
        # explicit coercions (defensive — shouldn't fire in practice
        # after the datetime fix in `_shape_job`).
        payload_json = json.dumps(payload, default=str)
        self._emit(
            f"window.dispatchEvent(new CustomEvent("
            f"'audit:done', {{detail: {payload_json}}}));")


def main(argv=None):
    api = Api()
    window = webview.create_window(
        title="Audit — Linguar Hub (web spike)",
        url=INDEX_HTML,
        js_api=api,
        width=1480, height=860,
        min_size=(820, 540),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
