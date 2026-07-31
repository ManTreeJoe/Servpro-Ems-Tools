"""Dispute Tracker — Pywebview panel.

Surfaces the shared `Dispute Tracker.xlsx` (auto-seeded by APA
Monitor + dispute_email_scan). Per-row actions: edit status, copy
to clipboard, open Trello, open OneDrive folder, right-click ctx
menu via shared web_shared/ctx_menu.js.
"""
from __future__ import annotations
import os, sys, webbrowser
import datetime as _dt
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import dispute_tracker as dt

ASSETS_DIR = os.path.join(_HERE, "disputes_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


def _shape(r):
    """Flatten one dispute row to JSON-safe values."""
    out = {}
    for k, v in r.items():
        if hasattr(v, "isoformat"):
            try: out[k] = v.isoformat()
            except Exception: out[k] = str(v)
        else:
            out[k] = "" if v is None else str(v)
    out["_status"] = (out.get("Status") or out.get("status") or "").strip()
    out["_claim"]  = out.get("Claim#") or out.get("claim") or ""
    out["_insured"] = out.get("Insured") or out.get("insured") or out.get("Client") or ""
    out["_franchise"] = out.get("Franchise") or out.get("franchise") or ""
    out["_amount"] = out.get("Amount") or out.get("amount") or ""
    out["_card_id"] = out.get("trello_card_id") or out.get("Trello Card") or ""
    return out


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def all_disputes(self):
        try: rows = dt.read_rows() or []
        except Exception: rows = []
        shaped = [_shape(r) for r in rows]
        statuses = sorted({r["_status"] for r in shaped if r["_status"]})
        return {"rows": shaped, "statuses": statuses,
                "workbook": dt.path(), "total": len(shaped)}

    def open_url(self, url):
        if not url: return False
        try: webbrowser.open(url); return True
        except Exception: return False

    def open_workbook(self):
        try:
            p = dt.path()
            if p and os.path.isfile(p): os.startfile(p); return True
            return False
        except Exception:
            return False

    # ── Workbook location (move / repoint) ──────────────────────────
    def workbook_location(self) -> dict:
        """Current workbook path + whether the file actually exists."""
        p = dt.path()
        return {"path": p, "dir": os.path.dirname(p),
                "exists": bool(p and os.path.isfile(p))}

    def relocate_workbook(self) -> dict:
        """Folder picker → MOVE the Dispute Tracker workbook into the
        chosen directory and repoint config there. If a workbook already
        exists at the target, repoint without overwriting (no data loss).
        Mirrors the intent of dt.set_path's docstring (relocating once a
        copy is mirrored to X:\\IE_Public)."""
        try:
            if self._window is None:
                return {"ok": False, "error": "no window"}
            cur = dt.path()
            start_dir = os.path.dirname(cur) if cur else ""
            res = self._window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=start_dir or "", allow_multiple=False)
            if not res:
                return {"ok": False, "canceled": True}
            new_dir = res[0] if isinstance(res, (list, tuple)) else res
            if not new_dir:
                return {"ok": False, "canceled": True}
            fname = os.path.basename(cur) or "Dispute Tracker.xlsx"
            new_path = os.path.join(new_dir, fname)
            same = (os.path.normcase(os.path.abspath(new_path))
                    == os.path.normcase(os.path.abspath(cur or "")))
            if same:
                return {"ok": True, "path": cur, "moved": False,
                        "note": "Already in that folder"}
            moved = False
            if os.path.isfile(new_path):
                # Target already holds a workbook — repoint, don't clobber.
                pass
            elif os.path.isfile(cur):
                import shutil
                os.makedirs(new_dir, exist_ok=True)
                shutil.move(cur, new_path)
                moved = True
                # Best-effort: bring the pending-write sidecar along so
                # any queued (Excel-locked) writes aren't orphaned.
                try:
                    old_pending = os.path.join(
                        os.path.dirname(cur), ".pending_disputes")
                    new_pending = os.path.join(new_dir, ".pending_disputes")
                    if os.path.isdir(old_pending) and not os.path.exists(new_pending):
                        shutil.move(old_pending, new_pending)
                except Exception:
                    pass
            dt.set_path(new_path)
            return {"ok": True, "path": new_path, "moved": moved}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def point_to_workbook(self) -> dict:
        """File picker → repoint config at an EXISTING Dispute Tracker
        workbook elsewhere. Does not move or modify any file."""
        try:
            if self._window is None:
                return {"ok": False, "error": "no window"}
            res = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("Excel workbooks (*.xlsx;*.xlsm)",
                            "All files (*.*)"))
            if not res:
                return {"ok": False, "canceled": True}
            picked = res[0] if isinstance(res, (list, tuple)) else res
            if not picked:
                return {"ok": False, "canceled": True}
            dt.set_path(picked)
            return {"ok": True, "path": picked}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    # ── P1: New / Edit dispute ──────────────────────────────────────
    def column_keys(self):
        """Field schema for the new/edit dialogs. Reads from the
        dispute_tracker module's column constants so the schema can't
        drift from the actual workbook."""
        return {
            "insured":   getattr(dt, "COL_INSURED", "Insured"),
            "claim":     getattr(dt, "COL_CLAIM", "Claim#"),
            "carrier":   getattr(dt, "COL_CARRIER", "Carrier"),
            "franchise": getattr(dt, "COL_FRANCHISE", "Franchise"),
            "amount":    getattr(dt, "COL_AMOUNT", "Amount"),
            "status":    getattr(dt, "COL_STATUS", "Status"),
            "summary":   getattr(dt, "COL_SUMMARY", "Summary"),
            "estimator": getattr(dt, "COL_ESTIMATOR", "Estimator"),
        }

    def status_choices(self):
        """Allowed status values for the Status dropdown."""
        try:
            return list(dt.STATUS_OPTIONS)
        except Exception:
            return ["New", "Open", "Resolved", "Closed", "Lost", "Won"]

    def add_dispute(self, payload):
        """Insert a new dispute row. Returns {ok, was_new, row}."""
        if not isinstance(payload, dict):
            return {"ok": False, "error": "payload required"}
        if not payload.get("insured") and not payload.get("claim"):
            return {"ok": False, "error": "insured or claim# required"}
        try:
            cols = self.column_keys()
            # Map our flat payload keys to the workbook's COL_ names
            data = {}
            for k, col in cols.items():
                v = payload.get(k)
                if v is not None and str(v).strip():
                    data[col] = str(v).strip()
            was_new, row_num = dt.upsert(data, source="manual")
            return {"ok": True, "was_new": was_new, "row": row_num}
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}

    def preview_dispute_email(self, text):
        """Parse a pasted billing-dispute email WITHOUT saving — powers the
        paste dialog's live preview. Returns {ok, parsed} or {ok:False}."""
        try:
            import dispute_email_scan as des
            parsed = des.parse_billing_dispute(text or "")
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not parsed:
            return {"ok": False,
                    "error": "No line adjustments or totals found."}
        return {"ok": True, "parsed": parsed}

    def add_dispute_from_email(self, text, insured="", claim=""):
        """Parse a carrier billing-dispute email and upsert it into the
        tracker (Amount = total disputed reduction, Summary = the line-item
        breakdown). Needs an insured or claim# to key the row; returns
        need_insured + the parsed data when neither is available so the
        dialog can prompt."""
        try:
            import dispute_email_scan as des
            parsed = des.parse_billing_dispute(text or "")
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not parsed:
            return {"ok": False,
                    "error": "Doesn't look like a billing dispute — "
                             "no line adjustments or totals found."}
        ins = (insured or "").strip()
        clm = (claim or "").strip() or (parsed.get("claim") or "")
        if not ins and not clm:
            return {"ok": False, "need_insured": True, "parsed": parsed,
                    "error": "Add an insured name (or claim #) for this dispute."}
        res = self.add_dispute({
            "insured": ins, "claim": clm, "amount": parsed["amount"],
            "status": "Open", "summary": parsed["summary"],
        })
        if isinstance(res, dict) and res.get("ok"):
            res["parsed"] = parsed
        return res

    # ── Tk parity: sync from Trello disputes board + XA link ────────
    def sync_from_trello(self):
        """Background-thread sync from the Trello disputes board into
        the workbook. Mirrors dispute_tracker_gui._sync_from_trello_board.
        Streams progress via the `disputes:sync-progress` event and
        ends with `disputes:sync-done`.
        """
        import threading as _t
        if getattr(self, "_sync_running", False):
            return {"started": False, "reason": "sync already running"}
        self._sync_running = True

        def _bg():
            try:
                import web_event
                # Throttle per-card progress (Trello sync fires once per
                # card — the synchronous evaluate_js stream freezes UI).
                def _progress(i, n, name):
                    is_final = bool(n) and i >= n
                    web_event.throttled_event(
                        self._window, "disputes:sync-progress",
                        {"i": i, "n": n, "name": name},
                        final=is_final)
                result = dt.sync_from_trello_board(progress_cb=_progress)
                web_event.event(self._window, "disputes:sync-done",
                                {"ok": True, "result": result or {}})
            except Exception as ex:
                try:
                    import web_event
                    web_event.event(self._window, "disputes:sync-done",
                                    {"ok": False,
                                     "error": f"{type(ex).__name__}: {ex}"})
                except Exception:
                    pass
            finally:
                self._sync_running = False

        _t.Thread(target=_bg, daemon=True).start()
        return {"started": True}

    def export_pdf(self) -> dict:
        """Render the current dispute list to a PDF report. Uses
        reportlab — same library audit_export uses — so output is
        consistent across the tool suite."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
        except Exception as ex:
            return {"ok": False, "error": f"reportlab not available: {ex}"}
        rows = []
        try:
            rows = dt.read_rows() or []
        except Exception:
            rows = []
        if not rows:
            return {"ok": False, "error": "No disputes to export"}
        try:
            import paths
            import datetime as _dt
            out_dir = os.path.join(paths.DATA_DIR, "dispute_exports")
            os.makedirs(out_dir, exist_ok=True)
            today = _dt.date.today().strftime("%Y-%m-%d")
            out_path = os.path.join(out_dir, f"disputes_{today}.pdf")
        except Exception as ex:
            return {"ok": False, "error": f"output path: {ex}"}
        try:
            cols = self.column_keys()
            doc = SimpleDocTemplate(out_path, pagesize=letter,
                                     leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                                     topMargin=0.5 * inch, bottomMargin=0.5 * inch)
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle("T", parent=styles["Normal"],
                                          fontSize=16, fontName="Helvetica-Bold",
                                          alignment=TA_CENTER, spaceAfter=6)
            sub_style = ParagraphStyle("S", parent=styles["Normal"],
                                        fontSize=9, alignment=TA_CENTER,
                                        textColor=colors.grey, spaceAfter=14)
            data = [["Status", "Claim #", "Insured", "Franchise", "Amount", "Estimator"]]
            for r in rows:
                data.append([
                    str(r.get(cols["status"]) or "—")[:18],
                    str(r.get(cols["claim"]) or "")[:14],
                    str(r.get(cols["insured"]) or "")[:30],
                    str(r.get(cols["franchise"]) or "")[:20],
                    str(r.get(cols["amount"]) or "")[:14],
                    str(r.get(cols["estimator"]) or "")[:14],
                ])
            tbl = Table(data, repeatRows=1, colWidths=[
                0.9 * inch, 0.9 * inch, 1.9 * inch,
                1.2 * inch, 0.9 * inch, 1.1 * inch])
            tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#2E8B57")),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 8),
                ("BOX",          (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("INNERGRID",    (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                                 [colors.white, colors.HexColor("#F4F4F4")]),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]))
            import datetime as _dt
            today_str = _dt.date.today().strftime("%B %d, %Y")
            doc.build([
                Paragraph(f"Audit Disputes — {today_str}", title_style),
                Paragraph(f"{len(rows)} rows · exported from Dispute Tracker", sub_style),
                tbl,
            ])
            try: os.startfile(out_path)
            except Exception: pass
            return {"ok": True, "path": out_path, "rows": len(rows)}
        except Exception as ex:
            return {"ok": False, "error": f"PDF build: {ex}"}

    def xa_link_for(self, card_id: str) -> str:
        """Return the XactAnalysis URL attached to a Trello card."""
        if not card_id: return ""
        try:
            import trello_client as tc
            if hasattr(tc, "card_xa_link"):
                # card_xa_link parses the card DICT's desc — fetch it.
                card = tc.get_card(card_id) or {}
                return tc.card_xa_link(card) or ""
        except Exception:
            pass
        return ""

    def update_dispute(self, claim, insured, updates):
        """Update an existing dispute row identified by claim/insured.
        Walks the workbook to find the row, then updates the given
        fields. Returns {ok, row, error?}."""
        if not isinstance(updates, dict):
            return {"ok": False, "error": "updates required"}
        try:
            rows = dt.read_rows() or []
            cols = self.column_keys()
            target_row = None
            for r in rows:
                rc = (r.get(cols["claim"]) or "").strip()
                ri = (r.get(cols["insured"]) or "").strip()
                if rc == (claim or "").strip() and ri == (insured or "").strip():
                    target_row = r.get("row_number")
                    break
            if not target_row:
                return {"ok": False, "error": "row not found"}
            mapped = {}
            for k, col in cols.items():
                if k in updates:
                    mapped[col] = updates[k]
            ok = dt.update_row(target_row, mapped)
            return {"ok": ok, "row": target_row}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Right-click quick-action helpers ─────────────────────────────
    # Each mirrors the per-row context-menu items on Tk's
    # dispute_tracker_gui.py:580 _on_row_right_click. They take the
    # claim+insured tuple (the rendered row identifier) and resolve
    # the row_number internally so the frontend doesn't need to know
    # about workbook row indices.
    def _resolve_row_number(self, claim, insured):
        try:
            rows = dt.read_rows() or []
            cols = self.column_keys()
            for r in rows:
                rc = (r.get(cols["claim"]) or "").strip()
                ri = (r.get(cols["insured"]) or "").strip()
                if rc == (claim or "").strip() and ri == (insured or "").strip():
                    return r.get("row_number"), r
        except Exception:
            pass
        return None, None

    def quick_set_status(self, claim, insured, new_status):
        """One-click status transition. Auto-stamps Resolution Date
        when status flips to Closed (mirrors Tk dispute_tracker_gui.py:615)."""
        rn, _row = self._resolve_row_number(claim, insured)
        if not rn:
            return {"ok": False, "error": "row not found"}
        updates = {dt.COL_STATUS: new_status}
        if (new_status or "").lower() == "closed":
            try:
                updates.setdefault(dt.COL_RESOLUTION,
                                    _dt.date.today().isoformat())
            except Exception:
                pass
        try:
            ok = dt.update_row(rn, updates)
            return {"ok": ok, "row": rn}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def quick_set_ack(self, claim, insured, value):
        """Toggle the Ack Email Sent column. Mirrors Tk
        dispute_tracker_gui.py:625."""
        rn, _ = self._resolve_row_number(claim, insured)
        if not rn:
            return {"ok": False, "error": "row not found"}
        try:
            ok = dt.update_row(rn, {dt.COL_ACK: value})
            return {"ok": ok, "row": rn}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def delete_dispute(self, claim, insured):
        """Blank the dispute row in the workbook. Mirrors Tk
        dispute_tracker_gui.py:631 _confirm_delete (Tk also prompts
        for confirmation — the frontend does that here)."""
        rn, _ = self._resolve_row_number(claim, insured)
        if not rn:
            return {"ok": False, "error": "row not found"}
        try:
            ok = dt.delete_row(rn)
            return {"ok": ok, "row": rn}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Inquiries & Disputes — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=1280, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
