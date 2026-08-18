"""Cheat Sheet — Pywebview spike (markdown viewer)."""
from __future__ import annotations
import os, sys
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import cheat_sheet_logic as cs   # pure parser; NOT the Tk panel
import paths

ASSETS_DIR = os.path.join(_HERE, "cheat_sheet_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def sections(self):
        try:
            md_path = paths.resource("EMS_Admin_Cheat_Sheet.md")
            return cs.parse_markdown(md_path)
        except Exception:
            return []

    # ── My Shortcuts — the user's own links and copy buttons ─────────
    #
    # The cheat sheet itself is a shipped markdown file: the same for
    # everyone, and read-only for good reason. But half of what anyone
    # reaches for daily is personal — a Workcenter URL, an office phone
    # number, a snippet they paste twenty times a day — and those have
    # nowhere to live except a sticky note.
    #
    # Stored in persistence (state.json) under one key, so it is on THIS
    # machine and survives an update: nothing here is written back into
    # the markdown, which would be overwritten on the next release.
    _QUICK_KEY = "cheat_sheet_shortcuts"

    def quick_items(self) -> dict:
        """The user's saved shortcuts, oldest first."""
        try:
            import persistence
            raw = persistence.get(self._QUICK_KEY) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex), "items": []}
        items = []
        for it in raw if isinstance(raw, list) else []:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or "").strip()
            value = str(it.get("value") or "").strip()
            kind = "link" if str(it.get("kind")) == "link" else "copy"
            if label and value:
                items.append({"label": label, "kind": kind, "value": value})
        return {"ok": True, "items": items}

    def save_quick_items(self, items) -> dict:
        """Replace the whole list. The panel owns the ordering, so a
        merge here would fight it.

        Validated rather than trusted: a blank label or value would
        render an invisible button, and an unknown kind would render one
        that does nothing when clicked.
        """
        clean = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            label = str(it.get("label") or "").strip()[:60]
            value = str(it.get("value") or "").strip()[:2000]
            kind = "link" if str(it.get("kind")) == "link" else "copy"
            if label and value:
                clean.append({"label": label, "kind": kind, "value": value})
        if len(clean) > 60:
            clean = clean[:60]
        try:
            import persistence
            persistence.set_value(self._QUICK_KEY, clean)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True, "count": len(clean)}

    def open_link(self, url: str) -> dict:
        """Open one of the user's link shortcuts.

        http(s) only. A shortcut is free text the user typed, and
        handing an arbitrary scheme to the shell — file:, or worse — is
        not something a notes panel should do.
        """
        u = str(url or "").strip()
        if not u:
            return {"ok": False, "error": "no link"}
        low = u.lower()
        if not (low.startswith("http://") or low.startswith("https://")):
            return {"ok": False,
                    "error": "Links have to start with http:// or https://"}
        try:
            import dept_browser
            dept_browser.open_url(u)
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def export_pdf(self) -> dict:
        """Render the cheat sheet to a printable PDF. Uses reportlab —
        same library audit_export uses — for consistency."""
        try:
            md_path = paths.resource("EMS_Admin_Cheat_Sheet.md")
            sections = cs.parse_markdown(md_path) or []
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not sections:
            return {"ok": False, "error": "Cheat sheet is empty"}
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.enums import TA_LEFT
        except Exception as ex:
            return {"ok": False, "error": f"reportlab unavailable: {ex}"}
        try:
            import datetime as _dt
            out_dir = os.path.join(paths.DATA_DIR, "cheat_sheet_exports")
            os.makedirs(out_dir, exist_ok=True)
            today = _dt.date.today().strftime("%Y-%m-%d")
            out_path = os.path.join(out_dir, f"cheat_sheet_{today}.pdf")
            doc = SimpleDocTemplate(out_path, pagesize=letter,
                                     leftMargin=0.6 * inch,
                                     rightMargin=0.6 * inch,
                                     topMargin=0.6 * inch,
                                     bottomMargin=0.6 * inch)
            styles = getSampleStyleSheet()
            h1 = ParagraphStyle("H1", parent=styles["Heading1"],
                                 fontSize=14, spaceAfter=6,
                                 textColor=colors.HexColor("#2E8B57"))
            body = ParagraphStyle("B", parent=styles["Normal"],
                                   fontSize=10, spaceAfter=4, leading=14)
            story = [Paragraph("EMS Admin Cheat Sheet", h1)]
            for sec in sections:
                story.append(Paragraph(sec.get("title") or "—", h1))
                content = sec.get("content") or ""
                for ln in content.split("\n"):
                    if ln.strip():
                        story.append(Paragraph(ln.replace("&", "&amp;"), body))
                story.append(Spacer(1, 0.1 * inch))
            doc.build(story)
            try: os.startfile(out_path)
            except Exception: pass
            return {"ok": True, "path": out_path,
                    "sections": len(sections)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="EMS Cheat Sheet — Linguar Hub (web)",
        url=INDEX_HTML, js_api=api,
        width=1100, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
