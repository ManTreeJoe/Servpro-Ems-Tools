"""Snapshot — Pywebview panel.

Full snapshot lifecycle: discover candidates (Trello SNAPSHOT lane),
intake form + Trello card prefill, parse comments → sub + log rows,
PDF generation, audit subview (per-row import / pin / Trello /
docusketch / CLOSE OUT), Tracked tab (Snapshots <YY>.xlsx viewer),
post-generate Trello attach + missing-items comment.
"""
from __future__ import annotations
import os, sys, datetime, re
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import config, persistence

ASSETS_DIR = os.path.join(_HERE, "snapshot_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


def _date_sort_key(date_str: str) -> tuple:
    """Return a sortable (year, month, day) tuple from a M/D/Y-style
    date string. Falls through to a sentinel that lands AFTER any
    real date when the string can't be parsed, so undated rows sink
    to the end (visible but not interleaved with real chronological
    data).

    Handles the formats parse_comments emits:
        "4/30"       → 4/30 of the current calendar year
        "4/30/26"    → 2026/4/30
        "4/30/2026"  → 2026/4/30
    """
    if not date_str or not isinstance(date_str, str):
        return (9999, 99, 99, 0)
    s = date_str.strip().lstrip("[").rstrip("]").strip()
    if not s:
        return (9999, 99, 99, 0)
    import re as _re, datetime as _dt
    m = _re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", s)
    if not m:
        return (9999, 99, 99, 0)
    mm = int(m.group(1))
    dd = int(m.group(2))
    if m.group(3):
        yy = int(m.group(3))
        if yy < 100:
            yy += 2000  # "26" → 2026
    else:
        # No year — assume current calendar year.
        yy = _dt.date.today().year
    return (yy, mm, dd, 0)


def _sort_rows_by_date(rows: list) -> list:
    """Stable chronological sort of {date,...} rows by the parsed
    date. Stable so rows with the same date keep input order; undated
    rows sink to the end."""
    if not rows:
        return rows
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda ir: (_date_sort_key(ir[1].get("date", "")), ir[0]))
    return [r for _i, r in indexed]


def _log_dedupe_key(row: dict) -> tuple:
    """Canonical key for log/sub row dedupe.

    Date: normalized to (year, month, day) via _date_sort_key so
    "5/28/26" and "05/28/26" collapse to the same key.

    Activity: split on " - " or "-" and lowercased to the head, so
    "Initial Inspection - slab leak" and "Initial Inspection" match.
    Run-doc emits the short form; Trello comments emit the
    detail-appended form — without this collapse they each land as
    their own row and the user sees the same event twice.
    """
    date_key = _date_sort_key(row.get("date") or "")[:3]
    act = str(row.get("activity") or "").strip()
    head = re.split(r"\s*-\s*|-", act, maxsplit=1)[0].lower().strip()
    return (date_key, head)


def _merge_log_row(existing: dict, incoming: dict) -> dict:
    """Combine two log rows that represent the same event into one.

    - activity: keep the longer/more-detailed version
    - techs: union (preserve order, drop duplicates)
    - date: keep the original format the user is more likely to read
            (the longer string — usually zero-padded "05/28/26")
    - weekday: keep the longer form ("Thursday" > "Thu")

    Mutates and returns `existing` so the caller can replace in place.
    """
    def _longer(a, b):
        a, b = (a or "").strip(), (b or "").strip()
        return a if len(a) >= len(b) else b
    existing["activity"] = _longer(existing.get("activity"),
                                     incoming.get("activity"))
    existing["weekday"]  = _longer(existing.get("weekday"),
                                     incoming.get("weekday"))
    existing["date"]     = _longer(existing.get("date"),
                                     incoming.get("date"))
    # Union techs — preserve display order, case-insensitive dedupe.
    def _split_techs(s):
        return [t.strip() for t in re.split(r"\s*,\s*|\s+\+\s+",
                                              str(s or "")) if t.strip()]
    seen, merged = set(), []
    for src in (existing.get("techs"), incoming.get("techs")):
        for t in _split_techs(src):
            k = t.lower()
            if k not in seen:
                seen.add(k)
                merged.append(t)
    existing["techs"] = ", ".join(merged)
    return existing


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def recent_snapshots(self, limit=50):
        """List PDFs in config.snapshot_output newest-mtime first."""
        try:
            cfg = config.load()
            out_dir = cfg.get("snapshot_output") or ""
        except Exception:
            out_dir = ""
        if not out_dir or not os.path.isdir(out_dir):
            return {"dir": out_dir, "rows": []}
        rows = []
        try:
            with os.scandir(out_dir) as it:
                for e in it:
                    if e.is_file() and e.name.lower().endswith(".pdf"):
                        try:
                            stat = e.stat()
                            rows.append({
                                "name":  e.name,
                                "path":  e.path,
                                "mtime": datetime.datetime.fromtimestamp(
                                    stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                                "mtime_epoch": stat.st_mtime,
                                "size_kb": int(stat.st_size / 1024),
                            })
                        except OSError:
                            pass
        except OSError:
            pass
        rows.sort(key=lambda r: -r["mtime_epoch"])
        return {"dir": out_dir, "rows": rows[:limit]}

    def open_pdf(self, path):
        if not path or not os.path.isfile(path): return False
        try: os.startfile(path); return True
        except Exception: return False

    def open_file(self, path):
        """Alias for open_pdf — exposes the same backend the audit
        panel uses so the scope-saved view JS can call it from either
        panel without branching on which Api is bound."""
        return self.open_pdf(path)

    def reveal_in_explorer(self, path):
        """Open Explorer with the file selected (highlighted) rather
        than just opening the containing folder. Lets the user see
        exactly which PDF just landed."""
        if not path or not os.path.isfile(path): return False
        try:
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return True
        except Exception:
            try: os.startfile(os.path.dirname(path)); return True
            except Exception: return False

    def read_pdf_b64(self, path):
        """Return PDF bytes base64-encoded so the JS can embed it as
        a `data:application/pdf;base64,…` URL. Capped at 10 MB to
        prevent OOM on stray huge PDFs."""
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "file not found"}
        try:
            size = os.path.getsize(path)
            if size > 10 * 1024 * 1024:
                return {"ok": False,
                        "error": f"PDF too large to preview ({size // 1024} KB)"}
            import base64
            with open(path, "rb") as fh:
                data = fh.read()
            return {"ok": True, "b64": base64.b64encode(data).decode("ascii"),
                    "size": size, "name": os.path.basename(path)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_folder(self, path):
        if not path or not os.path.isdir(path): return False
        try: os.startfile(path); return True
        except Exception: return False

    def open_od_for_client(self, client, hint_path=""):
        """Same smart-resolve path the audit + IUQ use, so a stale
        snapshot-row path doesn't silently fail when you click 📁 OD."""
        return self._aw().open_od_for_client(client, hint_path)

    def open_url(self, url):
        if not url: return False
        import webbrowser
        try: webbrowser.open(url); return True
        except Exception: return False

    # ── Trello card picker for snapshot intake ───────────────────────
    def search_trello_for_snapshot(self, query):
        """Find Trello cards matching a name query — used by the
        Snapshot intake form to pre-fill the form from a chosen card.
        Returns a flat list of {card_id, name, lane, board, short_url}."""
        if not query or len(query.strip()) < 2:
            return []
        try:
            import trello_client as tc
            return [{
                "card_id":   h.get("card_id") or h.get("id") or "",
                "name":      h.get("name") or "",
                "lane":      h.get("list_name") or h.get("lane") or "",
                "board":     h.get("board") or h.get("board_name") or "",
                "short_url": h.get("url") or h.get("shortUrl") or "",
            } for h in (tc.find_cards_by_name(query.strip()) or [])[:20]]
        except Exception:
            return []

    def snapshot_lane_candidates(self, max_n=40):
        """Surface cards in SNAPSHOT-named lanes across the user's
        boards. Uses trello_client._call directly (no public
        list-lists helper exists) — best-effort, swallows errors."""
        try:
            import trello_client as tc
            boards = tc.list_boards(exclude_quality=True) or []
            candidates = []
            for b in boards[:30]:
                bid = b.get("id")
                if not bid: continue
                try:
                    lists = tc._call(
                        f"/boards/{bid}/lists",
                        params={"fields": "id,name"}) or []
                except Exception:
                    continue
                for lst in lists:
                    name = (lst.get("name") or "").upper()
                    if "SNAPSHOT" not in name:
                        continue
                    try:
                        cards = tc.cards_in_list(lst.get("id")) or []
                    except Exception:
                        cards = []
                    for c in cards:
                        candidates.append({
                            "card_id":   c.get("id") or "",
                            "name":      c.get("name") or "",
                            "lane":      lst.get("name") or "",
                            "board":     b.get("name") or "",
                            "short_url": c.get("shortUrl") or "",
                        })
                        if len(candidates) >= max_n:
                            return candidates
            return candidates
        except Exception:
            return []

    # ── P0: Post snapshot PDF + missing-items comment to Trello ─────
    def post_snapshot_to_trello(self, client, pdf_path, missing_items=None):
        """Attach the generated PDF to the client's pinned card +
        post a consolidated 'Missing items' comment. Mirrors the Tk
        snapshot panel's post-after-generate flow.

        Returns {ok, attached, posted, error?}.
        """
        if not client:
            return {"ok": False, "error": "no client"}
        if not pdf_path or not os.path.isfile(pdf_path):
            return {"ok": False, "error": "PDF not found"}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False,
                    "error": f"{client} has no Trello pin — pin a card first."}
        attached = False
        posted = False
        try:
            import trello_client as tc
            try:
                tc.attach_file(card_id, pdf_path,
                                name=os.path.basename(pdf_path),
                                mime="application/pdf")
                attached = True
            except Exception:
                attached = False
            # Consolidated missing-items comment
            if missing_items:
                body = "📸 Snapshot generated.\n\n**Missing items:**\n"
                body += "\n".join(f"  • {m}" for m in missing_items)
            else:
                body = "📸 Snapshot generated — all items present."
            try:
                tc.post_comment(card_id, body)
                posted = True
            except Exception:
                posted = False
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, "attached": attached, "posted": posted,
                "card_id": card_id}

    # ── P1: Scope dialog + Flag missing (proxied to audit_web) ──────
    def parse_comments_blob(self, raw):
        """Parse a raw Trello-comments paste into structured snapshot
        rows. Mirrors the Tk panel's _refresh flow: pulls sub rows +
        daily log rows + first-visit + scope rooms in one pass. Lets
        the web user paste a comment dump and let the parser populate
        the snapshot form (same backend, no Tk dependency).

        Rows are chronologically sorted by parsed date before return.
        `parse_comments` walks the raw comments in their natural Trello
        order — newest activity often sits near the top of the paste
        but older catch-up notes can show up anywhere. Without a sort
        the UI rendered "4/30 after 5/20"-style out-of-order tables
        (user report 2026-05-29). Undated / unparseable rows fall to
        the end in their original order so they're still visible.
        """
        if not raw or not raw.strip():
            return {"ok": True, "subs": [], "logs": [],
                    "first_visit": "", "scope_rooms": []}
        try:
            import snapshot_logic as sg
            sub_rows, log_rows = sg.parse_comments(raw)
            first_visit = sg.detect_first_visit(raw) or ""
            scope_rooms = []
            try:
                scope_rooms = sg.parse_scope(raw) or []
            except Exception:
                scope_rooms = []
            # Sub rows from parse_comments come back as
            # (date, weekday, activity, vendor) tuples — shape to the
            # JS row format used by the snapshot form.
            subs = [{"date": d or "", "weekday": w or "",
                     "activity": a or "", "techs": v or ""}
                    for (d, w, a, v) in (sub_rows or [])]
            logs = [{"date": d or "", "weekday": w or "",
                     "activity": a or "", "techs": t or ""}
                    for (d, w, a, t) in (log_rows or [])]
            # Dedupe + merge before sort — covers the case where the
            # same event was logged in two adjacent comments with
            # slightly different wording (e.g. one comment has
            # "Initial Inspection" and a follow-up adds the detail
            # "Initial Inspection - slab leak"). See _log_dedupe_key.
            def _dd(rows):
                deduped, seen = [], {}
                for row in rows:
                    k = _log_dedupe_key(row)
                    if k in seen:
                        _merge_log_row(seen[k], row)
                    else:
                        deduped.append(row)
                        seen[k] = row
                return deduped
            subs = _sort_rows_by_date(_dd(subs))
            logs = _sort_rows_by_date(_dd(logs))
            return {"ok": True, "subs": subs, "logs": logs,
                    "first_visit": first_visit,
                    "scope_rooms": [{"name": r.get("name") or "",
                                      "items": r.get("items") or []}
                                     for r in scope_rooms]}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def parse_scope_text(self, raw):
        try:
            import audit_web as _aw
            return _aw.Api().parse_scope_text(raw)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def save_scope(self, client, rooms,
                    override_dir: str = "",
                    override_filename: str = ""):
        try:
            import audit_web as _aw
            return _aw.Api().save_scope(client, rooms,
                                         override_dir=override_dir,
                                         override_filename=override_filename)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def preview_scope_path(self, client):
        try:
            import audit_web as _aw
            return _aw.Api().preview_scope_path(client)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def pick_scope_save_dir(self, start_dir: str = ""):
        """Snapshot's window — open a folder picker on it directly so
        the dialog parents to the snapshot window (not the audit one)."""
        try:
            if self._window is None:
                return {"ok": False, "error": "no window"}
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

    def flag_missing(self, client, item_text, note=""):
        """Flag a missing item at the snapshot stage. Mirrors the
        audit_web.flag_missing but stages it as 'snapshot' so the
        Hygiene tracker shows it under SNAPSHOT chip rather than
        AUDIT/INTAKE."""
        if not client or not item_text:
            return {"ok": False, "error": "client + item required"}
        try:
            import missing_items_tracker as _mit
            _mit.capture_missing_items(
                client_name=client,
                items=[item_text],
                stage="snapshot",
                note=note)
        except Exception:
            pass
        # Post to Trello if pinned
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        posted = False
        if card_id:
            try:
                import trello_client as tc
                body = f"🚩 **Flagged missing at snapshot**: {item_text}"
                if note: body += f"\n\n{note}"
                tc.post_comment(card_id, body)
                posted = True
            except Exception:
                pass
        return {"ok": True, "posted_trello": posted}

    # ── P0: Audit subview (per-job audit inline in snapshot) ────────
    def audit_current(self, client):
        """Run the same per-client audit the Audit panel runs, shaped
        for the snapshot's inline subview. Lets the user check missing
        items before generating the PDF — no need to flip to the
        Audit tab. Reuses `audit_web.Api.reaudit_one` so the data
        format is identical to what Audit web renders."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            res = self._aw().reaudit_one(client)
            return res
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Audit-row action passthroughs ────────────────────────────────
    # Every per-row button the Audit detail view exposes (Open Trello,
    # SP import, Pin/Find folder, Flag, Docusketch, Re-audit, Match
    # diagnostic, Commercial toggle, etc.) is delegated to audit_web.Api
    # so the snapshot audit subview behaves identically. Keeps the
    # frontend's call sites unprefixed and the underlying logic single-
    # sourced — no audit/snapshot drift.
    def _aw(self):
        import audit_web as _aw_mod
        if not hasattr(self, "_aw_singleton"):
            self._aw_singleton = _aw_mod.Api()
            try: self._aw_singleton.attach(self._window)
            except Exception: pass
        return self._aw_singleton

    def open_trello_card(self, card_id):
        return self._aw().open_trello_card(card_id)
    def open_xa_link(self, client):
        return self._aw().open_xa_link(client)
    def open_companycam_link(self, client):
        return self._aw().open_companycam_link(client)
    def request_docusketch(self, client, card_id: str = ""):
        # Forward both args — the snapshot audit-subview JS calls
        # `request_docusketch(row.client, row.trello_card_id || "")`,
        # so dropping `card_id` here meant the snapshot button silently
        # failed when the audit_web side rejected the arg-count
        # mismatch. With explicit card_id pass-through, the docusketch
        # request posts the same way the daily-audit button does.
        return self._aw().request_docusketch(client, card_id)
    def reaudit_one(self, client):
        return self._aw().reaudit_one(client)
    def match_diagnostic(self, client):
        return self._aw().match_diagnostic(client)
    def set_commercial(self, client, on):
        return self._aw().set_commercial(client, on)
    def post_comment(self, client, body):
        return self._aw().post_comment(client, body)
    def escalate(self, client, role="", note=""):
        return self._aw().escalate(client, role, note)
    # Audit panel pins a folder via set_folder_path; expose with a
    # name the snapshot UI uses so the action name stays consistent
    # ("pin_folder") across panels.
    def pin_folder(self, client, path):
        return self._aw().set_folder_path(client, path)
    def list_folder_candidates(self, client, year=""):
        return self._aw().list_folder_candidates(client, year)
    def list_year_folders(self):
        return self._aw().list_year_folders()
    def list_subfolders(self, path):
        return self._aw().list_subfolders(path)
    # Per-client memory items (mirror Tk's shared right-click menu)
    def get_search_aliases(self, client):
        return self._aw().get_search_aliases(client)
    def set_search_aliases(self, client, aliases):
        return self._aw().set_search_aliases(client, aliases)
    def list_property_groups(self):
        return self._aw().list_property_groups()
    def find_property_for_folder(self, folder_basename):
        return self._aw().find_property_for_folder(folder_basename)
    def add_folder_to_property_group(self, group_name, folder_basename):
        return self._aw().add_folder_to_property_group(group_name, folder_basename)
    def remove_folder_from_property_group(self, group_name, folder_basename):
        return self._aw().remove_folder_from_property_group(group_name, folder_basename)
    def create_property_group(self, group_name, folder_basename=""):
        return self._aw().create_property_group(group_name, folder_basename)
    def clear_folder_path(self, client):
        return self._aw().clear_folder_path(client)
    def reset_client_memory(self, client):
        return self._aw().reset_client_memory(client)
    # Workcenter / DocuSign Downloads scanner (extracts zips into
    # the OD job folder split by extension — same flow IUQ uses).
    def scan_downloads_for_card(self, client):
        return self._aw().scan_downloads(client)
    def do_import(self, client, kind, zip_paths, dest_subfolder=""):
        return self._aw().do_import(client, kind, zip_paths, dest_subfolder)
    def stamp_photo_dates(self, folder, date_iso):
        return self._aw().stamp_photo_dates(folder, date_iso)
    def pick_and_import_file(self, client, dest_subfolder=""):
        # Native file picker → import any loose docs/photos the scanner
        # missed. Same handler the audit panel uses (file dialog parents
        # to the snapshot window via the shared _aw singleton).
        return self._aw().pick_and_import_file(client, dest_subfolder)
    # SP enrich passthroughs needed by the full SP modal
    def sp_cloud_only_count(self, sp_path):
        return self._aw().sp_cloud_only_count(sp_path)
    def sp_browse_for_folder(self):
        return self._aw().sp_browse_for_folder()
    def sp_reject_match(self, client, sp_path):
        return self._aw().sp_reject_match(client, sp_path)
    def sp_open_folder(self, sp_path):
        return self._aw().sp_open_folder(sp_path)
    # 📋 Copy PICS to clipboard (XA upload helper)
    def list_pics_stages(self, client):
        return self._aw().list_pics_stages(client)
    def copy_pics_to_clipboard(self, client, stage=""):
        return self._aw().copy_pics_to_clipboard(client, stage)
    # 📎 Trello attachments manager
    def list_card_attachments(self, card_id):
        return self._aw().list_card_attachments(card_id)
    def fetch_trello_image(self, url):
        return self._aw().fetch_trello_image(url)
    def download_card_attachments(self, card_id, attachment_ids, client=""):
        return self._aw().download_card_attachments(card_id, attachment_ids, client)
    # SharePoint import flow
    def sp_find_matches(self, client, unit=""):
        return self._aw().sp_find_matches(client, unit)
    def property_structure(self, client):
        return self._aw().property_structure(client)
    def set_property_settings(self, client, is_commercial=None, aliases=None):
        return self._aw().set_property_settings(client, is_commercial, aliases)
    def list_day_units(self, client):
        return self._aw().list_day_units(client)
    def set_day_units(self, client, paths):
        return self._aw().set_day_units(client, paths)
    def sp_copy_to_pics(self, client, sp_path, target_pics, job_path):
        return self._aw().sp_copy_to_pics(client, sp_path, target_pics, job_path)
    def sp_pin_folder(self, client, sp_path):
        return self._aw().sp_pin_folder(client, sp_path)
    def sp_force_pull(self, sp_path):
        return self._aw().sp_force_pull(sp_path)
    def sp_cloud_only_count(self, sp_path):
        return self._aw().sp_cloud_only_count(sp_path)
    def sp_mark_in_od(self, client, sp_path):
        return self._aw().sp_mark_in_od(client, sp_path)
    # Trello hover popover (60s cache lives on audit_web)
    def trello_card_hover(self, card_id):
        return self._aw().trello_card_hover(card_id)
    def clear_trello_hover_cache(self):
        return self._aw().clear_trello_hover_cache()

    # ── P0: Close-out (mark drafted) ────────────────────────────────
    def mark_closeout_drafted(self, client):
        """Mark the snapshot drafted in persistence so the Hygiene
        closeout_watcher stops nagging on this card. Mirrors the Tk
        Hygiene panel's "Mark drafted" button."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            card_id = persistence.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False,
                    "error": f"No Trello pin for {client}"}
        try:
            import closeout_watcher as cw
            cw.mark_drafted(card_id)
            return {"ok": True, "card_id": card_id}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Generation flow ──────────────────────────────────────────────
    def candidate_jobs(self):
        """Jobs the user might want to snapshot — cards in the
        Estimating board's SNAPSHOT lane. Only that source: the
        user explicitly asked NOT to mix in run-doc jobs (those
        belong to the Daily Run audit + Photo Folders panels, not
        here). Walks every board whose name contains 'ESTIMATING'
        (handles 'Estimating - 2026' etc.) and pulls every lane
        whose name contains 'SNAPSHOT'.
        """
        out = []
        seen = set()
        try:
            import trello_client as tc
            boards = tc.list_boards(exclude_quality=True) or []
            for b in boards[:30]:
                bn = (b.get("name") or "").upper()
                if "ESTIMATING" not in bn:
                    continue
                bid = b.get("id")
                if not bid: continue
                try:
                    lists = tc._call(
                        f"/boards/{bid}/lists",
                        params={"fields": "id,name"}) or []
                except Exception:
                    continue
                for lst in lists:
                    lane_name = lst.get("name") or ""
                    if "SNAPSHOT" not in lane_name.upper():
                        continue
                    try:
                        cards = tc.cards_in_list(lst.get("id")) or []
                    except Exception:
                        cards = []
                    for c in cards:
                        client = (c.get("name") or "").strip()
                        if not client or client.lower() in seen:
                            continue
                        seen.add(client.lower())
                        out.append({
                            "client":  client,
                            "source":  "estimating",
                            "card_id": c.get("id") or "",
                            "lane":    lane_name,
                            "board":   b.get("name") or "",
                            "short_url": c.get("shortUrl") or "",
                        })
        except Exception:
            pass
        return out

    # ── 📋 CLOSE OUT checklist (mirrors Tk open_close_out_dialog) ──
    # Resolves the client's Trello card, finds its CLOSE OUT (or
    # CLOSE OUT - ADMIN) checklist, returns the 6 items with their
    # current state so the snapshot UI can render toggleable rows.
    # Sources the canonical name/order from initial_upload_queue so
    # the two surfaces never drift.
    def load_closeout_checklist(self, client: str,
                                card_id: str = "") -> dict:
        # Single resolution chain shared with every other Trello
        # flow (Docusketch, attachments, post comment) — see
        # card_resolver.resolve for the chain definition.
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
            # All checklist names — surfaced in the response so the
            # frontend can show "card has these checklists: …" when
            # nothing matches, helping the user spot a naming quirk.
            other_names = [(c.get("name") or "") for c in all_checklists]
            # Find the first checklist whose name matches a close-out
            # alias (case + punctuation insensitive). Accepts "Close
            # Out", "CLOSE-OUT", "Closeout", "CLOSE OUT - ADMIN",
            # "Close Out Checklist", etc.
            import re as _re
            def _norm(s):
                return _re.sub(r"[^a-z]", "", (s or "").lower())
            target_norms = [_norm(a) for a in CLOSE_OUT_CHECKLIST_NAME]
            cl = None
            for cand in all_checklists:
                cn = _norm(cand.get("name") or "")
                if not cn: continue
                # Match if the candidate's normalized name STARTS WITH
                # or CONTAINS the close-out alias — catches "closeout",
                # "closeoutadmin", "closeoutchecklist", etc.
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
            # Render items in canonical order. Add any items on the
            # checklist that AREN'T in the canonical list at the end
            # so the user can see them (and delete them via right-
            # click). Same map for both passes.
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
            # Append any extra items on the checklist that aren't in
            # the canonical set — keeps the UI honest with what's
            # actually on the card.
            for it in check_items:
                if it.get("id") in used_ids: continue
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
        """Delete a checklist item from Trello entirely. Used by the
        right-click 'Remove' option in the CLOSE OUT modal — for when
        an item is no longer relevant for this job."""
        if not checklist_id or not item_id:
            return {"ok": False, "error": "checklist_id + item_id required"}
        try:
            import trello_client as tc
            tc.delete_check_item(checklist_id, item_id)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Tracked snapshots (Snapshots workbook view) ─────────────────
    # Reads the Snapshots <YY>.xlsx (snapshots_excel.read_jobs) and
    # surfaces every row across NEW LOSS / Completed / Incomplete so
    # the snapshot panel can show a "📋 Tracked" tab styled like the
    # disputes table — cleaner than the raw Excel viewer.
    def tracked_snapshots(self, year: int = 0) -> dict:
        try:
            import snapshots_excel as sx
            import datetime as _dt
            y = int(year) if year else _dt.date.today().year
            rows = sx.read_jobs(y) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "rows": []}
        # Shape for the frontend — keep the canonical column names so
        # the table renderer can read them by header.
        out = []
        for r in rows:
            out.append({
                "sheet":         r.get("_sheet") or "",
                "received":      str(r.get("Date Received") or "")[:10],
                "name":          str(r.get("Name") or "").strip(),
                "closing":       str(r.get("Closing Date") or "")[:10],
                "comment":       (str(r.get("Comment") or "").strip())[:200],
                "type_of_loss":  str(r.get("Type of Loss") or "").strip(),
                "claim":         str(r.get("Claim#") or "").strip(),
                "carrier":       str(r.get("Carrier") or "").strip(),
                "folder":        str(r.get("Folder") or "").strip(),
                "inspection":    str(r.get("Inspection") or "").strip(),
                "initial_photos":str(r.get("Initial Photos") or "").strip(),
                "demo_start":    str(r.get("Demo Start") or "").strip(),
                "scope":         str(r.get("Scope") or "").strip(),
                "final_photos":  str(r.get("Final Photos") or "").strip(),
                "atp":           str(r.get("ATP") or "").strip(),
                "cif":           str(r.get("CIF") or "").strip(),
                "cer":           str(r.get("CER") or "").strip(),
                "cos":           str(r.get("COS") or "").strip(),
                "addl_docs":     str(r.get("Add'l Docs") or "").strip(),
            })
        return {"ok": True, "rows": out, "year": y,
                "total": len(out),
                "by_sheet": {
                    "NEW LOSS":   sum(1 for r in out if r["sheet"] == "NEW LOSS"),
                    "Completed":  sum(1 for r in out if r["sheet"] == "Completed"),
                    "Incomplete": sum(1 for r in out if r["sheet"] == "Incomplete"),
                    "Needs Attention": sum(1 for r in out if r["sheet"] == "Needs Attention"),
                }}

    def update_tracked_row(self, name: str, fields: dict,
                            year: int = 0) -> dict:
        """Hand-edit cells on a tracked row (Carrier / Claim# / Type of
        Loss / dates / Comment / yes-no columns). `fields` is a
        {column_name: value} map; only whitelisted columns are written.
        Returns {ok, updated, error}. Used by the Tracked tab ✎ Edit
        dialog."""
        import datetime as _dt
        if not name or not name.strip():
            return {"ok": False, "error": "no name"}
        if not isinstance(fields, dict) or not fields:
            return {"ok": False, "error": "no fields"}
        yr = int(year) if year else _dt.date.today().year
        try:
            import snapshots_excel as sx
            return sx.update_row_fields(name.strip(), fields, year=yr)
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def move_tracked_row(self, name: str, target_sheet: str,
                          year: int = 0) -> dict:
        """Move a tracked row to another sheet (NEW LOSS / Completed /
        Incomplete / Needs Attention). The headline Tracked-tab edit:
        manual re-sheeting when the auto-route got it wrong. Returns
        {ok, error}."""
        import datetime as _dt
        if not name or not name.strip():
            return {"ok": False, "error": "no name"}
        try:
            import snapshots_excel as sx
            if target_sheet not in sx._ALL_SHEETS:
                return {"ok": False,
                        "error": f"unknown sheet: {target_sheet!r}"}
            yr = int(year) if year else _dt.date.today().year
            ok = sx.move_existing_row(name.strip(), target_sheet, year=yr)
            if not ok:
                return {"ok": False,
                        "error": "row not found or workbook is open in Excel"}
            return {"ok": True, "sheet": target_sheet}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def open_trello_for_tracked(self, name: str) -> dict:
        """Resolve a tracked-snapshot row's `name` to its Trello card
        (pinned first, then fuzzy search via client_search_terms)
        and open the card in the browser. Used by the Tracked tab's
        click-row-to-open-Trello flow."""
        if not name or not name.strip():
            return {"ok": False, "error": "no name"}
        try:
            import snapshots_excel as sx
            card_id, err = sx._resolve_card_for_client(name.strip())
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not card_id:
            return {"ok": False,
                    "error": err or f"no Trello card found for '{name.strip()}'"}
        try:
            import webbrowser
            webbrowser.open(f"https://trello.com/c/{card_id}")
            return {"ok": True, "card_id": card_id}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_tracked_workbook(self, year: int = 0) -> bool:
        """Open the Snapshots <YY>.xlsx in Excel — used by the
        Tracked tab's "📊 Open Excel" button."""
        try:
            import snapshots_excel as sx
            import datetime as _dt
            y = int(year) if year else _dt.date.today().year
            p = sx.workbook_path(y)
            if not p or not os.path.isfile(p):
                return False
            os.startfile(p)
            return True
        except Exception:
            return False

    # ── Tracking workbook location (change folder) ──────────────────
    def tracking_location(self) -> dict:
        """Current Snapshots-tracking root dir + this year's workbook."""
        try:
            import snapshots_excel as sx
            import datetime as _dt
            y = _dt.date.today().year
            root = sx.get_root()
            wb = sx.workbook_path(y)
            return {"root": root, "year": y, "workbook": wb,
                    "root_exists": bool(root and os.path.isdir(root)),
                    "workbook_exists": bool(wb and os.path.isfile(wb))}
        except Exception as ex:
            return {"error": str(ex)}

    def change_tracking_dir(self) -> dict:
        """Folder picker → repoint the Snapshots-tracking root (persisted
        to config). If the new folder has no Snapshots workbooks yet but
        the old one does, MOVE the existing `Snapshots *.xlsx` files (and
        the `.pending` sidecar) so tracking history follows. If the new
        folder already has them, just repoint — nothing is overwritten."""
        try:
            if self._window is None:
                return {"ok": False, "error": "no window"}
            import snapshots_excel as sx
            import glob as _glob
            import shutil as _shutil
            cur = sx.get_root()
            res = self._window.create_file_dialog(
                webview.FOLDER_DIALOG, directory=cur or "",
                allow_multiple=False)
            if not res:
                return {"ok": False, "canceled": True}
            new_dir = res[0] if isinstance(res, (list, tuple)) else res
            if not new_dir:
                return {"ok": False, "canceled": True}
            if (os.path.normcase(os.path.abspath(new_dir))
                    == os.path.normcase(os.path.abspath(cur or ""))):
                return {"ok": True, "root": cur, "moved": 0,
                        "note": "Already that folder"}
            moved = 0
            try:
                existing_new = _glob.glob(
                    os.path.join(new_dir, "Snapshots *.xlsx"))
                if not existing_new and cur and os.path.isdir(cur):
                    os.makedirs(new_dir, exist_ok=True)
                    for f in _glob.glob(
                            os.path.join(cur, "Snapshots *.xlsx")):
                        dest = os.path.join(new_dir, os.path.basename(f))
                        if not os.path.exists(dest):
                            _shutil.move(f, dest)
                            moved += 1
                    old_pending = os.path.join(cur, ".pending")
                    new_pending = os.path.join(new_dir, ".pending")
                    if (os.path.isdir(old_pending)
                            and not os.path.exists(new_pending)):
                        _shutil.move(old_pending, new_pending)
            except Exception:
                pass  # best-effort move; the repoint below still applies
            sx.set_root(new_dir)
            return {"ok": True, "root": new_dir, "moved": moved}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── Reconcile NEW LOSS → Completed against Trello ────────────────
    def reconcile_tracked(self, year: int = 0) -> dict:
        """Walk the Snapshots workbook + move each row to the sheet its
        Trello card says it belongs in — so jobs whose card is closed
        (on the AR or LOGS board, archived, or in a terminal lane) leave
        NEW LOSS. Rows the reconciler can't resolve (no matching Trello
        card / unclassifiable) are moved to the Needs Attention sheet.
        Backgrounded with a progress/done event stream so the (network-
        heavy, per-row) walk doesn't freeze the UI. Emits
        `snap:recon-progress` / `snap:recon-done`."""
        import threading as _t
        import datetime as _dt
        if getattr(self, "_recon_running", False):
            return {"started": False, "reason": "reconcile already running"}
        self._recon_running = True
        yr = int(year) if year else _dt.date.today().year

        def _bg():
            payload = {"ok": False}
            try:
                import snapshots_excel as se
                import web_event

                def _prog(i, total, name):
                    try:
                        web_event.throttled_event(
                            self._window, "snap:recon-progress",
                            {"label": name, "done": i, "total": total},
                            final=bool(total) and i >= total)
                    except Exception:
                        pass
                result = se.reconcile_with_trello(yr, progress_cb=_prog)
                payload = {"ok": True, "result": result}
            except Exception as ex:
                payload = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
            finally:
                self._recon_running = False
                try:
                    import web_event
                    web_event.event(self._window, "snap:recon-done", payload)
                except Exception:
                    pass

        _t.Thread(target=_bg, daemon=True).start()
        return {"started": True, "year": yr}

    def docusign_email(self, insured: str = "", card_id: str = "") -> dict:
        """Build the closeout DocuSign request email body for the insured,
        auto-filling the property city from the Trello card's address.
        Returns {ok, text, city}. The city is "" when no card/address is
        available — the body just drops the '…in <city>' clause."""
        try:
            import docusign_requests as dsr
            city = ""
            if card_id:
                try:
                    import trello_client as tc
                    card = tc.get_card(card_id, actions_limit=0)
                    fields = (tc.parse_card_desc((card or {}).get("desc"))
                              if card else {}) or {}
                    addr = ""
                    for sect in ("CUSTOMER INFORMATION", "PROPERTY DETAILS"):
                        blk = fields.get(sect) or {}
                        for k in ("PROPERTY ADDRESS", "ADDRESS", "LOSS ADDRESS"):
                            if (blk.get(k) or "").strip():
                                addr = blk[k].strip()
                                break
                        if addr:
                            break
                    city = dsr.city_from_address(addr)
                except Exception:
                    city = ""
            return {"ok": True, "text": dsr.customer_email_text(city),
                    "city": city}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_auto_reconcile(self) -> bool:
        """Whether the Tracked tab auto-reconciles with Trello on load."""
        try:
            return bool(config.load().get("snapshot_auto_reconcile"))
        except Exception:
            return False

    def set_auto_reconcile(self, enabled: bool) -> dict:
        """Persist the auto-reconcile-on-open preference."""
        try:
            cfg = config.load()
            cfg["snapshot_auto_reconcile"] = bool(enabled)
            config.save(cfg)
            return {"ok": True, "enabled": bool(enabled)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def prefill_from_trello_card(self, card_id, client_fallback=""):
        """Pull EVERY auto-fillable field from a Trello card — mirrors
        what the Tk snapshot does in HygieneApp._fetch_trello_card_and_fill.

        Parses card desc (CUSTOMER / INSURANCE / PROPERTY blocks),
        walks the paged comments + Subs checklist, runs the snapshot
        field-rules helper to derive carrier_line / commercial flag,
        and uses detect_first_visit() to pin down the earliest
        Initial Inspection date from the comments. Result merges
        with the run-doc-based log prefill so the user lands on a
        fully populated form when they pick a card from search.
        """
        if not card_id:
            return self.prefill_for(client_fallback or "")
        out = {"insured": "", "carrier": "", "dol": "",
               "first_visit": "", "cause": "", "claim": "",
               "subs": [], "logs": [], "card_id": card_id,
               "folder": "", "comments": ""}
        try:
            import trello_client as tc
            import snapshot_logic as sg
            card = tc.get_card(card_id) or {}
            fields = tc.parse_card_desc(card.get("desc") or "") or {}
            cust = fields.get("CUSTOMER INFORMATION", {}) or {}
            ins  = fields.get("INSURANCE INFORMATION", {}) or {}
            prop = fields.get("PROPERTY DETAILS", {}) or {}
            customer_name = (cust.get("CUSTOMER NAME") or "").strip()
            card_title    = (card.get("name") or "").strip()
            carrier_raw   = (ins.get("INSURANCE COMPANY") or "").strip()
            claim         = (ins.get("CLAIM NUMBER") or "").strip()
            dol           = (prop.get("DATE OF LOSS") or "").strip()
            cause_raw     = (prop.get("CAUSE OF LOSS") or "").strip()

            # Paged comment fetch — matches Tk behavior so older
            # comments on long-running jobs aren't truncated.
            try:
                comment_actions = tc.get_all_comments(card_id) or []
            except Exception:
                comment_actions = [a for a in (card.get("actions") or [])
                                   if a.get("type") == "commentCard"]
            comment_actions.reverse()
            blocks = []
            for k, v in (fields.get("NOTES") or {}).items():
                if v: blocks.append(f"{k.title()}: {v}")
            for a in comment_actions:
                who  = ((a.get("memberCreator") or {}).get("fullName") or "?")
                when = ""
                try: when = tc._fmt_action_date(a.get("date", ""))
                except Exception: pass
                body = (a.get("data", {}).get("text") or "").strip()
                if body:
                    blocks.append(f"{who} · {when}\n{body}")
            comments_text = "\n\n".join(blocks)

            # Subs-checklist fallback (case-insensitive match on name)
            subs_fallback = []
            for cl in (card.get("checklists") or []):
                if (cl.get("name") or "").strip().lower() == "subs":
                    for it in (cl.get("checkItems") or []):
                        txt = (it.get("name") or "").strip()
                        if txt: subs_fallback.append(txt)

            # Field-rules helper derives insured / carrier_line /
            # cause from the title + customer name + carrier + claim
            # + scan-text combo. Same routine Tk uses, so output is
            # byte-identical.
            scan_text = "\n".join([comments_text,
                                    "\n".join(subs_fallback)])
            insured, carrier_line, cause, _customer_for_header = (
                sg.apply_snapshot_field_rules(
                    job_title=card_title,
                    customer_name=customer_name,
                    carrier=carrier_raw, claim=claim,
                    cause=cause_raw, scan_text=scan_text))

            first_visit = ""
            try:
                fv = sg.detect_first_visit(comments_text)
                if fv: first_visit = fv
            except Exception:
                pass

            out.update({
                "insured":     insured or customer_name or card_title or client_fallback,
                "carrier":     carrier_line,
                "claim":       claim,
                "dol":         dol,
                "first_visit": first_visit,
                "cause":       cause,
                "comments":    comments_text,
            })

            # Run the same comment parser the Tk panel uses so the
            # daily-log table AND comment-derived sub rows populate
            # from the Trello comment stream. Mirrors snapshot_gui's
            # _parse_and_preview flow: parse_comments → (subs, logs)
            # → merge Subs checklist as ground-truth, deduped by
            # vendor.
            parsed_subs, parsed_logs = [], []
            try:
                parsed_subs, parsed_logs = sg.parse_comments(comments_text)
            except Exception:
                parsed_subs, parsed_logs = [], []

            # parse_comments returns (date, weekday, activity, vendor)
            # for subs, (date, weekday, activity, techs) for logs.
            def _vendor_key(text):
                head = re.split(r"\s*-\s*|-", str(text or ""), maxsplit=1)[0]
                return head.strip().lower()
            already = set()
            for (d_, w_, a_, v_) in (parsed_subs or []):
                out["subs"].append({"date": d_ or "", "weekday": w_ or "",
                                    "activity": a_ or "", "techs": v_ or ""})
                already.add(_vendor_key(v_ or a_))
            # Merge Subs checklist (ground truth) on top — dedupe by
            # vendor against comment-parsed rows. Use the checklist
            # item's full text as the activity; vendor in techs col.
            for txt in subs_fallback:
                v = _vendor_key(txt)
                if v and v not in already:
                    out["subs"].append({"date": "", "weekday": "",
                                        "activity": txt,
                                        "techs": v.title()})
                    already.add(v)

            for (d_, w_, a_, t_) in (parsed_logs or []):
                out["logs"].append({"date": d_ or "", "weekday": w_ or "",
                                    "activity": a_ or "", "techs": t_ or ""})
        except Exception as ex:
            out["error"] = f"{type(ex).__name__}: {ex}"

        # Merge run-doc logs from prefill_for so daily-log table also
        # populates. Trello comments emit "Initial Inspection - slab
        # leak" on date "5/28/26" while the run-doc emits "Initial
        # Inspection" on date "05/28/26" — string-equal dedupe missed
        # them both, dropping a duplicate row in the UI. _log_dedupe_key
        # normalizes the date (year/month/day tuple) AND the activity
        # head (split on " - "), so the two collapse to one entry.
        # When a duplicate IS detected we MERGE techs + keep the
        # longer activity instead of discarding — the run-doc usually
        # knows different techs than the Trello card, so dropping it
        # entirely would lose data.
        try:
            run_doc_data = self.prefill_for(out["insured"] or client_fallback or "")
            existing_by_key = {_log_dedupe_key(l): l for l in out["logs"]}
            for r in (run_doc_data.get("logs") or []):
                k = _log_dedupe_key(r)
                if k in existing_by_key:
                    _merge_log_row(existing_by_key[k], r)
                else:
                    out["logs"].append(r)
                    existing_by_key[k] = r
            if not out["folder"]:
                out["folder"] = run_doc_data.get("folder") or ""
        except Exception:
            pass

        # Final dedupe sweep against out["logs"] AND out["subs"] —
        # catches duplicates already present in the Trello parsing
        # step (parse_comments occasionally yields adjacent rows for
        # the same event when the tech logged it in two comments).
        # Idempotent: a single-pass list with no dupes survives
        # untouched.
        for bucket_key in ("logs", "subs"):
            deduped, seen = [], {}
            for row in (out.get(bucket_key) or []):
                k = _log_dedupe_key(row)
                if k in seen:
                    _merge_log_row(seen[k], row)
                else:
                    deduped.append(row)
                    seen[k] = row
            out[bucket_key] = deduped

        try:
            out["folder"] = (out["folder"]
                or persistence.get_folder_path(out["insured"] or client_fallback or "")
                or "")
        except Exception:
            pass

        # ── Auto-pin the Trello card to the resolved insured name ──
        # When the user picks a card from the snapshot search, the
        # downstream flows (Open Trello, Docusketch, CLOSE OUT,
        # Post comment) look up the pin via persistence — they
        # shouldn't have to fuzzy-search again. Pin only when no
        # existing pin is set so a manual override stays sticky.
        pin_name = (out["insured"] or client_fallback or "").strip()
        if pin_name and card_id:
            try:
                existing = persistence.get_trello_card_id(pin_name) or ""
                if not existing:
                    persistence.set_trello_card_id(pin_name, card_id)
                    out["auto_pinned"] = True
                else:
                    out["auto_pinned"] = False
            except Exception:
                out["auto_pinned"] = False
        return out

    def prefill_for(self, client):
        """Pull what we can auto-fill for a snapshot — carrier, DOL,
        recent log entries from the audit history, pinned card, etc."""
        if not client:
            return {}
        out = {"insured": client, "carrier": "", "dol": "",
               "first_visit": "", "cause": "", "subs": [], "logs": [],
               "card_id": "", "folder": ""}
        try:
            out["card_id"] = persistence.get_trello_card_id(client) or ""
        except Exception:
            pass
        try:
            out["folder"] = persistence.get_folder_path(client) or ""
        except Exception:
            pass
        # Recent run-doc entries → pre-fill the daily log table
        try:
            import datetime as _dt
            import run_audit_gui as _rag
            from state_hub import hub as _sh
            today = _dt.date.today()
            for back in range(0, 28):
                d = today - _dt.timedelta(days=back)
                doc = _rag._find_run_doc_for_date(d)
                if not doc:
                    continue
                jobs, _ = _sh.parse_run_doc(doc)
                for j in jobs:
                    if (j.get("client") or "").strip().lower() == client.strip().lower():
                        # Activity labels for this row
                        try:
                            import audit_logic
                            info = audit_logic.detect_activity(
                                j.get("raw") or "",
                                section=j.get("section"),
                                new_loss=j.get("new_loss"))
                            act = ", ".join(info.get("labels") or [])
                        except Exception:
                            act = ""
                        out["logs"].append({
                            "date":     d.strftime("%m/%d/%y"),
                            "weekday":  d.strftime("%a"),
                            "activity": act,
                            "techs":    "/".join(j.get("techs") or []),
                        })
        except Exception:
            pass
        # Keep newest-first
        out["logs"].reverse()
        return out

    def check_multi_unit(self, insured: str) -> dict:
        """Mirrors snapshot_gui._multi_unit_gate. When `insured`
        resolves to a multi-unit umbrella (≥2 sibling units in
        ems_db), return the unit list so the frontend can show a
        picker. Returns `{multi_unit: false}` for normal jobs so
        the caller proceeds straight to generate.
        """
        if not insured:
            return {"multi_unit": False}
        try:
            import ems_db
        except Exception:
            return {"multi_unit": False}
        units = []
        property_name = ""
        came_in_as = "umbrella"
        try:
            # Path 1: typed the umbrella ("Avila Apartments")
            umbrella_units = ems_db.find_units_of(
                ems_db.canon_key(insured)) or []
            if len(umbrella_units) >= 2:
                units = umbrella_units
                property_name = insured
                came_in_as = "umbrella"
        except Exception:
            umbrella_units = []
        if not units:
            try:
                # Path 2: typed a unit — find siblings via parent
                prop_name, _unum = ems_db.detect_property_and_unit(insured)
                if prop_name:
                    parent_canon = ems_db.canon_key(prop_name)
                    sibs = ems_db.find_units_of(parent_canon) or []
                    if len(sibs) >= 2:
                        units = sibs
                        property_name = prop_name
                        came_in_as = insured
            except Exception:
                pass
        if not units:
            return {"multi_unit": False}
        return {
            "multi_unit":     True,
            "property_name":  property_name,
            "came_in_as":     came_in_as,
            "units": [
                {"unit_number":  (u.get("unit_number") if isinstance(u, dict)
                                  else getattr(u, "unit_number", "")) or "",
                 "display_name": (u.get("display_name") if isinstance(u, dict)
                                  else getattr(u, "display_name", "")) or "",
                 "canon_key":    (u.get("canon_key") if isinstance(u, dict)
                                  else getattr(u, "canon_key", "")) or ""}
                for u in units],
        }

    def generate(self, payload):
        """Generate the snapshot PDF from form data. Returns
        {ok, path, error?}. Reuses snapshot_gui.fill_pdf +
        snapshot_gui.append_overflow_pages so the output is
        byte-identical to what the Tk panel produces.
        """
        if not isinstance(payload, dict):
            return {"ok": False, "error": "bad payload"}
        insured = (payload.get("insured") or "").strip()
        if not insured:
            return {"ok": False, "error": "Insured name is required"}
        carrier = payload.get("carrier") or ""
        dol     = payload.get("dol") or ""
        first   = payload.get("first_visit") or ""
        cause   = payload.get("cause") or ""
        subs    = payload.get("subs") or []
        logs    = payload.get("logs") or []

        try:
            import snapshot_logic as sg
        except Exception as ex:
            return {"ok": False, "error": f"snapshot_logic import failed: {ex}"}

        data = {
            "insured_job":          insured,
            "carrier_claim":        carrier,
            "date_of_loss":         dol,
            "first_site_visit":     first,
            "cause_category_class": cause,
            "subs_used":            "Y" if subs else "N",
        }
        sub_cap = getattr(sg, "SNAPSHOT_TEMPLATE_SUBS_MAX", 8)
        log_cap = getattr(sg, "SNAPSHOT_TEMPLATE_LOGS_MAX", 53)
        for i, r in enumerate(subs[:sub_cap], 1):
            data[f"sub_date_{i}"]     = (r.get("date") or "").strip()
            data[f"sub_weekday_{i}"]  = (r.get("weekday") or "").strip()
            data[f"sub_activity_{i}"] = (r.get("activity") or "").strip()
            data[f"sub_techs_{i}"]    = (r.get("techs") or "").strip()
        for i, r in enumerate(logs[:log_cap], 1):
            data[f"log_date_{i}"]     = (r.get("date") or "").strip()
            data[f"log_weekday_{i}"]  = (r.get("weekday") or "").strip()
            data[f"log_activity_{i}"] = (r.get("activity") or "").strip()
            data[f"log_techs_{i}"]    = (r.get("techs") or "").strip()

        # Sanitize filename — same Windows-illegal-char strip the Tk
        # version applies.
        import re as _re
        safe = _re.sub(r'[\\/:*?"<>|]', "-", insured).strip(" .-") or "snapshot"

        try:
            cfg = config.load()
            out_dir = cfg.get("snapshot_output") or ""
        except Exception:
            out_dir = ""
        if not out_dir:
            return {"ok": False, "error": "snapshot_output not configured"}
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as ex:
            return {"ok": False, "error": f"folder error: {ex}"}
        output_path = os.path.join(out_dir, f"{safe}.pdf")

        try:
            sg.fill_pdf(data, output_path)
            # Overflow continuation pages if there were >cap rows
            sub_overflow = subs[sub_cap:]
            log_overflow = logs[log_cap:]
            if sub_overflow or log_overflow:
                try:
                    sg.append_overflow_pages(
                        output_path,
                        [(r.get("date") or "", r.get("weekday") or "",
                          r.get("activity") or "", r.get("techs") or "")
                         for r in sub_overflow],
                        [(r.get("date") or "", r.get("weekday") or "",
                          r.get("activity") or "", r.get("techs") or "")
                         for r in log_overflow],
                        insured=insured)
                except Exception:
                    pass  # main PDF still produced
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
        # Auto-mark the Trello card as "snapshot drafted" so the
        # Closeout Hygiene section stops nagging this client.
        # Mirrors snapshot_gui.py:4679 — generating IS the strongest
        # possible "done" signal, no manual click required.
        try:
            card_id = persistence.get_trello_card_id(insured) or ""
            if card_id:
                import closeout_watcher as _cw
                _cw.mark_drafted(card_id)
        except Exception:
            pass
        return {"ok": True, "path": output_path,
                "rows_logs": len(logs), "rows_subs": len(subs)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Snapshot — EMS Tools (web)",
        url=INDEX_HTML, js_api=api,
        width=1200, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
